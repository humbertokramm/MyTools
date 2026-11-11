"""
emissao_captura.py  --  Sequencias de captura de emissao radiada e conduzida
(N9010A), sem interface. Usado pelo emissao_gui.py.

Mesma sequencia e mesmos nomes de arquivo dos scripts de console que
vieram antes (radiada_capture.py e conduzida_capture.py, ja removidos; estao
no historico do git), com estas diferencas:
  - a conduzida tambem salva os traces em CSV e as limit lines, para
    analise depois (antes era so o PNG da tela);
  - o rotulo de cada trace (Max, Med...) vem do tipo do trace no
    analisador, e nao de uma lista fixa;
  - da para abortar no meio de uma varredura;
  - cada execucao grava numa subpasta com a hora (10h32), entao repetir
    uma medida nao sobrescreve a anterior;
  - a conduzida sugere uma captura detalhada extra quando a faixa completa
    mostra pico perto do limite numa regiao sem zoom.

Compativel com Python 3.8 (o exe roda no Windows 7).
"""

import math
import os
import time
from datetime import datetime

# Estados no disco do analisador, por ensaio e classe
STATES = {
    'Radiada': {
        'A': r'D:\State\Setup_Emissao_Radiada_Classe_A_Desenvolvimento.state',
        'B': r'D:\State\Setup_Emissao_Radiada_Classe_B_Desenvolvimento.state',
    },
    'Conduzida': {
        'A': r'D:\State\Setup_Emissao_Conduzida_Classe_A_Desenvolvimento.state',
        'B': r'D:\State\Setup_Emissao_Conduzida_Classe_B_Desenvolvimento.state',
    },
}

BANDAS = {
    'Radiada': [(30e6 + 100e6 * i, min(130e6 + 100e6 * i, 1000e6)) for i in range(10)],
    'Conduzida': [(150e3, 30e6), (150e3, 1e6)],
}

VARREDURAS = {'Radiada': 30, 'Conduzida': 100}

# Tipo do trace no analisador -> sufixo do arquivo
ROTULO_TIPO = {
    'MAXH': 'Max', 'MAXHOLD': 'Max',
    'AVER': 'Med', 'AVERAGE': 'Med',
    'MINH': 'Min', 'MINHOLD': 'Min',
    'WRIT': 'Clr', 'WRITE': 'Clr',
}


class Cancelado(Exception):
    """Operador abortou a sequencia."""


# -----------------------------------------------------------------------
# Nomes de arquivo (identicos aos scripts originais)
# -----------------------------------------------------------------------

def faixa_str(freq_ini, freq_fim):
    """'150kHz-30MHz', como nos nomes de arquivo da conduzida."""
    def _fmt(hz):
        if hz >= 1e6 and hz % 1e6 == 0:
            return '{:.0f}MHz'.format(hz / 1e6)
        if hz >= 1e3:
            return '{:.0f}kHz'.format(hz / 1e3)
        return '{:.0f}Hz'.format(hz)
    return '{}-{}'.format(_fmt(freq_ini), _fmt(freq_fim))


def nome_radiada(local, pol, classe, tensao, freq_ini, freq_fim, rotulo=''):
    faixa = '{:.0f}MHz-{:.0f}MHz'.format(freq_ini / 1e6, freq_fim / 1e6)
    suf = ' - ' + rotulo if rotulo else ''
    if local == 'EUT':
        return '{} Radiada - {} - EUT - Classe {} {}V{}'.format(
            faixa, pol, classe, tensao, suf)
    return '{} Radiada - {} - Ambiente - Classe {}{}'.format(faixa, pol, classe, suf)


def nome_conduzida(linha, tensao, freq_ini, freq_fim, rotulo=''):
    base = '{}_{}_{}'.format(linha, tensao, faixa_str(freq_ini, freq_fim))
    return base + (' - ' + rotulo if rotulo else '')


def _data_hora(quando=None):
    """('2026-11-11', '10h32'). A hora vira subpasta: cada execucao fica na
    sua, entao repetir uma medida nao sobrescreve a anterior. 'h' no lugar
    de ':' porque o Windows nao aceita ':' em nome de pasta."""
    quando = quando or datetime.now()
    return quando.strftime('%Y-%m-%d'), quando.strftime('%Hh%M')


def pasta_radiada(raiz, pol, tensao, quando=None):
    data, hora = _data_hora(quando)
    return os.path.join(raiz, 'Radiada', data, pol, tensao, hora)


def pasta_conduzida(raiz, quando=None):
    data, hora = _data_hora(quando)
    return os.path.join(raiz, 'Conduzida', data, hora)


# -----------------------------------------------------------------------
# Instrumento
# -----------------------------------------------------------------------

def rotulo_trace(sa, trace):
    """'Max', 'Med'... pelo tipo do trace no analisador; 'TraceN' se nao der."""
    try:
        tipo = sa.driver.inst.query(':TRACe' + trace[-1] + ':TYPE?').strip().upper()
    except Exception:
        tipo = ''
    return ROTULO_TIPO.get(tipo, trace)


def limit_lines(sa):
    """[(n, trace_ou_None, freq_hz, amp)] das limit lines habilitadas."""
    inst = sa.driver.inst
    res = []
    for n in range(1, 7):
        try:
            if inst.query(':CALCulate:LLINe{}:STATe?'.format(n)).strip() != '1':
                continue
            raw = inst.query(':CALCulate:LLINe{}:DATA?'.format(n)).strip()
        except Exception:
            continue
        try:
            tr = 'Trace' + str(int(float(
                inst.query(':CALCulate:LLINe{}:TRACe?'.format(n)).strip())))
        except Exception:
            tr = None
        vals = [float(v) for v in raw.split(',')]
        if vals[0::3]:
            res.append((n, tr, vals[0::3], vals[1::3]))
    return res


def salva_limite(path, freq_hz, amp):
    """CSV de limite no formato do agilent_sa (X em MHz)."""
    linhas = ['Limit', 'Number of Points,' + str(len(freq_hz)),
              'X Axis Units,MHz', 'Y Axis Units,dBuV', 'DATA']
    linhas += ['{:.10g},{:.15g}'.format(f / 1e6, a) for f, a in zip(freq_hz, amp)]
    with open(path, 'w') as fh:
        fh.write('\n'.join(linhas))


def varrer(sa, n, cancelado, timeout=1800):
    """Varredura unica com n medias; aborta se cancelado() ficar True.

    Faz o mesmo que SA.sweep_single, mas olhando o cancelamento a cada
    segundo. Retorna True se concluiu, False se estourou o timeout.
    """
    sa.driver.set_average(n)
    sa.driver._write(':INITiate:CONTinuous 0')
    sa.driver._write(':INITiate:RESTart')
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        time.sleep(1.0)
        if cancelado():
            try:
                sa.driver._write(':ABORt')
            except Exception:
                pass
            raise Cancelado()
        cond = int(sa.driver.inst.query(':STATus:OPERation:CONDition?').strip())
        if cond & 8 == 0:
            return True
    return False


# -----------------------------------------------------------------------
# Sequencias
# -----------------------------------------------------------------------

class Operador:
    """Interface com quem esta rodando. A GUI implementa; o padrao e console.

    prompt(texto)      espera o operador (EUT ligado, trocar a linha...)
    confirma(texto)    pergunta de sim/nao: True/False/None (None = abortar)
    log(texto)
    progresso(i, n)
    cancelado()        True quando o operador pediu para abortar
    alerta() / ok()    avisos sonoros antes e depois de cada varredura
    """

    def prompt(self, texto):
        input(texto + '  [ENTER]')

    def confirma(self, texto):
        return input(texto + ' (s/N) ').strip().lower() == 's'

    def log(self, texto):
        print(texto)

    def progresso(self, i, n):
        pass

    def cancelado(self):
        return False

    def alerta(self):
        pass

    def ok(self):
        pass


def _pode_gravar(op, caminhos):
    """Pergunta se ja existe algum dos arquivos. None aborta."""
    existentes = [p for p in caminhos if os.path.exists(p)]
    if not existentes:
        return True
    r = op.confirma('{} ja existe{}. Sobrescrever?\n\n'
                    'Sim: sobrescreve.  Nao: pula esta captura.'.format(
                        os.path.basename(existentes[0]),
                        ' (e mais {})'.format(len(existentes) - 1)
                        if len(existentes) > 1 else ''))
    if r is None:
        raise Cancelado()
    return r


def _captura(sa, op, n, pasta, nomes, traces, peak_table):
    """Varre e salva um CSV por trace + o PNG. nomes(rotulo) -> nome base.

    Retorna [(trace, rotulo, csv)], ou [] se o operador pulou a captura.
    """
    rotulos = [(t, rotulo_trace(sa, t)) for t in traces]
    csvs = [os.path.join(pasta, nomes(r) + '.csv') for _, r in rotulos]
    png = os.path.join(pasta, nomes('') + '.png')
    if not _pode_gravar(op, csvs + [png]):
        op.log('  pulado (arquivos mantidos)')
        return []

    op.alerta()
    op.log('  Varrendo {}x ... aguarde.'.format(n))
    if not varrer(sa, n, op.cancelado):
        op.log('  AVISO: timeout na varredura!')
    sa.pause()

    for (tr, _), path in zip(rotulos, csvs):
        sa.driver.export_csv(tr, path)

    sa.set_fullscreen(True)       # o load_state pode ter tirado o full screen
    if peak_table:
        sa.set_peak_table(True)
    img = sa.driver.capture_screen()
    if peak_table:
        sa.set_peak_table(False)
    with open(png, 'wb') as fh:
        fh.write(img)
    op.log('  PNG: ' + os.path.basename(png))
    op.ok()
    return [(t, r, path) for (t, r), path in zip(rotulos, csvs)]


def radiada(sa, op, raiz, classe, pol, tensao, n, bandas=None,
            traces=('Trace1', 'Trace2'), state=None):
    """Sequencia da radiada. Retorna a pasta da medida."""
    bandas = list(bandas or BANDAS['Radiada'])
    state = state or STATES['Radiada'][classe]
    pasta = pasta_radiada(raiz, pol, tensao)
    os.makedirs(os.path.join(pasta, 'full_band'), exist_ok=True)
    op.log('Pasta de saida: ' + pasta)

    # bandas divididas e, por ultimo, a banda completa (em full_band)
    full = (min(b[0] for b in bandas), max(b[1] for b in bandas))
    etapas = []           # (local, f0, f1, is_full, primeira_do_local)
    for local in ('EUT', 'Ambiente'):
        for j, b in enumerate(bandas):
            etapas.append((local, b[0], b[1], False, j == 0))
        etapas.append((local, full[0], full[1], True, False))
    limite_salvo = False
    sa.set_fullscreen(True)

    for i, (local, f0, f1, is_full, primeira) in enumerate(etapas):
        if op.cancelado():
            raise Cancelado()
        if primeira:
            op.prompt('EUT ligado, antena na polarizacao ' + pol if local == 'EUT'
                      else 'Desligue o EUT (medida de ambiente)')
        destino = os.path.join(pasta, 'full_band') if is_full else pasta
        op.progresso(i, len(etapas))
        op.log('\n[{}/{}] {} {:.0f}-{:.0f} MHz{}'.format(
            i + 1, len(etapas), local, f0 / 1e6, f1 / 1e6, '  (FULL BAND)' if is_full else ''))

        sa.load_state(state)
        sa.set_freq_range(f0, f1)

        if not limite_salvo:
            # so o primeiro limite, com o nome que o radiada_plot procura
            lim = limit_lines(sa)
            if lim:
                salva_limite(os.path.join(pasta, 'Radiada - Limite - Classe ' + classe + '.csv'),
                             lim[0][2], lim[0][3])
                op.log('  Limite salvo')
            else:
                op.log('  AVISO: nenhuma limit line habilitada no state!')
            limite_salvo = True

        _captura(sa, op, n, destino,
                 lambda r, local=local, f0=f0, f1=f1: nome_radiada(
                     local, pol, classe, tensao, f0, f1, r),
                 traces, peak_table=True)

    op.progresso(len(etapas), len(etapas))
    return pasta


# Regioes em que a conduzida ganha uma captura com mais detalhe quando a
# faixa completa mostra problema nelas
SEGMENTOS_ZOOM = [(150e3, 1e6), (1e6, 5e6), (5e6, 30e6)]
JANELA_ZOOM_DB = 6.0      # pico a menos disso do limite ja justifica o zoom


def _le_trace(path):
    """(freq_hz, amp) de um CSV salvo pelo agilent_sa."""
    f, a, dados = [], [], False
    with open(path) as fh:
        for linha in fh:
            linha = linha.strip()
            if linha == 'DATA':
                dados = True
            elif dados and ',' in linha:
                x, y = linha.split(',')[:2]
                f.append(float(x))
                a.append(float(y))
    return f, a


def _limite_em(f, lim_f, lim_a):
    """Limite em f, interpolando em log de frequencia (como o analisador)."""
    for i in range(len(lim_f) - 1):
        f0, f1 = lim_f[i], lim_f[i + 1]
        if f0 < f1 and f0 <= f <= f1:
            k = math.log10(f / f0) / math.log10(f1 / f0)
            return lim_a[i] + k * (lim_a[i + 1] - lim_a[i])
    return None


def piores_por_segmento(capturas, limites, segmentos=SEGMENTOS_ZOOM):
    """{segmento: (margem_dB, freq_hz, rotulo)} do pior ponto de cada regiao.

    capturas: [(trace, rotulo, csv)] de uma varredura; limites: {trace: (f, a)}.
    Margem positiva = acima do limite.
    """
    piores = {}
    for trace, rotulo, path in capturas:
        lim = limites.get(trace, limites.get(None))
        if lim is None:
            continue
        for f, a in zip(*_le_trace(path)):
            lv = _limite_em(f, lim[0], lim[1])
            if lv is None:
                continue
            for seg in segmentos:
                if seg[0] <= f <= seg[1] and (seg not in piores or a - lv > piores[seg][0]):
                    piores[seg] = (a - lv, f, rotulo)
    return piores


def conduzida(sa, op, raiz, classe, tensoes, n, bandas=None,
              traces=('Trace1', 'Trace2'), state=None, linhas=('L1', 'L2')):
    """Sequencia da conduzida: imagem, traces em CSV e limites.

    Depois da faixa mais larga de cada linha, olha os traces contra os
    limites: se houver pico perto do limite numa regiao sem captura
    detalhada, pergunta ao operador se quer captura-la tambem. A resposta
    vale para o resto da execucao (as outras linhas e tensoes).
    """
    bandas = [tuple(b) for b in (bandas or BANDAS['Conduzida'])]
    state = state or STATES['Conduzida'][classe]
    pasta = pasta_conduzida(raiz)
    os.makedirs(pasta, exist_ok=True)
    op.log('Pasta de saida: ' + pasta)

    larga = max(bandas, key=lambda b: b[1] - b[0])
    extras = []           # zooms que o operador aceitou
    decidido = set()      # regioes ja perguntadas nesta execucao
    limites = None        # {trace: (freq, amp)}
    feitas = 0

    def total():
        return len(tensoes) * len(linhas) * (len(bandas) + len(extras))

    def coberta(seg):
        return any(b != larga and b[0] <= seg[0] and b[1] >= seg[1]
                   for b in bandas + extras)

    for tensao in tensoes:
        for linha in linhas:
            if op.cancelado():
                raise Cancelado()
            op.prompt('Tensao {}: conecte a LISN ao condutor {}'.format(tensao, linha))
            fila = bandas + extras
            while fila:
                if op.cancelado():
                    raise Cancelado()
                f0, f1 = fila.pop(0)
                op.progresso(feitas, total())
                op.log('\n[{}/{}] {} {} {}'.format(feitas + 1, total(), tensao, linha,
                                                   faixa_str(f0, f1)))
                sa.load_state(state)
                sa.set_freq_range(f0, f1)

                if limites is None:
                    limites = {}
                    for _, tr, fq, amp in limit_lines(sa):
                        nome = 'Conduzida - Limite - Classe {}{}.csv'.format(
                            classe, ' - ' + tr if tr else '')
                        salva_limite(os.path.join(pasta, nome), fq, amp)
                        limites[tr] = (fq, amp)
                        op.log('  Limite salvo: ' + nome)

                capt = _captura(sa, op, n, pasta,
                                lambda r, linha=linha, tensao=tensao, f0=f0, f1=f1:
                                nome_conduzida(linha, tensao, f0, f1, r),
                                traces, peak_table=False)
                feitas += 1

                if (f0, f1) != larga or not capt:
                    continue
                for seg, (margem, fq, rotulo) in sorted(
                        piores_por_segmento(capt, limites).items()):
                    if (margem <= -JANELA_ZOOM_DB or seg in decidido or coberta(seg)
                            or seg[0] < larga[0] or seg[1] > larga[1]):
                        continue
                    decidido.add(seg)
                    r = op.confirma(
                        '{} em {}: pico {} em {:.3g} MHz ({}).\n\n'
                        'Capturar tambem a faixa {}, com mais detalhe?\n'
                        'Vale para as proximas linhas e tensoes desta execucao.'.format(
                            linha, tensao,
                            '{:.1f} dB ACIMA do limite'.format(margem) if margem > 0
                            else 'a {:.1f} dB do limite'.format(-margem),
                            fq / 1e6, rotulo, faixa_str(*seg)))
                    if r is None:
                        raise Cancelado()
                    if r:
                        extras.append(seg)
                        fila.append(seg)
                        op.log('  Faixa extra: ' + faixa_str(*seg))

    op.progresso(1, 1)
    return pasta
