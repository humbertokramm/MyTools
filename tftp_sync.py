#!/usr/bin/env python3
"""Mantem a pasta TFTP do pc da camara climatica igual a pasta TFTP local.

O DUT do Liem baixa os arquivos por TFTP do pc da camara (172.22.239.100),
que esta na rede dele; o pc do 1berto fica em outra rede e o TFTP direto e
instavel. Este app fica na bandeja vigiando C:\\Testes\\TFTP e manda por scp
cada arquivo novo ou alterado, entao o que esta la e sempre a ultima versao,
com ou sem macro aberta.

    pythonw tftp_sync.py            icone na bandeja (uso normal)
    python  tftp_sync.py --console  mesmo vigia, imprimindo no terminal
    python  tftp_sync.py --once     confere, manda o que falta e sai

So envia e atualiza: nada e apagado no pc da camara.
"""

import argparse
import fnmatch
import hashlib
import logging
import logging.handlers
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time

# ── Configuracao ─────────────────────────────────────────────────────────
PASTA      = r'C:\Testes\TFTP'
DESTINO    = 'datacom@172.22.239.100'
DIR_REMOTO = 'tftp/1berto'
# so a raiz da pasta, sem subpastas; para mandar o FPGA junto, acrescentar '*.rbf'
PADROES    = ('*.lua', '*.tar', '*.tar.gz')

INTERVALO  = 1.0    # s entre varreduras da pasta
REPETIR    = 30     # s ate tentar de novo depois de uma falha
T_SSH      = 120    # s de limite para cada scp/ssh

# os arquivos sobem para ca e so depois sao movidos para o lugar: o mv e
# atomico, entao o DUT nunca baixa um arquivo pela metade
DIR_TEMP   = '.envio'

NOME_APP   = 'TftpSync'
AQUI       = os.path.dirname(os.path.abspath(__file__))
ARQ_LOG    = os.path.join(AQUI, 'tftp_sync.log')
SSH_OPTS   = ['-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10']
SEM_JANELA = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

log = logging.getLogger('tftp_sync')


class Falha(Exception):
    pass


# ── ssh / scp ────────────────────────────────────────────────────────────
def _roda(cmd, cwd=None):
    """Roda ssh/scp escondido; devolve o stdout ou levanta Falha."""
    exe = shutil.which(cmd[0])
    if not exe:
        raise Falha('%s nao encontrado no PATH' % cmd[0])
    try:
        p = subprocess.run([exe] + cmd[1:], cwd=cwd, capture_output=True, text=True,
                           errors='replace', timeout=T_SSH, stdin=subprocess.DEVNULL,
                           creationflags=SEM_JANELA)
    except subprocess.TimeoutExpired:
        raise Falha('%s nao respondeu em %d s' % (cmd[0], T_SSH))
    if p.returncode != 0:
        # tira os avisos do proprio ssh (linhas com **) para sobrar o erro
        linhas = [l for l in p.stderr.splitlines() if l.strip() and not l.startswith('**')]
        raise Falha(linhas[-1] if linhas else '%s saiu com codigo %d' % (cmd[0], p.returncode))
    return p.stdout


def _ssh(comando):
    return _roda(['ssh'] + SSH_OPTS + [DESTINO, comando])


def hashes_remotos(nomes):
    """sha256 de cada arquivo que ja existe no pc da camara."""
    cmd = 'mkdir -p %s/%s && cd %s' % (DIR_REMOTO, DIR_TEMP, DIR_REMOTO)
    if nomes:
        # sha256sum reclama dos que ainda nao existem; isso nao e erro aqui
        cmd += ' && { sha256sum -- %s 2>/dev/null; true; }' % ' '.join(map(shlex.quote, nomes))
    res = {}
    for linha in _ssh(cmd).splitlines():
        partes = linha.split(None, 1)
        if len(partes) == 2:
            res[partes[1].lstrip('*').strip()] = partes[0]
    return res


def envia(nomes):
    """Copia para a pasta temporaria de la e move para o lugar."""
    _roda(['scp', '-q'] + SSH_OPTS + ['--'] + nomes + ['%s:%s/%s/' % (DESTINO, DIR_REMOTO, DIR_TEMP)],
          cwd=PASTA)
    origem = ' '.join(shlex.quote('%s/%s' % (DIR_TEMP, n)) for n in nomes)
    _ssh('cd %s && mv -f -- %s .' % (DIR_REMOTO, origem))


# ── pasta local ──────────────────────────────────────────────────────────
def varre():
    """{nome: (tamanho, mtime_ns)} dos arquivos da raiz que casam com PADROES."""
    res = {}
    try:
        with os.scandir(PASTA) as it:
            for e in it:
                if e.is_file() and any(fnmatch.fnmatch(e.name.lower(), p) for p in PADROES):
                    st = e.stat()
                    res[e.name] = (st.st_size, st.st_mtime_ns)
    except OSError as exc:
        raise Falha('pasta local: %s' % exc)
    return res


def sha256(nome):
    h = hashlib.sha256()
    with open(os.path.join(PASTA, nome), 'rb') as f:
        for bloco in iter(lambda: f.read(1 << 20), b''):
            h.update(bloco)
    return h.hexdigest()


# ── vigia ────────────────────────────────────────────────────────────────
class Vigia:
    """Laco de sincronismo; `aviso(estado, texto)` e chamado a cada mudanca."""

    def __init__(self, aviso=None):
        self.aviso = aviso or (lambda estado, texto: None)
        self.enviados = {}      # nome -> assinatura local que ja esta igual la
        self.conferir = True    # comparar por hash com o que esta la
        self.acorda = threading.Event()
        self.sair = False
        self.estado = None

    def _muda(self, estado, texto):
        if (estado, texto) != self.estado:
            self.estado = (estado, texto)
            (log.error if estado == 'erro' else log.info)(texto)
            self.aviso(estado, texto)

    def agora(self):
        """Pedido do menu: confere tudo de novo com o pc da camara."""
        self.conferir = True
        self.acorda.set()

    def para(self):
        self.sair = True
        self.acorda.set()

    def _confere(self, atual):
        """Marca como enviados os arquivos cujo conteudo ja e o mesmo la."""
        la = hashes_remotos(sorted(atual))
        self.enviados = {}
        for nome, sig in atual.items():
            if la.get(nome) == sha256(nome):
                self.enviados[nome] = sig
        self.conferir = False

    def passo(self, anterior, exige_estavel=True):
        """Uma varredura; devolve a foto da pasta para a proxima chamada."""
        atual = varre()
        if self.conferir:
            self._muda('enviando', 'Conferindo com o pc da camara...')
            self._confere(atual)
        mudou = [n for n, sig in atual.items() if self.enviados.get(n) != sig]
        # so manda o que nao mudou desde a varredura anterior: assim nao vai
        # um .tar.gz que ainda esta sendo gravado
        prontos = sorted(n for n in mudou if not exige_estavel or anterior.get(n) == atual[n])
        if prontos:
            self._muda('enviando', 'Enviando ' + ', '.join(prontos))
            envia(prontos)
            depois = varre()
            for n in prontos:
                if depois.get(n) == atual[n]:   # se mudou durante o envio, vai de novo
                    self.enviados[n] = atual[n]
            self._muda('ok', '%s - enviado: %s' % (time.strftime('%H:%M:%S'), ', '.join(prontos)))
        elif not mudou:
            if self.estado is None or self.estado[0] != 'ok':
                self._muda('ok', '%s - em dia (%d arquivos)' % (time.strftime('%H:%M:%S'), len(atual)))
        return atual

    def roda(self):
        anterior = {}
        while not self.sair:
            espera = INTERVALO
            try:
                anterior = self.passo(anterior)
            except Falha as exc:
                self._muda('erro', 'Falha: %s' % exc)
                espera = REPETIR
            except Exception:
                log.exception('erro inesperado')
                self._muda('erro', 'Erro inesperado (ver tftp_sync.log)')
                espera = REPETIR
            self.acorda.wait(espera)
            self.acorda.clear()


# ── bandeja ──────────────────────────────────────────────────────────────
CORES = {'ok': (46, 160, 67), 'enviando': (219, 171, 9), 'erro': (207, 34, 46)}


def _icone(estado):
    from PIL import Image, ImageDraw
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 62, 62), fill=CORES[estado])
    # seta para cima: e um envio
    d.polygon([(32, 12), (50, 32), (39, 32), (39, 52), (25, 52), (25, 32), (14, 32)],
              fill=(255, 255, 255))
    return img


def _comando_inicio():
    exe = sys.executable
    semjanela = os.path.join(os.path.dirname(exe), 'pythonw.exe')
    if os.path.exists(semjanela):
        exe = semjanela
    return '"%s" "%s"' % (exe, os.path.abspath(__file__))


CHAVE_RUN = r'Software\Microsoft\Windows\CurrentVersion\Run'


def _inicia_com_windows():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as k:
            return winreg.QueryValueEx(k, NOME_APP)[0] == _comando_inicio()
    except OSError:
        return False


def _alterna_inicio():
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if _inicia_com_windows():
            winreg.DeleteValue(k, NOME_APP)
        else:
            winreg.SetValueEx(k, NOME_APP, 0, winreg.REG_SZ, _comando_inicio())


def bandeja():
    import pystray
    import win32api
    import win32event
    import winerror

    # uma instancia so: duas mandariam os mesmos arquivos ao mesmo tempo
    trava = win32event.CreateMutex(None, False, 'Local\\' + NOME_APP)
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        return 0

    situacao = {'texto': 'Iniciando...'}

    def aviso(estado, texto):
        situacao['texto'] = texto
        icone.icon = _icone(estado)
        icone.title = ('TFTP -> camara: ' + texto)[:120]
        icone.update_menu()
        if estado == 'erro':
            try:
                icone.notify(texto[:200], 'Sincronismo TFTP parado')
            except Exception:
                pass

    vigia = Vigia(aviso)

    def sair(icon, item):
        vigia.para()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: situacao['texto'][:80], None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Sincronizar agora', lambda icon, item: vigia.agora(), default=True),
        pystray.MenuItem('Abrir pasta TFTP', lambda icon, item: os.startfile(PASTA)),
        pystray.MenuItem('Abrir log', lambda icon, item: os.startfile(ARQ_LOG)),
        pystray.MenuItem('Iniciar com o Windows', lambda icon, item: _alterna_inicio(),
                         checked=lambda item: _inicia_com_windows()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Sair', sair),
    )
    icone = pystray.Icon(NOME_APP, _icone('enviando'), 'TFTP -> camara', menu)
    threading.Thread(target=vigia.roda, daemon=True).start()
    icone.run()
    del trava
    return 0


# ── entrada ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='Sincroniza %s com %s:%s' % (PASTA, DESTINO, DIR_REMOTO))
    ap.add_argument('--once', action='store_true', help='confere, manda o que falta e sai')
    ap.add_argument('--console', action='store_true', help='vigia no terminal, sem bandeja')
    args = ap.parse_args()

    fmt = logging.Formatter('[%(asctime)s] %(message)s', '%Y-%m-%d %H:%M:%S')
    arq = logging.handlers.RotatingFileHandler(ARQ_LOG, maxBytes=500000, backupCount=1,
                                               encoding='utf-8')
    arq.setFormatter(fmt)
    log.addHandler(arq)
    log.setLevel(logging.INFO)
    if args.once or args.console:
        tela = logging.StreamHandler()
        tela.setFormatter(fmt)
        log.addHandler(tela)

    if args.once:
        try:
            Vigia().passo({}, exige_estavel=False)
        except Falha as exc:
            log.error('Falha: %s', exc)
            return 1
        return 0
    if args.console:
        vigia = Vigia()
        try:
            vigia.roda()
        except KeyboardInterrupt:
            pass
        return 0
    return bandeja()


if __name__ == '__main__':
    sys.exit(main())
