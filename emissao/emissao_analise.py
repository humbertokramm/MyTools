"""
emissao_analise.py  --  Leitura e plot das medidas de emissao radiada e
conduzida, desenhando numa Figure que a GUI fornece (emissao_gui.py).

A leitura dos CSVs, a costura das sub-bandas e a deteccao dos conjuntos
Max/Med vem do radiada_plot.py, que continua valendo sozinho.

Compativel com Python 3.8 (o exe roda no Windows 7).
"""

import os
import re
import glob

import numpy as np
import matplotlib.ticker as ticker
from matplotlib.widgets import SpanSelector

import radiada_plot as rp

BG, GRID, SPINE, TXT = '#1c1c1c', '#2e2e2e', '#555', '#cccccc'
VERMELHO = '#e63946'

# janela, em dB abaixo do limite, em que um pico ja entra na tabela
JANELA_DB = 6.0
MAX_PICOS = 15

_RE_COND = re.compile(r'^(L\d)_(.+)_([\d.]+k?M?Hz-[\d.]+k?M?Hz) - (.+)\.csv$', re.I)


# -----------------------------------------------------------------------
# O que existe na pasta de medidas
# -----------------------------------------------------------------------

def _subpastas(p):
    try:
        return sorted(d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d)))
    except OSError:
        return []


def grupos_conduzida(pasta):
    """{(tensao, faixa): {linha: {rotulo: caminho}}} dos CSVs da pasta."""
    grupos = {}
    for path in sorted(glob.glob(os.path.join(pasta, '*.csv'))):
        m = _RE_COND.match(os.path.basename(path))
        if m:
            linha, tensao, faixa, rotulo = m.groups()
            grupos.setdefault((tensao, faixa), {}).setdefault(linha.upper(), {})[rotulo] = path
    return grupos


_RE_HORA = re.compile(r'^(\d\d)h(\d\d)$')


def _execucoes(base):
    """[(hora 'hh:mm' ou '', pasta)] de uma pasta de medida.

    As capturas pela janela ficam numa subpasta por execucao (10h32); as
    antigas, dos scripts de console, ficam direto na pasta (hora '').
    """
    res = [('', base)]
    for d in _subpastas(base):
        m = _RE_HORA.match(d)
        if m:
            res.append(('{}:{}'.format(*m.groups()), os.path.join(base, d)))
    return res


def lista_medidas(raiz):
    """Medidas sob *raiz*, mais novas primeiro.

    Cada item: dict(tipo, data, hora, nome, pasta, chave). 'chave' e
    (tensao, faixa) na conduzida e None na radiada; 'hora' e '' nas medidas
    sem subpasta de execucao.
    """
    itens = []
    rad = os.path.join(raiz, 'Radiada')
    for data in _subpastas(rad):
        for pol in _subpastas(os.path.join(rad, data)):
            for tensao in _subpastas(os.path.join(rad, data, pol)):
                for hora, base in _execucoes(os.path.join(rad, data, pol, tensao)):
                    for sub, sufixo in (('', ''), ('full_band', ' (full band)')):
                        p = os.path.join(base, sub) if sub else base
                        if glob.glob(os.path.join(p, '*EUT*.csv')):
                            itens.append(dict(tipo='Radiada', data=data, hora=hora, pasta=p,
                                              chave=None,
                                              nome='{} - {}{}'.format(pol, tensao, sufixo)))
    con = os.path.join(raiz, 'Conduzida')
    for data in _subpastas(con):
        for hora, base in _execucoes(os.path.join(con, data)):
            for tensao, faixa in sorted(grupos_conduzida(base)):
                itens.append(dict(tipo='Conduzida', data=data, hora=hora, pasta=base,
                                  chave=(tensao, faixa),
                                  nome='{} - {}'.format(tensao, faixa)))
    # Radiada antes de Conduzida; dentro de cada uma, o mais novo primeiro
    itens.sort(key=lambda m: (m['data'], m['hora']), reverse=True)
    itens.sort(key=lambda m: m['tipo'] != 'Radiada')
    return itens


# -----------------------------------------------------------------------
# Exclusao
# -----------------------------------------------------------------------

def _e_limite(nome):
    return 'limite' in nome.lower() and nome.lower().endswith('.csv')


def arquivos_de(medida):
    """Arquivos (CSV e PNG) que pertencem so a esta medida.

    O CSV de limite fica de fora: ele serve a todas as medidas da pasta e
    sai junto quando a ultima delas for excluida (ver exclui).
    """
    pasta = medida['pasta']
    try:
        nomes = [n for n in os.listdir(pasta) if os.path.isfile(os.path.join(pasta, n))]
    except OSError:
        return []
    if medida['tipo'] == 'Conduzida':
        tensao, faixa = medida['chave']
        padrao = re.compile(r'^L\d_{}_{}( - .+)?\.(csv|png)$'.format(
            re.escape(tensao), re.escape(faixa)), re.I)
        nomes = [n for n in nomes if padrao.match(n)]
    else:
        nomes = [n for n in nomes if not _e_limite(n)]
    return [os.path.join(pasta, n) for n in sorted(nomes)]


def exclui(medida, raiz):
    """Apaga os arquivos da medida e as pastas que ficarem sem medida.

    Uma pasta em que so sobrou o CSV de limite e apagada tambem, e assim
    por diante para cima, sem nunca sair de *raiz* nem apagar a pasta do
    ensaio (Radiada, Conduzida). Retorna quantos arquivos apagou.
    """
    raiz = os.path.abspath(raiz)
    pasta = os.path.abspath(medida['pasta'])
    if os.path.commonpath([raiz, pasta]) != raiz or pasta == raiz:
        raise ValueError('pasta fora da pasta das medidas: ' + pasta)
    n = 0
    for p in arquivos_de(medida):
        os.remove(p)
        n += 1
    # sobe apagando o que ficou vazio; para na pasta do ensaio
    while len(os.path.relpath(pasta, raiz).split(os.sep)) > 1:
        nomes = os.listdir(pasta)
        if any(not _e_limite(x) or os.path.isdir(os.path.join(pasta, x)) for x in nomes):
            break
        for x in nomes:
            os.remove(os.path.join(pasta, x))
            n += 1
        os.rmdir(pasta)
        pasta = os.path.dirname(pasta)
    return n


# -----------------------------------------------------------------------
# Curvas
# -----------------------------------------------------------------------
# Cada curva: dict(rotulo, f (MHz), a (dBuV), cor, lw, alpha,
#                  lim (array na grade de f, ou None), lim_rotulo)

def _limite_na_grade(f_hz, lim_path):
    lf, la = rp._parse_limit(lim_path)
    return rp._interp_limit(f_hz, lf, la)


def curvas_radiada(pasta):
    """EUT, Ambiente e EUT - Ambiente de cada conjunto (Max, Med)."""
    conjuntos, lim_path = rp._find_in_folder(pasta)
    if not lim_path:
        # a pasta full_band usa o limite salvo na pasta de cima
        acima = glob.glob(os.path.join(os.path.dirname(pasta), '*Limite*.csv'))
        lim_path = acima[0] if acima else None
    curvas, titulo = [], 'Emissão Radiada'
    for i, (eut_p, amb_p, lbl) in enumerate(conjuntos):
        _, f_eut, a_eut = rp._load_trace(eut_p)
        _, f_amb, a_amb = rp._load_trace(amb_p)
        if not np.array_equal(f_eut, f_amb):
            a_amb = np.interp(f_eut, f_amb, a_amb)
        pal = rp._PALETTES[i % len(rp._PALETTES)]
        f = f_eut / 1e6
        # o limite e comparado com o primeiro conjunto, como no radiada_plot
        lim = _limite_na_grade(f_eut, lim_path) if (lim_path and i == 0) else None
        curvas += [
            dict(rotulo=rp._lbl('Ambiente', lbl), f=f, a=a_amb, cor=pal['amb'],
                 lw=0.7, alpha=0.5, lim=None),
            dict(rotulo=rp._lbl('EUT', lbl), f=f, a=a_eut, cor=pal['eut'],
                 lw=0.8, alpha=0.8, lim=None),
            dict(rotulo=rp._lbl('EUT - Ambiente', lbl), f=f, a=a_eut - a_amb,
                 cor=pal['net'], lw=pal['lw'], alpha=1.0, lim=lim, lim_rotulo='Limite'),
        ]
    nome = os.path.basename(conjuntos[0][0][0] if isinstance(conjuntos[0][0], (list, tuple))
                            else conjuntos[0][0])
    m = re.search(r'Radiada - (.+?) - EUT - Classe (\S+) (.+?)V(?: - .+)?\.csv$', nome)
    if m:
        titulo = 'Emissão Radiada  —  Polarização {}  —  {}V  —  Classe {}'.format(
            m.group(1), m.group(3), m.group(2))
    return curvas, titulo


_CORES_COND = {('L1', 0): '#ffd166', ('L1', 1): '#26c6da',
               ('L2', 0): '#f4a261', ('L2', 1): '#81c784'}


def curvas_conduzida(pasta, chave):
    """L1 e L2 (Max, Med...) de uma (tensao, faixa), cada um com o seu limite."""
    tensao, faixa = chave
    linhas = grupos_conduzida(pasta)[chave]
    # limite por trace do analisador: 'Conduzida - Limite - Classe A - Trace1.csv'
    limites = {}
    for p in glob.glob(os.path.join(pasta, '*Limite*.csv')):
        m = re.search(r'(Trace\d)\.csv$', p)
        limites[m.group(1) if m else None] = p

    curvas = []
    for linha in sorted(linhas):
        for j, rotulo in enumerate(sorted(linhas[linha])):
            meta, f_hz, a = rp._parse_csv(linhas[linha][rotulo])
            lim_path = limites.get(meta.get('Trace Name'), limites.get(None))
            curvas.append(dict(
                rotulo='{} {}'.format(linha, rotulo), f=f_hz / 1e6, a=a,
                cor=_CORES_COND.get((linha, j), '#bbbbbb'), lw=0.9, alpha=0.9,
                lim=_limite_na_grade(f_hz, lim_path) if lim_path else None,
                lim_rotulo='Limite ' + rotulo))
    classe = ''
    for p in limites.values():
        m = re.search(r'Classe (\S+)', os.path.basename(p))
        classe = '  —  Classe ' + m.group(1) if m else ''
    titulo = 'Emissão Conduzida  —  {}  —  {}{}'.format(tensao, faixa, classe)
    return curvas, titulo


def curvas_de(medida):
    if medida['tipo'] == 'Radiada':
        return curvas_radiada(medida['pasta'])
    return curvas_conduzida(medida['pasta'], medida['chave'])


# -----------------------------------------------------------------------
# Picos
# -----------------------------------------------------------------------

def picos(f, a, lim, janela=JANELA_DB, maximo=MAX_PICOS):
    """Indices dos picos a menos de *janela* dB do limite (ou acima dele).

    Pontos vizinhos viram um grupo so, representado pelo de maior margem.
    A distancia que separa dois grupos e 1 % dos pontos, o que acompanha
    tanto a radiada costurada quanto a conduzida.
    """
    margem = a - lim
    idx = np.where(margem > -janela)[0]
    if len(idx) == 0:
        return []
    sep = max(1, len(f) // 100)
    grupos, g = [], [idx[0]]
    for i in idx[1:]:
        if i - g[-1] <= sep:
            g.append(i)
        else:
            grupos.append(g)
            g = [i]
    grupos.append(g)
    ps = [g[int(np.argmax(margem[g]))] for g in grupos]
    return sorted(ps, key=lambda i: -margem[i])[:maximo]


# -----------------------------------------------------------------------
# Plot
# -----------------------------------------------------------------------

def _fmt_mhz(x, _=None):
    return '{:g}'.format(x)


def plota(fig, medida):
    """Desenha *medida* em *fig* e devolve as linhas da tabela de picos.

    Cada linha: (curva, freq_MHz, valor, limite, margem), pior margem primeiro.
    """
    curvas, titulo = curvas_de(medida)

    fig.clear()
    fig.patch.set_facecolor(BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(SPINE)
    ax.tick_params(colors=TXT, which='both')

    linhas, tabela, lim_feitos = {}, [], set()
    for c in curvas:
        l, = ax.plot(c['f'], c['a'], color=c['cor'], lw=c['lw'], alpha=c['alpha'],
                     label=c['rotulo'])
        linhas[c['rotulo']] = l
    for c in curvas:
        if c['lim'] is None:
            continue
        if c['lim_rotulo'] not in lim_feitos:
            l, = ax.plot(c['f'], c['lim'], color=VERMELHO, lw=1.5,
                         ls='--' if not lim_feitos else ':', label=c['lim_rotulo'])
            linhas[c['lim_rotulo']] = l
            lim_feitos.add(c['lim_rotulo'])
        acima = c['a'] > c['lim']
        if acima.any():
            ax.fill_between(c['f'], c['a'], c['lim'], where=acima,
                            color=VERMELHO, alpha=0.20, zorder=2)
        ps = picos(c['f'], c['a'], c['lim'])
        fora = [p for p in ps if c['a'][p] > c['lim'][p]]
        if fora:
            ax.scatter(c['f'][fora], c['a'][fora], color=VERMELHO, s=18, zorder=5)
        for p in ps:
            tabela.append((c['rotulo'], float(c['f'][p]), float(c['a'][p]),
                           float(c['lim'][p]), float(c['a'][p] - c['lim'][p])))
    tabela.sort(key=lambda r: -r[4])

    ax.set_xscale('log')
    ax.xaxis.set_major_locator(ticker.LogLocator(subs=(1, 2, 3, 5)))
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(_fmt_mhz))
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())
    ax.set_title(titulo, color='#eeeeee')
    ax.set_xlabel('Frequência (MHz)', color=TXT)
    ax.set_ylabel('Amplitude (dBuV)', color=TXT)
    ax.grid(True, which='major', color=GRID, lw=0.8)
    ax.grid(True, which='minor', color=GRID, lw=0.3)
    ax.set_xlim(min(c['f'][0] for c in curvas), max(c['f'][-1] for c in curvas))

    # legenda clicavel: liga/desliga a curva
    leg = ax.legend(loc='upper right', facecolor='#2a2a2a', edgecolor=SPINE,
                    labelcolor=TXT, fontsize=8)
    mapa = {}
    for ll in leg.get_lines():
        ll.set_picker(5)
        if ll.get_label() in linhas:
            mapa[ll] = linhas[ll.get_label()]

    def on_pick(event):
        orig = mapa.get(event.artist)
        if orig is not None:
            vis = not orig.get_visible()
            orig.set_visible(vis)
            event.artist.set_alpha(1.0 if vis else 0.2)
            fig.canvas.draw_idle()

    # arrastar mede o delta de frequencia; duplo clique limpa
    marca = {'rect': None, 'txt': None}

    def limpa():
        for k in marca:
            if marca[k] is not None:
                try:
                    marca[k].remove()
                except Exception:
                    pass
                marca[k] = None

    def on_span(xmin, xmax):
        if abs(xmax - xmin) < 1e-9:
            return
        limpa()
        marca['rect'] = ax.axvspan(xmin, xmax, alpha=0.15, color='steelblue', zorder=1)
        marca['txt'] = ax.text(
            np.sqrt(xmin * xmax), ax.get_ylim()[1], rp._fmt_span(xmin, xmax),
            ha='center', va='top', fontsize=10, fontweight='bold', color='white',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='steelblue',
                      alpha=0.85, edgecolor='none'), zorder=10)
        fig.canvas.draw_idle()

    def on_click(event):
        if event.dblclick and event.inaxes is ax:
            limpa()
            fig.canvas.draw_idle()

    # desconecta os eventos do plot anterior e guarda as referencias novas
    for cid in getattr(fig, '_emissao_cids', []):
        fig.canvas.mpl_disconnect(cid)
    fig._emissao_cids = [fig.canvas.mpl_connect('pick_event', on_pick),
                         fig.canvas.mpl_connect('button_press_event', on_click)]
    fig._emissao_span = SpanSelector(ax, on_span, 'horizontal', useblit=False,
                                     props=dict(alpha=0.12, facecolor='steelblue'))
    fig.tight_layout()
    fig.canvas.draw_idle()
    return tabela
