"""Servidor TFTP mínimo (RFC 1350 + opções blksize/tsize/timeout, RFC 2347-2349).

Serve leitura (RRQ) e escrita (WRQ) dentro de uma pasta raiz, uma thread por
transferência. Usado para o equipamento baixar/enviar arquivos do PC.
"""

import os
import socket
import struct
import threading
import time

OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 2, 3, 4, 5, 6

ERR_NOT_FOUND = 1
ERR_ACCESS = 2
ERR_ILLEGAL = 4
ERR_UNKNOWN_TID = 5
ERR_OPTION = 8

MAX_BLKSIZE = 65464
RETRIES = 6


class TftpError(Exception):
    pass


def _no_connreset(sock):
    # No Windows, um ICMP "port unreachable" faz o próximo recvfrom levantar
    # WSAECONNRESET e derruba o socket de escuta.
    if hasattr(socket, "SIO_UDP_CONNRESET"):
        try:
            sock.ioctl(socket.SIO_UDP_CONNRESET, False)
        except OSError:
            pass


def _parse_request(data):
    parts = data[2:].split(b"\0")
    if len(parts) < 2:
        raise TftpError("requisição malformada")
    fname = parts[0].decode("utf-8", "replace")
    mode = parts[1].decode("ascii", "replace").lower()
    opts = {}
    rest = parts[2:]
    for i in range(0, len(rest) - 1, 2):
        if rest[i]:
            opts[rest[i].decode("ascii", "replace").lower()] = rest[i + 1].decode("ascii", "replace")
    return fname, mode, opts


def _error_pkt(code, msg):
    return struct.pack("!HH", OP_ERROR, code) + msg.encode("utf-8", "replace") + b"\0"


def _oack_pkt(opts):
    body = b"".join(k.encode() + b"\0" + v.encode() + b"\0" for k, v in opts.items())
    return struct.pack("!H", OP_OACK) + body


class TftpServer:
    """Servidor TFTP em thread. `log(msg)` e `progress(op, nome, feito, total)`."""

    def __init__(self, root, host, port=69, log=None, progress=None, allow_write=True):
        self.root = os.path.realpath(root)
        self.host = host
        self.port = port
        self.log = log or (lambda m: None)
        self.progress = progress or (lambda *a: None)
        self.allow_write = allow_write
        self._sock = None
        self._thread = None
        self._stop = threading.Event()
        self.completed = []   # (op, nome, bytes)
        self.failed = []      # (op, nome, motivo)

    # ------------------------------------------------------------ ciclo de vida
    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _no_connreset(s)
        try:
            s.bind((self.host, self.port))
        except OSError as e:
            s.close()
            raise TftpError(f"não foi possível abrir {self.host}:{self.port}/udp ({e}). "
                            "Outro servidor TFTP aberto?") from e
        s.settimeout(0.5)
        self._sock = s
        self._stop.clear()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.log(f"Servidor TFTP ouvindo em {self.host}:{self.port}, pasta {self.root}")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(2)
        if self._sock:
            self._sock.close()
        self._sock = None
        self._thread = None

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.stop()

    # ------------------------------------------------------------------ escuta
    def _serve(self):
        while not self._stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65536)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    break
                continue
            if len(data) < 4:
                continue
            op = struct.unpack("!H", data[:2])[0]
            if op not in (OP_RRQ, OP_WRQ):
                continue
            try:
                fname, mode, opts = _parse_request(data)
            except TftpError:
                continue
            threading.Thread(target=self._session, args=(op, fname, mode, opts, addr),
                             daemon=True).start()

    def _resolve(self, fname):
        rel = fname.replace("\\", "/").lstrip("/")
        parts = [p for p in rel.split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            raise TftpError("caminho inválido")
        full = os.path.realpath(os.path.join(self.root, *parts))
        if not (full == self.root or full.startswith(self.root + os.sep)):
            raise TftpError("caminho fora da pasta raiz")
        return "/".join(parts), full

    # ---------------------------------------------------------------- sessões
    def _session(self, op, fname, mode, opts, client):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        _no_connreset(s)
        s.bind((self.host, 0))
        opname = "GET" if op == OP_RRQ else "PUT"
        rel = fname
        try:
            rel, full = self._resolve(fname)
            if mode not in ("octet", "netascii"):
                raise TftpError(f"modo {mode} não suportado")
            if op == OP_RRQ:
                n = self._send_file(s, client, rel, full, opts)
            else:
                if not self.allow_write:
                    s.sendto(_error_pkt(ERR_ACCESS, "escrita desabilitada"), client)
                    raise TftpError("escrita desabilitada")
                n = self._recv_file(s, client, rel, full, opts)
            self.completed.append((opname, rel, n))
            self.log(f"TFTP {opname} {rel} OK ({n} bytes) <-> {client[0]}")
        except (TftpError, OSError) as e:
            self.failed.append((opname, rel, str(e)))
            self.log(f"TFTP {opname} {rel} FALHOU: {e}")
        finally:
            s.close()

    def _negotiate(self, opts, tsize=None):
        blksize, timeout, oack = 512, 1.0, {}
        if "blksize" in opts:
            try:
                blksize = max(8, min(int(opts["blksize"]), MAX_BLKSIZE))
                oack["blksize"] = str(blksize)
            except ValueError:
                pass
        if "timeout" in opts:
            try:
                t = int(opts["timeout"])
                if 1 <= t <= 255:
                    timeout = float(t)
                    oack["timeout"] = str(t)
            except ValueError:
                pass
        if "tsize" in opts:
            oack["tsize"] = str(tsize if tsize is not None else opts["tsize"])
        return blksize, timeout, oack

    def _recv_pkt(self, s, client, timeout):
        """Recebe um pacote do cliente certo; devolve None em timeout."""
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return None
            s.settimeout(left)
            try:
                data, addr = s.recvfrom(65536)
            except socket.timeout:
                return None
            if addr != client:
                s.sendto(_error_pkt(ERR_UNKNOWN_TID, "TID desconhecido"), addr)
                continue
            if len(data) < 4:
                continue
            op, num = struct.unpack("!HH", data[:4])
            if op == OP_ERROR:
                msg = data[4:].split(b"\0")[0].decode("utf-8", "replace")
                raise TftpError(f"cliente abortou: {msg} (código {num})")
            return op, num, data[4:]

    def _send_and_wait_ack(self, s, client, pkt, block, timeout):
        for _ in range(RETRIES):
            s.sendto(pkt, client)
            end = time.monotonic() + timeout
            while True:
                r = self._recv_pkt(s, client, end - time.monotonic())
                if r is None:
                    break  # timeout -> retransmite
                op, num, _ = r
                if op == OP_ACK and num == block:
                    return
                # ACK duplicado de bloco anterior: ignora (evita Sorcerer's Apprentice)
        raise TftpError(f"timeout aguardando ACK do bloco {block}")

    def _send_file(self, s, client, rel, full, opts):
        if not os.path.isfile(full):
            s.sendto(_error_pkt(ERR_NOT_FOUND, "arquivo não encontrado"), client)
            raise TftpError("arquivo não encontrado")
        total = os.path.getsize(full)
        blksize, timeout, oack = self._negotiate(opts, tsize=total)
        with open(full, "rb") as f:
            if oack:
                self._send_and_wait_ack(s, client, _oack_pkt(oack), 0, timeout)
            block, sent, last_rep = 1, 0, 0
            while True:
                chunk = f.read(blksize)
                pkt = struct.pack("!HH", OP_DATA, block & 0xFFFF) + chunk
                self._send_and_wait_ack(s, client, pkt, block & 0xFFFF, timeout)
                sent += len(chunk)
                if sent - last_rep >= 262144 or len(chunk) < blksize:
                    self.progress("GET", rel, sent, total)
                    last_rep = sent
                if len(chunk) < blksize:
                    return sent
                block += 1

    def _recv_file(self, s, client, rel, full, opts):
        total = None
        if "tsize" in opts:
            try:
                total = int(opts["tsize"]) or None
            except ValueError:
                pass
        blksize, timeout, oack = self._negotiate(opts)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        tmp = full + ".tftp_part"
        reply = _oack_pkt(oack) if oack else struct.pack("!HH", OP_ACK, 0)
        expected, received, last_rep = 1, 0, 0
        try:
            with open(tmp, "wb") as f:
                s.sendto(reply, client)
                tries = 0
                while True:
                    r = self._recv_pkt(s, client, timeout)
                    if r is None:
                        tries += 1
                        if tries >= RETRIES:
                            raise TftpError(f"timeout aguardando bloco {expected}")
                        s.sendto(reply, client)
                        continue
                    op, num, payload = r
                    if op != OP_DATA:
                        continue
                    if num == (expected & 0xFFFF):
                        tries = 0
                        f.write(payload)
                        received += len(payload)
                        reply = struct.pack("!HH", OP_ACK, num)
                        if len(payload) < blksize:
                            break  # último ACK só depois do arquivo estar no lugar
                        s.sendto(reply, client)
                        if received - last_rep >= 262144:
                            self.progress("PUT", rel, received, total)
                            last_rep = received
                        expected += 1
                    elif num == ((expected - 1) & 0xFFFF):
                        s.sendto(reply, client)  # nosso ACK se perdeu
            os.replace(tmp, full)
            s.sendto(reply, client)
            self.progress("PUT", rel, received, total)
            # Se o último ACK se perder o cliente repete o último DATA; re-ACK por 1 s.
            while True:
                try:
                    r = self._recv_pkt(s, client, 1.0)
                except TftpError:
                    break
                if r is None:
                    break
                s.sendto(reply, client)
            return received
        except BaseException:
            try:
                os.remove(tmp)
            except OSError:
                pass
            raise
