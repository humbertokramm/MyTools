"""
emissao_captura.py  --  Sequencias de captura de emissao radiada e conduzida
(N9010A), sem interface. Usado pelo emissao_gui.py.

Cada execucao passa por todas as combinacoes escolhidas (polarizacao da
antena, slot da PSU e tensao, na ordem de troca que o operador define) e
grava tudo em duas pastas unicas por ensaio: Imagens (PNG da tela do
analisador) e Traces (CSV dos traces e dos limites). O nome do arquivo
identifica a medida; ver "Cenarios e nomes de arquivo".

Alem disso:
  - o rotulo de cada trace (Max, Med...) vem do tipo do trace no
    analisador, e nao de uma lista fixa;
  - da para abortar no meio de uma varredura;
  - na radiada o ambiente, sempre depois do EUT, pode ser medido em cada
    combinacao, n vezes por polarizacao ou nao ser medido;
  - a conduzida sugere uma captura detalhada extra quando a faixa completa
    mostra pico perto do limite numa regiao sem zoom.

Compativel com Python 3.8 (o exe roda no Windows 7).
"""

import itertools
import math
import os
import time
from datetime import datetime, timedelta

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


# resposta do operador a um aviso que aceita pular a combinacao
PULAR = 'pular'


# -----------------------------------------------------------------------
# Cenarios e nomes de arquivo
# -----------------------------------------------------------------------
# Tudo de um ensaio fica em duas pastas unicas, e o nome do arquivo diz o
# resto:
#   <raiz>\Radiada\Imagens\  PNG da tela do analisador (com a peak table)
#   <raiz>\Radiada\Traces\   CSV de cada trace e o CSV do limite
#   Radiada 48 VDC SL1 - Classe A - 30MHz-130MHz - H - (17-11 11h30) EUT.png
#   Conduzida 48 VDC SL1 - Classe A - 150kHz-30MHz - (17-11 11h30) L1 - Max.csv
# A hora e a do inicio da combinacao: o ambiente medido depois do EUT sai
# com a mesma hora, e os dois ficam lado a lado na pasta. 'h' no lugar de
# ':' porque o Windows nao aceita ':' em nome de arquivo.

TENSOES_PADRAO = ['48 VDC', '127 VAC', '220 VAC']
SLOTS_PADRAO = ['SL1', 'SL2']
POLS = ['H', 'V']

# o que muda entre uma combinacao e outra (a ordem e escolha do operador)
DIMENSOES = {'Radiada': ['Polarização', 'Slot', 'Tensão'],
             'Conduzida': ['Slot', 'Tensão']}

# ambiente na radiada
AMB_CADA = 'cada'        # depois do EUT, em cada combinacao (mesma hora no nome)
AMB_POL = 'pol'          # n medicoes depois da ultima combinacao de cada polarizacao
AMB_NAO = 'nao'


def modo_ambiente(valor):
    """Modo de ambiente de uma config salva ('inicio' era o AMB_POL)."""
    return AMB_POL if valor == 'inicio' else valor

_PROIBIDOS = '\\/:*?"<>|'


def limpa_nome(texto):
    """Texto digitado pronto para ir no nome do arquivo."""
    t = ''.join(' ' if c in _PROIBIDOS else c for c in texto)
    return ' '.join(t.replace(' - ', ' ').split())


def faixa_str(freq_ini, freq_fim):
    """'150kHz-30MHz' / '30MHz-130MHz'."""
    def _fmt(hz):
        if hz >= 1e6 and hz % 1e6 == 0:
            return '{:.0f}MHz'.format(hz / 1e6)
        if hz >= 1e6:
            return '{:g}MHz'.format(hz / 1e6)
        if hz >= 1e3:
            return '{:g}kHz'.format(hz / 1e3)
        return '{:.0f}Hz'.format(hz)
    return '{}-{}'.format(_fmt(freq_ini), _fmt(freq_fim))


def carimbo(quando=None):
    """'(17-11 11h30)'."""
    return (quando or datetime.now()).strftime('(%d-%m %Hh%M)')


class Relogio:
    """Hora de cada medida de uma execucao, sempre num minuto novo.

    O nome do arquivo so tem hora e minuto: duas medidas iguais no mesmo
    minuto (ex.: as n medicoes de ambiente seguidas) teriam o mesmo nome.
    Quando isso aconteceria, a hora avanca para o minuto seguinte.
    """

    def __init__(self):
        self.ultimo = None

    def agora(self):
        q = datetime.now().replace(second=0, microsecond=0)
        if self.ultimo is not None and q <= self.ultimo:
            q = self.ultimo + timedelta(minutes=1)
        self.ultimo = q
        return q


def cenario(tensao, slot):
    """'48 VDC SL1' (vazio no ambiente medido a parte)."""
    return ' '.join(x for x in (tensao, slot) if x)


def nome_radiada(tensao, slot, classe, f0, f1, pol, quando, origem, rotulo=''):
    cen = cenario(tensao, slot)
    base = 'Radiada{} - Classe {} - {} - {} - {} {}'.format(
        ' ' + cen if cen else '', classe, faixa_str(f0, f1), pol, carimbo(quando), origem)
    return base + (' - ' + rotulo if rotulo else '')


def nome_conduzida(tensao, slot, classe, f0, f1, quando, linha, rotulo=''):
    cen = cenario(tensao, slot)
    base = 'Conduzida{} - Classe {} - {} - {} {}'.format(
        ' ' + cen if cen else '', classe, faixa_str(f0, f1), carimbo(quando), linha)
    return base + (' - ' + rotulo if rotulo else '')


def nome_limite(ensaio, classe, trace=None):
    return '{} - Limite - Classe {}{}.csv'.format(ensaio, classe,
                                                  ' - ' + trace if trace else '')


def pastas(raiz, ensaio):
    """(Imagens, Traces) do ensaio, criadas se preciso."""
    img = os.path.join(raiz, ensaio, 'Imagens')
    tr = os.path.join(raiz, ensaio, 'Traces')
    for p in (img, tr):
        os.makedirs(p, exist_ok=True)
    return img, tr


def combinacoes(ordem, valores):
    """Combinacoes na ordem de troca escolhida.

    ordem: dimensoes da que troca menos (primeira) a que troca a cada
    combinacao (ultima). valores: {dimensao: [valores]}; lista vazia vira
    [''] (ex.: equipamento sem slot).
    """
    listas = [valores.get(d) or [''] for d in ordem]
    return [dict(zip(ordem, c)) for c in itertools.product(*listas)]


def _avisa_puladas(op, puladas):
    if puladas:
        op.log('\nCombinacoes puladas ({}):\n'.format(len(puladas)) +
               '\n'.join('  ' + p for p in puladas))


def _descreve(c, anterior):
    """Texto do aviso ao operador: o que trocar e como deve ficar."""
    partes = {'Polarização': 'antena {}', 'Slot': 'PSU no {}', 'Tensão': '{}'}
    agora = ', '.join(partes[d].format(v) for d, v in c.items() if v)
    if anterior is None:
        return 'Configure: ' + agora
    troca = [partes[d].format(v) for d, v in c.items() if v and anterior.get(d) != v]
    return ('TROQUE: ' + ', '.join(troca) + '   (fica: ' + agora + ')') if troca \
        else 'Mesma configuração: ' + agora


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

    prompt(texto, pular=False)
                       espera o operador (EUT ligado, trocar a linha...);
                       com pular=True ele pode responder PULAR, e a
                       combinacao fica sem medir
    confirma(texto)    pergunta de sim/nao: True/False/None (None = abortar)
    log(texto)
    progresso(i, n)
    cancelado()        True quando o operador pediu para abortar
    alerta() / ok()    avisos sonoros antes e depois de cada varredura
    """

    def prompt(self, texto, pular=False):
        if not pular:
            input(texto + '  [ENTER]')
            return None
        r = input(texto + '  [ENTER, ou P para pular a combinacao]')
        return PULAR if r.strip().lower() == 'p' else None

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


def _captura(sa, op, n, pastas_saida, nomes, traces, peak_table):
    """Varre e salva um CSV por trace (Traces) + o PNG da tela (Imagens).

    nomes(rotulo) -> nome base. Retorna [(trace, rotulo, csv)], ou [] se o
    operador pulou a captura.
    """
    img, tr = pastas_saida
    rotulos = [(t, rotulo_trace(sa, t)) for t in traces]
    csvs = [os.path.join(tr, nomes(r) + '.csv') for _, r in rotulos]
    png = os.path.join(img, nomes('') + '.png')
    if not _pode_gravar(op, csvs + [png]):
        op.log('  pulado (arquivos mantidos)')
        return []

    op.alerta()
    op.log('  Varrendo {}x ... aguarde.'.format(n))
    if not varrer(sa, n, op.cancelado):
        op.log('  AVISO: timeout na varredura!')
    sa.pause()

    for (t, _), path in zip(rotulos, csvs):
        sa.driver.export_csv(t, path)

    sa.set_fullscreen(True)       # o load_state pode ter tirado o full screen
    if peak_table:
        sa.set_peak_table(True)
    imagem = sa.driver.capture_screen()
    if peak_table:
        sa.set_peak_table(False)
    with open(png, 'wb') as fh:
        fh.write(imagem)
    op.log('  ' + os.path.basename(png))
    op.ok()
    return [(t, r, path) for (t, r), path in zip(rotulos, csvs)]


def _salva_limites(sa, op, tr, ensaio, classe, por_trace):
    """Limit lines do state em Traces. Retorna {trace: (freq, amp)}."""
    limites = {}
    lls = limit_lines(sa)
    if not lls:
        op.log('  AVISO: nenhuma limit line habilitada no state!')
    for _, t, fq, amp in (lls if por_trace else lls[:1]):
        nome = nome_limite(ensaio, classe, t if por_trace else None)
        salva_limite(os.path.join(tr, nome), fq, amp)
        limites[t if por_trace else None] = (fq, amp)
        op.log('  Limite salvo: ' + nome)
    return limites


def etapas_radiada(bandas):
    """Sub-bandas e, por ultimo, a banda completa (se houver mais de uma)."""
    bandas = [tuple(b) for b in bandas]
    full = (min(b[0] for b in bandas), max(b[1] for b in bandas))
    return bandas + ([full] if len(bandas) > 1 and full not in bandas else [])


def plano_radiada(combos, pols, etapas, amb_modo, amb_n):
    """Numero de capturas da execucao (para a barra de progresso)."""
    por_vez = len(etapas)
    eut = len(combos) * por_vez
    if amb_modo == AMB_CADA:
        return 2 * eut
    if amb_modo == AMB_POL:
        npol = len({c.get('Polarização', '') for c in combos})
        return eut + npol * amb_n * por_vez
    return eut


def radiada(sa, op, raiz, classe, n, tensoes, slots, pols, ordem,
            amb_modo=AMB_CADA, amb_n=1, bandas=None, traces=('Trace1', 'Trace2'),
            state=None):
    """Radiada em todas as combinacoes de polarizacao, slot e tensao.

    *ordem* diz o que troca menos (primeiro) e o que troca a cada
    combinacao (ultimo). O ambiente e sempre medido DEPOIS do EUT:
      AMB_CADA    em cada combinacao: EUT e, desligado o EUT, o ambiente,
                  com a mesma hora no nome;
      AMB_POL     amb_n medicoes depois da ultima combinacao de cada
                  polarizacao (pega raias esporadicas sem refazer o boot
                  do EUT a cada combinacao);
      AMB_NAO     so o EUT.
    Retorna a pasta Traces.
    """
    etapas = etapas_radiada(bandas or BANDAS['Radiada'])
    state = state or STATES['Radiada'][classe]
    saida = pastas(raiz, 'Radiada')
    op.log('Imagens: {}\nTraces:  {}'.format(*saida))
    combos = combinacoes(ordem, {'Polarização': pols, 'Slot': slots, 'Tensão': tensoes})
    total = plano_radiada(combos, pols, etapas, amb_modo, amb_n)
    estado = dict(feitas=0, limite=False)
    relogio = Relogio()
    sa.set_fullscreen(True)

    def mede(origem, pol, tensao, slot, quando):
        for f0, f1 in etapas:
            if op.cancelado():
                raise Cancelado()
            op.progresso(estado['feitas'], total)
            op.log('\n[{}/{}] {} {} {} {}'.format(
                estado['feitas'] + 1, total, origem, pol, cenario(tensao, slot) or '',
                faixa_str(f0, f1)).replace('  ', ' '))
            sa.load_state(state)
            sa.set_freq_range(f0, f1)
            if not estado['limite']:
                _salva_limites(sa, op, saida[1], 'Radiada', classe, por_trace=False)
                estado['limite'] = True
            _captura(sa, op, n, saida,
                     lambda r, f0=f0, f1=f1: nome_radiada(tensao, slot, classe, f0, f1,
                                                          pol, quando, origem, r),
                     traces, peak_table=True)
            estado['feitas'] += 1

    anterior = None
    puladas = []
    # AMB_POL: o ambiente de uma polarizacao sai depois da ultima combinacao
    # com ela (a antena ainda esta nessa polarizacao)
    ultima = {c.get('Polarização', ''): i for i, c in enumerate(combos)}
    medidas_pol = {}           # pol -> combinacoes medidas (EUT)
    eut_desligado = False      # depois do ambiente, o EUT precisa de boot

    def pula(pol, tensao, slot, oque, capturas):
        desc = '{} {} ({})'.format(pol, cenario(tensao, slot), oque)
        puladas.append(desc)
        op.log('  PULADA: ' + desc)
        estado['feitas'] += capturas

    for i, c in enumerate(combos):
        if op.cancelado():
            raise Cancelado()
        pol, slot, tensao = c.get('Polarização', ''), c.get('Slot', ''), c.get('Tensão', '')
        texto = _descreve(c, anterior)
        anterior = c
        if amb_modo == AMB_CADA or eut_desligado:
            pronto = '\nLigue o EUT e espere o boot terminar'
        else:
            pronto = '\nEUT ligado e pronto'
        if op.prompt(texto + pronto, pular=True) == PULAR:
            pula(pol, tensao, slot, 'EUT e ambiente' if amb_modo == AMB_CADA else 'EUT',
                 (2 if amb_modo == AMB_CADA else 1) * len(etapas))
        else:
            eut_desligado = False
            quando = relogio.agora()
            mede('EUT', pol, tensao, slot, quando)
            medidas_pol[pol] = medidas_pol.get(pol, 0) + 1
            if amb_modo == AMB_CADA:
                if op.prompt('DESLIGUE o EUT: medida de ambiente  ({}, {})'.format(
                        pol, cenario(tensao, slot)), pular=True) == PULAR:
                    pula(pol, tensao, slot, 'ambiente; o EUT foi medido', len(etapas))
                else:
                    mede('Ambiente', pol, tensao, slot, quando)
        if amb_modo == AMB_POL and ultima[pol] == i:
            if not medidas_pol.get(pol):
                op.log('  Ambiente {} não medido: nenhuma combinação {} foi medida'.format(
                    pol, pol))
                estado['feitas'] += amb_n * len(etapas)
                continue
            op.prompt('DESLIGUE o EUT: ambiente com a antena {} ({} medição(ões))'.format(
                pol, amb_n))
            eut_desligado = True
            for k in range(amb_n):
                op.log('\n--- Ambiente {} {}/{}'.format(pol, k + 1, amb_n))
                mede('Ambiente', pol, '', '', relogio.agora())

    _avisa_puladas(op, puladas)
    op.progresso(1, 1)
    return saida[1]


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


def conduzida(sa, op, raiz, classe, n, tensoes, slots, ordem, bandas=None,
              traces=('Trace1', 'Trace2'), state=None, linhas=('L1', 'L2')):
    """Conduzida em todas as combinacoes de slot e tensao, L1 e L2 em cada.

    Depois da faixa mais larga de cada linha, olha os traces contra os
    limites: se houver pico perto do limite numa regiao sem captura
    detalhada, pergunta ao operador se quer captura-la tambem. A resposta
    vale para o resto da execucao (as outras linhas e combinacoes).
    Retorna a pasta Traces.
    """
    bandas = [tuple(b) for b in (bandas or BANDAS['Conduzida'])]
    state = state or STATES['Conduzida'][classe]
    saida = pastas(raiz, 'Conduzida')
    op.log('Imagens: {}\nTraces:  {}'.format(*saida))
    combos = combinacoes(ordem, {'Slot': slots, 'Tensão': tensoes})

    larga = max(bandas, key=lambda b: b[1] - b[0])
    extras = []           # zooms que o operador aceitou
    decidido = set()      # regioes ja perguntadas nesta execucao
    limites = None        # {trace: (freq, amp)}
    feitas = 0

    def total():
        return len(combos) * len(linhas) * (len(bandas) + len(extras))

    def coberta(seg):
        return any(b != larga and b[0] <= seg[0] and b[1] >= seg[1]
                   for b in bandas + extras)

    anterior = None
    relogio = Relogio()
    puladas = []
    for c in combos:
        slot, tensao = c.get('Slot', ''), c.get('Tensão', '')
        cen = cenario(tensao, slot)
        texto = _descreve(c, anterior)
        anterior = c
        quando = None
        for k, linha in enumerate(linhas):
            if op.cancelado():
                raise Cancelado()
            if op.prompt((texto + '\n' if k == 0 else '') +
                         'EUT ligado; LISN no condutor {}'.format(linha),
                         pular=True) == PULAR:
                resto = linhas[k:]
                desc = '{} ({})'.format(cen, ', '.join(resto))
                puladas.append(desc)
                op.log('  PULADA: ' + desc)
                feitas += len(resto) * (len(bandas) + len(extras))
                break
            quando = quando or relogio.agora()     # L1 e L2 com a mesma hora
            fila = bandas + extras
            while fila:
                if op.cancelado():
                    raise Cancelado()
                f0, f1 = fila.pop(0)
                op.progresso(feitas, total())
                op.log('\n[{}/{}] {} {} {}'.format(feitas + 1, total(), cen, linha,
                                                   faixa_str(f0, f1)))
                sa.load_state(state)
                sa.set_freq_range(f0, f1)
                if limites is None:
                    limites = _salva_limites(sa, op, saida[1], 'Conduzida', classe,
                                             por_trace=True)

                capt = _captura(sa, op, n, saida,
                                lambda r, linha=linha, f0=f0, f1=f1: nome_conduzida(
                                    tensao, slot, classe, f0, f1, quando, linha, r),
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
                        'Vale para as proximas linhas e combinacoes desta execucao.'.format(
                            linha, cen,
                            '{:.1f} dB ACIMA do limite'.format(margem) if margem > 0
                            else 'a {:.1f} dB do limite'.format(-margem),
                            fq / 1e6, rotulo, faixa_str(*seg)))
                    if r is None:
                        raise Cancelado()
                    if r:
                        extras.append(seg)
                        fila.append(seg)
                        op.log('  Faixa extra: ' + faixa_str(*seg))

    _avisa_puladas(op, puladas)
    op.progresso(1, 1)
    return saida[1]
