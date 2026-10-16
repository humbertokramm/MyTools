"""
**File: pcbzoom.py**

**Descrição**
	Apontador de componentes em PDF de montagem (Assembly / Draftsman).
	Indexa os designadores presentes na camada de texto do PDF (lado de cima e
	lado de baixo), permite buscar um componente e dar zoom imediato nele.

**Uso**

	Interface gráfica (busca interativa)::

		python pcbzoom.py "Output_Job.PDF"

	Consulta direta pela linha de comando::

		python pcbzoom.py "Output_Job.PDF" -d R1234
		python pcbzoom.py "Output_Job.PDF" -d R1234 -o r1234.png
		python pcbzoom.py "Output_Job.PDF" --list U

**Teclas (GUI)**

	- ``Enter``        : localiza o designador digitado
	- ``roda do mouse``: zoom in/out no ponteiro
	- ``arrastar``     : pan
	- ``+`` / ``-``    : zoom in/out
	- ``0``            : enquadra a página inteira
	- ``Z``            : volta ao zoom do componente localizado
	- ``F3`` / ``Shift+F3``: próxima/anterior ocorrência do designador
	- ``Tab``          : alterna lado de cima / lado de baixo
	- ``Ctrl+S``       : salva a vista atual em PNG
	- ``Esc``          : volta o foco para o campo de busca

**Requisitos**
	``pymupdf``
"""

import argparse
import os
import re
import sys
from collections import OrderedDict

try:
	import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
	sys.exit('pcbzoom: modulo "pymupdf" nao encontrado. Instale com: pip install pymupdf')


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


class Lado:
	"""Um lado da placa: uma pagina do PDF com seus designadores indexados."""

	def __init__(self, doc, numero, nome):
		self.doc = doc
		self.numero = numero          # indice da pagina (0-based)
		self.nome = nome              # 'Top', 'Bottom' ou titulo do bookmark
		self.page = doc[numero]
		self.rect = fitz.Rect(self.page.rect)
		self.itens = OrderedDict()    # designador -> [fitz.Rect, ...]
		self.colunas = []             # [(rotulo, x), ...]
		self.linhas = []              # [(rotulo, y), ...]
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

	def __init__(self, caminho):
		self.caminho = caminho
		self.doc = fitz.open(caminho)
		self.lados = [Lado(self.doc, i, self._nome_pagina(i))
					  for i in range(self.doc.page_count)]

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
		self.centro = (self.lado.rect.width / 2, self.lado.rect.height / 2)
		self.achados = []          # [(lado, rect), ...] do designador atual
		self.indice = 0
		self.alvo = None           # (lado, rect) em destaque
		self.zoom_alvo = None
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
		r.bind('<plus>', lambda e: self.aplicar_zoom(1.25))
		r.bind('<KP_Add>', lambda e: self.aplicar_zoom(1.25))
		r.bind('<minus>', lambda e: self.aplicar_zoom(1 / 1.25))
		r.bind('<KP_Subtract>', lambda e: self.aplicar_zoom(1 / 1.25))
		r.bind('<Key-0>', lambda e: self.enquadrar())
		r.bind('<Key-z>', lambda e: self.ir_para(self.indice))
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
			self.agendar()
			return
		self.msg = ''
		self.indice = 0
		self.ir_para(0)
		if foco:
			self.busca.select_range(0, 'end')

	def proxima(self, passo):
		if len(self.achados) > 1:
			self.indice = (self.indice + passo) % len(self.achados)
			self.ir_para(self.indice)

	def ir_para(self, i):
		if not self.achados:
			return
		lado, rect = self.achados[i % len(self.achados)]
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
		self.zoom = min(cw / pr.width, ch / pr.height)
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
		x0, y0, (cx, cy) = self._pan_ref
		self.centro = (cx - (event.x - x0) / self.zoom, cy - (event.y - y0) / self.zoom)
		self.agendar()

	def _tela_para_pdf(self, x, y):
		cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
		cx, cy = self.centro
		return (cx + (x - cw / 2) / self.zoom, cy + (y - ch / 2) / self.zoom)

	def _pdf_para_tela(self, x, y):
		cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
		cx, cy = self.centro
		return (cw / 2 + (x - cx) * self.zoom, ch / 2 + (y - cy) * self.zoom)

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

		clip = fitz.Rect(cx - meia_w, cy - meia_h, cx + meia_w, cy + meia_h) & pr
		self.canvas.delete('all')
		if clip.is_empty:
			return
		pix = self.lado.page.get_pixmap(matrix=fitz.Matrix(self.zoom, self.zoom), clip=clip)
		self._img = self.tk.PhotoImage(data=pix.tobytes('ppm'))
		ox, oy = self._pdf_para_tela(clip.x0, clip.y0)
		self.canvas.create_image(round(ox), round(oy), image=self._img, anchor='nw')

		info = 'lado %s | zoom %.0f%% | %d componente(s) na lista' % (
			self.lado.nome, self.zoom * 100, self.n_lista)
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
			ocorr = ' (%d/%d)' % (self.indice + 1, len(self.achados)) if len(self.achados) > 1 else ''
			info = '%s%s | lado %s | zona %s | zoom %.0f%%' % (
				nome, ocorr, lado.nome, lado.zona(r) or '?', self.zoom * 100)
			self.canvas.create_text(x1 + m + 8, y0 - m - 8, text=nome, anchor='sw',
									fill='#ff2d2d', font=('Consolas', 13, 'bold'))
		if self.msg:
			info = '%s   <<< %s' % (info, self.msg)
		self.status.configure(text=info)

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

	def run(self):
		self.root.mainloop()


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

	prj = Projeto(caminho)

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
		if args.saida:
			lado, r = achados[0]
			dados = prj.recortar(lado, r, zoom=args.zoom)
			with open(args.saida, 'wb') as fh:
				fh.write(dados)
			print('recorte salvo em %s' % args.saida)
			return 0

	app = App(prj)
	if args.designador:
		app.var_busca.set(_norm(args.designador))
		app.root.after(120, app.localizar)
	app.run()
	return 0


if __name__ == '__main__':
	sys.exit(main())
