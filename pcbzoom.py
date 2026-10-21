"""
**File: pcbzoom.py**

**Descrição**
	Apontador de componentes em PDF de montagem (Assembly / Draftsman).
	Indexa os designadores presentes na camada de texto do PDF (lado de cima e
	lado de baixo), permite buscar um componente e dar zoom imediato nele.

	Se o PDF também tiver uma página de *PCB Print* (printout do Altium), os
	pads de cada componente são lidos dos marcadores invisíveis ``PA``/``CO``
	e cruzados com uma netlist Protel (``.NET``) procurada ao lado do PDF.
	Os pads são então projetados **de volta na vista de montagem** (a página
	do printout em si é ilegível para trabalho de bancada): cada pino aparece
	marcado em cima do desenho do Draftsman, com os de terra em verde.

**Uso**

	Interface gráfica (busca interativa)::

		python pcbzoom.py "Output_Job.PDF"

	Consulta direta pela linha de comando::

		python pcbzoom.py "Output_Job.PDF" -d R1234
		python pcbzoom.py "Output_Job.PDF" -d R1234 -o r1234.png
		python pcbzoom.py "Output_Job.PDF" -d CN29 --gnd     # pinos de terra
		python pcbzoom.py "Output_Job.PDF" -d CN29 --pinos   # pinos e nets
		python pcbzoom.py "Output_Job.PDF" --list U

	Acompanhando um script de bancada: a janela fica aberta e pula no
	componente a cada ponto de medicao (o PDF e lido uma vez so)::

		import pcbzoom
		pcbzoom.mostrar('C1052', pdf=PDF)   # abre a janela na 1a chamada
		pcbzoom.mostrar('C1052 gnd')        # ja no pad de terra
		pcbzoom.mostrar('I11 pino 45')

**Teclas (GUI)**

	- ``Enter``        : localiza o designador digitado
	- ``roda do mouse``: zoom in/out no ponteiro
	- ``arrastar``     : pan
	- ``+`` / ``-``    : zoom in/out
	- ``R``            : gira a vista 90° (``Shift+R`` para o outro lado)
	- ``0``            : enquadra a página inteira
	- ``G``            : destaca o primeiro pad de GND do componente
	- ``duplo clique`` : no painel de pinos, destaca o pad daquele pino
	- ``Z``            : volta ao zoom do componente localizado
	- ``F3`` / ``Shift+F3``: próxima/anterior ocorrência do designador
	- ``Tab``          : alterna lado de cima / lado de baixo
	- ``Ctrl+S``       : salva a vista atual em PNG
	- ``Esc``          : volta o foco para o campo de busca

	As teclas de uma letra valem com o foco no desenho; enquanto se digita no
	campo de busca elas são texto. Depois do ``Enter`` o foco já vai para o
	desenho, e o ``Esc`` traz de volta para a busca.

**Requisitos**
	``pymupdf``
"""

import argparse
import bisect
import collections
import os
import re
import sys
from collections import OrderedDict

try:
	import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
	fitz = None   # so faz falta na hora de abrir o PDF; importar o modulo nao quebra

FALTA_PYMUPDF = 'pcbzoom: modulo "pymupdf" nao encontrado. Instale com: pip install pymupdf'


# Designador de componente: prefixo de letras + numero (R1, CN52, BRK12, U7A)
RE_DESIG = re.compile(r'^[A-Z]{1,4}\d{1,5}[A-Z]?$')

# Rotulos da moldura: letras nas bordas superior/inferior, numeros nas laterais
RE_COL = re.compile(r'^[A-Z]$')
RE_ROW = re.compile(r'^\d{1,2}$')

ZOOM_MIN = 0.3
ZOOM_MAX = 400.0
PAD_PT = 14.0        # folga em pontos ao redor do componente localizado
PAD_FACTOR = 3.0     # quantas vezes o tamanho do texto cabe na vista


def _norm(texto):
	"""Normaliza um designador para busca (maiusculas, sem espacos/pontuacao)."""
	return re.sub(r'[\s.\-_]+', '', (texto or '').strip().upper())


def _rect_key(rect):
	"""Chave para deduplicar retangulos praticamente iguais."""
	return (round(rect.x0, 1), round(rect.y0, 1), round(rect.x1, 1), round(rect.y1, 1))


class Netlist:
	"""Netlist Protel (.NET): associa cada pino de componente a uma net."""

	def __init__(self, caminho):
		self.caminho = caminho
		self.refs = {}                # ref -> {pino: net}
		self.nets = {}                # net -> [(ref, pino), ...]
		self._carregar()

	def _carregar(self):
		with open(self.caminho, encoding='latin-1', errors='replace') as fh:
			linhas = [l.strip() for l in fh]
		i, n = 0, len(linhas)
		while i < n:
			if linhas[i] == '(':
				net = linhas[i + 1] if i + 1 < n else ''
				i += 2
				while i < n and linhas[i] != ')':
					if '-' in linhas[i]:
						ref, pino = linhas[i].rsplit('-', 1)
						self.refs.setdefault(ref, {})[pino] = net
						self.nets.setdefault(net, []).append((ref, pino))
					i += 1
			i += 1

	def net(self, ref, pino):
		return self.refs.get(ref, {}).get(pino, '')

	def pinos(self, ref):
		return self.refs.get(ref, {})


def _eh_gnd(net):
	"""Heuristica: a net e um terra?"""
	u = (net or '').upper()
	return bool(re.search(r'(^|[^A-Z])(A|D|P|F|X|E|SIG|PWR)?GND\d*([^A-Z]|$)', u)
				or re.match(r'^V?SS\d*$', u) or 'GROUND' in u)


class Pads:
	"""Pads do PCB Print, lidos dos marcadores 'PA<ref><pino>' / 'CO<ref>'.

	O Altium escreve, na pagina de printout, um texto invisivel sobre cada pad
	('PA' + designador + numero do pino, com zeros a esquerda) e sobre cada
	componente ('CO' + designador). No fluxo do PDF os pads de um componente
	vem agrupados logo antes do marcador 'CO' dele, o que permite separar o
	designador do numero do pino sem ambiguidade.
	"""

	def __init__(self, lado, universo=()):
		self.lado = lado
		self.comps = {}               # ref -> {'pos': Point, 'pinos': {pino: Rect}, 'incerto': bool}
		self.universo = set(universo)
		self.larguras = collections.Counter()   # largura do campo de pino
		self._indexar()

	@staticmethod
	def _pino(texto):
		"""Normaliza o numero de pino ('01' -> '1', '0S' -> 'S')."""
		return texto.lstrip('0') or texto or '0'

	def _marcadores(self):
		"""Marcadores PA/CO na ordem do fluxo da pagina."""
		for b in self.lado.page.get_text('rawdict')['blocks']:
			if b.get('type'):
				continue
			for ln in b.get('lines', ()):
				for s in ln['spans']:
					txt = ''.join(ch['c'] for ch in s['chars']).strip()
					if txt.startswith(('PA', 'CO')) and len(txt) > 2:
						yield txt[:2], txt[2:], fitz.Rect(s['bbox'])

	def _registrar(self, ref, pendentes, incerto=False, medir=False):
		c = self.comps.setdefault(ref, {'pos': None, 'pinos': {}, 'incerto': False})
		c['incerto'] = c['incerto'] or incerto
		for corpo, r in pendentes:
			if medir:
				self.larguras[len(corpo) - len(ref)] += 1
			c['pinos'].setdefault(self._pino(corpo[len(ref):]), r)

	@staticmethod
	def _larguras(pads, ref):
		"""Larguras do campo de pino dos pads que comecam por 'ref'."""
		c = collections.Counter()
		for corpo, _r in pads:
			if corpo.startswith(ref) and corpo[len(ref):].isdigit():
				c[len(corpo) - len(ref)] += 1
		return c

	@staticmethod
	def _separar(pads, ref):
		"""Separa de 'pads' os que comecam pelo designador 'ref'."""
		meus = [(c, r) for c, r in pads if c.startswith(ref)]
		resto = [(c, r) for c, r in pads if not c.startswith(ref)]
		return meus, resto

	def _resolver_orfaos(self, orfaos, com_co):
		"""Pads de um componente sem marcador 'CO' proprio.

		Sao os casos em que 'PAC101' tanto pode ser C1 pino 01 quanto C10
		pino 1. Descarta os designadores que ja tem 'CO' proprio (os pads
		deles ja foram agrupados) e, entre os que sobram, prefere o que
		produz a largura de pino tipica do desenho; se mais de um candidato
		serve, o componente fica marcado como incerto.
		"""
		if not orfaos:
			return
		comum = os.path.commonprefix([c for c, _r in orfaos])
		cands = [ref for ref in self.universo
				 if comum.startswith(ref) and all(c.startswith(ref) for c, _r in orfaos)]
		livres = [ref for ref in cands if ref not in com_co]
		cands = livres or cands
		if not cands:
			return
		larg = self.larguras.most_common(1)[0][0] if self.larguras else 2
		certos = [r for r in cands if len(orfaos[0][0]) - len(r) == larg]
		cands.sort(key=lambda ref: (len(orfaos[0][0]) - len(ref) != larg, -len(ref)))
		self._registrar(cands[0], orfaos, incerto=len(certos) != 1)

	def _indexar(self):
		pend, orfaos, com_co = [], [], set()
		for tipo, corpo, r in self._marcadores():
			if tipo == 'PA':
				pend.append((corpo, r))
				continue
			ref = corpo
			meus, sobra = self._separar(pend, ref)
			# o que sobra e de um vizinho sem marcador 'CO'; so da para decidir
			# de quem e depois de conhecer todos os 'CO' da pagina
			if sobra:
				orfaos.append(sobra)
			self._registrar(ref, meus, medir=True)
			self.comps[ref]['pos'] = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
			com_co.add(ref)
			pend = []
		for sobra in orfaos:
			self._resolver_orfaos(sobra, com_co)
		# o fim da pagina e a segunda passada do printout: os mesmos pads
		# desenhados de novo, que so completam quem ainda nao tem pino
		for ref in sorted({r for c, _ in pend for r in self.comps if c.startswith(r)},
						  key=len, reverse=True):
			meus, pend = self._separar(pend, ref)
			self._registrar(ref, meus)

	def pinos(self, ref):
		c = self.comps.get(ref)
		return c['pinos'] if c else {}

	def incerto(self, ref):
		c = self.comps.get(ref)
		return bool(c and c['incerto'])


def _similaridade(pares, espelho):
	"""Ajusta A -> B (escala + rotacao + translacao, x espelhado se pedido).

	Devolve (transforma, residuos, escala). Minimos quadrados fechados: com
	os centroides removidos, a parte rotacional sai direto dos somatorios.
	"""
	n = len(pares)
	sinal = -1 if espelho else 1
	ax0 = sum(p[0][0] for p in pares) / n
	ay0 = sum(p[0][1] for p in pares) / n
	bx0 = sum(p[1][0] for p in pares) / n
	by0 = sum(p[1][1] for p in pares) / n
	num_a = num_b = den = 0.0
	for (ax, ay), (bx, by) in pares:
		ax, ay = (ax - ax0) * sinal, ay - ay0
		bx, by = bx - bx0, by - by0
		num_a += ax * bx + ay * by
		num_b += ax * by - ay * bx
		den += ax * ax + ay * ay
	a = num_a / den if den else 0.0
	b = num_b / den if den else 0.0

	def transforma(ponto):
		x, y = (ponto[0] - ax0) * sinal, ponto[1] - ay0
		return fitz.Point(a * x - b * y + bx0, b * x + a * y + by0)

	res = []
	for p, q in pares:
		t = transforma(p)
		res.append(((t.x - q[0]) ** 2 + (t.y - q[1]) ** 2) ** 0.5)
	return transforma, res, (a * a + b * b) ** 0.5


def _ajuste_robusto(pares, espelho, voltas=8):
	"""Ajuste descartando os pares que nao seguem o grosso dos pontos.

	Boa parte dos designadores e reposicionada pelo Draftsman e nao serve de
	referencia; sobra o nucleo que ficou onde estava no PCB.
	"""
	atual = list(pares)
	transforma, res, esc = _similaridade(atual, espelho)
	for _volta in range(voltas):
		res_ord = sorted(res)
		med = res_ord[len(res_ord) // 2]
		corte = max(med * 2.5, 0.25)
		novos = [p for p, d in zip(atual, res) if d <= corte]
		if len(novos) < 30 or len(novos) == len(atual):
			break
		atual = novos
		transforma, res, esc = _similaridade(atual, espelho)
	res_ord = sorted(res)
	return {
		'transforma': transforma,
		'escala': esc,
		'pares': len(atual),
		'residuo': res_ord[len(res_ord) // 2] if res_ord else 0.0,
	}


class Lado:
	"""Uma pagina do PDF: lado da montagem ou o printout de PCB."""

	def __init__(self, doc, numero, nome, tipo='montagem'):
		self.doc = doc
		self.numero = numero          # indice da pagina (0-based)
		self.nome = nome              # 'Top', 'Bottom', 'PCB Print'
		self.tipo = tipo              # 'montagem' ou 'print'
		self.page = doc[numero]
		self.rect = fitz.Rect(self.page.rect)
		self.itens = OrderedDict()    # designador -> [fitz.Rect, ...]
		self.colunas = []             # [(rotulo, x), ...]
		self.linhas = []              # [(rotulo, y), ...]
		self.ajuste = None            # transformacao do printout nesta pagina
		self._formas = None
		self._formas_x = []
		if tipo == 'montagem':
			self._indexar()

	def _indexar(self):
		cols, rows = {}, {}
		pr = self.rect
		for x0, y0, x1, y1, txt, *_ in self.page.get_text('words'):
			r = fitz.Rect(x0, y0, x1, y1)
			up = txt.strip().upper()
			if RE_DESIG.match(up):
				lista = self.itens.setdefault(up, [])
				if _rect_key(r) not in [_rect_key(x) for x in lista]:
					lista.append(r)
			elif RE_COL.match(up) and (y0 < pr.y0 + 12 or y1 > pr.y1 - 12):
				cols.setdefault(up, (r.x0 + r.x1) / 2)
			elif RE_ROW.match(up) and (x0 < pr.x0 + 12 or x1 > pr.x1 - 12):
				rows.setdefault(up, (r.y0 + r.y1) / 2)
		self.colunas = sorted(cols.items(), key=lambda kv: kv[1])
		self.linhas = sorted(rows.items(), key=lambda kv: kv[1])

	def formas(self):
		"""Centros das figuras preenchidas da pagina (pads, furos, vias).

		Servem de referencia para encaixar os pads projetados do printout em
		cima do desenho de montagem.
		"""
		if self._formas is None:
			self._formas = []
			for p in self.page.get_drawings():
				r = p['rect']
				if p['type'] == 's' or r.width <= 0 or r.height <= 0:
					continue
				if r.width > 40 or r.height > 40:     # corpos e areas grandes nao sao pad
					continue
				self._formas.append(fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
			self._formas.sort(key=lambda p: p.x)
			self._formas_x = [p.x for p in self._formas]
		return self._formas

	def formas_perto(self, ponto, raio):
		"""Centros de figura a menos de 'raio' do ponto (busca por faixa em x)."""
		formas = self.formas()
		i = bisect.bisect_left(self._formas_x, ponto.x - raio)
		j = bisect.bisect_right(self._formas_x, ponto.x + raio)
		return [p for p in formas[i:j] if abs(p.y - ponto.y) <= raio]

	def zona(self, rect):
		"""Retorna a zona da moldura ('C2') correspondente a um retangulo."""
		if not self.colunas or not self.linhas:
			return ''
		cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
		col = min(self.colunas, key=lambda kv: abs(kv[1] - cx))[0]
		lin = min(self.linhas, key=lambda kv: abs(kv[1] - cy))[0]
		return '%s%s' % (col, lin)


class Projeto:
	"""PDF de montagem com um ou mais lados indexados."""

	def __init__(self, caminho, netlist=None):
		if fitz is None:
			raise RuntimeError(FALTA_PYMUPDF)
		self.caminho = caminho
		self.doc = fitz.open(caminho)
		self.lados = []
		self.print_lado = None
		for i in range(self.doc.page_count):
			if self._eh_printout(i):
				lado = Lado(self.doc, i, 'PCB Print', tipo='print')
				self.print_lado = lado
			else:
				lado = Lado(self.doc, i, self._nome_pagina(i))
			self.lados.append(lado)

		self.netlist = None
		caminho_net = netlist or self._achar_netlist()
		if caminho_net and os.path.isfile(caminho_net):
			try:
				self.netlist = Netlist(caminho_net)
			except Exception as erro:            # netlist e um extra: nao pode derrubar a GUI
				print('pcbzoom: netlist ignorada (%s)' % erro, file=sys.stderr)

		self.pads = None
		if self.print_lado is not None:
			universo = set()
			for lado in self.lados:
				universo.update(lado.itens)
			if self.netlist:
				universo.update(self.netlist.refs)
			self.pads = Pads(self.print_lado, universo)
			self._alinhar()

	def _alinhar(self):
		"""Calcula, para cada lado, a transformacao do printout na montagem.

		Os marcadores 'CO' do printout ficam onde esta o designador no PCB, e
		o mesmo designador aparece na vista de montagem: casando os dois da
		para projetar os pads do printout sobre o desenho de montagem.
		"""
		for lado in self.lados:
			lado.ajuste = None
			if lado.tipo != 'montagem':
				continue
			pares = []
			for ref, rects in lado.itens.items():
				c = self.pads.comps.get(ref)
				if c and c['pos'] is not None and len(rects) == 1:
					r = rects[0]
					pares.append(((c['pos'].x, c['pos'].y),
								  ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)))
			if len(pares) < 30:
				continue
			# o lado de baixo e desenhado espelhado; fica o ajuste que explica melhor
			tentativas = [_ajuste_robusto(pares, esp) for esp in (False, True)]
			lado.ajuste = min(tentativas, key=lambda a: a['residuo'])
			self._refinar(lado)

	def _refinar(self, lado, amostra=1500, raio=6.0, passo=0.2):
		"""Corrige a translacao usando todos os pads do lado de uma vez.

		O ajuste pelos designadores erra alguns pontos, o bastante para
		apontar o pino vizinho. Como a vista de montagem desenha os pads,
		projetar a nuvem inteira de pads do printout e votar no deslocamento
		acerta a posicao: o padrao da placa toda so encaixa de um jeito.
		"""
		pontos = []
		for ref in lado.itens:
			c = self.pads.comps.get(ref)
			if not c:
				continue
			for rect in c['pinos'].values():
				pontos.append(lado.ajuste['transforma'](
					((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)))
		if len(pontos) < 200:
			return
		salto = max(1, len(pontos) // amostra)
		votos = collections.Counter()
		for p in pontos[::salto]:
			for q in lado.formas_perto(p, raio):
				votos[(round((q.x - p.x) / passo), round((q.y - p.y) / passo))] += 1
		if not votos:
			return
		(dx, dy), n = votos.most_common(1)[0]
		usados = len(pontos[::salto])
		if n < usados // 10:
			return
		base = lado.ajuste['transforma']
		lado.ajuste['transforma'] = lambda p, _b=base, _dx=dx * passo, _dy=dy * passo: (
			fitz.Point(_b(p).x + _dx, _b(p).y + _dy))
		lado.ajuste['refino'] = (dx * passo, dy * passo, n, usados)

	def pads_na_montagem(self, ref, lado):
		"""[(pino, net, Point na pagina de montagem)] do componente.

		Devolve tambem a distancia tipica, em pontos, entre cada pad
		projetado e o pad mais proximo desenhado na vista de montagem: e a
		confirmacao de que a projecao caiu em cima dos pads certos.
		"""
		if lado is None or getattr(lado, 'ajuste', None) is None:
			return [], None
		fora, erros = [], []
		for pino, net, rect in self.pinos(ref):
			if rect is None:
				continue
			c = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
			p = lado.ajuste['transforma'](c)
			fora.append((pino, net, p))
			perto = lado.formas_perto(p, 6.0)
			if perto:
				erros.append(min(((q.x - p.x) ** 2 + (q.y - p.y) ** 2) ** 0.5 for q in perto))
		erros.sort()
		return fora, (erros[len(erros) // 2] if erros else None)

	def _eh_printout(self, i):
		"""Pagina de PCB printout: o texto e dominado pelos marcadores PA/CO."""
		palavras = self.doc[i].get_text('words')
		if len(palavras) < 200:
			return False
		marc = sum(1 for w in palavras if w[4].startswith(('PA', 'CO')))
		return marc > 0.5 * len(palavras)

	def _achar_netlist(self):
		"""Procura uma netlist Protel (.NET) ao lado do PDF."""
		raiz = os.path.dirname(os.path.abspath(self.caminho))
		achados = []
		for pasta, _dirs, arquivos in os.walk(raiz):
			for nome in arquivos:
				if nome.lower().endswith('.net'):
					achados.append(os.path.join(pasta, nome))
		achados.sort(key=lambda p: os.path.getmtime(p), reverse=True)
		return achados[0] if achados else None

	def pinos(self, ref):
		"""[(pino, net, rect_do_pad)] do componente, ordenado por pino."""
		ref = _norm(ref)
		pads = self.pads.pinos(ref) if self.pads else {}
		nets = self.netlist.pinos(ref) if self.netlist else {}
		nomes = set(pads) | set(nets)

		def chave(p):
			return (0, int(p), '') if p.isdigit() else (1, 0, p)

		return [(p, nets.get(p, ''), pads.get(p)) for p in sorted(nomes, key=chave)]

	def _nome_pagina(self, i):
		"""Deduz o nome do lado pelo bookmark da pagina ('Top'/'Bottom')."""
		titulos = [t for lvl, t, pg in self.doc.get_toc() if pg - 1 == i]
		for t in titulos:
			low = t.lower()
			if 'bottom' in low:
				return 'Bottom'
			if 'top' in low:
				return 'Top'
		if titulos:
			return titulos[-1]
		return 'Pagina %d' % (i + 1)

	def buscar(self, designador):
		"""Lista de (lado, rect) das ocorrencias de um designador."""
		alvo = _norm(designador)
		achados = []
		for lado in self.lados:
			for r in lado.itens.get(alvo, []):
				achados.append((lado, r))
		return achados

	def designadores(self, prefixo=''):
		"""Designadores conhecidos, filtrados por trecho; prefixo vem primeiro."""
		p = _norm(prefixo)
		vistos = {}
		for lado in self.lados:
			for nome in lado.itens:
				if p and p not in nome:
					continue
				vistos.setdefault(nome, []).append(lado.nome)

		def chave(nome):
			m = re.match(r'^([A-Z]+)(\d+)', nome)
			letras, num = (m.group(1), int(m.group(2))) if m else (nome, 0)
			return (0 if p and nome.startswith(p) else 1, letras, num, nome)

		return OrderedDict((n, vistos[n]) for n in sorted(vistos, key=chave))

	def recortar(self, lado, rect, zoom=None, largura=1400, altura=1000, marcar=True):
		"""Renderiza um PNG centrado no componente; devolve os bytes da imagem."""
		if zoom is None:
			w = max(rect.width, 1.0) * PAD_FACTOR + PAD_PT
			h = max(rect.height, 1.0) * PAD_FACTOR + PAD_PT
			zoom = min(largura / w, altura / h)
			zoom = max(ZOOM_MIN, min(ZOOM_MAX, zoom))
		meia_w, meia_h = largura / (2 * zoom), altura / (2 * zoom)
		cx, cy = (rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2
		clip = fitz.Rect(cx - meia_w, cy - meia_h, cx + meia_w, cy + meia_h) & lado.rect
		page = lado.page
		anot = None
		if marcar:
			anot = page.add_rect_annot(rect + (-1.5, -1.5, 1.5, 1.5))
			anot.set_colors(stroke=(1, 0, 0))
			anot.set_border(width=0.4)
			anot.update()
		try:
			pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, annots=marcar)
			dados = pix.tobytes('png')
		finally:
			if anot is not None:
				page.delete_annot(anot)
		return dados


# ---------------------------------------------------------------- interface

class App:
	"""Janela de busca e zoom."""

	def __init__(self, projeto):
		import tkinter as tk
		from tkinter import ttk
		self.tk, self.ttk = tk, ttk
		self.prj = projeto
		self.lado = projeto.lados[0]
		self.zoom = 1.0
		self.giro = 0               # graus; acompanha a placa na bancada
		self.centro = (self.lado.rect.width / 2, self.lado.rect.height / 2)
		self.achados = []          # [(lado, rect), ...] do designador atual
		self.indice = 0
		self.alvo = None           # (lado, rect) em destaque
		self.zoom_alvo = None
		self.pinos = []             # [(pino, net, rect_do_pad), ...] do componente
		self.pads_vista = {}        # pino -> Point projetado na vista atual
		self.pads_erro = None       # distancia tipica da projecao aos pads desenhados
		self.pino_alvo = None       # (pino, net) em destaque
		self.msg = ''               # aviso transitorio na barra de status
		self.n_lista = 0
		self._img = None
		self._render_id = None

		self.root = tk.Tk()
		self.root.title('pcbzoom - %s' % os.path.basename(projeto.caminho))
		self.root.geometry('1280x820')
		self._montar()
		self.enquadrar()
		self.busca.focus_set()

	# ------------------------------------------------------------ layout
	def _montar(self):
		tk, ttk = self.tk, self.ttk
		barra = ttk.Frame(self.root, padding=(8, 6))
		barra.pack(side='top', fill='x')

		ttk.Label(barra, text='Componente:').pack(side='left')
		self.var_busca = tk.StringVar()
		self.busca = ttk.Entry(barra, textvariable=self.var_busca, width=16, font=('Consolas', 12))
		self.busca.pack(side='left', padx=(6, 6))
		self.busca.bind('<Return>', lambda e: self.localizar())
		self.busca.bind('<KeyRelease>', self._filtrar)
		self.busca.bind('<Down>', lambda e: (self.lista.focus_set(), self._sel_lista(0)))

		ttk.Button(barra, text='Localizar', command=self.localizar).pack(side='left')
		ttk.Button(barra, text='Pagina inteira (0)', command=self.enquadrar).pack(side='left', padx=(10, 0))
		ttk.Button(barra, text='Salvar PNG', command=self.salvar).pack(side='left', padx=(6, 0))

		self.var_lado = tk.StringVar(value=self.lado.nome)
		cx = ttk.Combobox(barra, textvariable=self.var_lado, state='readonly', width=12,
						  values=[l.nome for l in self.prj.lados])
		cx.pack(side='right')
		cx.bind('<<ComboboxSelected>>', lambda e: self.trocar_lado(self.var_lado.get()))
		ttk.Label(barra, text='Lado:').pack(side='right', padx=(0, 6))

		corpo = ttk.Panedwindow(self.root, orient='horizontal')
		corpo.pack(fill='both', expand=True)

		esq = ttk.Frame(corpo)
		self.lista = tk.Listbox(esq, font=('Consolas', 10), activestyle='none', exportselection=False)
		sb = ttk.Scrollbar(esq, orient='vertical', command=self.lista.yview)
		self.lista.configure(yscrollcommand=sb.set)
		sb.pack(side='right', fill='y')
		self.lista.pack(side='left', fill='both', expand=True)
		self.lista.bind('<<ListboxSelect>>', self._da_lista)
		self.lista.bind('<Return>', lambda e: self.localizar())
		corpo.add(esq, weight=0)

		# painel de pinos: pino, net e um salto para o pad no PCB Print
		pinos = ttk.Frame(corpo)
		self.rotulo_pinos = ttk.Label(pinos, text='Pinos', anchor='w', padding=(4, 2))
		self.rotulo_pinos.pack(side='top', fill='x')
		self.lista_pinos = tk.Listbox(pinos, font=('Consolas', 10), activestyle='none',
									  exportselection=False, width=30)
		sbp = ttk.Scrollbar(pinos, orient='vertical', command=self.lista_pinos.yview)
		self.lista_pinos.configure(yscrollcommand=sbp.set)
		sbp.pack(side='right', fill='y')
		self.lista_pinos.pack(side='left', fill='both', expand=True)
		self.lista_pinos.bind('<Double-Button-1>', lambda e: self.ir_para_pino())
		self.lista_pinos.bind('<Return>', lambda e: self.ir_para_pino())
		corpo.add(pinos, weight=0)

		dir_ = ttk.Frame(corpo)
		self.canvas = tk.Canvas(dir_, bg='#202020', highlightthickness=0)
		self.canvas.pack(fill='both', expand=True)
		corpo.add(dir_, weight=1)

		self.status = ttk.Label(self.root, text='', anchor='w', padding=(8, 4),
								relief='sunken', font=('Consolas', 9))
		self.status.pack(side='bottom', fill='x')

		c = self.canvas
		c.bind('<Configure>', lambda e: self.agendar())
		c.bind('<MouseWheel>', self._roda)
		c.bind('<Button-4>', lambda e: self._roda(e, 1))
		c.bind('<Button-5>', lambda e: self._roda(e, -1))
		c.bind('<ButtonPress-1>', self._pan_ini)
		c.bind('<B1-Motion>', self._pan)
		c.bind('<Button-1>', lambda e: c.focus_set(), add='+')

		r = self.root
		r.bind('<plus>', self._atalho(lambda: self.aplicar_zoom(1.25)))
		r.bind('<KP_Add>', self._atalho(lambda: self.aplicar_zoom(1.25)))
		r.bind('<minus>', self._atalho(lambda: self.aplicar_zoom(1 / 1.25)))
		r.bind('<KP_Subtract>', self._atalho(lambda: self.aplicar_zoom(1 / 1.25)))
		r.bind('<Key-0>', self._atalho(self.enquadrar))
		r.bind('<Key-z>', self._atalho(lambda: self.ir_para(self.indice)))
		r.bind('<Key-g>', self._atalho(self.ir_para_gnd))
		r.bind('<Key-r>', self._atalho(lambda: self.girar(90)))
		r.bind('<Key-R>', self._atalho(lambda: self.girar(-90)))
		r.bind('<F3>', lambda e: self.proxima(1))
		r.bind('<Shift-F3>', lambda e: self.proxima(-1))
		r.bind('<Tab>', self._tab)
		r.bind('<Control-s>', lambda e: self.salvar())
		r.bind('<Escape>', lambda e: (self.busca.focus_set(), self.busca.select_range(0, 'end')))
		self._preencher_lista('')

	# ------------------------------------------------------------ lista
	def _preencher_lista(self, filtro):
		itens = self.prj.designadores(filtro)
		self.lista.delete(0, 'end')
		for nome, lados in list(itens.items())[:3000]:
			self.lista.insert('end', '%-10s %s' % (nome, ','.join(lados)))
		self.n_lista = len(itens)
		self.agendar()

	def _filtrar(self, event=None):
		if event is not None and event.keysym in ('Return', 'Up', 'Down', 'Tab'):
			return
		self._preencher_lista(self.var_busca.get())

	def _sel_lista(self, i):
		if self.lista.size():
			self.lista.selection_clear(0, 'end')
			self.lista.selection_set(i)
			self.lista.see(i)
			self._da_lista()

	def _da_lista(self, event=None):
		sel = self.lista.curselection()
		if not sel:
			return
		nome = self.lista.get(sel[0]).split()[0]
		self.var_busca.set(nome)
		self.localizar(foco=False)

	# ------------------------------------------------------------ busca
	def localizar(self, foco=True):
		nome = _norm(self.var_busca.get())
		if not nome:
			return
		self.achados = self.prj.buscar(nome)
		if not self.achados:
			self.msg = '%s: nao encontrado no PDF' % nome
			self._preencher_pinos(nome)
			self.pads_vista = {}
			self.agendar()
			return
		self.msg = ''
		self.pino_alvo = None
		self._preencher_pinos(nome, self.achados[0][0])
		self.indice = 0
		self.ir_para(0)
		if foco:
			# com o componente achado, o foco vai para o desenho: e la que as
			# teclas de uma letra valem (R gira, G vai no GND, 0 enquadra).
			# Esc traz o foco de volta para a busca.
			self.busca.select_range(0, 'end')
			self.canvas.focus_set()

	# ------------------------------------------------------------ pinos
	def _preencher_pinos(self, ref, lado=None):
		"""Lista os pinos do componente com a net de cada um."""
		self.pinos = self.prj.pinos(ref)
		self.pads_vista, self.pads_erro = {}, None
		if lado is not None and lado.tipo == 'montagem':
			pads, erro = self.prj.pads_na_montagem(ref, lado)
			self.pads_vista = {pino: ponto for pino, _net, ponto in pads}
			self.pads_erro = erro
		self.lista_pinos.delete(0, 'end')
		gnd = 0
		for i, (pino, net, rect) in enumerate(self.pinos):
			marca = '*' if _eh_gnd(net) else (' ' if rect else '?')
			self.lista_pinos.insert('end', '%s%-5s %s' % (marca, pino, net or '-'))
			if _eh_gnd(net):
				gnd += 1
				self.lista_pinos.itemconfigure(i, foreground='#0a7d24')
			elif not rect:
				self.lista_pinos.itemconfigure(i, foreground='#999999')
		texto = 'Pinos de %s' % ref if self.pinos else 'Pinos'
		if gnd:
			texto += '  -  %d em GND (tecla G)' % gnd
		if self.pads_erro is not None and self.pads_erro > 1.0:
			texto += '  [projecao a %.1f pt dos pads]' % self.pads_erro
		if self.prj.pads and self.prj.pads.incerto(ref):
			texto += '  [pads incertos]'
		self.rotulo_pinos.configure(text=texto)

	def ir_para_pino(self, indice=None):
		"""Destaca o pad do pino escolhido, na propria vista de montagem."""
		if indice is None:
			sel = self.lista_pinos.curselection()
			if not sel:
				return
			indice = sel[0]
		if indice >= len(self.pinos):
			return
		pino, net, rect = self.pinos[indice]
		ponto = self.pads_vista.get(pino)
		if ponto is None:
			self.msg = ('pino %s: sem pad no PCB Print' % pino if rect is None else
						'pino %s: pad nao projetado nesta vista' % pino)
			self.agendar()
			return
		self.msg = ''
		self.pino_alvo = (pino, net)
		self.lista_pinos.selection_clear(0, 'end')
		self.lista_pinos.selection_set(indice)
		self.lista_pinos.see(indice)
		cw = max(self.canvas.winfo_width(), 200)
		ch = max(self.canvas.winfo_height(), 200)
		# enquadra o componente inteiro, para o pino aparecer no contexto dele
		xs = [p.x for p in self.pads_vista.values()]
		ys = [p.y for p in self.pads_vista.values()]
		w = max(max(xs) - min(xs), 1.0) + PAD_PT
		h = max(max(ys) - min(ys), 1.0) + PAD_PT
		self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min(cw / w, ch / h)))
		self.centro = (ponto.x, ponto.y)
		self.agendar()

	def ir_para_gnd(self):
		"""Pula para o primeiro pino de terra do componente localizado."""
		for i, (pino, net, rect) in enumerate(self.pinos):
			if _eh_gnd(net) and pino in self.pads_vista:
				return self.ir_para_pino(i)
		self.msg = 'sem pino de GND com pad localizado'
		self.agendar()

	def proxima(self, passo):
		if len(self.achados) > 1:
			self.indice = (self.indice + passo) % len(self.achados)
			self.ir_para(self.indice)

	def ir_para(self, i):
		if not self.achados:
			return
		lado, rect = self.achados[i % len(self.achados)]
		if lado.tipo != 'print':
			self.pino_alvo = None
		self.lado = lado
		self.var_lado.set(lado.nome)
		self.alvo = (lado, rect)
		w = max(rect.width, 1.0) * PAD_FACTOR + PAD_PT
		h = max(rect.height, 1.0) * PAD_FACTOR + PAD_PT
		cw = max(self.canvas.winfo_width(), 200)
		ch = max(self.canvas.winfo_height(), 200)
		self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, min(cw / w, ch / h)))
		self.zoom_alvo = self.zoom
		self.centro = ((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)
		self.agendar()

	def trocar_lado(self, nome):
		for lado in self.prj.lados:
			if lado.nome == nome and lado is not self.lado:
				# se o componente procurado existe nesse lado, pula direto nele
				for i, (l, _r) in enumerate(self.achados):
					if l is lado:
						self.indice = i
						return self.ir_para(i)
				self.lado = lado
				self.alvo = None
				return self.enquadrar()

	def _tab(self, event=None):
		lados = [l.nome for l in self.prj.lados]
		i = (lados.index(self.lado.nome) + 1) % len(lados)
		self.var_lado.set(lados[i])
		self.trocar_lado(lados[i])
		return 'break'

	# ------------------------------------------------------------ vista
	def enquadrar(self):
		cw = max(self.canvas.winfo_width(), 200)
		ch = max(self.canvas.winfo_height(), 200)
		pr = self.lado.rect
		vista = fitz.Rect(pr) * fitz.Matrix(1, 1).prerotate(self.giro)
		self.zoom = min(cw / vista.width, ch / vista.height)
		self.centro = (pr.width / 2, pr.height / 2)
		self.agendar()

	def aplicar_zoom(self, fator, ancora=None):
		novo = max(ZOOM_MIN, min(ZOOM_MAX, self.zoom * fator))
		if novo == self.zoom:
			return
		if ancora:
			# mantem o ponto sob o cursor parado
			px, py = self._tela_para_pdf(*ancora)
			cx, cy = self.centro
			self.centro = (px - (px - cx) * (self.zoom / novo),
						   py - (py - cy) * (self.zoom / novo))
		self.zoom = novo
		self.agendar()

	def _roda(self, event, delta=None):
		d = delta if delta is not None else (1 if event.delta > 0 else -1)
		self.aplicar_zoom(1.25 if d > 0 else 1 / 1.25, (event.x, event.y))

	def _pan_ini(self, event):
		self._pan_ref = (event.x, event.y, self.centro)

	def _pan(self, event):
		# mede o arrasto em coordenadas da pagina, para funcionar girado
		x0, y0, ref = self._pan_ref
		self.centro = ref
		px0, py0 = self._tela_para_pdf(x0, y0)
		px1, py1 = self._tela_para_pdf(event.x, event.y)
		self.centro = (ref[0] - (px1 - px0), ref[1] - (py1 - py0))
		self.agendar()

	def matriz(self):
		"""Matriz da vista: zoom e giro, a mesma que o render usa.

		Tirar as duas conversoes daqui garante que os marcadores nao possam
		divergir do desenho quando a placa esta girada.
		"""
		return fitz.Matrix(self.zoom, self.zoom).prerotate(self.giro)

	def _centro_dev(self, m=None):
		m = m or self.matriz()
		return fitz.Point(*self.centro) * m

	def _tela_para_pdf(self, x, y):
		cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
		m = self.matriz()
		c = self._centro_dev(m)
		p = fitz.Point(c.x + x - cw / 2, c.y + y - ch / 2) * ~m
		return (p.x, p.y)

	def _pdf_para_tela(self, x, y):
		cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
		m = self.matriz()
		c = self._centro_dev(m)
		p = fitz.Point(x, y) * m
		return (cw / 2 + p.x - c.x, ch / 2 + p.y - c.y)

	def _atalho(self, acao):
		"""Atalho de uma tecla que nao atrapalha quem esta digitando na busca.

		As teclas soltas ('r', 'g', '0', 'z') sao presas na janela, entao
		tambem disparavam no meio de um designador: digitar 'R1052' girava a
		vista e o '0' enquadrava a pagina.
		"""
		def disparar(event=None):
			try:
				if self.root.focus_get() is self.busca:
					return None
			except Exception:
				pass
			acao()
			return 'break'
		return disparar

	def girar(self, passo):
		"""Gira a vista em 90 graus, para acompanhar a placa na bancada."""
		self.giro = (self.giro + passo) % 360
		self.agendar()

	def agendar(self):
		"""Agrupa redesenhos seguidos (resize, pan) num unico render."""
		if self._render_id:
			self.root.after_cancel(self._render_id)
		self._render_id = self.root.after(15, self.desenhar)

	def desenhar(self):
		self._render_id = None
		cw = max(self.canvas.winfo_width(), 1)
		ch = max(self.canvas.winfo_height(), 1)
		pr = self.lado.rect
		cx, cy = self.centro
		# mantem a vista sobre a pagina
		meia_w, meia_h = cw / (2 * self.zoom), ch / (2 * self.zoom)
		cx = min(max(cx, pr.x0 - meia_w / 2), pr.x1 + meia_w / 2)
		cy = min(max(cy, pr.y0 - meia_h / 2), pr.y1 + meia_h / 2)
		self.centro = (cx, cy)

		# o pedaco de pagina a renderizar e o que cabe nos cantos da tela,
		# que com a vista girada nao e mais um retangulo alinhado
		cantos = [self._tela_para_pdf(x, y)
				  for x, y in ((0, 0), (cw, 0), (0, ch), (cw, ch))]
		clip = fitz.Rect(min(p[0] for p in cantos), min(p[1] for p in cantos),
						 max(p[0] for p in cantos), max(p[1] for p in cantos)) & pr
		self.canvas.delete('all')
		if clip.is_empty:
			return
		mat = self.matriz()
		pix = self.lado.page.get_pixmap(matrix=mat, clip=clip)
		self._img = self.tk.PhotoImage(data=pix.tobytes('ppm'))
		# pix.x/pix.y sao a posicao do recorte ja girado, no espaco da matriz
		c = self._centro_dev(mat)
		self.canvas.create_image(round(cw / 2 + pix.x - c.x), round(ch / 2 + pix.y - c.y),
								 image=self._img, anchor='nw')

		info = 'lado %s | zoom %.0f%% | %d componente(s) na lista' % (
			self.lado.nome, self.zoom * 100, self.n_lista)
		self._desenhar_pads()
		if self.alvo and self.alvo[0] is self.lado:
			lado, r = self.alvo
			x0, y0 = self._pdf_para_tela(r.x0, r.y0)
			x1, y1 = self._pdf_para_tela(r.x1, r.y1)
			m = 6
			self.canvas.create_rectangle(x0 - m, y0 - m, x1 + m, y1 + m,
										 outline='#ff2d2d', width=2)
			# miras apontando o componente
			for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
				self.canvas.create_line(
					(x0 + x1) / 2 + dx * (m + 10 + (x1 - x0) / 2),
					(y0 + y1) / 2 + dy * (m + 10 + (y1 - y0) / 2),
					(x0 + x1) / 2 + dx * (m + 34 + (x1 - x0) / 2),
					(y0 + y1) / 2 + dy * (m + 34 + (y1 - y0) / 2),
					fill='#ff2d2d', width=2)
			nome = _norm(self.var_busca.get())
			if self.pino_alvo:
				pino, net = self.pino_alvo
				info = '%s pino %s | net %s%s | lado %s | zoom %.0f%%' % (
					nome, pino, net or '(sem net)',
					'  <<< GND' if _eh_gnd(net) else '', lado.nome, self.zoom * 100)
			else:
				ocorr = ' (%d/%d)' % (self.indice + 1, len(self.achados)) if len(self.achados) > 1 else ''
				info = '%s%s | lado %s | zona %s | zoom %.0f%%' % (
					nome, ocorr, lado.nome, lado.zona(r) or '?', self.zoom * 100)
			self.canvas.create_text(x1 + m + 8, y0 - m - 8, text=nome, anchor='sw',
									fill='#ff2d2d', font=('Consolas', 13, 'bold'))
		if self.giro:
			info = '%s | girado %d graus' % (info, self.giro)
		if self.msg:
			info = '%s   <<< %s' % (info, self.msg)
		self.status.configure(text=info)

	def _desenhar_pads(self):
		"""Marca os pads do componente sobre o desenho: GND em verde."""
		if not self.pads_vista or self.alvo is None or self.alvo[0] is not self.lado:
			return
		nets = {pino: net for pino, net, _r in self.pinos}
		raio = max(3.0, min(16.0, 0.55 * self.zoom))
		for pino, ponto in self.pads_vista.items():
			x, y = self._pdf_para_tela(ponto.x, ponto.y)
			if not (-20 <= x <= self.canvas.winfo_width() + 20
					and -20 <= y <= self.canvas.winfo_height() + 20):
				continue
			escolhido = self.pino_alvo and self.pino_alvo[0] == pino
			gnd = _eh_gnd(nets.get(pino, ''))
			cor = '#0a7d24' if gnd else '#1467d6'
			r = raio * (1.6 if escolhido else 1.0)
			self.canvas.create_oval(x - r, y - r, x + r, y + r,
									outline='#ff2d2d' if escolhido else cor,
									width=3 if escolhido else 2)
			if escolhido or (gnd and raio >= 6):
				self.canvas.create_text(x + r + 3, y - r - 2,
										text=pino if not gnd else '%s GND' % pino,
										anchor='sw', fill='#ff2d2d' if escolhido else cor,
										font=('Consolas', 10, 'bold'))

	# ------------------------------------------------------------ saida
	def salvar(self):
		from tkinter import filedialog, messagebox
		nome = _norm(self.var_busca.get()) or 'vista'
		destino = filedialog.asksaveasfilename(
			title='Salvar vista', defaultextension='.png',
			initialfile='%s_%s.png' % (nome, self.lado.nome),
			filetypes=[('PNG', '*.png')])
		if not destino:
			return
		if self.alvo and self.alvo[0] is self.lado:
			lado, r = self.alvo
			dados = self.prj.recortar(lado, r, zoom=self.zoom,
									  largura=self.canvas.winfo_width(),
									  altura=self.canvas.winfo_height())
		else:
			pix = self.lado.page.get_pixmap(matrix=fitz.Matrix(max(self.zoom, 2), max(self.zoom, 2)))
			dados = pix.tobytes('png')
		with open(destino, 'wb') as fh:
			fh.write(dados)
		messagebox.showinfo('pcbzoom', 'Vista salva em:\n%s' % destino)

	# ------------------------------------------------------------ servidor
	def escutar(self, porta):
		"""Aceita designadores por socket local, para scripts de bancada."""
		import queue
		import socket
		import threading
		self.fila = queue.Queue()

		def servir():
			s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
			s.bind(('127.0.0.1', porta))     # so aceita conexao da propria maquina
			s.listen(4)
			while True:
				try:
					conexao, _end = s.accept()
					with conexao:
						dados = conexao.recv(256).decode('utf-8', 'replace').strip()
						if dados:
							self.fila.put(dados)
						conexao.sendall(b'ok\n')
				except OSError:
					break

		threading.Thread(target=servir, daemon=True).start()
		self._drenar()

	def _drenar(self):
		"""Aplica, na thread da interface, o que chegou pelo socket."""
		try:
			while True:
				self.comando(self.fila.get_nowait())
		except Exception:
			pass
		self.root.after(100, self._drenar)

	def comando(self, texto):
		"""Executa um pedido vindo de fora: 'C1052', 'C1052 gnd', 'I11 pino 4'."""
		partes = texto.split()
		if not partes:
			return
		self.var_busca.set(partes[0])
		self._filtrar()
		self.localizar(foco=False)
		resto = ' '.join(partes[1:]).lower().replace('pino', '').strip()
		if resto in ('gnd', 'terra'):
			self.ir_para_gnd()
		elif resto:
			for i, (pino, _net, _r) in enumerate(self.pinos):
				if pino.upper() == resto.upper():
					self.ir_para_pino(i)
					break
		try:
			self.root.deiconify()
			self.root.lift()
		except Exception:
			pass

	def run(self):
		self.root.mainloop()


# ---------------------------------------------------------------- uso como modulo

PORTA_PADRAO = 51789


def mostrar(designador, pdf=None, porta=PORTA_PADRAO, iniciar=True, espera=90):
	"""Mostra um componente na janela do pcbzoom, abrindo-a se preciso.

	Feita para scripts de bancada: a cada ponto de medicao basta chamar
	``pcbzoom.mostrar('C1052')`` que a janela pula no componente. A janela
	fica aberta entre as chamadas, entao o PDF so e lido uma vez.

	:param designador: componente ('C1052'), com pino opcional ('C1052 gnd',
		'I11 pino 4')
	:param pdf: PDF de montagem; se omitido, usa a variavel de ambiente
		``PCBZOOM_PDF``
	:param iniciar: abre o visualizador se ele ainda nao estiver rodando
	:return: True se a janela recebeu o pedido
	"""
	import socket
	import subprocess
	import time

	def envia():
		with socket.create_connection(('127.0.0.1', porta), timeout=2) as s:
			s.sendall(('%s\n' % designador).encode('utf-8'))
			s.recv(16)
		return True

	try:
		return envia()
	except OSError:
		pass
	if not iniciar:
		return False

	caminho = pdf or os.environ.get('PCBZOOM_PDF')
	if not caminho:
		raise ValueError('pcbzoom.mostrar: informe o PDF em pdf= ou em PCBZOOM_PDF')
	criar = {}
	if os.name == 'nt':      # solta o visualizador do console do script
		criar['creationflags'] = (getattr(subprocess, 'DETACHED_PROCESS', 0)
								  | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
	subprocess.Popen([sys.executable, os.path.abspath(__file__), caminho,
					  '--servidor', str(porta), '-d', str(designador).split()[0]],
					 **criar)
	limite = time.time() + espera
	while time.time() < limite:
		time.sleep(0.5)
		try:
			return envia()
		except OSError:
			continue
	return False


# ---------------------------------------------------------------- cli

def main(argv=None):
	ap = argparse.ArgumentParser(
		description='Apontador de componentes em PDF de montagem de placa.')
	ap.add_argument('pdf', nargs='?', help='PDF de montagem (Assembly/Draftsman)')
	ap.add_argument('-d', '--designador', help='componente a localizar (ex.: R1234)')
	ap.add_argument('-o', '--saida', help='salva o recorte em PNG em vez de abrir a GUI')
	ap.add_argument('-z', '--zoom', type=float, help='zoom do recorte (pontos->pixels)')
	ap.add_argument('-l', '--list', dest='listar', nargs='?', const='',
					help='lista os designadores (opcionalmente filtrados por trecho)')
	ap.add_argument('-p', '--pinos', action='store_true',
					help='lista os pinos do componente com a net de cada um')
	ap.add_argument('-g', '--gnd', action='store_true',
					help='lista so os pinos de terra do componente')
	ap.add_argument('-n', '--netlist',
					help='netlist Protel (.NET); por padrao procura ao lado do PDF')
	ap.add_argument('-s', '--servidor', nargs='?', type=int, const=PORTA_PADRAO,
					help='mantem a janela aberta aceitando designadores por socket '
						 'local (use pcbzoom.mostrar() no seu script)')
	args = ap.parse_args(argv)

	caminho = args.pdf
	if not caminho:
		try:
			from tkinter import Tk, filedialog
			raiz = Tk()
			raiz.withdraw()
			caminho = filedialog.askopenfilename(title='PDF de montagem',
												 filetypes=[('PDF', '*.pdf'), ('Todos', '*.*')])
			raiz.destroy()
		except Exception:
			caminho = None
		if not caminho:
			ap.error('informe o PDF de montagem')
	if not os.path.isfile(caminho):
		sys.exit('pcbzoom: arquivo nao encontrado: %s' % caminho)

	prj = Projeto(caminho, netlist=args.netlist)

	if args.listar is not None:
		for nome, lados in prj.designadores(args.listar).items():
			print('%-10s %s' % (nome, ','.join(lados)))
		return 0

	if args.designador:
		achados = prj.buscar(args.designador)
		if not achados:
			sys.exit('pcbzoom: %s nao encontrado no PDF' % args.designador)
		for lado, r in achados:
			print('%s: lado %s, zona %s, pagina %d, x=%.1f y=%.1f'
				  % (_norm(args.designador), lado.nome, lado.zona(r) or '?',
					 lado.numero + 1, (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2))
		if args.pinos or args.gnd:
			pinos = prj.pinos(args.designador)
			if not pinos:
				print('   (sem pinos: faltam a netlist e/ou a pagina de PCB Print)')
			for pino, net, rect in pinos:
				if args.gnd and not _eh_gnd(net):
					continue
				onde = ('pad em x=%.0f y=%.0f' % ((rect.x0 + rect.x1) / 2,
												  (rect.y0 + rect.y1) / 2)
						if rect is not None else 'sem pad no PCB Print')
				print('   pino %-5s %-28s %s%s' % (pino, net or '-', onde,
													'   <<< GND' if _eh_gnd(net) else ''))
			if prj.pads and prj.pads.incerto(_norm(args.designador)):
				print('   atencao: os pads deste componente foram deduzidos e podem estar trocados')
			if not args.saida:
				return 0
		if args.saida:
			lado, r = achados[0]
			dados = prj.recortar(lado, r, zoom=args.zoom)
			with open(args.saida, 'wb') as fh:
				fh.write(dados)
			print('recorte salvo em %s' % args.saida)
			return 0

	app = App(prj)
	if args.servidor:
		app.escutar(args.servidor)
		print('pcbzoom: ouvindo em 127.0.0.1:%d' % args.servidor)
	if args.designador:
		app.var_busca.set(_norm(args.designador))
		app.root.after(120, app.localizar)
	app.run()
	return 0


if __name__ == '__main__':
	sys.exit(main())
