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
import time

import numpy as np
import matplotlib.ticker as ticker
from matplotlib.widgets import SpanSelector

import radiada_plot as rp

BG, GRID, SPINE, TXT = '#1c1c1c', '#2e2e2e', '#555', '#cccccc'
VERMELHO = '#e63946'
AMARELO = '#ffd60a'
RAIO_MARCA_PX = 12        # distancia do clique que gruda na curva / pega uma marca

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


_RE_DATA = re.compile(r'^\d{4}-\d\d-\d\d$')


def _datas(p):
    return [d for d in _subpastas(p) if _RE_DATA.match(d)]


def lista_medidas(raiz):
    """Medidas sob *raiz*, mais novas primeiro.

    Cada item: dict(tipo, data, hora, nome, pasta, chave). 'chave' e
    (tensao, faixa) na conduzida e None na radiada; 'hora' e '' nas medidas
    sem subpasta de execucao.
    """
    itens = []
    rad = os.path.join(raiz, 'Radiada')
    for data in _datas(rad):
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
    for data in _datas(con):
        for hora, base in _execucoes(os.path.join(con, data)):
            for tensao, faixa in sorted(grupos_conduzida(base)):
                itens.append(dict(tipo='Conduzida', data=data, hora=hora, pasta=base,
                                  chave=(tensao, faixa),
                                  nome='{} - {}'.format(tensao, faixa)))
    itens += medidas_novas(raiz)
    # Radiada antes de Conduzida; dentro de cada uma, o mais novo primeiro
    itens.sort(key=lambda m: (m['data'], m['hora']), reverse=True)
    itens.sort(key=lambda m: m['tipo'] != 'Radiada')
    return itens


# -----------------------------------------------------------------------
# Layout novo: <raiz>\<Ensaio>\Traces e \Imagens, cenario no nome
# -----------------------------------------------------------------------
#   Radiada 48 VDC SL1 - Classe A - 30MHz-130MHz - H - (17-11 11h30) EUT - Max.csv
#   Conduzida 48 VDC SL1 - Classe A - 150kHz-30MHz - (17-11 11h30) L1 - Max.csv

_FAIXA = r'(?P<faixa>[\d.]+[kM]?Hz-[\d.]+[kM]?Hz)'
_QUANDO = r'\((?P<dm>\d\d-\d\d) (?P<hm>\d\dh\d\d)\)'
_RE_NOVO = {
    'Radiada': re.compile(
        r'^Radiada(?: (?P<cen>.+?))? - Classe (?P<classe>\S+) - ' + _FAIXA +
        r' - (?P<pol>[^\s-]+) - ' + _QUANDO + r' (?P<org>EUT|Ambiente)'
        r'(?: - (?P<rot>[^.]+))?\.(?P<ext>csv|png)$', re.I),
    'Conduzida': re.compile(
        r'^Conduzida(?: (?P<cen>.+?))? - Classe (?P<classe>\S+) - ' + _FAIXA +
        r' - ' + _QUANDO + r' (?P<org>L\d)'
        r'(?: - (?P<rot>[^.]+))?\.(?P<ext>csv|png)$', re.I),
}
_ROTULO_LEGENDA = {'Max': 'Máx', 'Med': 'Méd'}
_ORDEM_ROTULO = {'Max': 0, 'Med': 1}


def _hz(txt):
    m = re.match(r'([\d.]+)([kM]?)Hz$', txt)
    return float(m.group(1)) * {'': 1, 'k': 1e3, 'M': 1e6}[m.group(2)]


def _faixa_hz(faixa):
    a, b = faixa.split('-')
    return _hz(a), _hz(b)


def _arquivos_novos(base, ensaio):
    """[dict(campos do nome, path, data)] de Traces e Imagens de *base*."""
    res = []
    for sub in ('Traces', 'Imagens'):
        pasta = os.path.join(base, sub)
        try:
            nomes = os.listdir(pasta)
        except OSError:
            continue
        for n in nomes:
            m = _RE_NOVO[ensaio].match(n)
            if not m:
                continue
            d = m.groupdict()
            d['path'] = os.path.join(pasta, n)
            d['cen'] = d['cen'] or ''
            d['rot'] = d['rot'] or ''
            d['ext'] = d['ext'].lower()
            # o nome nao tem o ano: vem da data do arquivo
            try:
                ano = time.localtime(os.path.getmtime(d['path'])).tm_year
            except OSError:
                ano = time.localtime().tm_year
            dia, mes = d['dm'].split('-')
            d['data'] = '{}-{}-{}'.format(ano, mes, dia)
            d['hora'] = d['hm'].replace('h', ':')
            res.append(d)
    return res


def _separa_full(faixas):
    """(sub-bandas, banda completa ou None) de um conjunto de faixas."""
    faixas = sorted(set(faixas), key=lambda x: _faixa_hz(x))
    if len(faixas) < 2:
        return faixas, None
    lo = min(_faixa_hz(x)[0] for x in faixas)
    hi = max(_faixa_hz(x)[1] for x in faixas)
    full = [x for x in faixas if _faixa_hz(x) == (lo, hi)]
    if not full:
        return faixas, None
    return [x for x in faixas if x != full[0]], full[0]


def _por_rotulo(arqs, faixas):
    """{rotulo: [csvs]} dos arquivos das *faixas*."""
    res = {}
    for a in arqs:
        if a['ext'] == 'csv' and a['faixa'] in faixas:
            res.setdefault(a['rot'], []).append(a['path'])
    return res


def _medidas_radiada(base):
    tr = os.path.join(base, 'Radiada', 'Traces')
    grupos = {}
    for a in _arquivos_novos(os.path.join(base, 'Radiada'), 'Radiada'):
        k = (a['cen'], a['classe'], a['pol'], a['data'], a['hora'])
        grupos.setdefault(k, []).append(a)
    # ambientes medidos a parte (sem cenario), para emparelhar com os EUT
    avulsos = {}
    for (cen, classe, pol, data, hora), arqs in grupos.items():
        if not cen and any(a['org'].lower() == 'ambiente' for a in arqs):
            avulsos.setdefault((classe, pol), []).append((data, hora, arqs))

    itens = []
    for (cen, classe, pol, data, hora), arqs in grupos.items():
        eut = [a for a in arqs if a['org'].upper() == 'EUT']
        amb = [a for a in arqs if a['org'].lower() == 'ambiente']
        sub, full = _separa_full(a['faixa'] for a in (eut or amb) if a['ext'] == 'csv')
        for faixas, sufixo in ((sub, ''), ([full] if full else [], ' (full band)')):
            if not faixas:
                continue
            fs = set(faixas)
            meus = [a for a in arqs if a['faixa'] in fs]
            novo = dict(classe=classe, pol=pol, cen=cen, arquivos=sorted(a['path'] for a in meus),
                        eut=_por_rotulo(eut, fs) or None, amb=[], amb_info='')
            if amb:
                novo['amb'] = [_por_rotulo(amb, fs)]
            elif eut:
                # sem ambiente proprio: o envelope dos ambientes avulsos da
                # mesma polarizacao, do mesmo dia se houver
                cands = avulsos.get((classe, pol), [])
                mesmo_dia = [c for c in cands if c[0] == data]
                cands = sorted(mesmo_dia or cands)
                novo['amb'] = [r for r in (_por_rotulo(c[2], fs) for c in cands) if r]
                if novo['amb']:
                    horas = [c[1] for c in cands]
                    novo['amb_info'] = (' (máx de {}, {} a {})'.format(len(horas), horas[0],
                                                                       horas[-1])
                                        if len(horas) > 1 else ' ({})'.format(horas[0]))
            if not novo['eut'] and not novo['amb']:
                continue
            nome = '{} - {}{}'.format(pol, cen or 'Ambiente', sufixo)
            itens.append(dict(tipo='Radiada', data=data, hora=hora, pasta=tr, chave=None,
                              nome=nome, novo=novo))
    return itens


def _medidas_conduzida(base):
    tr = os.path.join(base, 'Conduzida', 'Traces')
    grupos = {}
    for a in _arquivos_novos(os.path.join(base, 'Conduzida'), 'Conduzida'):
        k = (a['cen'], a['classe'], a['data'], a['hora'], a['faixa'])
        grupos.setdefault(k, []).append(a)
    itens = []
    for (cen, classe, data, hora, faixa), arqs in grupos.items():
        linhas = {}
        for a in arqs:
            if a['ext'] == 'csv':
                linhas.setdefault(a['org'].upper(), {})[a['rot']] = a['path']
        if not linhas:
            continue
        novo = dict(classe=classe, cen=cen, faixa=faixa, linhas=linhas,
                    arquivos=sorted(a['path'] for a in arqs))
        itens.append(dict(tipo='Conduzida', data=data, hora=hora, pasta=tr, chave=None,
                          nome='{} - {}'.format(cen or 'EUT', faixa), novo=novo))
    return itens


def medidas_novas(base):
    """Medidas no layout novo sob *base* (a pasta das medidas)."""
    itens = _medidas_radiada(base) + _medidas_conduzida(base)
    itens.sort(key=lambda m: (_faixa_hz(m['novo']['faixa']) if 'faixa' in m['novo'] else (0, 0),
                              m['nome']))
    return itens


def _limite_novo(tr, ensaio, classe, trace=None):
    p = os.path.join(tr, '{} - Limite - Classe {}{}.csv'.format(
        ensaio, classe, ' - ' + trace if trace else ''))
    return p if os.path.exists(p) else None


def curvas_radiada_novo(m):
    """EUT, Ambiente e EUT - Ambiente (Max, Med) de uma medida do layout novo.

    O ambiente e o da mesma combinacao, ou o envelope (maximo ponto a
    ponto) dos ambientes medidos a parte.
    """
    nv = m['novo']
    lim_path = _limite_novo(m['pasta'], 'Radiada', nv['classe'])
    rots = sorted(set(nv['eut'] or {}) | set(k for r in nv['amb'] for k in r),
                  key=lambda r: (_ORDEM_ROTULO.get(r, 9), r))
    curvas = []
    for i, rot in enumerate(rots):
        lbl = _ROTULO_LEGENDA.get(rot, rot)
        pal = rp._PALETTES[i % len(rp._PALETTES)]
        lim = None
        eut_p = (nv['eut'] or {}).get(rot)
        if eut_p:
            _, f_hz, a_eut = rp._load_trace(eut_p)
        amb = []
        for run in nv['amb']:
            if rot in run:
                _, fa, aa = rp._load_trace(run[rot])
                amb.append((fa, aa))
        if not eut_p:
            f_hz = amb[0][0]
        if amb:
            a_amb = np.max([aa if np.array_equal(fa, f_hz) else np.interp(f_hz, fa, aa)
                            for fa, aa in amb], axis=0)
        if lim_path and i == 0:
            lim = _limite_na_grade(f_hz, lim_path)
        f = f_hz / 1e6
        if amb:
            curvas.append(dict(rotulo=rp._lbl('Ambiente', lbl) + nv['amb_info'], f=f,
                               a=a_amb, cor=pal['amb'], lw=0.7, alpha=0.5,
                               lim=None if eut_p else lim, lim_rotulo='Limite'))
        if eut_p:
            curvas.append(dict(rotulo=rp._lbl('EUT', lbl), f=f, a=a_eut, cor=pal['eut'],
                               lw=0.8, alpha=0.8, lim=None if amb else lim,
                               lim_rotulo='Limite'))
        if eut_p and amb:
            curvas.append(dict(rotulo=rp._lbl('EUT - Ambiente', lbl), f=f, a=a_eut - a_amb,
                               cor=pal['net'], lw=pal['lw'], alpha=1.0, lim=lim,
                               lim_rotulo='Limite'))
    titulo = 'Emissão Radiada  —  Polarização {}  —  {}  —  Classe {}'.format(
        nv['pol'], nv['cen'] or 'Ambiente', nv['classe'])
    return curvas, titulo


def curvas_conduzida_novo(m):
    nv = m['novo']
    curvas = []
    for linha in sorted(nv['linhas']):
        for j, rotulo in enumerate(sorted(nv['linhas'][linha],
                                          key=lambda r: (_ORDEM_ROTULO.get(r, 9), r))):
            meta, f_hz, a = rp._parse_csv(nv['linhas'][linha][rotulo])
            lim_path = (_limite_novo(m['pasta'], 'Conduzida', nv['classe'],
                                     meta.get('Trace Name'))
                        or _limite_novo(m['pasta'], 'Conduzida', nv['classe']))
            curvas.append(dict(
                rotulo='{} {}'.format(linha, rotulo), f=f_hz / 1e6, a=a,
                cor=_CORES_COND.get((linha, j), '#bbbbbb'), lw=0.9, alpha=0.9,
                lim=_limite_na_grade(f_hz, lim_path) if lim_path else None,
                lim_rotulo='Limite ' + rotulo))
    titulo = 'Emissão Conduzida  —  {}  —  {}  —  Classe {}'.format(
        nv['cen'] or 'EUT', nv['faixa'], nv['classe'])
    return curvas, titulo


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
    if 'novo' in medida:
        return [p for p in medida['novo']['arquivos'] if os.path.exists(p)]
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
    if 'novo' in medida:
        # layout novo: so os arquivos; as pastas Imagens/Traces ficam
        arqs = arquivos_de(medida)
        for p in arqs:
            if os.path.commonpath([raiz, os.path.abspath(p)]) != raiz:
                raise ValueError('arquivo fora da pasta das medidas: ' + p)
        for p in arqs:
            os.remove(p)
        return len(arqs)
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
    if 'novo' in medida:
        return (curvas_radiada_novo(medida) if medida['tipo'] == 'Radiada'
                else curvas_conduzida_novo(medida))
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


# margens do grafico em polegadas (esquerda, direita, topo, base)
_MARGENS_POL = (0.72, 0.16, 0.40, 0.52)


def _margens(fig):
    """Margens fixas, iguais em todos os graficos.

    O tight_layout calcula a margem pelos rotulos de cada grafico (um "-20"
    no eixo ja a alarga), e a area do grafico mudava de lugar de uma medida
    para outra, o que atrapalha comparar com a escala travada.
    """
    w, h = fig.get_size_inches()
    e, d, t, b = _MARGENS_POL
    if w > e + d + 1 and h > t + b + 1:
        fig.subplots_adjust(left=e / w, right=1 - d / w, top=1 - t / h, bottom=b / h)


def _fmt_marca(f, a):
    return '{:g} MHz\n{:.1f} dBuV'.format(round(f, 4 if f < 30 else 2), a)


def plota(fig, medida, marcas=None, ao_marcar=None):
    """Desenha *medida* em *fig* e devolve as linhas da tabela de picos.

    Cada linha: (curva, freq_MHz, valor, limite, margem), pior margem primeiro.

    *marcas* e a lista [[freq_MHz, valor], ...] dos pontos marcados, que
    pertence a quem chama e vale para todos os graficos: um clique
    acrescenta um ponto (grudando na curva mais proxima) e um clique sobre
    uma marca a remove. *ao_marcar* e chamado depois de cada mudanca.
    """
    if marcas is None:
        marcas = []
    curvas, titulo = curvas_de(medida)

    fig.clear()
    fig.patch.set_facecolor(BG)
    ax = fig.add_subplot(111)
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(SPINE)
    ax.tick_params(colors=TXT, which='both')

    linhas, tabela, lim_feitos = {}, [], set()
    tracos = []               # linhas das curvas medidas (sem os limites)
    for c in curvas:
        l, = ax.plot(c['f'], c['a'], color=c['cor'], lw=c['lw'], alpha=c['alpha'],
                     label=c['rotulo'])
        linhas[c['rotulo']] = l
        tracos.append(l)
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
    # escala fixa daqui em diante: as marcas nao podem mexer nos eixos
    ax.set_ylim(ax.get_ylim())
    ax.set_autoscale_on(False)

    # pontos marcados, comuns a todos os graficos
    desenhadas = []

    def desenha_marcas():
        for art in desenhadas:
            try:
                art.remove()
            except Exception:
                pass
        del desenhadas[:]
        for f, a in marcas:
            desenhadas.append(ax.axvline(f, color=AMARELO, lw=0.7, ls=':', alpha=0.7,
                                         zorder=6))
            desenhadas.extend(ax.plot([f], [a], ls='none', marker='+', ms=13, mew=1.6,
                                      color=AMARELO, zorder=9))
            desenhadas.append(ax.annotate(
                _fmt_marca(f, a), (f, a), xytext=(7, 7), textcoords='offset points',
                fontsize=8, color=AMARELO, zorder=9, annotation_clip=True,
                bbox=dict(boxstyle='round,pad=0.25', facecolor='#2a2a2a',
                          edgecolor=AMARELO, lw=0.6, alpha=0.85)))

    desenha_marcas()

    def _px(f, a):
        return ax.transData.transform(np.column_stack([np.atleast_1d(f),
                                                       np.atleast_1d(a)]))

    def clique_marca(event):
        """Remove a marca sob o clique; senao, marca o ponto (na curva, se perto)."""
        alvo = np.array([event.x, event.y])
        if marcas:
            d = np.hypot(*(_px(*zip(*marcas)) - alvo).T)
            i = int(np.argmin(d))
            if d[i] <= RAIO_MARCA_PX:
                del marcas[i]
                return
        ponto, perto = (event.xdata, event.ydata), RAIO_MARCA_PX
        for l in tracos:
            if not l.get_visible():
                continue
            f, a = l.get_data()
            d = np.hypot(*(_px(f, a) - alvo).T)
            i = int(np.argmin(d))
            if d[i] <= perto:
                ponto, perto = (f[i], a[i]), d[i]
        marcas.append([float(ponto[0]), float(ponto[1])])

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

    aperto = {}

    def on_click(event):
        aperto['xy'] = (event.x, event.y) if event.inaxes is ax else None
        if event.dblclick and event.inaxes is ax:
            limpa()
            fig.canvas.draw_idle()

    def on_release(event):
        # clique simples (sem arrastar, fora do zoom/pan da barra) = marca.
        # No duplo clique, o segundo clique desfaz o que o primeiro fez.
        xy = aperto.pop('xy', None)
        barra = getattr(fig.canvas, 'toolbar', None)
        modo = getattr(barra, 'mode', '')
        if (xy is None or event.button != 1 or event.inaxes is not ax
                or str(getattr(modo, 'value', modo))
                or abs(event.x - xy[0]) > 3 or abs(event.y - xy[1]) > 3):
            return
        clique_marca(event)
        desenha_marcas()
        fig.canvas.draw_idle()
        if ao_marcar:
            ao_marcar()

    # desconecta os eventos do plot anterior e guarda as referencias novas
    for cid in getattr(fig, '_emissao_cids', []):
        fig.canvas.mpl_disconnect(cid)
    fig._emissao_cids = [fig.canvas.mpl_connect('pick_event', on_pick),
                         fig.canvas.mpl_connect('button_press_event', on_click),
                         fig.canvas.mpl_connect('button_release_event', on_release),
                         fig.canvas.mpl_connect('resize_event', lambda e: _margens(fig))]
    fig._emissao_marcas = desenha_marcas      # para redesenhar de fora
    fig._emissao_span = SpanSelector(ax, on_span, 'horizontal', useblit=False,
                                     props=dict(alpha=0.12, facecolor='steelblue'))
    _margens(fig)
    fig.canvas.draw_idle()
    return tabela
