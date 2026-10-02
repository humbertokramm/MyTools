"""Acesso ao shell Linux do equipamento (SSH, telnet raw ou serial) e as
operações de pendrive: listar, copiar para o PC e gravar a partir do PC.
"""

import hashlib
import os
import re
import shlex
import socket
import time

MOUNT_POINT = "/mnt/bios_usb"
DEFAULT_SKIP = ["System Volume Information"]
LOCAL_IGNORE = {"thumbs.db", "desktop.ini", ".ds_store"}
MARK_RE = re.compile(r"__R" r"C__(\d+)__")
# Montado em partes para o eco do comando não casar com o marcador.
MARK_CMD = 'echo "__R""C__$?__"'


class DeviceError(Exception):
    pass


# =========================================================================
# Transportes
# =========================================================================
class Transport:
    name = "?"

    def run(self, cmd, timeout=60):
        """Executa no shell do equipamento. Devolve (rc, saída)."""
        raise NotImplementedError

    def close(self):
        pass


class SshTransport(Transport):
    def __init__(self, host, port=22, user="root", password="root", timeout=10):
        import paramiko

        self.name = f"SSH {host}:{port}"
        t = paramiko.Transport(socket.create_connection((host, port), timeout))
        t.start_client(timeout=timeout)
        # O DmOS gera chave nova a cada boot: não dá para fixar a host key.
        try:
            t.auth_password(user, password)
        except paramiko.SSHException:
            if not t.is_authenticated():
                t.auth_interactive(user, lambda title, instr, prompts: [password] * len(prompts))
        if not t.is_authenticated():
            t.close()
            raise DeviceError("SSH: autenticação falhou")
        t.set_keepalive(15)
        self._t = t

    def run(self, cmd, timeout=60):
        ch = self._t.open_session()
        ch.settimeout(timeout)
        ch.exec_command(cmd)
        out = []
        end = time.monotonic() + timeout
        while True:
            if ch.recv_ready():
                out.append(ch.recv(65536))
            elif ch.recv_stderr_ready():
                out.append(ch.recv_stderr(65536))
            elif ch.exit_status_ready():
                while ch.recv_ready():
                    out.append(ch.recv(65536))
                while ch.recv_stderr_ready():
                    out.append(ch.recv_stderr(65536))
                break
            elif time.monotonic() > end:
                ch.close()
                raise DeviceError(f"timeout ({timeout}s) executando: {cmd[:80]}")
            else:
                time.sleep(0.02)
        rc = ch.recv_exit_status()
        ch.close()
        return rc, b"".join(out).decode("utf-8", "replace")

    def close(self):
        self._t.close()


class _SocketStream:
    """Socket TCP com tratamento mínimo de telnet (recusa toda negociação)."""

    IAC, DONT, DO, WONT, WILL, SB, SE = 255, 254, 253, 252, 251, 250, 240

    def __init__(self, host, port, timeout=10):
        self.s = socket.create_connection((host, port), timeout)
        self._pend = b""

    def write(self, data):
        self.s.sendall(data.replace(bytes([self.IAC]), bytes([self.IAC, self.IAC])))

    def read(self, timeout):
        self.s.settimeout(timeout)
        try:
            data = self.s.recv(65536)
        except socket.timeout:
            return b""
        if not data:
            raise DeviceError("conexão telnet fechada pelo servidor")
        return self._strip_iac(self._pend + data)

    def _strip_iac(self, data):
        out, i, n = bytearray(), 0, len(data)
        self._pend = b""
        while i < n:
            c = data[i]
            if c != self.IAC:
                out.append(c)
                i += 1
                continue
            if i + 1 >= n:
                self._pend = data[i:]
                break
            cmd = data[i + 1]
            if cmd == self.IAC:
                out.append(self.IAC)
                i += 2
            elif cmd in (self.DO, self.DONT, self.WILL, self.WONT):
                if i + 2 >= n:
                    self._pend = data[i:]
                    break
                opt = data[i + 2]
                if cmd == self.DO:
                    self.s.sendall(bytes([self.IAC, self.WONT, opt]))
                elif cmd == self.WILL:
                    self.s.sendall(bytes([self.IAC, self.DONT, opt]))
                i += 3
            elif cmd == self.SB:
                j = data.find(bytes([self.IAC, self.SE]), i)
                if j < 0:
                    self._pend = data[i:]
                    break
                i = j + 2
            else:
                i += 2
        return bytes(out)

    def close(self):
        self.s.close()


class _SerialStream:
    def __init__(self, port, baud):
        import serial

        self.ser = serial.Serial(port, baud, timeout=0)

    def write(self, data):
        self.ser.write(data)

    def read(self, timeout):
        end = time.monotonic() + timeout
        while True:
            n = self.ser.in_waiting
            if n:
                return self.ser.read(n)
            if time.monotonic() >= end:
                return b""
            time.sleep(0.01)

    def close(self):
        self.ser.close()


class ConsoleTransport(Transport):
    """Shell interativo por um fluxo de bytes (telnet raw ou porta serial)."""

    PROMPT_RE = re.compile(r"[#$>] ?$")

    def __init__(self, stream, name, user="root", password="root", log=None):
        self.st = stream
        self.name = name
        self.log = log or (lambda m: None)
        self._login(user, password)
        # Sem eco e sem mensagens de kernel no console, a saída fica limpa.
        self.run("stty -echo 2>/dev/null; dmesg -n 1 2>/dev/null; true", timeout=10)

    def _read_for(self, seconds, quiet=None):
        buf, end, last = b"", time.monotonic() + seconds, time.monotonic()
        while time.monotonic() < end:
            d = self.st.read(0.1)
            if d:
                buf += d
                last = time.monotonic()
            elif quiet and buf and time.monotonic() - last >= quiet:
                break
        return buf.decode("utf-8", "replace")

    def _login(self, user, password):
        self.st.write(b"\x03")
        time.sleep(0.2)
        self.st.write(b"\r")
        buf, end, sent_user, sent_pass = "", time.monotonic() + 25, False, False
        while time.monotonic() < end:
            buf += self._read_for(1.0, quiet=0.3)
            tail = buf.rstrip("\r\n ")[-60:]
            if re.search(r"login:\s*$", buf):
                if sent_user and sent_pass:
                    raise DeviceError("console: login recusado (usuário/senha?)")
                self.st.write(user.encode() + b"\r")
                sent_user, buf = True, ""
            elif re.search(r"[Pp]assword:\s*$", buf):
                self.st.write(password.encode() + b"\r")
                sent_pass, buf = True, ""
            elif tail and self.PROMPT_RE.search(tail):
                return
            elif not buf.strip():
                self.st.write(b"\r")
        raise DeviceError(f"console: não achei o prompt do shell. Última saída: {buf[-200:]!r}")

    def run(self, cmd, timeout=60):
        self._read_for(0.3, quiet=0.1)  # descarta restos (prompt, mensagens)
        self.st.write(f"{cmd}; {MARK_CMD}\r".encode())
        buf, end = "", time.monotonic() + timeout
        while time.monotonic() < end:
            d = self.st.read(0.2)
            if d:
                buf += d.decode("utf-8", "replace")
                m = MARK_RE.search(buf)
                if m:
                    out = buf[: m.start()].replace("\r", "")
                    lines = out.split("\n")
                    # Se o eco ainda estiver ligado, a 1a linha é o próprio comando.
                    if lines and MARK_CMD in "".join(lines[:3]):
                        while lines and MARK_CMD not in lines[0]:
                            lines.pop(0)
                        lines.pop(0)
                    return int(m.group(1)), "\n".join(lines).strip("\n")
        # Timeout: tenta devolver o shell ao prompt.
        self.st.write(b"\x03\r")
        raise DeviceError(f"timeout ({timeout}s) executando: {cmd[:80]}")

    def close(self):
        try:
            self.st.write(b"stty echo\r")
        except Exception:
            pass
        self.st.close()


def connect(kind, target, user="root", password="root", log=None):
    """kind: 'ssh' (host[:porta]), 'telnet' (host:porta) ou 'serial' (COMx[:baud])."""
    log = log or (lambda m: None)
    if kind == "ssh":
        host, _, port = target.partition(":")
        log(f"Conectando SSH em {host}:{port or 22}...")
        return SshTransport(host, int(port or 22), user, password)
    if kind == "telnet":
        host, _, port = target.partition(":")
        log(f"Conectando telnet em {host}:{port or 23}...")
        return ConsoleTransport(_SocketStream(host, int(port or 23)), f"Telnet {host}:{port or 23}",
                                user, password, log)
    if kind == "serial":
        port, _, baud = target.partition(":")
        log(f"Abrindo serial {port} @ {baud or 115200}...")
        return ConsoleTransport(_SerialStream(port, int(baud or 115200)), f"Serial {port}",
                                user, password, log)
    raise DeviceError(f"tipo de conexão desconhecido: {kind}")


# =========================================================================
# Operações
# =========================================================================
def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_local_files(folder):
    """[(caminho_relativo_com_/, caminho_absoluto, tamanho)] ordenado."""
    res = []
    for dirpath, dirnames, files in os.walk(folder):
        dirnames.sort()
        for fn in sorted(files):
            if fn.lower() in LOCAL_IGNORE or fn.endswith(".tftp_part"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, folder).replace(os.sep, "/")
            res.append((rel, full, os.path.getsize(full)))
    return res


def human(n):
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


class Device:
    def __init__(self, transport, log=None):
        self.t = transport
        self.log = log or print

    def sh(self, cmd, timeout=60, check=True):
        rc, out = self.t.run(cmd, timeout)
        if check and rc != 0:
            raise DeviceError(f"comando falhou (rc={rc}): {cmd}\n{out.strip()}")
        return out

    def close(self):
        self.t.close()

    # ------------------------------------------------------------- consulta
    def info(self):
        out = self.sh("hostname; uname -r; ip -4 -o addr show scope global | awk '{print $2\" \"$4}'")
        lines = out.strip().splitlines()
        host = lines[0] if lines else "?"
        kernel = lines[1] if len(lines) > 1 else "?"
        return host, kernel, lines[2:]

    def check_tools(self):
        missing = []
        for tool in ("sfdisk", "mkdosfs", "md5sum", "blkid"):
            if self.t.run(f"which {tool} >/dev/null 2>&1", 10)[0] != 0:
                missing.append(tool)
        if self.t.run("busybox tftp 2>&1 | grep -q -- '-p'", 10)[0] != 0:
            missing.append("busybox tftp")
        return missing

    def ping(self, ip):
        return self.t.run(f"ping -c 1 -W 2 {shlex.quote(ip)} >/dev/null 2>&1", 10)[0] == 0

    def usb_disks(self):
        """[{dev, size, model, id}] dos discos USB (nunca a eMMC interna)."""
        cmd = (
            'for l in /dev/disk/by-id/usb-*; do [ -e "$l" ] || continue; '
            'case "$l" in *-part*) continue;; esac; '
            'd=$(readlink -f "$l"); n=${d##*/}; '
            'echo "$d|$(cat /sys/block/$n/size 2>/dev/null)|'
            '$(cat /sys/block/$n/device/vendor 2>/dev/null | xargs) '
            '$(cat /sys/block/$n/device/model 2>/dev/null | xargs)|${l##*/}"; done'
        )
        disks = []
        for line in self.sh(cmd).splitlines():
            p = line.strip().split("|")
            if len(p) != 4 or not re.match(r"^/dev/sd[a-z]+$", p[0]):
                continue
            size = int(p[1]) * 512 if p[1].isdigit() else 0
            if size == 0:
                continue  # leitor sem mídia
            disks.append({"dev": p[0], "size": size, "model": p[2].strip(), "id": p[3]})
        return disks

    def describe(self, d):
        return f"{d['dev']}  {d['model']}  {human(d['size'])}"

    # ------------------------------------------------------------ montagem
    def umount_all(self, dev):
        self.sh(f"for m in $(grep '^{dev}' /proc/mounts | cut -d' ' -f2); do umount \"$m\" || umount -l \"$m\"; done; true")

    def _fs_device(self, dev):
        """Primeira partição com sistema de arquivos; senão o disco inteiro."""
        n = dev.rsplit("/", 1)[1]
        parts = self.sh(f"ls -d /sys/block/{n}/{n}* 2>/dev/null | sed 's#.*/#/dev/#'; true").split()
        for cand in parts + [dev]:
            t = self.sh(f"blkid -o value -s TYPE {cand} 2>/dev/null; true").strip()
            if t:
                return cand, t
        raise DeviceError(f"nenhum sistema de arquivos reconhecido em {dev}")

    def mount(self, dev, ro):
        self.umount_all(dev)
        src, fstype = self._fs_device(dev)
        self.sh(f"mkdir -p {MOUNT_POINT}")
        self.sh(f"mount {'-o ro' if ro else ''} {src} {MOUNT_POINT}")
        self.log(f"Montado {src} ({fstype}) em {MOUNT_POINT} {'(somente leitura)' if ro else ''}")
        return src

    def umount(self):
        self.sh(f"sync; umount {MOUNT_POINT} 2>/dev/null; true", timeout=120)

    def remote_md5s(self):
        """{rel: md5} dos arquivos em MOUNT_POINT."""
        out = self.sh(f"cd {MOUNT_POINT} && find . -type f -exec md5sum {{}} +", timeout=600)
        res = {}
        for line in out.splitlines():
            m = re.match(r"^([0-9a-f]{32})\s+\./(.+)$", line.strip())
            if m:
                res[m.group(2)] = m.group(1)
        return res

    # ------------------------------------------------- passo 1: pendrive -> PC
    def backup(self, dev, tftp_ip, local_dir, skip=None, blksize=1468, progress=None):
        """Copia todos os arquivos do pendrive para local_dir via TFTP (PUT)."""
        skip = DEFAULT_SKIP if skip is None else skip
        progress = progress or (lambda done, total: None)
        self.mount(dev, ro=True)
        try:
            files = self.sh(
                f"cd {MOUNT_POINT} && find . -type f | while read -r f; do "
                f"echo \"$(wc -c < \"$f\" | tr -d ' ')|$f\"; done", timeout=120)
            items = []
            for line in files.splitlines():
                size, _, rel = line.strip().partition("|")
                rel = rel[2:] if rel.startswith("./") else rel
                if not rel or not size.isdigit():
                    continue
                if any(rel == s or rel.startswith(s + "/") for s in skip):
                    self.log(f"  pulando {rel}")
                    continue
                items.append((rel, int(size)))
            total = sum(s for _, s in items)
            self.log(f"{len(items)} arquivos, {human(total)} a copiar")
            self.log("Calculando MD5 no pendrive...")
            md5s = self.remote_md5s()
            done = 0
            for rel, size in items:
                self.log(f"  -> {rel} ({human(size)})")
                self.sh(f"busybox tftp -p -b {blksize} -l {shlex.quote(MOUNT_POINT + '/' + rel)} "
                        f"-r {shlex.quote(rel)} {tftp_ip}", timeout=max(120, size // 50000))
                local = os.path.join(local_dir, *rel.split("/"))
                got = md5_file(local)
                if got != md5s.get(rel):
                    raise DeviceError(f"MD5 diferente em {rel}: PC {got} x pendrive {md5s.get(rel)}")
                done += size
                progress(done, total)
            self.log(f"Cópia concluída e conferida (MD5): {len(items)} arquivos em {local_dir}")
            return items
        finally:
            self.umount()

    # ---------------------------------------------- passo 2: PC -> pendrive
    def format_disk(self, dev, layout="mbr", label="BIOS"):
        """layout 'mbr': MBR + 1 partição FAT32. 'floppy': FAT32 no disco inteiro."""
        n = dev.rsplit("/", 1)[1]
        self.umount_all(dev)
        self.log(f"Apagando início e fim de {dev}...")
        self.sh(f"dd if=/dev/zero of={dev} bs=1M count=8 conv=fsync 2>/dev/null", timeout=120)
        self.sh(f"S=$(cat /sys/block/{n}/size); dd if=/dev/zero of={dev} bs=512 "
                f"seek=$((S-8192)) count=8192 conv=fsync 2>/dev/null", timeout=120)
        if layout == "mbr":
            self.log("Criando tabela MBR com uma partição FAT32 (tipo 0x0c)...")
            self.sh(f"printf 'label: dos\\n2048,,c,*\\n' | sfdisk --wipe always {dev}", timeout=60)
            self.sh(f"blockdev --rereadpt {dev} 2>/dev/null || partprobe {dev} 2>/dev/null; true")
            part = f"{dev}1"
            self.sh(f"i=0; while [ ! -b {part} ] && [ $i -lt 50 ]; do usleep 200000; i=$((i+1)); done; "
                    f"[ -b {part} ]", timeout=30)
        else:
            part = dev
        self.log(f"Formatando {part} em FAT32 (rótulo {label})...")
        self.sh(f"mkdosfs -n {shlex.quote(label)} {part}", timeout=300)
        self.sh("sync", timeout=60)
        return part

    def write(self, dev, tftp_ip, local_dir, layout="mbr", blksize=1468, progress=None):
        progress = progress or (lambda done, total: None)
        files = list_local_files(local_dir)
        if not files:
            raise DeviceError(f"pasta vazia: {local_dir}")
        total = sum(s for _, _, s in files)
        self.log(f"{len(files)} arquivos, {human(total)} a gravar")
        local_md5 = {rel: md5_file(full) for rel, full, _ in files}

        self.format_disk(dev, layout)
        self.mount(dev, ro=False)
        try:
            done = 0
            for rel, _, size in files:
                self.log(f"  <- {rel} ({human(size)})")
                dst = MOUNT_POINT + "/" + rel
                if "/" in rel:
                    self.sh(f"mkdir -p {shlex.quote(dst.rsplit('/', 1)[0])}")
                self.sh(f"busybox tftp -g -b {blksize} -l {shlex.quote(dst)} -r {shlex.quote(rel)} {tftp_ip}",
                        timeout=max(120, size // 50000))
                done += size
                progress(done, total)
            self.log("Sincronizando...")
        finally:
            self.umount()

        # Remonta do zero para ler da mídia e não do cache.
        self.log("Conferindo MD5 lendo de volta do pendrive...")
        self.sh("echo 3 > /proc/sys/vm/drop_caches; true")
        self.mount(dev, ro=True)
        try:
            remote = self.remote_md5s()
        finally:
            self.umount()
        bad = [rel for rel in local_md5 if remote.get(rel) != local_md5[rel]]
        if bad:
            raise DeviceError("MD5 diferente no pendrive: " + ", ".join(bad))
        self.log(f"Pendrive gravado e conferido (MD5): {len(files)} arquivos. Pode remover.")
        return files
