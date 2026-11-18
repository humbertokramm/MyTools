"""
organiza_medidas.py  --  Passa as medidas de emissao do layout antigo (pastas
por data/polarizacao/tensao/hora) para o atual: duas pastas unicas por
ensaio, com o cenario no nome do arquivo (ver emissao_captura.py).

    python organiza_medidas.py <pasta Medidas>              so mostra o plano
    python organiza_medidas.py <pasta Medidas> --executar   move os arquivos
    python organiza_medidas.py --desfazer <log .csv>        volta tudo

Os arquivos sao movidos (renomeados), nao copiados, e cada movimento vai
para um log CSV na pasta das medidas, que o --desfazer usa. Limites
repetidos (um por pasta antiga) vao para _organiza_sobras. Arquivos que o
script nao reconhece ficam onde estao e aparecem no plano. So e apagado o
que sobra nas pastas antigas vazias: Thumbs.db e desktop.ini, caches que o
Windows refaz sozinho.

De onde vem cada parte do nome novo:
  - tensao e slot: radiada, do nome da pasta da tensao (48, 127Vac,
    SL2_48...); conduzida, do nome do arquivo (L1_SL2_48Vdc_...). Numero
    sem unidade: ate 60 V e VDC, acima e VAC;
  - conduzida: PNG e CSV gravados com ate 2 min de diferenca sao a mesma
    captura; se so um dos dois tem o slot no nome, ele vale para os dois;
  - data e hora: a gravacao mais antiga dos CSVs da combinacao (a data das
    pastas pode ter sido mexida a mao; a dos arquivos e a da captura).
"""

import argparse
import csv
import filecmp
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import emissao_captura as cap

_FAIXA = r'(?P<faixa>[\d.]+[kM]?Hz-[\d.]+[kM]?Hz)'
RE_RAD = re.compile(
    r'^' + _FAIXA + r' Radiada - (?P<pol>\S+) - (?P<org>EUT|Ambiente) - Classe (?P<cl>\S+)'
    r'(?: (?P<tens>[^ ]+?))?(?: - (?P<rot>[^.]+))?\.(?P<ext>csv|png)$', re.I)
RE_COND = re.compile(
    r'^(?P<lin>L\d)_(?P<cen>.+)_' + _FAIXA + r'(?: - (?P<rot>[^.]+))?\.(?P<ext>csv|png)$', re.I)
RE_LIM = re.compile(r'^(Radiada|Conduzida) - Limite - Classe (\S+?)(?: - (Trace\d))?\.csv$', re.I)
RE_DATA = re.compile(r'^\d{4}-\d\d-\d\d$')
RE_HORA = re.compile(r'^\d\dh\d\d$')
LIXO = {'thumbs.db', 'desktop.ini'}
SOBRAS = '_organiza_sobras'
JANELA_PAR_S = 120          # PNG e CSV da mesma captura (conduzida)
JANELA_SESSAO_S = 20 * 60   # capturas da mesma combinacao (conduzida)


# -----------------------------------------------------------------------
# Cenario
# -----------------------------------------------------------------------

def tensao_de(token):
    """'48' -> '48 VDC', '127Vac' -> '127 VAC', '12V' -> '12 VDC'."""
    m = re.match(r'^(\d+(?:[.,]\d+)?)\s*(V|Vac|Vdc)?$', token, re.I)
    if not m:
        return cap.limpa_nome(token)
    n, un = m.group(1).replace(',', '.'), (m.group(2) or '').lower()
    if un in ('vac', 'vdc'):
        tipo = un[1:].upper()
    else:
        tipo = 'DC' if float(n) <= 60 else 'AC'
    return '{} V{}'.format(n, tipo)


def cenario_de(texto):
    """('48 VDC', 'SL2') de 'SL2_48', '48Vdc', 'SL1_127Vac'..."""
    slot, resto = '', []
    for t in texto.split('_'):
        if re.match(r'^SL\d+$', t, re.I):
            slot = t.upper()
        elif t:
            resto.append(t)
    return tensao_de('_'.join(resto)) if resto else '', slot


def _hz(faixa):
    def um(t):
        m = re.match(r'([\d.]+)([kM]?)Hz$', t)
        return float(m.group(1)) * {'': 1, 'k': 1e3, 'M': 1e6}[m.group(2)]
    a, b = faixa.split('-')
    return um(a), um(b)


def _mtime(p):
    return datetime.fromtimestamp(os.path.getmtime(p))


def _minuto(dt):
    return dt.replace(second=0, microsecond=0)


def _hora_da_pasta(pasta, primeiro):
    """Hora da subpasta da execucao (10h32), na data do primeiro arquivo.

    A janela cria a subpasta no inicio e o primeiro CSV sai um ou dois
    minutos depois; vale a hora da pasta se ela for ate 30 min antes do
    primeiro arquivo. Senao (pasta sem hora, ou hora que nao bate), vale o
    minuto do primeiro arquivo.
    """
    m = re.match(r'^(\d\d)h(\d\d)$', os.path.basename(pasta))
    if m:
        h = primeiro.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0,
                             microsecond=0)
        if 0 <= (primeiro - h).total_seconds() <= 30 * 60:
            return h
    return _minuto(primeiro)


# -----------------------------------------------------------------------
# Plano
# -----------------------------------------------------------------------

class Plano:
    def __init__(self, raiz):
        self.raiz = os.path.abspath(raiz)
        self.movs = []          # (origem, destino, motivo)
        self.grupos = []        # textos do plano, um por combinacao
        self.avisos = []
        self.ignorados = []

    def destino(self, ensaio, nome):
        sub = 'Imagens' if nome.lower().endswith('.png') else 'Traces'
        return os.path.join(self.raiz, ensaio, sub, nome)

    def move(self, origem, destino, motivo=''):
        self.movs.append((origem, destino, motivo))

    def rel(self, p):
        return os.path.relpath(p, self.raiz)

    # ---------------------------------------------------------- limites
    def limite(self, ensaio, p, vistos):
        nome = os.path.basename(p)
        dst = os.path.join(self.raiz, ensaio, 'Traces', nome)
        ja = vistos.get(nome)
        if ja is None and not os.path.exists(dst):
            vistos[nome] = p
            self.move(p, dst)
            return
        ref = ja or dst
        igual = filecmp.cmp(p, ref, shallow=False)
        if not igual:
            self.avisos.append('limite diferente do primeiro, vai para {}: {}'.format(
                SOBRAS, self.rel(p)))
        self.move(p, os.path.join(self.raiz, SOBRAS, self.rel(p)),
                  'limite repetido' + ('' if igual else ' (DIFERENTE)'))

    # ---------------------------------------------------------- radiada
    def radiada(self, lims):
        base = os.path.join(self.raiz, 'Radiada')
        for data in sorted(d for d in _subpastas(base) if RE_DATA.match(d)):
            for pol in _subpastas(os.path.join(base, data)):
                for tdir in _subpastas(os.path.join(base, data, pol)):
                    self._rad_tensao(os.path.join(base, data, pol, tdir), data, pol, tdir,
                                     lims)
        self._estranhos(base, ('Imagens', 'Traces'), RE_DATA)

    def _rad_tensao(self, pasta, data, pol, tdir, lims):
        tensao, slot = cenario_de(tdir)
        # uma execucao por subpasta de hora; sem ela, a propria pasta
        execs = [os.path.join(pasta, h) for h in _subpastas(pasta) if RE_HORA.match(h)]
        soltos = [os.path.join(pasta, n) for n in _arquivos(pasta)]
        if not execs:
            execs, soltos = [pasta], []
        grupos = []
        for ex in execs:
            arqs = [p for p in _arquivos_rec(ex) if ex != pasta or os.path.dirname(p) == pasta
                    or os.path.basename(os.path.dirname(p)) == 'full_band']
            csvs = [p for p in arqs if p.lower().endswith('.csv') and RE_RAD.match(
                os.path.basename(p))]
            if not csvs:
                self.ignorados += arqs
                continue
            ini = min(_mtime(p) for p in csvs)
            fim = max(_mtime(p) for p in csvs)
            grupos.append(dict(pasta=ex, arqs=arqs, ini=ini, fim=fim))
        # PNGs soltos na pasta da tensao (movidos a mao): execucao mais proxima
        for p in soltos:
            if not grupos:
                self.ignorados.append(p)
                continue
            t = _mtime(p)
            g = min(grupos, key=lambda g: 0 if g['ini'] <= t <= g['fim']
                    else min(abs((t - g['ini']).total_seconds()),
                             abs((t - g['fim']).total_seconds())))
            g['arqs'].append(p)
        for g in grupos:
            quando = _hora_da_pasta(g['pasta'], g['ini'])
            n, classes = 0, set()
            for p in g['arqs']:
                nome = os.path.basename(p)
                if nome.lower() in LIXO:
                    continue
                if RE_LIM.match(nome):
                    self.limite('Radiada', p, lims)
                    continue
                m = RE_RAD.match(nome)
                if not m:
                    self.ignorados.append(p)
                    continue
                f0, f1 = _hz(m.group('faixa'))
                if m.group('pol').upper() != pol.upper():
                    self.avisos.append('polarizacao do arquivo ({}) diferente da pasta ({}): '
                                       '{}'.format(m.group('pol'), pol, self.rel(p)))
                novo = cap.nome_radiada(tensao, slot, m.group('cl'), f0, f1, pol.upper(),
                                        quando, m.group('org').capitalize()
                                        if m.group('org').lower() == 'ambiente' else 'EUT',
                                        m.group('rot') or '') + '.' + m.group('ext').lower()
                self.move(p, self.destino('Radiada', novo))
                n += 1
                classes.add(m.group('cl'))
            obs = '' if quando.strftime('%Y-%m-%d') == data else \
                '   [pasta {}, arquivos de {}]'.format(data, quando.strftime('%Y-%m-%d'))
            self.grupos.append('Radiada   {:<26} -> {} {} - Classe {} - {}  {}: {} arquivos{}'.format(
                self.rel(g['pasta']), cap.cenario(tensao, slot), pol.upper(),
                '/'.join(sorted(classes)), cap.carimbo(quando), 'EUT+Ambiente', n, obs))

    # ---------------------------------------------------------- conduzida
    def conduzida(self, lims, classe_padrao):
        base = os.path.join(self.raiz, 'Conduzida')
        itens, classes_pasta = [], {}
        for p in _arquivos_rec(base, pular=('Imagens', 'Traces')):
            nome = os.path.basename(p)
            if nome.lower() in LIXO:
                continue
            ml = RE_LIM.match(nome)
            if ml:
                classes_pasta[os.path.dirname(p)] = ml.group(2)
                self.limite('Conduzida', p, lims)
                continue
            m = RE_COND.match(nome)
            if not m:
                self.ignorados.append(p)
                continue
            tensao, slot = cenario_de(m.group('cen'))
            itens.append(dict(p=p, lin=m.group('lin').upper(), tensao=tensao, slot=slot,
                              faixa=m.group('faixa'), rot=m.group('rot') or '',
                              ext=m.group('ext').lower(), t=_mtime(p)))
        # PNG e CSV da mesma captura: o slot de um vale para o outro
        csvs = [i for i in itens if i['ext'] == 'csv']
        for png in (i for i in itens if i['ext'] == 'png'):
            pares = [c for c in csvs if (c['lin'], c['tensao'], c['faixa']) ==
                     (png['lin'], png['tensao'], png['faixa'])
                     and abs((c['t'] - png['t']).total_seconds()) <= JANELA_PAR_S]
            for c in pares:
                if c['slot'] and png['slot'] and c['slot'] != png['slot']:
                    self.avisos.append('slot diferente no PNG e no CSV: {} x {}'.format(
                        self.rel(png['p']), self.rel(c['p'])))
                elif png['slot'] and not c['slot']:
                    c['slot'] = png['slot']
                    c['slot_do_png'] = True
                elif c['slot'] and not png['slot']:
                    png['slot'] = c['slot']
            png['par'] = bool(pares)
        # combinacao = mesma tensao/slot, capturas a menos de 20 min uma da outra
        sessoes = []
        for i in sorted(itens, key=lambda i: i['t']):
            for s in sessoes:
                if (s['tensao'], s['slot']) == (i['tensao'], i['slot']) and \
                        (i['t'] - s['fim']).total_seconds() <= JANELA_SESSAO_S:
                    s['itens'].append(i)
                    s['fim'] = i['t']
                    break
            else:
                sessoes.append(dict(tensao=i['tensao'], slot=i['slot'], fim=i['t'],
                                    itens=[i]))
        for s in sessoes:
            ts = [i['t'] for i in s['itens'] if i['ext'] == 'csv'] or \
                 [i['t'] for i in s['itens']]
            quando = _minuto(min(ts))
            pastas = sorted({os.path.dirname(i['p']) for i in s['itens']})
            classe = next((classes_pasta[d] for d in pastas if d in classes_pasta), None)
            if classe is None:
                classe = classe_padrao
                self.avisos.append('conduzida {} sem limite na pasta: classe {} (--classe)'.format(
                    cap.cenario(s['tensao'], s['slot']), classe))
            for i in s['itens']:
                f0, f1 = _hz(i['faixa'])
                novo = cap.nome_conduzida(s['tensao'], s['slot'], classe, f0, f1, quando,
                                          i['lin'], i['rot']) + '.' + i['ext']
                self.move(i['p'], self.destino('Conduzida', novo))
            inferido = any(i.get('slot_do_png') for i in s['itens'])
            self.grupos.append('Conduzida {:<26} -> {} - Classe {}  {}: {} arquivos{}'.format(
                '({} pasta(s))'.format(len(pastas)), cap.cenario(s['tensao'], s['slot']),
                classe, cap.carimbo(quando), len(s['itens']),
                '   [slot dos CSVs tirado dos PNGs]' if inferido else ''))
        self._estranhos(base, ('Imagens', 'Traces'), None)

    def _estranhos(self, base, conhecidas, re_data):
        """Pastas que nao sao do layout antigo nem do novo: ficam como estao."""
        for d in _subpastas(base):
            if d in conhecidas or d == SOBRAS or (re_data and re_data.match(d)):
                continue
            if re_data is not None:
                self.avisos.append('pasta nao mexida: ' + self.rel(os.path.join(base, d)))

    # ---------------------------------------------------------- conferencia
    def confere(self):
        """Destinos repetidos ou ja existentes viram aviso e saem do plano."""
        vistos, ok = {}, []
        for o, d, mot in self.movs:
            k = os.path.normcase(d)
            if k in vistos:
                self.avisos.append('dois arquivos iriam para o mesmo nome; o segundo fica: '
                                   '{} e {}'.format(self.rel(vistos[k]), self.rel(o)))
                continue
            if os.path.exists(d):
                self.avisos.append('ja existe, nao movido: {}'.format(self.rel(d)))
                continue
            vistos[k] = o
            ok.append((o, d, mot))
        self.movs = ok


def _subpastas(p):
    try:
        return sorted(d for d in os.listdir(p) if os.path.isdir(os.path.join(p, d)))
    except OSError:
        return []


def _arquivos(p):
    try:
        return sorted(n for n in os.listdir(p) if os.path.isfile(os.path.join(p, n)))
    except OSError:
        return []


def _arquivos_rec(p, pular=()):
    res = []
    for d, subs, fs in os.walk(p):
        if d == p:
            subs[:] = [s for s in subs if s not in pular and s != SOBRAS]
        res += [os.path.join(d, f) for f in sorted(fs)]
    return res


def monta_plano(raiz, classe_padrao='A'):
    pl = Plano(raiz)
    lims = {}
    pl.radiada(lims)
    pl.conduzida(lims, classe_padrao)
    pl.confere()
    return pl


# -----------------------------------------------------------------------
# Execucao
# -----------------------------------------------------------------------

def _limpa_pastas(raiz, pastas):
    """Apaga, de baixo para cima, as pastas antigas que ficaram vazias."""
    removidas = []
    for d in sorted(set(pastas), key=lambda x: -x.count(os.sep)):
        while os.path.commonpath([raiz, d]) == raiz and d != raiz and \
                os.path.basename(d) not in ('Radiada', 'Conduzida') and os.path.isdir(d):
            nomes = os.listdir(d)
            if any(n.lower() not in LIXO for n in nomes):
                break
            for n in nomes:
                os.remove(os.path.join(d, n))
            os.rmdir(d)
            removidas.append(d)
            d = os.path.dirname(d)
    return removidas


def executa(pl):
    log = os.path.join(pl.raiz, 'organiza_medidas_{}.csv'.format(
        datetime.now().strftime('%Y-%m-%d_%Hh%M%S')))
    feitos = 0
    with open(log, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(['de', 'para', 'motivo'])
        for o, d, mot in pl.movs:
            os.makedirs(os.path.dirname(d), exist_ok=True)
            os.rename(o, d)
            w.writerow([pl.rel(o), pl.rel(d), mot])
            fh.flush()
            feitos += 1
    removidas = _limpa_pastas(pl.raiz, [os.path.dirname(o) for o, _, _ in pl.movs])
    return feitos, len(removidas), log


def desfaz(log):
    raiz = os.path.dirname(os.path.abspath(log))
    with open(log, newline='', encoding='utf-8') as fh:
        linhas = list(csv.DictReader(fh, delimiter=';'))
    n = 0
    for ln in reversed(linhas):
        o, d = os.path.join(raiz, ln['de']), os.path.join(raiz, ln['para'])
        if os.path.exists(d) and not os.path.exists(o):
            os.makedirs(os.path.dirname(o), exist_ok=True)
            os.rename(d, o)
            n += 1
        else:
            print('nao voltou: ' + ln['para'])
    return n


# -----------------------------------------------------------------------

def imprime(pl, saida=sys.stdout):
    w = saida.write
    w('Pasta das medidas: {}\n\n'.format(pl.raiz))
    w('Combinacoes encontradas ({}):\n'.format(len(pl.grupos)))
    for g in pl.grupos:
        w('  ' + g + '\n')
    sobras = [m for m in pl.movs if m[2]]
    w('\n{} arquivo(s) a mover ({} limite(s) repetido(s) para {}).\n'.format(
        len(pl.movs), len(sobras), SOBRAS))
    if pl.avisos:
        w('\nAvisos ({}):\n'.format(len(pl.avisos)))
        for a in pl.avisos:
            w('  - ' + a + '\n')
    if pl.ignorados:
        w('\nFicam onde estao, nao sao medidas reconhecidas ({}):\n'.format(len(pl.ignorados)))
        for p in pl.ignorados:
            w('  ' + pl.rel(p) + '\n')
    w('\nDe -> para:\n')
    for o, d, mot in pl.movs:
        w('  {}\n    -> {}{}\n'.format(pl.rel(o), pl.rel(d), '   (' + mot + ')' if mot else ''))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('raiz', nargs='?', help='pasta das medidas (a que tem Radiada e Conduzida)')
    ap.add_argument('--executar', action='store_true', help='move os arquivos (sem isto, so mostra)')
    ap.add_argument('--classe', default='A', help='classe da conduzida sem limite na pasta')
    ap.add_argument('--plano', help='grava o plano neste arquivo, alem de mostrar')
    ap.add_argument('--desfazer', metavar='LOG', help='volta os movimentos de um log')
    a = ap.parse_args()
    if a.desfazer:
        print('{} arquivo(s) voltaram.'.format(desfaz(a.desfazer)))
        return
    if not a.raiz:
        ap.error('informe a pasta das medidas')
    pl = monta_plano(a.raiz, a.classe)
    imprime(pl)
    if a.plano:
        with open(a.plano, 'w', encoding='utf-8') as fh:
            imprime(pl, fh)
    if a.executar:
        feitos, pastas, log = executa(pl)
        print('\nMovidos: {}. Pastas antigas vazias removidas: {}.\nLog (para --desfazer): {}'.format(
            feitos, pastas, log))
    else:
        print('\nNada foi movido. Para aplicar: --executar')


if __name__ == '__main__':
    main()
