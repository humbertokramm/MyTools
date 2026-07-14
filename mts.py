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

Opcoes:
    --host 172.22.239.40   IP do MTS (default)
    --user tb-5800         usuario SSH (default; alt: mts-5800)
    --app  <id>            forca o app alvo (default: 1o app rodando)
    --service MTS-5800     nome do servico no Credential Manager (default)
"""
import argparse
import sys
import time

import paramiko

import win_credential as wc

DEFAULT_HOST = "172.22.239.40"
DEFAULT_USER = "tb-5800"
DEFAULT_SERVICE = "MTS-5800"
VERBOS = {"traffic-on", "traffic-off", "start", "stop", "restart", "results", "status"}


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
    ap = argparse.ArgumentParser(description="Controle do MTS-5800-100G (comandos agrupados)")
    ap.add_argument("tokens", nargs="+", help="verbos e/ou comandos SCPI em sequencia")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--app", default=None)
    ap.add_argument("--service", default=DEFAULT_SERVICE)
    args = ap.parse_args()

    invalidos = [t for t in args.tokens if not valida_token(t)]
    if invalidos:
        sys.exit(f"ERRO: token(s) invalido(s): {invalidos}\nVerbos: {sorted(VERBOS)} | wait:N | \":SCPI\"")

    pw = wc.get_password(args.service, args.user,
                         message=f"Senha SSH do MTS ({args.user}@{args.host}): ")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[ssh] conectando {args.user}@{args.host} ...")
    cli.connect(args.host, username=args.user, password=pw,
                look_for_keys=False, allow_agent=False, timeout=15)
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
            for tok in args.tokens:
                if tok == "status":
                    print("Apps rodando:", rodando or "(nenhum)")
                    print("App alvo    :", alvo or "(nenhum)")
                else:
                    faz_token(io, tok)
        finally:
            if precisa_app:
                io.cmd(":SESSion:END", query=False)
            io.close()
    finally:
        cli.close()
        print("[ssh] fechado.")


if __name__ == "__main__":
    main()
