"""Aciona (liga/desliga) uma porta Digital Output do DM706KE via menu telnet.

Substituto do Macro_Estagiario_v2.ttl (Tera Term): em vez de mandar teclas
"as cegas" com pausas fixas, este cliente le o buffer telnet de verdade e so
avanca quando reconhece o TITULO da proxima tela. Isso elimina os
travamentos por timing e por "tela errada" da macro TTL.

Por que telnet e nao SNMP/PCGA:
  - o agente SNMP deste firmware NAO mapeia as saidas digitais (so
    identificacao e contadores do router);
  - o protocolo de gerencia PCGA v1 (TCP 5554, usado pelo DmView) esta
    com a porta fechada neste equipamento.
  Entao o menu (telnet/serial) e a unica via de rede disponivel - mas aqui
  ela fica robusta e sem Tera Term.

Uso:
  python estagiario.py <CANAL A-D> <CMD>
    CANAL e CMD nao sao case-sensitive (aceitam maiuscula ou minuscula).
    CMD: on     = liga    (Start Alarm test  -> FORCE_ALARM)
         off    = desliga (Stop testing / volta ao configurado)
         noalarm= forca desligado (Start No Alarm test -> FORCE_NO_ALARM)
         status = so le o estado atual, sem acionar
         (aliases numericos aceitos: 1=off, 2=on, 3=noalarm)
  Ex.: python estagiario.py C on      -> liga a porta 3
       python estagiario.py c off     -> desliga a porta 3
       python estagiario.py C status  -> le o estado da porta 3

Saida/erros vao para a tela e para aciona_porta.log (append, com timestamp).
Codigo de saida: 0 = ok, 1 = erro (util para o .bat testar %ERRORLEVEL%).

Arvore do menu percorrida:
  ENTER -> menu raiz -> 1 (Configure TDM) -> 1 (Choose equipment)
  -> 1 (*1 DM706KE) -> 2 (Tests menu) -> H (Digital Output) -> A..D (porta)
  -> 1/2/3 (comando)  [ENTER faz Refresh e redesenha "Current test status"]
"""
import os
import re
import select
import socket
import sys
import time
from datetime import datetime

DEBUG = bool(os.environ.get("ACIONA_DEBUG"))


def dbg(msg):
    if DEBUG:
        print(f"    [dbg {time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr)

HOST = "172.22.239.102"
PORT = 23
LOGFILE = r"C:\Testes\TFTP\aciona_porta.log"

TSCREEN = 15        # timeout (s) esperando o refresh de status
TSTEP = 8           # timeout (s) por passo de navegacao. A tela mais lenta
                    # (Configure TDM) desenha em ~4.5 s; se em 8 s o titulo
                    # nao veio, a sessao telnet anterior ainda esta presa no
                    # equipamento (ele ecoa o clear-screen mas nao desenha).
MAXTENTATIVAS = 6   # tentativas completas de navegacao
ESPERA_PRESA = 7    # pausa (s) antes de retentar quando a sessao esta presa


class SessaoPresa(Exception):
    """Equipamento aceitou o TCP e o handshake inicial mas ignora o menu: a
    sessao telnet anterior ainda nao expirou. Some sozinha em ~15-20 s."""

CANAL_PORTA = {"A": 1, "B": 2, "C": 3, "D": 4}

# Comando do usuario -> (tecla enviada ao menu, descricao no log).
# "on"/"off" sao os nomes preferidos; 1/2/3 seguem aceitos por retrocompat
# (a rebootVHW.ttl e os .bat de ciclo ainda chamam com 1/2).
CMD_MAP = {
    "off": ("1", "OFF - Stop testing (desliga)"),
    "on":  ("2", "ON - Start Alarm test (liga)"),
    "noalarm": ("3", "Force No Alarm (forca desligado)"),
    # aliases numericos (retrocompat):
    "1": ("1", "OFF - Stop testing (desliga)"),
    "2": ("2", "ON - Start Alarm test (liga)"),
    "3": ("3", "Force No Alarm (forca desligado)"),
}
# comandos validos mostrados nas mensagens de erro (os preferidos)
CMDS_VALIDOS = "on, off, status (aliases: 1=off, 2=on, 3=noalarm)"


def log(msg):
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linha)
    try:
        with open(LOGFILE, "a", encoding="utf-8") as f:
            f.write(linha + "\n")
    except OSError:
        pass


class Telnet:
    """Telnet minimo: recusa toda negociacao de opcao (equipamento e VT100 cru)."""

    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buf = ""

    def _strip_iac(self, data: bytes) -> bytes:
        out = bytearray()
        i = 0
        while i < len(data):
            b = data[i]
            if b != 255:
                out.append(b)
                i += 1
                continue
            if i + 1 >= len(data):
                break
            cmd = data[i + 1]
            if cmd == 255:
                out.append(255)
                i += 2
            elif cmd in (251, 252, 253, 254):  # WILL/WONT/DO/DONT
                if i + 2 < len(data):
                    opt = data[i + 2]
                    resp = {253: 252, 251: 254}.get(cmd)  # DO->WONT, WILL->DONT
                    if resp:
                        self.sock.sendall(bytes([255, resp, opt]))
                    i += 3
                else:
                    break
            else:
                i += 2
        return bytes(out)

    def wait_any(self, patterns, timeout):
        """Espera qualquer padrao (lista de str). Retorna (indice_1based, texto)
        ou (0, texto) no timeout. Consome o buffer no match."""
        end = time.time() + timeout
        while True:
            for n, p in enumerate(patterns, 1):
                if p in self.buf:
                    text, self.buf = self.buf, ""
                    return n, text
            restante = end - time.time()
            if restante <= 0:
                text, self.buf = self.buf, ""
                return 0, text
            r, _, _ = select.select([self.sock], [], [], min(0.5, restante))
            if r:
                data = self.sock.recv(4096)
                if not data:
                    raise ConnectionError("conexao fechada pelo equipamento")
                self.buf += self._strip_iac(data).decode("latin-1", "replace")

    def drain(self, quiet=0.5, maxwait=TSCREEN):
        """Le (acumulando no buffer) ate o equipamento ficar 'quiet' segundos
        sem enviar nada - ou seja, ate o redesenho da tela terminar. Isso
        evita mandar a proxima tecla enquanto o equipamento ainda desenha
        (teclas recebidas durante o redesenho sao ignoradas por ele)."""
        end = time.time() + maxwait
        while time.time() < end:
            r, _, _ = select.select([self.sock], [], [], quiet)
            if not r:
                return  # silencio: redesenho terminou
            data = self.sock.recv(4096)
            if not data:
                raise ConnectionError("conexao fechada pelo equipamento")
            self.buf += self._strip_iac(data).decode("latin-1", "replace")

    def send(self, s):
        self.sock.sendall(s.encode("latin-1"))

    def clear(self):
        self.buf = ""

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def resync(t):
    """Leva ao menu raiz (tela '1 Configure TDM / 2 Configure Router / ...').
    Uma conexao nova sempre reinicia na tela inicial 'Type ENTER to run
    terminal' (confirmado empiricamente), entao basta: ler o que veio,
    e se for a tela inicial, dar ENTER e esperar o raiz.
    Nunca mandamos ESC no raiz - isso encerraria a sessao."""
    t.drain(0.6, 8)                       # coleta a tela que o equipamento mostrou
    if "2 - Configure Router" in t.buf:   # ja estamos no raiz
        return True
    if "Type ENTER to run terminal" not in t.buf:
        # estado inesperado (sessao herdada suja): um ENTER tenta redesenhar
        t.clear()
        t.send("\r")
        t.drain(0.6, 8)
        if "2 - Configure Router" in t.buf:
            return True
    # tela inicial -> ENTER -> menu raiz
    t.clear()
    t.send("\r")
    idx, _ = t.wait_any(["2 - Configure Router"], TSCREEN)
    if idx == 0:
        return False
    t.drain()                             # completa o desenho do raiz
    return True


def passo(t, tecla, titulo):
    """Estando numa tela ja desenhada (estavel), envia uma tecla e espera o
    TITULO da tela de destino. wait_any cobre a 'tela lenta' (ha um gap de
    ~4-5 s entre o clear-screen e o conteudo). O drain final completa o
    desenho da tela de destino, deixando-a estavel para o proximo passo."""
    t.clear()
    t.send(tecla)
    t0 = time.time()
    idx, _ = t.wait_any([titulo], TSTEP)
    if idx == 0:
        # titulo nao veio no tempo da tela mais lenta => sessao presa
        dbg(f"passo '{tecla}' -> '{titulo}': sem titulo em {time.time()-t0:.1f}s (sessao presa)")
        raise SessaoPresa()
    dbg(f"passo '{tecla}' -> '{titulo}': ok em {time.time()-t0:.1f}s")
    t.drain()
    return True


def navega_ate_porta(t, canal, portnum):
    tela_porta = f"Digital Output Test [port {portnum}]"
    if not resync(t):
        return None
    ok = (passo(t, "1", "equipment to configure")  # Configure TDM
          and passo(t, "1", "Choose Equipment")     # Choose equipment
          and passo(t, "1", "Main Menu")            # *1 DM706KE
          and passo(t, "2", "Tests Menu")           # Tests menu
          and passo(t, "H", "Digital Output Tests")  # House Keep Digital Out
          and passo(t, canal, tela_porta))          # porta A..D
    return tela_porta if ok else None


def le_status(t):
    """Refresh (ENTER) e le a linha 'Current test status :[ ... ]'."""
    t.clear()
    t.send("\r")       # ENTER = Refresh
    idx, texto = t.wait_any(["Current test status"], TSCREEN)
    if idx == 0:
        return None
    t.drain()          # captura o restante ate o ']' do valor
    m = re.search(r"Current test status\s*:\[\s*([^\]]*?)\s*\]", texto + t.buf)
    return m.group(1).strip() if m else "(status ilegivel)"


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    canal = sys.argv[1].strip().upper()      # A-D, aceita maiuscula/minuscula
    cmd = sys.argv[2].strip().lower()        # on/off/status, idem
    if canal not in CANAL_PORTA:
        log(f"ERRO: canal invalido '{sys.argv[1]}' (use A, B, C ou D).")
        return 1
    if cmd != "status" and cmd not in CMD_MAP:
        log(f"ERRO: comando invalido '{sys.argv[2]}' (use {CMDS_VALIDOS}).")
        return 1
    portnum = CANAL_PORTA[canal]

    for tentativa in range(1, MAXTENTATIVAS + 1):
        t = None
        try:
            t = Telnet(HOST, PORT)
            tela_porta = navega_ate_porta(t, canal, portnum)
            if not tela_porta:
                log(f"tentativa {tentativa}: nao cheguei na tela da porta {portnum}; reconectando")
                t.close()
                continue

            if cmd == "status":
                st = le_status(t)
                log(f"OK: porta {portnum} ({canal}) status: {st}")
                _sair(t)
                return 0

            tecla, descricao = CMD_MAP[cmd]
            t.clear()
            t.send(tecla)                   # 1/2/3 (a tela da porta ja esta estavel)
            st = le_status(t)               # ENTER + le confirmacao
            log(f"OK: porta {portnum} ({canal}) -> {descricao}; status: {st}")
            _sair(t)
            return 0

        except SessaoPresa:
            # sessao telnet anterior ainda ativa no equipamento; espera expirar
            dbg(f"tentativa {tentativa}: sessao presa; aguardando {ESPERA_PRESA}s")
            if t:
                t.close()
            time.sleep(ESPERA_PRESA)
        except (OSError, ConnectionError) as e:
            log(f"tentativa {tentativa}: erro de conexao ({e})")
            if t:
                t.close()
            time.sleep(3)

    log(f"ERRO: falhei apos {MAXTENTATIVAS} tentativas (porta {portnum}, cmd {cmd}).")
    return 1


def _sair(t):
    """Saida graciosa: sobe ao menu raiz com ESC (seguro nos submenus) e
    encerra o acesso ao terminal com 'E' (Exit). Isso LIBERA a sessao telnet
    no equipamento imediatamente; se apenas fechassemos o socket, o
    equipamento manteria a sessao 'presa' por ~30-40 s e a proxima invocacao
    perderia tempo se recuperando. O estado fisico da porta ja foi aplicado
    e persiste independentemente da saida."""
    try:
        for _ in range(8):
            t.clear()
            t.send("\x1b")            # ESC: sobe um nivel (nunca no raiz ainda)
            t.drain(0.6, 6)
            if "2 - Configure Router" in t.buf:   # chegou ao raiz
                t.clear()
                t.send("E")           # E - Exit: encerra o acesso ao terminal
                t.drain(0.5, 3)
                break
    except (ConnectionError, OSError):
        pass                          # se a conexao caiu no meio, tudo bem
    t.close()


if __name__ == "__main__":
    sys.exit(main())
