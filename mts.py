"""Controle do MTS-5800-100G via SCPI sobre SSH (paramiko), com comandos agrupados.

Uma unica conexao SSH e uma unica sessao de remote control para TODA a sequencia
de comandos -> evita reabrir tunel a cada comando e nao deixa conexao pendurada
(fecha a sessao com :SESS:END no fim). A senha vem do Windows Credential Manager
(win_credential), servico "MTS-5800"; na 1a vez pede e salva.

Uso (um ou varios comandos em sequencia):
    py mts.py traffic-off restart traffic-on
    py mts.py traffic-off wait:3 results
    py mts.py results
    py mts.py status

Verbos: traffic-on traffic-off start stop restart results status
Especiais:
    wait:N            espera N segundos entre comandos
    ":SCPI ..."       qualquer comando SCPI cru (token comecando com ':'); use aspas
                      ex: py mts.py ":SOURCE:MAC:TRAFFIC ON" ":SYST:ERR?"

Delays de estabilizacao (aplicados ENTRE comandos, nao apos o ultimo):
    --settle 5   apos comandos criticos (traffic-off/restart/start): drena os
                 pacotes em transito e da tempo de armar os contadores
    --delay  2   entre os demais comandos
    (wait:N no meio da sequencia continua funcionando por conta propria)

Opcoes:
    --host 172.22.239.50   IP do MTS (default; era .40 ate 15/07/2026 - conflito de IP)
    --user tb-5800         usuario SSH (default; alt: mts-5800)
    --app  <id>            forca o app alvo (default: 1o app rodando)
    --service MTS-5800     nome do servico no Credential Manager (default)
"""
import argparse
import os
import sys
import threading
import time

import paramiko

import win_credential as wc

DEFAULT_HOST = "172.22.239.50"
DEFAULT_USER = "tb-5800"
DEFAULT_SERVICE = "MTS-5800"
VERBOS = {"traffic-on", "traffic-off", "start", "stop", "restart", "results", "status"}

# Espera (s) generica apos cada comando intermediario (estabilizacao geral).
DELAY = 2.0
# Espera (s) maior para comandos criticos: drenagem apos traffic-off e
# armar os contadores na partida (restart/start). Evita perda falsa de frames
# tanto no inicio (contadores nao armados) quanto no fim (pacotes em transito).
SETTLE = 5.0
SETTLE_TOKENS = {"traffic-off", "restart", "start"}

# Watchdog: teto absoluto (s) para o processo. Se estourar, mata o processo no
# nivel do SO com os._exit() — isso ignora threads presas do paramiko em um
# socket.recv() sem timeout (o que travou a macro por horas em 14/07). Garante
# que o mts.py SEMPRE termina, mesmo com a conexao com o MTS "engolida" pela rede.
WATCHDOG_BASE = 90.0


def armar_watchdog(segundos):
    def matar():
        sys.stderr.write(f"\n!!! WATCHDOG: mts.py excedeu {segundos:.0f}s - "
                         "encerrando a forca (conexao com o MTS travada?).\n")
        sys.stderr.flush()
        try:
            sys.stdout.flush()
        except Exception:
            pass
        os._exit(3)          # nao roda finally/atexit; mata threads presas junto
    t = threading.Timer(segundos, matar)
    t.daemon = True
    t.start()
    return t


# --------------------------- IO sobre canal SSH ---------------------------
class ChanIO:
    """Envia/le linhas por um canal direct-tcpip do paramiko (como um socket)."""

    def __init__(self, chan):
        self.chan = chan
        self.buf = b""

    def send(self, s):
        self.chan.sendall((s + "\n").encode("ascii"))

    def readline(self):
        while b"\n" not in self.buf:
            data = self.chan.recv(4096)
            if not data:
                break
            self.buf += data
        line, _, self.buf = self.buf.partition(b"\n")
        return line.decode("ascii", "replace").strip()

    def cmd(self, c, query=None):
        self.send(c)
        if query is None:
            query = "?" in c
        return self.readline() if query else None

    def close(self):
        try:
            self.chan.close()
        except Exception:
            pass


def canal(cli, porta, timeout=20):
    tr = cli.get_transport()
    ch = tr.open_channel("direct-tcpip", ("127.0.0.1", porta), ("127.0.0.1", 0),
                         timeout=timeout)
    ch.settimeout(timeout)
    return ChanIO(ch)


def abrir_rc(cli):
    """Percorre 8000 -> modulo -> remote control. Devolve o ChanIO da porta RC."""
    io = canal(cli, 8000)
    io.cmd("*REM", query=False)
    pm = int(io.cmd('MOD:FUNC:PORT? BOTH,BASE,"BERT"'))
    io.close()
    if pm < 0:
        sys.exit("ERRO: modulo BERT nao esta ready (-1).")

    io = canal(cli, pm)
    io.cmd("*REM", query=False)
    prc = int(io.cmd(':SYST:FUNC:PORT? BOTH,BASE,"BERT"'))
    io.close()
    if prc < 0:
        sys.exit("ERRO: remote control port -1.")

    io = canal(cli, prc, timeout=90)
    io.cmd("*REM VISIBLE FULL")  # mantem a GUI/VNC vivos
    return io


# ------------------------------ acoes ------------------------------
def faz_token(io, tok):
    if tok == "traffic-on":
        io.cmd(":SOURCE:MAC:TRAFFIC ON")
        print("TRAFEGO LIGADO      ->", io.cmd(":SYSTem:ERRor?"))
    elif tok == "traffic-off":
        io.cmd(":SOURCE:MAC:TRAFFIC OFF")
        print("TRAFEGO DESLIGADO   ->", io.cmd(":SYSTem:ERRor?"))
    elif tok == "start":
        io.cmd(":INITiate")
        print("TESTE INICIADO      ->", io.cmd(":SYSTem:ERRor?"))
    elif tok == "stop":
        io.cmd(":ABORt")
        print("TESTE PARADO        ->", io.cmd(":SYSTem:ERRor?"))
    elif tok == "restart":
        io.cmd(":ABORt")
        io.cmd(":INITiate")
        print("TESTE REINICIADO    ->", io.cmd(":SYSTem:ERRor?"))
    elif tok == "results":
        sig = io.cmd(":SENSe:DATA? CSTatus:PHYSical:SIGNal")
        sync = io.cmd(":SENSe:DATA? CSTatus:PCS:PHY:SYNC:ACTive")
        tx = io.cmd(":SENSe:DATA? COUNT:MAC:ETH:TX:FRAME")
        rx = io.cmd(":SENSe:DATA? COUNT:MAC:ETH:FRAME")
        print(f"  Signal present     : {sig}")
        print(f"  PCS sync           : {sync}")
        print(f"  Transmitted Frames : {tx}")
        print(f"  Received Frames    : {rx}")
        try:
            d = int(tx) - int(rx)
            est = "OK (in == out)" if d == 0 else f"DIVERGENCIA ({d:+d} frames)"
            print(f"  TX - RX            : {d:+d}  -> {est}")
        except (TypeError, ValueError):
            pass
    elif tok.startswith("wait:"):
        seg = float(tok.split(":", 1)[1])
        print(f"... aguardando {seg}s ...")
        time.sleep(seg)
    elif tok.startswith(":"):  # comando SCPI cru
        if "?" in tok:
            print(f"{tok} -> {io.cmd(tok, query=True)}")
        else:
            io.cmd(tok, query=False)
            print(f"{tok} -> {io.cmd(':SYSTem:ERRor?')}")
    else:
        print(f"(token ignorado: {tok})")


def valida_token(tok):
    return (tok in VERBOS or tok.startswith("wait:") or tok.startswith(":"))


def main():
    global SETTLE, DELAY
    ap = argparse.ArgumentParser(description="Controle do MTS-5800-100G (comandos agrupados)")
    ap.add_argument("tokens", nargs="+", help="verbos e/ou comandos SCPI em sequencia")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--app", default=None)
    ap.add_argument("--service", default=DEFAULT_SERVICE)
    ap.add_argument("--settle", type=float, default=SETTLE,
                    help=f"espera (s) apos comandos criticos {sorted(SETTLE_TOKENS)} (default {SETTLE})")
    ap.add_argument("--delay", type=float, default=DELAY,
                    help=f"espera (s) entre os demais comandos (default {DELAY})")
    ap.add_argument("--watchdog", type=float, default=0,
                    help="teto absoluto (s) do processo; 0 = auto (90s + waits)")
    args = ap.parse_args()
    SETTLE = args.settle
    DELAY = args.delay

    invalidos = [t for t in args.tokens if not valida_token(t)]
    if invalidos:
        sys.exit(f"ERRO: token(s) invalido(s): {invalidos}\nVerbos: {sorted(VERBOS)} | wait:N | \":SCPI\"")

    # watchdog: base + qualquer espera explicita (wait:N) para nao disparar em run lento
    espera_prevista = sum(float(t.split(":", 1)[1]) for t in args.tokens
                          if t.startswith("wait:"))
    armar_watchdog(args.watchdog if args.watchdog > 0 else WATCHDOG_BASE + espera_prevista)

    pw = wc.get_password(args.service, args.user,
                         message=f"Senha SSH do MTS ({args.user}@{args.host}): ")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[ssh] conectando {args.user}@{args.host} ...")
    # Retry: "Error reading SSH protocol banner"/EOF sao transitorios - o sshd
    # embarcado (dropbear) derruba a conexao quando chegam duas quase juntas
    # (ex.: outra instancia da macro rodando). Algumas tentativas resolvem.
    # AuthenticationException NAO tem retry (senha errada nao melhora tentando).
    ultimo_erro = None
    for tentativa in range(1, 4):
        try:
            cli.connect(args.host, username=args.user, password=pw,
                        look_for_keys=False, allow_agent=False, timeout=15,
                        banner_timeout=15, auth_timeout=15)
            ultimo_erro = None
            break
        except paramiko.AuthenticationException:
            raise
        except Exception as e:
            ultimo_erro = e
            print(f"[ssh] tentativa {tentativa}/3 falhou ({type(e).__name__}: {e}); "
                  "nova tentativa em 3s...")
            time.sleep(3)
    if ultimo_erro is not None:
        raise ultimo_erro
    # keepalive: se a rede engolir a conexao, o transport levanta EOF em ~15s
    # (3 pings de 5s sem resposta) em vez de ficar preso indefinidamente.
    tr = cli.get_transport()
    if tr is not None:
        tr.set_keepalive(5)
    try:
        io = abrir_rc(cli)
        rodando = io.cmd(":SYSTem:APPLication:CAPPlications?")
        apps = [a for a in (rodando or "").split(",") if a]
        alvo = args.app or (apps[0] if apps else None)

        precisa_app = any(t != "status" for t in args.tokens)
        if precisa_app:
            if not alvo:
                sys.exit("ERRO: nenhum app rodando (faca LAUNch antes, ou use --app).")
            io.cmd(f":SYSTem:APPLication:SELect {alvo}")
            print(f"App: {alvo}  ({io.cmd(':SYSTem:ERRor?')})")
            io.cmd(":SESSion:CREate")
            io.cmd(":SESSion:STARt")

        try:
            n = len(args.tokens)
            for idx, tok in enumerate(args.tokens):
                if tok == "status":
                    print("Apps rodando:", rodando or "(nenhum)")
                    print("App alvo    :", alvo or "(nenhum)")
                else:
                    faz_token(io, tok)
                # delay de estabilizacao entre comandos (nao apos o ultimo nem apos wait:)
                if idx < n - 1 and not tok.startswith("wait:"):
                    d = SETTLE if tok in SETTLE_TOKENS else DELAY
                    if d > 0:
                        print(f"... estabilizando {d}s ...")
                        time.sleep(d)
        finally:
            if precisa_app:
                io.cmd(":SESSion:END", query=False)
            io.close()
    finally:
        cli.close()
        print("[ssh] fechado.")


if __name__ == "__main__":
    main()
