"""Diagnostico do slot de remote control SCPI do MTS-5800 (read-only via SSH).

Objetivo: quando o SCPI trava (PipeTimeout ao ler a porta 8000), descobrir o
que segura o slot SEM reiniciar o instrumento - conexoes TCP penduradas na
8000/portas de modulo, e o processo dono da porta. Com isso avaliamos se da
para destravar sem reboot (ex.: derrubar uma conexao CLOSE_WAIT, reiniciar so
o servico dono da porta).

Uso: py mts_scpi_diag.py            (so coleta, nao altera nada)

Senha vem do Windows Credential Manager (win_credential), servico "MTS-5800".
"""
import os
import sys
import threading

import paramiko

import win_credential as wc

HOST = "172.22.239.50"
USER = "tb-5800"
SERVICE = "MTS-5800"

# tudo read-only
CMDS = [
    ("data/hora", "date"),
    ("portas SCPI abertas (8000-8099)",
     "ss -tan 2>/dev/null | grep -E ':80[0-9][0-9]' || netstat -tan 2>/dev/null | grep -E ':80[0-9][0-9]'"),
    ("conexoes com PID (so processos do usuario)",
     "ss -tanp 2>/dev/null | grep -E ':80[0-9][0-9]'"),
    ("processos donos da 8000 (lsof, se houver)",
     "lsof -i :8000 2>/dev/null || echo '(sem lsof ou sem permissao)'"),
    ("processos SCPI/remote/BERT",
     "ps -ef 2>/dev/null | grep -iE 'scpi|remote|bert|resultserver|expresso' | grep -v grep || ps aux 2>/dev/null | grep -iE 'scpi|remote|bert' | grep -v grep"),
    ("servicos systemd relacionados",
     "systemctl list-units --type=service --no-pager 2>/dev/null | grep -iE 'scpi|remote|bert|test' || echo '(list-units indisponivel)'"),
    ("posso mexer em servico? (dry-run)",
     "systemctl status 2>/dev/null | head -1; echo '---'; ls -l /sbin/reboot"),
]


def armar_watchdog(segundos=60):
    def matar():
        sys.stderr.write(f"\n!!! WATCHDOG: excedeu {segundos}s - encerrando.\n")
        sys.stderr.flush()
        os._exit(3)
    t = threading.Timer(segundos, matar)
    t.daemon = True
    t.start()


def run(cli, cmd, timeout=15):
    _, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    rc = stdout.channel.recv_exit_status()
    return rc, out, err


def main():
    armar_watchdog(60)
    pw = wc.get_password(SERVICE, USER, message=f"Senha SSH do MTS ({USER}@{HOST}): ")
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"[ssh] conectando {USER}@{HOST} ...")
    cli.connect(HOST, username=USER, password=pw,
                look_for_keys=False, allow_agent=False, timeout=15,
                banner_timeout=15, auth_timeout=15)
    try:
        for titulo, cmd in CMDS:
            print(f"\n=== {titulo} ===")
            print(f"$ {cmd}")
            rc, out, err = run(cli, cmd)
            if out:
                print(out)
            if err:
                print(f"[stderr] {err}")
    finally:
        cli.close()
        print("\n[ssh] fechado.")


if __name__ == "__main__":
    main()
