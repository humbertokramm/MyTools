"""
**File: pcbview.py**

**Descrição**
	Abre o "Viewer PCB & 3D" (o HTML da empresa) já no componente certo, com
	o projeto carregado e só a camada do lado dele visível.

	O HTML sozinho não consegue: uma página ``file://`` não lê pasta por
	caminho, então o projeto tem que ser escolhido na mão. Aqui o Python
	serve o viewer e os arquivos do projeto em ``http://127.0.0.1``; um
	gancho injetado na página busca o ``.PcbDoc`` por ``fetch``, acha o
	componente, isola a camada e vira a placa se ele estiver embaixo. Tambem
	aceita o nome de uma net no lugar do componente: nesse caso seleciona a
	net inteira, ligando a Top, a Bottom e as camadas em que aquela net tem
	cobre - uma trilha por layer interno sumiria e pareceria que nada foi
	selecionado. O status diz em quais camadas o cobre esta.

	A mesma aba acompanha as chamadas seguintes (ela consulta o alvo no
	servidor), então dá para seguir uma varredura de pontos de medição sem
	reabrir nada.

**Uso**

	Linha de comando::

		python pcbview.py C:\\Projetos\\089100_PROJ -c C1052
		python pcbview.py C:\\Projetos\\089100_PROJ -c C200 -p 2
		python pcbview.py C:\\Projetos\\089100_PROJ -c C200 --sem-isolar

	De dentro de um script de bancada::

		import pcbview
		pcbview.abrir(r'C:\\Projetos\\089100_PROJ', 'C1052')   # abre a aba
		pcbview.abrir(r'C:\\Projetos\\089100_PROJ', 'C200', pino='2')

	O HTML do viewer fica em ``viewer/Viewer_PCB_3D.html``, no próprio
	repositório, numa cópia intacta do arquivo do Diogo — o gancho é injetado
	só na hora de servir, então atualizar é substituir o arquivo. A busca
	tenta, nesta ordem: ``viewer=``/``--viewer``, a variável ``PCBVIEW_HTML``,
	``viewer/``, a pasta deste arquivo, ``~/Downloads`` e o diretório atual.

**Requisitos**
	Só a biblioteca padrão. O gancho fica em ``pcbview_gancho.js``, ao lado
	deste arquivo.
"""

import argparse
import base64
import http.server
import json
import os
import re
import sys
import threading
import webbrowser

PORTA_PADRAO = 51790
NOMES_VIEWER = ('Viewer_PCB_3D.html', 'Viewer PCB 3D.html')
EXT_PROJETO = ('.pcbdoc',)                 # só a placa: os .SchDoc deixam a carga lenta
IGNORAR = re.compile(r'(^|[\\/])(history|__previews|Project Outputs)([\\/]|$)', re.I)


def achar_viewer(dado=None):
	"""Localiza o HTML do Viewer PCB & 3D."""
	candidatos = []
	if dado:
		candidatos.append(dado)
	if os.environ.get('PCBVIEW_HTML'):
		candidatos.append(os.environ['PCBVIEW_HTML'])
	aqui = os.path.dirname(os.path.abspath(__file__))
	# a copia do repositorio vem antes do Downloads, para o comportamento nao
	# depender do que sobrou na pasta de downloads da maquina
	pastas = [os.path.join(aqui, 'viewer'), aqui,
			  os.path.join(os.path.expanduser('~'), 'Downloads'), os.getcwd()]
	for pasta in pastas:
		for nome in NOMES_VIEWER:
			candidatos.append(os.path.join(pasta, nome))
	for c in candidatos:
		if c and os.path.isfile(c):
			return c
	raise FileNotFoundError(
		'pcbview: nao achei o HTML do viewer. Passe viewer=/--viewer ou defina PCBVIEW_HTML.')


def arquivos_do_projeto(pasta, extensoes=EXT_PROJETO):
	"""Arquivos do projeto que o viewer precisa, com caminho relativo."""
	achados = []
	for raiz, dirs, nomes in os.walk(pasta):
		dirs[:] = [d for d in dirs if not IGNORAR.search(d)]
		for nome in nomes:
			if nome.lower().endswith(tuple(extensoes)):
				inteiro = os.path.join(raiz, nome)
				rel = os.path.relpath(inteiro, pasta).replace('\\', '/')
				if not IGNORAR.search(rel):
					achados.append(rel)
	achados.sort(key=lambda p: (p.count('/'), p.lower()))
	if not achados:
		raise FileNotFoundError('pcbview: nenhum %s em %s'
								% ('/'.join(extensoes), pasta))
	return achados


def pagina_com_gancho(caminho_viewer):
	"""Devolve o HTML do viewer com o gancho injetado no visualizador de projeto.

	O viewer guarda cada ferramenta como um documento em base64; aqui o de
	projeto e desempacotado, recebe o gancho antes de ``</body>`` e volta
	empacotado. O arquivo original nao e tocado.
	"""
	with open(caminho_viewer, encoding='utf-8') as fh:
		pagina = fh.read()
	gancho = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pcbview_gancho.js')
	with open(gancho, encoding='utf-8') as fh:
		js = fh.read()

	m = re.search(r'id="src-proj">([^<]+)</script>', pagina)
	if not m:
		raise ValueError('pcbview: nao achei o visualizador de projeto dentro do HTML')
	doc = base64.b64decode(m.group(1).strip()).decode('utf-8')
	marca = '</body>'
	if marca not in doc:
		raise ValueError('pcbview: o visualizador de projeto mudou de formato')
	doc = doc.replace(marca, '<script>\n%s\n</script>\n%s' % (js, marca), 1)
	novo = base64.b64encode(doc.encode('utf-8')).decode('ascii')
	return pagina[:m.start(1)] + novo + pagina[m.end(1):]


class _Handler(http.server.BaseHTTPRequestHandler):
	"""Serve o viewer, o alvo atual e os arquivos listados do projeto."""

	servidor = None       # preenchido pelo Servidor

	def log_message(self, *a):
		pass              # silencia o log de cada requisicao

	def _envia(self, dados, tipo='application/octet-stream'):
		self.send_response(200)
		self.send_header('Content-Type', tipo)
		self.send_header('Content-Length', str(len(dados)))
		self.send_header('Cache-Control', 'no-store')
		self.end_headers()
		self.wfile.write(dados)

	def do_GET(self):
		s = self.servidor
		caminho = self.path.split('?')[0].split('#')[0]
		if caminho in ('/', '/index.html', '/viewer.html'):
			return self._envia(s.pagina.encode('utf-8'), 'text/html; charset=utf-8')
		if caminho == '/alvo.json':
			return self._envia(json.dumps(s.alvo).encode('utf-8'), 'application/json')
		if caminho == '/projeto/manifest.json':
			return self._envia(json.dumps(s.arquivos).encode('utf-8'), 'application/json')
		if caminho.startswith('/projeto/'):
			from urllib.parse import unquote
			rel = unquote(caminho[len('/projeto/'):])
			if rel in s.arquivos:          # so o que esta no manifesto
				with open(os.path.join(s.projeto, rel.replace('/', os.sep)), 'rb') as fh:
					return self._envia(fh.read())
		self.send_error(404)


class Servidor:
	"""Servidor local que entrega o viewer e o projeto para o navegador."""

	def __init__(self, projeto, caminho_viewer=None, porta=PORTA_PADRAO, extensoes=EXT_PROJETO):
		self.projeto = os.path.abspath(projeto)
		self.viewer = achar_viewer(caminho_viewer)
		self.pagina = pagina_com_gancho(self.viewer)
		self.arquivos = arquivos_do_projeto(self.projeto, extensoes)
		self.alvo = {'comp': '', 'pino': '', 'net': '', 'iso': True, 'seq': 0}
		classe = type('Handler', (_Handler,), {'servidor': self})
		self.http = http.server.ThreadingHTTPServer(('127.0.0.1', porta), classe)
		self.porta = self.http.server_address[1]
		threading.Thread(target=self.http.serve_forever, daemon=True).start()

	def define_alvo(self, componente, pino='', isolar=True, net=''):
		self.alvo = {'comp': str(componente or '').strip(), 'pino': str(pino or '').strip(),
					 'net': str(net or '').strip(), 'iso': bool(isolar),
					 'seq': self.alvo['seq'] + 1}

	def url(self):
		from urllib.parse import quote
		a = self.alvo
		return 'http://127.0.0.1:%d/?comp=%s&pino=%s&net=%s&iso=%d#projeto' % (
			self.porta, quote(a['comp']), quote(a['pino']), quote(a['net']),
			1 if a['iso'] else 0)

	def fechar(self):
		self.http.shutdown()


_SERVIDOR = None


def abrir(projeto, componente='', pino='', isolar=True, viewer=None, porta=PORTA_PADRAO,
		  extensoes=EXT_PROJETO, abrir_navegador=True, net=''):
	"""Mostra um componente (ou uma net) no viewer, subindo o servidor na 1a chamada.

	:param projeto: pasta do projeto Altium (onde esta o ``.PcbDoc``)
	:param componente: designador, ex. ``'C1052'``
	:param pino: pino a destacar, ex. ``'2'`` (opcional)
	:param net: nome da net, ex. ``'DGND'``; tem prioridade sobre o componente
	:param isolar: para um componente, deixa visivel so a camada do lado dele;
		para uma net, a Top, a Bottom e as camadas em que ela tem cobre
	:return: URL servida
	"""
	global _SERVIDOR
	novo = False
	if _SERVIDOR is None or _SERVIDOR.projeto != os.path.abspath(projeto):
		if _SERVIDOR is not None:
			_SERVIDOR.fechar()
		try:
			_SERVIDOR = Servidor(projeto, viewer, porta, extensoes)
		except OSError as erro:          # porta ocupada: provavelmente outra instancia
			if erro.errno not in (10048, 98):
				raise
			_SERVIDOR = Servidor(projeto, viewer, 0, extensoes)
		novo = True
	_SERVIDOR.define_alvo(componente, pino, isolar, net)
	url = _SERVIDOR.url()
	if novo and abrir_navegador:
		webbrowser.open(url)
	return url


def servindo():
	"""Servidor em uso nesta sessao, se houver."""
	return _SERVIDOR


def main(argv=None):
	ap = argparse.ArgumentParser(
		description='Abre o Viewer PCB & 3D no componente, com a camada do lado dele.')
	ap.add_argument('projeto', help='pasta do projeto Altium (com o .PcbDoc)')
	ap.add_argument('-c', '--componente', default='', help='designador, ex. C1052')
	ap.add_argument('-n', '--net', default='',
					help='nome da net, ex. DGND; aceita trecho ("SWITCH_TRST" acha '
						 '"#SWITCH_TRST"). Nome com # precisa de aspas no shell')
	ap.add_argument('-p', '--pino', default='', help='pino a destacar, ex. 2')
	ap.add_argument('--sem-isolar', action='store_true',
					help='mantem todas as camadas visiveis')
	ap.add_argument('--viewer', help='caminho do Viewer_PCB_3D.html')
	ap.add_argument('--porta', type=int, default=PORTA_PADRAO)
	ap.add_argument('--tudo', action='store_true',
					help='serve tambem os .SchDoc e o .PrjPcb (carga bem mais lenta)')
	args = ap.parse_args(argv)

	exts = ('.pcbdoc', '.schdoc', '.prjpcb') if args.tudo else EXT_PROJETO
	if not args.componente and not args.net:
		ap.error('informe um componente (-c) ou uma net (-n)')
	url = abrir(args.projeto, args.componente, args.pino, not args.sem_isolar,
				args.viewer, args.porta, exts, net=args.net)
	s = servindo()
	print('pcbview: %d arquivo(s) de %s' % (len(s.arquivos), s.projeto))
	print('pcbview: servindo em %s' % url)
	print('pcbview: deixe esta janela aberta enquanto usar o viewer (Ctrl+C encerra)')
	try:
		threading.Event().wait()
	except KeyboardInterrupt:
		print('\npcbview: encerrado')
	return 0


if __name__ == '__main__':
	sys.exit(main())
