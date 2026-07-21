"""Diagnostico SSH do MTS-5800: descobre se da para reiniciar remoto via shell.

Roda uma bateria de comandos READ-ONLY (nao reinicia nada) para responder:
  - o usuario tb-5800 cai num shell de verdade? (exec_command funciona?)
  - qual e o uid (root?) e o SO
  - existem reboot/shutdown/systemctl/poweroff no PATH?
  - da para usar sudo sem senha?

Com base na saida, decidimos o comando de reboot certo (rodado depois,
manualmente, com --reboot).

Uso:
    py mts_ssh_diag.py            # so diagnostico read-only
    py mts_ssh_diag.py --reboot   # APOS confirmar o metodo, dispara o reboot

Senha vem do Windows Credential Manager (win_credential), servico "MTS-5800".
"""
import argparse
import os
import sys
import threading

import paramiko

import win_credential as wc

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

HOST = "172.22.239.50"
USER = "tb-5800"
SERVICE = "MTS-5800"

# comandos read-only de diagnostico (nao alteram estado)
DIAG = [
    "whoami",
    "id",
    "uname -a",
    "cat /etc/os-release 2>/dev/null | head -3",
    "command -v reboot shutdown systemctl poweroff halt 2>/dev/null",
    "sudo -n true 2>&1; echo sudo_exit=$?",
]


def armar_watchdog(segundos=60):
    def matar():
        sys.stderr.write(f"\n!!! WATCHDOG: excedeu {segundos}s - encerrando.\n")
        sys.stderr.flush()
        os._exit(3)
    t = threading.Timer(segundos, matar)
    t.daemon = True
    t.start()


def run(cli, cmd, timeout=15, senha=None):
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    # comandos 'sudo -S' leem a senha da primeira linha do stdin
    if senha is not None and "sudo -S" in cmd:
        stdin.write(senha + "\n")
        stdin.flush()
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def main():
    ap = argparse.ArgumentParser(description="Diagnostico/reboot SSH do MTS-5800")
    ap.add_argument("--host", default=HOST)
    ap.add_argument("--user", default=USER)
    ap.add_argument("--service", default=SERVICE)
    ap.add_argument("--reboot", action="store_true",
                    help="APOS confirmar o metodo no diagnostico, dispara o reboot")
    ap.add_argument("--exec", dest="execcmd", default=None,
                    help="roda um comando arbitrario via SSH (senha via stdin se 'sudo -S')")
    ap.add_argument("--cmd", default=None,
                    help="comando de reboot a usar (ex: 'sudo reboot'); "
                         "default tenta reboot -> sudo reboot -> systemctl reboot")
    args = ap.parse_args()

    armar_watchdog(60)
    pw = wc.get_password(args.service, args.user,
                         message=f"Senha SSH do MTS ({args.user}@{args.host}): ")

    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[ssh] conectando {args.user}@{args.host} ...")
    cli.connect(args.host, username=args.user, password=pw,
                look_for_keys=False, allow_agent=False, timeout=15,
                banner_timeout=15, auth_timeout=15)
    try:
        if args.execcmd:
            print(f"$ {args.execcmd}")
            rc, out, err = run(cli, args.execcmd, timeout=20, senha=pw)
            if out:
                print(out)
            if err:
                print(f"[stderr] {err}")
            print(f"[exit={rc}]")
        elif not args.reboot:
            print("=== DIAGNOSTICO (read-only) ===")
            for cmd in DIAG:
                rc, out, err = run(cli, cmd)
                print(f"\n$ {cmd}")
                if out:
                    print(out)
                if err:
                    print(f"[stderr] {err}")
                print(f"[exit={rc}]")
            print("\nInterprete: se 'id' mostrar uid=0(root) -> 'reboot' direto deve "
                  "funcionar. Se sudo_exit=0 -> 'sudo reboot' funciona sem senha. "
                  "Se exec_command retornar vazio/erro em tudo -> shell restrito, "
                  "reboot via SSH nao e viavel (usar o botao/GUI).")
        else:
            candidatos = [args.cmd] if args.cmd else [
                "systemctl reboot", "sudo -S systemctl reboot", "sudo -S reboot"]
            print("=== REBOOT ===")
            for cmd in candidatos:
                print(f"\n$ {cmd}")
                try:
                    rc, out, err = run(cli, cmd, timeout=10, senha=pw)
                    if out:
                        print(out)
                    if err:
                        print(f"[stderr] {err}")
                    print(f"[exit={rc}]")
                    # se o reboot pegou, a conexao cai (exit pode nem voltar)
                    if rc == 0:
                        print(">>> comando aceito; o MTS deve estar reiniciando.")
                        break
                except Exception as e:
                    print(f"[erro/queda de conexao: {type(e).__name__}: {e}]")
                    print(">>> provavelmente reiniciou (conexao caiu).")
                    break
    finally:
        cli.close()
        print("\n[ssh] fechado.")


if __name__ == "__main__":
    main()
