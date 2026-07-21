#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
registrarhook.py - Instala o hook `commit-msg` do Gerrit num repositorio git.

O hook `commit-msg` e quem injeta a linha `Change-Id:` na mensagem de commit
(exigida pelo Gerrit no `git push HEAD:refs/for/<branch>`). Ele mora em
`.git/hooks/`, que NAO vem no clone -- por isso todo repo novo do Gerrit precisa
dele instalado uma vez.

Neste ambiente (Datacom) a autenticacao SSH no Gerrit e via PuTTY/Pageant, entao
o download e feito com `pscp` (nao o `scp` do OpenSSH, que da publickey denied).
Se o pscp/Pageant nao estiver disponivel, cai no fallback por HTTPS.

Uso:
    py registrarhook.py [caminho_do_repo]     # default: diretorio atual
    py registrarhook.py --https               # forca o fallback HTTPS
    py registrarhook.py --test                # apos instalar, faz commit vazio
                                              #   de teste e desfaz (valida o hook)
    py registrarhook.py --user OUTRO_USER     # sobrescreve o usuario do pscp
    py registrarhook.py --remote upstream     # usa outro remote (default: origin)
"""

import argparse
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
from urllib.parse import urlparse

PSCP_CANDIDATES = [
    r"C:\Program Files\PuTTY\pscp.exe",
    r"C:\Program Files (x86)\PuTTY\pscp.exe",
]


def run(cmd, **kw):
    """Executa comando e devolve (rc, stdout+stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def git(repo, *args):
    rc, out = run(["git", "-C", repo, *args])
    return rc, out.strip()


def achar_pscp():
    p = shutil.which("pscp")
    if p:
        return p
    for c in PSCP_CANDIDATES:
        if os.path.isfile(c):
            return c
    return None


def parse_remote(url):
    """Extrai (user, host, port) de uma URL de remote ssh do Gerrit."""
    # Formatos: ssh://[user@]host[:port]/proj  ou  [user@]host:proj
    if "://" in url:
        u = urlparse(url)
        return u.username, u.hostname, (u.port or 22)
    # forma scp-like user@host:proj
    user = None
    rest = url
    if "@" in rest.split(":", 1)[0]:
        user, rest = rest.split("@", 1)
    host = rest.split(":", 1)[0]
    return user, host, 22


def baixar_via_pscp(pscp, user, host, port, destino):
    alvo = f"{user}@{host}:hooks/commit-msg"
    cmd = [pscp, "-P", str(port), alvo, destino]
    print(f"  -> pscp {alvo}  (porta {port})")
    # 'y' aceita o host key na primeira conexao; ignorado se ja estiver em cache.
    p = subprocess.run(cmd, input="y\n", capture_output=True, text=True)
    if p.returncode != 0:
        print((p.stdout or "") + (p.stderr or ""))
    return p.returncode == 0


def baixar_via_https(host, destino):
    url = f"https://{host}/tools/hooks/commit-msg"
    print(f"  -> HTTPS {url}")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE  # Gerrit interno costuma ter cert self-signed
    try:
        with urllib.request.urlopen(url, timeout=15, context=ctx) as r:
            if r.status != 200:
                print(f"  HTTP {r.status}")
                return False
            dados = r.read()
        with open(destino, "wb") as f:
            f.write(dados)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  falhou: {e}")
        return False


def tornar_executavel(caminho):
    try:
        st = os.stat(caminho)
        os.chmod(caminho, st.st_mode | 0o755)
    except OSError:
        pass  # no Windows/NTFS o bit e ignorado pelo Git; nao e critico


def validar_conteudo(caminho):
    try:
        with open(caminho, "r", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except OSError:
        return False
    return "Change-Id" in txt and "gerrit" in txt.lower()


def teste_commit(repo):
    """Faz um commit vazio, confere o Change-Id e desfaz (soft)."""
    rc, _ = git(repo, "commit", "--allow-empty", "-m", "teste hook change-id")
    if rc != 0:
        print("  [teste] nao consegui criar o commit de teste (repo ocupado?)")
        return False
    rc, msg = git(repo, "log", "-1", "--format=%B")
    ok = "Change-Id:" in msg
    git(repo, "reset", "--soft", "HEAD~1")  # desfaz mantendo a arvore
    if ok:
        linha = next(l for l in msg.splitlines() if l.startswith("Change-Id:"))
        print(f"  [teste] OK -> {linha.strip()}")
    else:
        print("  [teste] FALHOU: commit saiu sem Change-Id")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Instala o hook commit-msg do Gerrit.")
    ap.add_argument("repo", nargs="?", default=".", help="caminho do repo (default: .)")
    ap.add_argument("--remote", default="origin", help="nome do remote (default: origin)")
    ap.add_argument("--user", help="usuario para o pscp (default: o do remote ou o do SO)")
    ap.add_argument("--https", action="store_true", help="forca o download por HTTPS")
    ap.add_argument("--test", action="store_true", help="valida com commit vazio de teste")
    args = ap.parse_args()

    repo = os.path.abspath(args.repo)
    if not os.path.isdir(repo):
        sys.exit(f"ERRO: {repo} nao existe.")

    rc, git_dir = git(repo, "rev-parse", "--absolute-git-dir")
    if rc != 0:
        sys.exit(f"ERRO: {repo} nao e um repositorio git.")

    hooks_dir = os.path.join(git_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    destino = os.path.join(hooks_dir, "commit-msg")

    rc, url = git(repo, "remote", "get-url", args.remote)
    if rc != 0:
        sys.exit(f"ERRO: remote '{args.remote}' nao encontrado neste repo.")
    user, host, port = parse_remote(url)
    if not host:
        sys.exit(f"ERRO: nao consegui extrair o host de: {url}")
    user = args.user or user or os.getenv("USERNAME") or os.getenv("USER")

    print(f"Repo:   {repo}")
    print(f"Remote: {url}")
    print(f"Gerrit: {host}:{port}  (usuario pscp: {user})")
    print(f"Hook:   {destino}")

    sucesso = False
    if not args.https:
        pscp = achar_pscp()
        if pscp:
            sucesso = baixar_via_pscp(pscp, user, host, port, hooks_dir)
            if not sucesso:
                print("  pscp falhou; tentando HTTPS...")
        else:
            print("  pscp nao encontrado; usando HTTPS...")
    if not sucesso:
        sucesso = baixar_via_https(host, destino)

    if not sucesso or not os.path.isfile(destino):
        sys.exit("\nERRO: nao foi possivel baixar o hook commit-msg.")

    tornar_executavel(destino)

    if not validar_conteudo(destino):
        sys.exit("\nERRO: o arquivo baixado nao parece ser o hook do Gerrit.")

    tam = os.path.getsize(destino)
    print(f"\nOK: hook instalado ({tam} bytes).")

    if args.test:
        teste_commit(repo)

    print("Pronto -- os proximos commits vao gerar o Change-Id automaticamente.")


if __name__ == "__main__":
    main()
