"""
**File: csvscope.py**

**Descrição**
	Classe para processamento e visualização de dados de osciloscópios e instrumentos de medição.
	Suporta múltiplos formatos (ROHDE, Tektronix, Master Tool) com análises avançadas.

**Classe Principal**

``class CsvScope``
	
	Processa sinais de osciloscópios com suporte para:
	- Múltiplos formatos de arquivo CSV
	- Análise FFT
	- Diagramas de olho PAM
	- Anotações automáticas
	- Conexão com instrumentos via PyVISA
	
	**Atributos**
	
	- ``reads``: Lista de séries de dados carregadas
	- ``title``: Título das leituras
	- ``indexNote``: Contador para anotações automáticas
	- ``path``: Caminho para salvar arquivos
	- ``yDf``: DataFrame com informações de eixos Y
	- ``inst``: Lista de instrumentos conectados
	
	**Métodos Principais**
	
	``__init__(title='Minhas Leituras', path='')``
		Inicializa uma instância da classe csvscope.
	
	``format_eng(nota, s=False)``
		Extrai notação de engenharia de labels.
		
		:param nota: String com notação entre colchetes
		:type nota: str
		:param s: Modo de retorno (False/True/'symbol')
		:type s: bool or str
		:return: Fator numérico, string com notação ou símbolo
		
	``__str__()``
		Retorna o título das leituras.

**Constantes**

``EngNotation`` (dict): Mapeamento de notação de engenharia (Y, Z, E, P, T, G, M, k, m, µ, n, p, f, etc.)

``Symbol`` (list): Lista de símbolos de unidades (V, W, A, Ω, s, Hz)

**Dependências**
	- pandas
	- matplotlib
	- numpy
	- scipy
	- sklearn
	- dirHandle

See: docs/guia_documentacao.rst
"""

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np
import matplotlib.colors as mcolors
import csv
from copy import copy,deepcopy
from scipy.signal import welch
from scipy.signal import find_peaks
from scipy import signal
import os
from datetime import datetime
from pprint import pprint
import dirHandle as dh
import re
from sklearn.cluster import KMeans
from pathlib import Path
from engMath import *
from pulse_mask import G703Clock2048kHz, G703Data2048kbits


class CsvScope:
	"""
	Classe para processamento e visualização de dados de osciloscópios e instrumentos de medição.
	
	Esta classe permite carregar, processar, filtrar e plotar sinais de diferentes formatos
	de arquivos CSV (ROHDE, Tektronix, Master Tool, etc.), além de realizar análises como FFT,
	diagramas de olho PAM e anotações automáticas.
	"""
	def __init__(self, title='Minhas Leituras',path = ''):
		"""
		Inicializa uma instância da classe csvscope.
		
		Args:
			title (str, optional): Título para as leituras. Se for um Path, usa apenas o nome do arquivo.
				Padrão é 'Minhas Leituras'.
			path (str, optional): Caminho para salvar os gráficos gerados. Padrão é string vazia.
		
		Attributes:
			reads (list): Lista de séries de dados carregadas.
			title (str): Título das leituras.
			indexNote (int): Contador para anotações automáticas.
			path (str): Caminho para salvar arquivos.
			yDf (pd.DataFrame): DataFrame com informações de eixos Y e anotações.
			inst (list): Lista de instrumentos conectados via PyVISA.
		"""
		self.reads = []
		self.title = str(title).split('\\')[-1] if isinstance(title, Path) else title
		self.indexNote = 0
		self.path = path
		#self.ySeries = []
		self.yDf = pd.DataFrame(columns=['label','xMin','yMin','xMax','yMax','xAr','yAr','draw'])
		self.inst = []
		self.Limits = {
			"logicLimits":False,
			"maxLimits":False
		}
		self.labelx='Time[ms]'
		self.dt = [0.1,0.9]
		self.fftZone = None
		self.fftZonetxt = 'left'
		self.fftylabel = "auto"
	def __str__(self):
		return self.title

	def filter_signal(self,name='ch1',fc=1e3,order=2,overwrite=True,cutoff=0.2):
		"""
		Aplica um filtro passa-baixas Butterworth a uma série de dados.
		
		Args:
			name (str, optional): Nome da série a filtrar. Padrão é 'ch1'.
			fc (float, optional): Frequência de corte do filtro em Hz. Padrão é 1e3 (1 kHz).
			ordem (int, optional): Ordem do filtro Butterworth. Padrão é 2.
			overwrite (bool, optional): Se True, substitui os dados originais pelos filtrados.
				Se False, retorna os dados filtrados sem modificar a série. Padrão é True.
			corte (float, optional): Percentual de amostras a descartar do início (0-100).
				Padrão é 0.2 (0.2%).
		
		Returns:
			tuple or None: Se overwrite=False, retorna (x_filtrado, y_filtrado).
				Se overwrite=True, retorna None (modifica a série in-place).
				Retorna None se a série não for encontrada.
		
		Note:
			O filtro remove transientes iniciais descartando uma porcentagem das amostras.
		"""
		try:
			i= self.get_order().index(name)
		except:
			print('Series not found: '+str(name))
			return
		T=self.reads[i]['x'].iat[1]-self.reads[i]['x'].iat[0]
		fs = 1/(T*self.reads[i]['engNoteX'])
		b, a = signal.butter(order, fc/(fs/2), btype='low')
		filtered = signal.lfilter(b, a, self.reads[i]['y'])
		filtered = pd.DataFrame(filtered)
		if overwrite:
			cut = int(len(filtered)*(cutoff/100))
			self.reads[i]['data'] += f'[Filtered with order {order} Butterworth @ {format_eng_str(fc,2)}Hz]'
			self.reads[i]['y'] = filtered[cut:]
			self.reads[i]['x'] = self.reads[i]['x'][cut:]
		return self.reads[i]['x']*self.reads[i]['engNoteX'], filtered*self.reads[i]['engNoteY']

	def _apply_filter(self,df,filter_params=[1e3,4]):
		fc = filter_params[0]
		ordem = filter_params[1]
		T=df['x'].iat[1]-df['x'].iat[0]
		fs = 1/(T*df['engNoteX'])
		# filtro passa-baixas Butterworth
		b, a = signal.butter(ordem, fc/(fs/2), btype='low')
		# Aplicar o filtro ao sinal
		sinal_filtrado = signal.lfilter(b, a, df['y'])
		sinal_filtrado=pd.DataFrame(sinal_filtrado)
		df['y'] = sinal_filtrado[sinal_filtrado.columns[0]]
		df['x'] = df['x'].reset_index(drop = True)

	def detect_brand_file(self, f):
		brand = ''
		try:
			with open(f, 'r') as file:
				firstLines = [next(file) for _ in range(16)]
			if len(firstLines)==16:
				if 'in s,CH' in firstLines[0]:
					if ' in V' in firstLines[0]:
						brand  = 'ROHDE'
				if 'TDS3052B in s,CH' in firstLines[0]:
					if ' in V' in firstLines[0]:
						brand  = 'TDS3052B'
				if '[key]; [value]' in firstLines[0]:
					if 'Version;' in firstLines[1]:
						if 'Name; Application.Trace' in firstLines[2]:
							brand  = 'Master Tool'
				if 'Record Length' in firstLines[0]:
					if 'Sample Interval' in firstLines[1]:
						if 'Trigger Point' in firstLines[2]:
							brand = firstLines[15].split(',')[1]
							brand  = brand
				if '# Instrumento:' in firstLines[0]:
					brand  = 'USB.VISA'
		except FileNotFoundError:
			print("Arquivo não encontrado.")
		except Exception as e:
			print( f"Ocorreu um erro: {e}")
		return brand

	def load_mtool_csv(self,f):
		with open(f, newline='') as csvfile:
			leitor_csv = csv.reader(csvfile, delimiter=';')
			data = {}
			timeLabel = 'in s'
			for linha in leitor_csv:
				index = linha[0].find('.')
				if linha[0][index+1:] == 'Variable':
					label = linha[1]
					data[label] = []
					data[timeLabel] = []
				if linha[0] == '':
					data[timeLabel].append(linha[1])
					data[label].append(linha[2])
			df = pd.DataFrame(data)
			df = df.sort_index(axis=1)
			df.insert(0, timeLabel, df.pop(timeLabel))
			df[timeLabel] = pd.to_numeric(df[timeLabel])
			df[timeLabel] = df[timeLabel] / 1000
		return df

	def load_tektronix_csv(self,f):
		df = pd.read_csv(f, header=None)
		labely = df[1][6]
		df = df.drop(df.columns[[0, 1, 2,5]], axis=1)
		df.columns = ['in s',labely]
		return df

	def load_usb_visa(self,file):
		instrumento = None
		data = None
		
		# Ler cabeçalho manualmente
		with open(file, 'r', encoding='latin-1') as f:
			linhas = f.readlines()
			
			for linha in linhas:
				if linha.startswith("# Instrumento:"):
					# exemplo: # Instrumento: TEKTRONIX,DPO2024,C013019,...
					partes = linha.split(":")[1].split(",")
					instrumento = partes[1].strip()
				
				if linha.startswith("# Data da captura:"):
					data_raw = linha.split(": ", 1)[1].strip()
					data = normalize_data(data_raw)
		
		# Ler dataframe ignorando comentários
		df = pd.read_csv(file, comment="#", encoding='latin-1')
		df.columns = ['in s',"ch1 in V"]
		return df, instrumento, data

	def read_file(self, f,data):
		if type(f) != type(" "): f = str(f)
		i = f.lower().find('.csv')
		if i > 0:
			f = f[:i]+'.csv'
		else:
			f = f+'.csv'
		
		brd = self.detect_brand_file(f)
		infoFile = os.stat(f).st_ctime
		info = normalize_data(infoFile)

		if brd == 'TDS3052B':
			df = pd.read_csv(f)
			df = df.rename(columns={'TDS3052B in s':'in s'})
		elif brd[:3] == 'TDS':
			df = self.load_tektronix_csv(f)
		elif brd == 'Master Tool':
			df = self.load_mtool_csv(f)
		elif brd == 'USB.VISA':
			df,brd,info = self.load_usb_visa(f)
		else: df = pd.read_csv(f)
		data['data'] = brd +' - '+ info
		return df

	def add_manual_table(self,x,y,dados):
		table = [x,y]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		return df

	def format_h_line(self, y,n='serie',color=False,config=None):
		"""
		Cria uma linha horizontal de referência no gráfico.
		
		Args:
			y (float): Valor Y onde a linha será desenhada.
			n (str, optional): Nome da série. Padrão é 'serie'.
			color (str or bool, optional): Cor da linha. Padrão é False.
			config (dict, optional): Dicionário de configurações (mesmo formato de format()).
				Padrão é [].
		
		Returns:
			dict or str: Dicionário com dados da linha formatada, ou 'nan' se y não for numérico.
		
		Note:
			A linha será estendida automaticamente para cobrir todo o eixo X do gráfico.
		"""
		dados = self.set_data(n,config,'Line H')
		if color: dados['color']=color
		#lx=config['label x'] if 'label x' in config else 'Tempo[ms]'
		#ly=config['label y'] if 'label y' in config else 'Tensão[V]'
		#pln=config['plane'] if 'plane' in config else 1

		if not isinstance(y, (int, float)):
			print('ERROR format_h_line: Entre com um número válido em y')
			return 'nan'

		table = [[None,None],[y,y]]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		
		# Manipula as escala
		self._handle_scales(dados,df)
		self._plot_area4(dados)
		self.reads.append(dados)
		return dados

	def format_v_line(self, x,n='serie',color=False,config=None):
		"""
		Cria uma linha vertical de referência no gráfico.
		
		Args:
			x (float): Valor X onde a linha será desenhada.
			n (str, optional): Nome da série. Padrão é 'serie'.
			color (str or bool, optional): Cor da linha. Padrão é False.
			config (dict, optional): Dicionário de configurações (mesmo formato de format()).
				Padrão é [].
		
		Returns:
			dict or str: Dicionário com dados da linha formatada, ou 'nan' se x não for numérico.
		
		Note:
			A linha será estendida automaticamente para cobrir todo o eixo Y do gráfico.
		"""
		dados = self.set_data(n,config,'Line V')
		if color: dados['color']=color

		if not isinstance(x, (int, float)):
			print('ERROR format_v_line: Entre com um número válido em x')
			return 'nan'

		table = [[x,x],[None,None]]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		
		# Manipula as escala
		self._handle_scales(dados,df)
		self._plot_area4(dados)
		self.reads.append(dados)
		return dados

	def get_order(self):
		"""
		Retorna lista com os nomes de todas as séries carregadas, na ordem atual.
		
		Returns:
			list: Lista de strings com os nomes das séries.
		"""
		list = []
		for n in self.reads:
			list.append(n['name'])
		return list

	def set_order(self,names='nan',index='nan'):
		"""
		Reordena as séries carregadas conforme a lista de nomes fornecida.
		
		Args:
			names (list, optional): Lista de nomes na ordem desejada. Padrão é 'nan'.
			index (str, optional): Não utilizado (mantido para compatibilidade).
				Padrão é 'nan'.
		
		Returns:
			bool: True se a reordenação foi bem-sucedida, False caso contrário.
		
		Note:
			Séries não encontradas na lista são ignoradas.
		"""
		temp = deepcopy(self.reads)
		if type(names) == type([]):
			self.reads = []
			for n in names:
				v,_= self._find_key(temp,n)
				if not v == None: self.reads.append(v)
			return True
		else: return False

	def set_data(self, n,config,modo):
		if config is None: config = {}
		lx=config['label x'] if 'label x' in config else self.labelx
		ly=config['label y'] if 'label y' in config else 'Voltage[V]'
		brd=config['brand'] if 'brand' in config else 'ROHDE'
		pln=config['plane'] if 'plane' in config else 1
		ot=config['offset time'] if 'offset time' in config else 0 
		dt=config['std duty'] if 'std duty' in config else self.dt
		g = config['gain'] if 'gain' in config else 1
		
		dados={
			'labelx':lx,
			'labely':ly,
			'name': n,
			'plane':pln,
			'engNoteX':format_eng(lx),
			'engNoteY':format_eng(ly),
			'engNoteXstr':format_eng(lx,'str'),
			'engNoteYstr':format_eng(ly,'str'),
			'symbolX':format_eng(lx,'symbol'),
			'symbolY':format_eng(ly,'symbol'),
			'type': modo,
			#'brand':brd,
			'offset time':ot,
			'std duty':dt,
			#'draw':[],
			'gain':g,
		}
		if 'note' in config: dados['note'] = config['note']
		if 'findY' in config: dados['findY'] = config['findY']
		if 'findT' in config: dados['findT'] = config['findT']
		if 'loc_legend' in config: dados['loc_legend'] = config['loc_legend']
		if 'loc_legend2' in config: dados['loc_legend2'] = config['loc_legend2']
		if 'color' in config: dados['color'] = config['color']
		if dados['labely'] not in self.yDf['label'].values:
			self.yDf.loc[len(self.yDf), ['label']] = dados['labely']
		#pprint(dados)
		return dados

	def _handle_scales(self, d,df,o=0,gain=None,c=1):
		lx = d['labelx']
		ly = d['labely']
		ot = d['offset time']
		g = gain if gain != None else d['gain']
		d['x'] = df[df.columns[0]].astype(float)*(1/format_eng(lx))+ot*(1/format_eng(lx))
		d['y'] = df[df.columns[c]].astype(float)*g*(1/format_eng(ly))+o*(1/format_eng(ly))

	def _handle_cuts(self,df,config):
		if config is None: config = {}
		coi=config['cutoff in'] if 'cutoff in' in config else 'nan'
		coo=config['cutoff out'] if 'cutoff out' in config else 'nan'
		# Verificar se a coluna 'in s' existe
		if 'in s' not in df.columns:
			df.rename(columns={df.columns[0]: 'in s'}, inplace=True)
		# selecting rows based on condition
		if not coi =='nan': df = df.loc[df['in s'] >= coi]
		if not coo =='nan': df = df.loc[df['in s'] <= coo]
		return df

	def load(self, f='TRC01',g=None,o=0,c=1,x=None,y=None,n='nan',color=False,config=None,low_pass=0):
		"""
		Carrega e formata uma série de dados de um arquivo CSV ou dados manuais.
		
		Args:
			f (str, optional): Nome do arquivo CSV (sem extensão) ou caminho completo.
				Padrão é 'TRC01'.
			g (float, optional): Ganho a aplicar ao sinal. Se None, usa o ganho do config.
				Padrão é None.
			o (float, optional): Offset a aplicar ao eixo Y. Padrão é 0.
			c (int, optional): Índice da coluna a usar (1-based). Padrão é 1 (primeira coluna Y).
			x (list, optional): Dados manuais do eixo X. Se fornecido, ignora o arquivo.
				Padrão é [].
			y (list, optional): Dados manuais do eixo Y. Deve ter mesmo tamanho que x.
				Padrão é [].
			n (str, optional): Nome da série. Se 'nan', usa o nome da coluna do arquivo.
				Padrão é 'nan'.
			color (str or bool, optional): Cor da linha no gráfico. Padrão é False.
			config (dict, optional): Dicionário de configurações:
				- 'label x': label do eixo X (ex: "Time[ms]").
				- 'label y': label do eixo Y (ex: "Voltage[V]").
				- 'plane': plano do gráfico (1 ou 2).
				- 'offset time': offset de tempo.
				- 'std duty': lista [min, max] para cálculo de transições.
				- 'gain': ganho do sinal.
				- 'cutoff in': tempo inicial para corte.
				- 'cutoff out': tempo final para corte.
				- 'note': lista de anotações automáticas.
				- 'findY': lista de valores Y para encontrar.
				- 'findT': lista de valores T para encontrar.
				- 'loc_legend': posição da legenda.
			filtro (int or list, optional): Se lista [fc, ordem], aplica filtro interno.
				Se 0, não aplica filtro. Padrão é 0.
		
		Returns:
			dict or str: Dicionário com dados da série formatada, ou 'nan' em caso de erro.
				O dicionário contém: 'name', 'x', 'y', 'labelx', 'labely', 'engNoteX', 'engNoteY',
				'symbolX', 'symbolY', 'samplingPeriod', 'samplingFrequency', 'data', etc.
		"""
		
		# Carrega as configurações
		dados = self.set_data(n,config,'signal')
		if color: dados['color']=color
		
		# carrega o dataframe
		if x is None: df = self.read_file(f,dados)
		else: df = self.add_manual_table(x,y,dados)
		
		# verifica o tamanho
		if(c+1 > len(df.columns)):
			print('ERROR format: Sua planilha de dados possui menos colunas do que o requisitado')
			print(df)
			return 'nan'
		# define o nome da série se vier em branco
		if n == 'nan':
			dados['name'] = df.columns[c]
		# Manipula os cortes
		df = self._handle_cuts(df,config)
		if type(df) == type('nan'): return 'nan'
		
		samplingPeriod  = df.iloc[1,0]-df.iloc[0,0]
		samplingFrequency = 1/samplingPeriod
		samplingPeriod = format_eng_str(samplingPeriod)+'s'
		samplingFrequency = format_eng_str(samplingFrequency)+'Hz'

		# Manipula as escala
		self._handle_scales(dados,df,o,g,c)
		self._plot_area4(dados)
		if type(low_pass) == type([]):
			self._apply_filter(dados,low_pass)
		self.get_annotations(dados)
		self.reads.append(dados)
		
		dados['samplingPeriod'] = samplingPeriod
		dados['samplingFrequency'] = samplingFrequency
		dados['data'] = 'Sampling Period: '+dados['samplingPeriod'] +' - '+ dados['data']

		return dados

	def get_annotations(self, dados):
		for busca in ['note','findY','findT']:
				if busca in dados:
					for n in dados[busca]:
						self.annotation(n,dados,busca)

	def _find_key(self,list,value,key='name'):
		for i,dictio in enumerate(list):
			if key in dictio:
				if dictio[key] == value:
					return dictio,i
		return None,None

	def _find_key_by_col(self,col,value,n):
		index = -1
		for row in col:
			index += 1
			for i in row:
				if i[4]==value:
					if i[1][:len(n)] == n:
						return i[0][0],index
		return None,None

	def draw_delay(self, s1,n1,s2,n2,u='s',name=''):
		"""
		Desenha anotação de delay entre dois pontos de diferentes séries.
		
		Args:
			s1 (str): Nome da primeira série.
			n1 (str): Nome do ponto na primeira série (ex: 'p1').
			s2 (str): Nome da segunda série.
			n2 (str): Nome do ponto na segunda série (ex: 'p2').
			u (str, optional): Unidade do delay: 's' (segundos), 'Hz' (frequência),
				'bps' (bits por segundo). Padrão é 's'.
			name (str, optional): Nome personalizado para a anotação. Se '', usa nome padrão
				baseado na unidade. Padrão é ''.
		
		Returns:
			None: Adiciona anotações de delay ao gráfico. Imprime erro se pontos não existirem.
		
		Note:
			- Os pontos devem ter sido criados previamente com anotações 'findY' ou 'findT'.
			- Desenha linha horizontal conectando os dois pontos e texto com o valor do delay.
		"""
		cord1,indexLabel = self._find_key_by_col(self.yDf['draw'],s1,n1)
		cord2,indexLabel = self._find_key_by_col(self.yDf['draw'],s2,n2)
		s_,_ = self._find_key(self.reads,s1)

		if cord1 == None:
			print(n1+' não existe em '+s1)
			return
		if cord2 == None:
			print(n2+' não existe em '+s1)
			return
		if cord1[1] > cord2[1]:
			y = cord1[1]
			x = cord2[0]
		else:
			y = cord2[1]
			x = cord1[0]
		cord=[[cord1[0],y],[cord2[0],y]]
		meioX = (cord2[0]-cord1[0])/2+cord1[0]
		meio = [[meioX,y],[None,None]]
		text=''
		style = '|-|'
		dir = 'delay'
		self.yDf['draw'][indexLabel].append([cord,text,style,dir,n1,':'])
		
		cordBar=[[x,cord1[1]],[x,cord2[1]]]
		style = '-'
		self.yDf['draw'][indexLabel].append([cordBar,text,style,dir,n1,':'])
		
		dt = abs(cord1[0]-cord2[0])
		if name == '':
			if u == 's': name='Delay'
			if u == 'Hz': name='Freq'
			if u == 'bps': name='bit rate'
		
		if u == 's': text = name + ' = '+format_value(dt,s_,'x')
		if u == 'Hz': text = name + ' = '+format_value(1/dt,s_,'f')
		if u == 'bps': text = name + ' = '+format_value(1/dt,s_,'bps')
		style = '-'
		dir = 'NE'
		xo=cord1[0] if cord1[0] < cord2[0] else cord2[0]
		cordT = [[xo+dt/2,y],[None,None]]
		self.yDf['draw'][indexLabel].append([meio,text,style,dir,n1])

	def _find_note(self,list, value,key='name'):
		for i in range(len(list)):
			if key in list[i]:
				for point in range(len(list[i][key])):
					if list[i][key][point][1][:len(value)] == value:
						return i,point
		return None,None

	def interpolate_df(self,df,sampleTarget=1000):
		# Verificar o número de amostras no DataFrame atual
		lenSample = len(df)
		temp=df.tolist()
		# Se o número atual de amostras for menor que o desejado, realizar a interpolação
		if lenSample < sampleTarget and lenSample > 0:
			newDF = []
			n=int(round(sampleTarget/lenSample,0))+1
			last=''
			for v in temp:
				if last == '': last = v
				else:
					for i in range(n):
						newDF.append(last+(v-last)*i/n)
					last = v
			newDF.append(last)
			df = pd.DataFrame(newDF)
			df = df[df.columns[0]]
		return df

	def set_annotation_dir(self,n,dir,newname=''):
		# Função para procurar e substituir com base no primeiro item da lista
		def setL(lista, string_verificacao, substituto):
			for i in range(len(lista)):
				if lista[i][1].startswith(string_verificacao):
					lista[i][3] = substituto
			return lista
		# Aplicar a função a cada linha do DataFrame
		self.yDf['draw'] = self.yDf.apply(lambda row: setL(row['draw'], n, dir), axis=1)
	
	def _handle_note_name(self, d):
		if type(d) == type({}):
			especificName = list(d.keys())[0]
			d = d[especificName]
		else:
			self.indexNote += 1
			especificName = 'p'+str(self.indexNote)
		return d, especificName

	def annotation(self, d,s,n):
		indexLabel = self.yDf.index[self.yDf['label'] == s['labely']].tolist()[0]
		name = s['name']
		if not 'info' in s: s['info']={}
		x = self.interpolate_df(s['x'])
		y = self.interpolate_df(s['y'])
		if len(x) == 0: return print('ERROR ANOTATION: '+name+" has no signal")
		d, id = self._handle_note_name(d)
		if n == 'note':
			if d == 'Vmáx':
				i = y.idxmax()
				y = y[i]
				x = x[i]
				cord=[[x,y],[None,None]]
				text=d+ ': '+format_value(y,s,'y')
				style = '->'
				dir = 'S'
				s['info'][d]=[y,text]
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				return
				
			elif d == 'Vmin':
				i = y.idxmin()
				y = y[i]
				x = x[i]
				cord=[[x,y],[None,None]]
				text=d+ ': '+format_value(y,s,'y')
				style = '->'
				dir = 'N'
				s['info'][d]=[y,text]
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				return
				
			elif d == 'RMS':
				rms = np.sqrt((y**2).mean())
				meio = int(len(y)/2)
				cord=[[x[meio],y[meio]],[None,None]]
				text=d+ ': '+format_value(rms,s,'y',decimals=4)
				style = '->'
				dir = 'NE'
				s['info'][d]=[rms,text]
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				return
				
			elif d == 'ΔV':
				i1 = y.idxmin()
				y1 = y[i1]
				x1 = x[i1]
				i2 = y.idxmax()
				y2 = y[i2]
				x2 = x[i2]
				cord=[[x2,abs(y2-y1)/2+y1],[None,None]]
				text=d+ ': '+format_value(y2-y1,s,'y')
				style = '-'
				dir = 'NE'
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				cord=[[x2,y1],[x2,y2]]
				text=''
				style = '|-|'
				dir = ''
				line = ':'
				s['info'][d]=[y,text]
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name,':'])
				return
				
			elif d == 'transition' or d == 'transition in f' or d == 'slew rate':
				i1 = y.idxmax()
				i2 = y.idxmin()
				ymax = y[i1]
				ymin = y[i2]
				dV = ymax - ymin
				if self.Limits["logicLimits"]:
					dy1= self.Limits["logicLimits"]["high_min"]
					dy2= self.Limits["logicLimits"]["low_max"]
				else:
					dy1 = dV*max(s['std duty'])+ymin
					dy2 = dV*min(s['std duty'])+ymin
				i = (y - dy1).abs().idxmin()
				x1 = x[i]
				y1 = y[i]
				i = (y - dy2).abs().idxmin()
				x2 = x[i]
				y2 = y[i]
				dt = abs(x2-x1)
				cord=[[x1,y1],[x2,y2]]
				text=''
				style = '|-|'
				dir = ''
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name,':'])
				if(i1>i2):
					d_ = 'Trise'
					cord=[[x1,y1],[None,None]]
					dir = 'SE'
					s['info'][d_]=[dt,text]
				else:
					d_ = 'Tfall'
					cord=[[x2,y2],[None,None]]
					dir = 'NE'
					s['info'][d_]=[dt,text]
				text=d_+ ': '+format_value(dt,s,'x')
				if d == 'transition in f':
					text=d+ ': '+format_value(1/dt,s,'f')
					s['info'][d]=[1/dt,text]
				elif d == 'slew rate':
					text=d+ ': '+format_value(dV/dt,s,'v/t')
					s['info'][d]=[dV/dt,text]
				style = '->'
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				return
		elif n == 'findY':
			d /= s['engNoteY']
			i = (y - d).abs().idxmin()
			amp = y.max()-y.min()
			y = y[i]
			x = x[i]
			
			diff = d-y if d>y else y-d
			error = round((diff/amp)*100,2)
			if error > 5:
				print('not find t '+str(d)+' in '+name+' just '+str(y)+' p['+str(i)+'] error = '+str(error)+' %')
				return

			cord=[[x,y],[None,None]]
			text=id+' ('+format_value(x,s,'x')+' , '+format_value(y,s,'y')+')'
			style = '->'
			dir = 'NE'
			s['info']['findY']=[id,y,text]
			s['info'][id]=[y,text]
			self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
			return
		elif n == 'findT':
			d /= s['engNoteX']
			amp = abs(x.iloc[1]-x.iloc[0])
			i = (x - d).abs().idxmin()
			x = x[i]
			y = y[i]
			#verifica se a diferença está dentro de um intervalo entre duas amostras
			diff = d-x if d>x else x-d
			if diff > amp:
				print('not find t '+str(d)+' in '+name+' just '+str(x)+' p['+str(i)+'] diff = '+format_value(diff,s,'x'))
				return
			cord=[[x,y],[None,None]]
			text=id+' ('+format_value(x,s,'x')+' , '+format_value(y,s,'y')+')'
			style = '->'
			dir = 'NE'
			s['info'][id]=[y,text]
			self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
			return
		return

	def _plot_area(self, serie,axe,area=None):


		if area == None:
			area =  {
				'xMin':serie['x'].min(),
				'yMin':serie['y'].min(),
				'xMax':serie['x'].max(),
				'yMax':serie['y'].max(),
			}
		else:
			if area['yMin'] >= serie['y'].min(): area['yMin'] = serie['y'].min()
			if area['xMin'] >= serie['x'].min(): area['xMin'] = serie['x'].min()
			if area['yMax'] <= serie['y'].max(): area['yMax'] = serie['y'].max()
			if area['xMax'] <= serie['x'].max(): area['xMax'] = serie['x'].max()

		if axe =='linear': area['xCenter']=(area['xMax']-area['xMin'])/2+area['xMin']
		else: area['xCenter']=np.sqrt(area['xMax'])*np.sqrt(area['xMin'])

		if self.fftZonetxt == 'center':
			area['xTxt'] = area['xCenter']
			area['ha'] ='center'
		elif self.fftZonetxt == 'right':
			area['xTxt'] = area['xMax']
			area['ha']='right'
		else:
			area['xTxt'] = area['xMin']
			area['ha']='left'

		return area

	def _plot_area4(self, serie):
		# Obter o índice da linha que contém o valor "serie n" na coluna "Nome"
		i = self.yDf.index[self.yDf['label'] == serie['labely']].tolist()[0]
		
		if pd.isnull(self.yDf.loc[i,'xMax']):
			self.yDf.loc[i,'xMin'] =  serie['x'].min()
			self.yDf.loc[i,'xMax'] =  serie['x'].max()
			self.yDf.loc[i,'yMin'] =  serie['y'].min()
			self.yDf.loc[i,'yMax'] =  serie['y'].max()
			self.yDf.loc[i,'draw'] = []
		else:
			if self.yDf.loc[i,'xMin'] >= serie['x'].min(): self.yDf.loc[i,'xMin'] = serie['x'].min()
			if self.yDf.loc[i,'xMax'] <= serie['x'].max(): self.yDf.loc[i,'xMax'] = serie['x'].max()
			if self.yDf.loc[i,'yMin'] >= serie['y'].min(): self.yDf.loc[i,'yMin'] = serie['y'].min()
			if self.yDf.loc[i,'yMax'] <= serie['y'].max(): self.yDf.loc[i,'yMax'] = serie['y'].max()
		
		self.yDf.loc[i,'xAr' ] =  self.yDf.loc[i,'xMax']-self.yDf.loc[i,'xMin']
		self.yDf.loc[i,'yAr' ] =  self.yDf.loc[i,'yMax']-self.yDf.loc[i,'yMin']
		return 

	def _plot_notes(self,f,ax,i):#,notes):
		factor= 0.05
		figsize = f.get_size_inches()
		rate= figsize[1]/figsize[0]
		deltax = self.yDf['xAr'][i]*factor*rate
		deltay = self.yDf['yAr'][i]*factor
		#for note in notes:
		#print('_plot_notes()')
		#pprint(self.yDf['draw'])
		for note in self.yDf['draw'][i]:
			#print('for note in self.yDf')
			#pprint(note)
			a=self._draw_arrow(note,[deltax,deltay])
			ax.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],ha=a['ha'],va=a['va'],arrowprops=a['props'])

	def _draw_arrow(self, n,d=0):
		#print('arrow()')
		#pprint(n)
		xp = n[0][0][0]
		yp = n[0][0][1]
		#print(xp,yp)
		o = n[3]
		linestyle = '-'
		va = 'center'
		ha = 'center'
		if len(n)>5: linestyle=n[5]
		if   o == 'NE':	xo = xp+d[0];	yo = yp+d[1];		ha = 'left';	va = 'bottom'
		elif o == 'N':	xo = xp;			yo = yp+d[1]*2;	ha = 'center';va = 'bottom'
		elif o == 'NW':	xo = xp-d[0];	yo = yp+d[1];		ha = 'right';	va = 'bottom'
		elif o == 'W':	xo = xp-d[0];	yo = yp;				ha = 'right';	va = 'center'
		elif o == 'SW':	xo = xp-d[0];	yo = yp-d[1];		ha = 'right';	va = 'top'
		elif o == 'S':	xo = xp;			yo = yp-d[1]*2;	ha = 'center';va = 'top'
		elif o == 'SE':	xo = xp+d[0];	yo = yp-d[1];		ha = 'left';	va = 'top'
		elif o == 'E':	xo = xp+d[0];	yo = yp;				ha = 'left';	va = 'center'
		
		if n[0][1][0] == None: 
			n[0][1][0] = xo
			n[0][1][1] = yo
		
		result={
			'txt':n[1],
			'xy' :(n[0][0][0],n[0][0][1]),
			'xytext':(n[0][1][0],n[0][1][1]),
			'va':va,
			'ha':ha,
			'props': dict(arrowstyle=n[2], linestyle=linestyle)
		}
		#pprint(result)
		return result

	def _rolling_rms(self, x, N):
		return (pd.DataFrame(abs(x)**2).rolling(N).mean()) **0.5

	def _complete_lines(self):
		# trata o sinal
		for serie in self.reads:
			indexLabel = self.yDf.index[self.yDf['label'] == serie['labely']].tolist()[0]
			if 'type' in serie:
				if serie['type'] == 'Line H':
					serie['x'] = [self.yDf['xMin'][indexLabel],self.yDf['xMax'][indexLabel]]
				if serie['type'] == 'Line V':
					serie['y'] = [self.yDf['yMin'][indexLabel],self.yDf['yMax'][indexLabel]]

	def _plot_series(self,ax,serie):
		if 'color' in serie:
			ax.plot(serie['x'], serie['y'], linewidth=2.0,label=self._format_label(serie['name']),color=serie['color'])
		else:
			ax.plot(serie['x'], serie['y'], linewidth=2.0,label=self._format_label(serie['name']))
		ax.set_ylabel(serie['labely'])
		ax.legend()

	def save_figure(self,obj,out='png',path='',t='nan',transparent=False):
		filenames = []
		if type([]) == type(out):
			for o in out:
				filenames.append(path+t+'.'+o)
		elif out == '':
			filenames.append(t+'.png')
			filenames.append(t+'.pdf')
		else: filenames.append(path+t+'.'+out)
		
		for filename in filenames:
			obj.savefig(dh.sanitize_filename(filename), bbox_inches='tight', pad_inches=0, transparent=transparent)

	def _format_label(self,texto):
		if texto.startswith("\\"):
			partes = []
			for caractere in texto[1:]:  # Pula a barra invertida inicial
				if re.match(r'[a-zA-Z]', caractere):  # Verifica se é letra
					partes.append(r'\overline{' + caractere + '}')
				else:
					partes.append(caractere)  # Mantém símbolos sem traço
			return r'$' + ''.join(partes) + '$'
		else:
			return texto  # Retorna sem modificação

	def _apply_mask(self,ax):
		# =============================
		# Optional logic mask
		# =============================
		if 'logicLimits' in self.Limits:
			if self.Limits['logicLimits']:
				ax.axhspan(self.Limits['logicLimits']["low_min"], self.Limits['logicLimits']["low_max"], alpha=0.15)
				ax.axhspan(self.Limits['logicLimits']["high_min"], self.Limits['logicLimits']["high_max"], alpha=0.15)

				ax.axhline(self.Limits['logicLimits']["low_max"], linestyle='--', linewidth=0.8)
				ax.axhline(self.Limits['logicLimits']["high_min"], linestyle='--', linewidth=0.8)

		# Max limits (independent)
		if 'maxLimits' in self.Limits:
			if self.Limits['maxLimits']:
				ax.axhline(self.Limits['maxLimits']["low"], linestyle='--', linewidth=0.8, color="red")
				ax.axhline(self.Limits['maxLimits']["high"], linestyle='--', linewidth=0.8, color="red")
		return ax

	def plot(self,t='nan',grid = True,size=(12, 6),out='png',path='',transparent=False):
		"""
		Plota todas as séries de dados carregadas em um gráfico.
		
		Args:
			t (str, optional): Título do gráfico. Se 'nan', usa self.title. Padrão é 'nan'.
			grid (bool, optional): Se True, exibe grade no gráfico. Padrão é True.
			size (tuple, optional): Tamanho da figura em polegadas (largura, altura).
				Padrão é (12, 6).
			out (str or list, optional): Formato(s) de saída: 'png', 'pdf', 'svg', etc.
				Se lista, salva em múltiplos formatos. Se '', salva PNG e PDF.
				Padrão é 'png'.
			path (str, optional): Caminho para salvar o arquivo. Se '', usa self.path.
				Padrão é ''.
			transparent (bool, optional): Se True, fundo transparente. Padrão é False.
		
		Returns:
			None: Exibe o gráfico e salva os arquivos. Retorna None se não houver séries.
		
		Note:
			- Séries com mesmo 'labely' são plotadas no mesmo eixo Y.
			- Séries com 'labely' diferentes usam eixos Y duplos.
			- Anotações são plotadas automaticamente.
		"""
		if t == 'nan': t = self.title
		if path=='': path = self.path
		loc_legend = None
		loc_legend2 = None
		
		# verifica a consistência das séries
		if self.reads == []: return print('ERROR PLOT: Planilha incompleta')
		
		# Completa as linhas horizontais e verticais com os limites do gráfico
		self._complete_lines()
		
		# Inicia a plotagem
		fig, ax = plt.subplots(figsize=size)#,axes_class=axisartist.Axes)
		ax.set_title(t)
		self._plot_notes(fig,ax,0)
		
		if len(self.yDf)>1:
			ax2 = ax.twinx() # Create another axes that shares the same x-axis as ax.
			self._plot_notes(fig,ax2,1)
		
		ax = self._apply_mask(ax)
		
		# Percorre plota as séries
		for serie in self.reads:
			indexLabel = self.yDf.index[self.yDf['label'] == serie['labely']].tolist()[0]
			#if serie['labely'] == self.ySeries[0]:
			if indexLabel == 0:
				self._plot_series(ax,serie)
			else:
				self._plot_series(ax2,serie)
			ax.set_xlabel(serie['labelx'])
			ax.grid(grid)
			
			if serie['data'] != 'None': data = serie['data']
			else: data = 'None'
			if 'loc_legend' in serie: loc_legend = serie['loc_legend']
			if 'loc_legend2' in serie: loc_legend2 = serie['loc_legend2']

		loc = loc_legend if loc_legend is not None else 'upper right'
		legenda = ax.legend(loc=loc)

		# Legenda interativa: clique para mostrar/ocultar a linha
		mapa = {}
		def _map_legend(legend, ax_lines):
			label_to_line = {l.get_label(): l for l in ax_lines if not l.get_label().startswith('_')}
			for leg_line in legend.get_lines():
				leg_line.set_picker(5)
				orig = label_to_line.get(leg_line.get_label())
				if orig:
					mapa[leg_line] = orig

		_map_legend(legenda, ax.get_lines())

		def on_pick(event):
			orig = mapa.get(event.artist)
			if orig:
				visible = not orig.get_visible()
				orig.set_visible(visible)
				event.artist.set_alpha(1.0 if visible else 0.2)
				fig.canvas.draw()

		fig.canvas.mpl_connect('pick_event', on_pick)

		if loc_legend2 is not None:
			legenda2 = ax2.legend(loc=loc_legend2)
			_map_legend(legenda2, ax2.get_lines())
		if data != 'None':
			ax.annotate(data,xy=(0.5,1e-2),xycoords='axes fraction', ha='center', fontsize=8)

		# SpanSelector: arrasta para ver ΔT; duplo-clique para limpar
		def _fmt_dt(dt):
			"""Formata ΔT com a unidade mais legível."""
			abs_dt = abs(dt)
			if abs_dt >= 1:       return f'ΔT = {dt:.4g} s'
			if abs_dt >= 1e-3:    return f'ΔT = {dt*1e3:.4g} ms'
			if abs_dt >= 1e-6:    return f'ΔT = {dt*1e6:.4g} µs'
			if abs_dt >= 1e-9:    return f'ΔT = {dt*1e9:.4g} ns'
			return                       f'ΔT = {dt*1e12:.4g} ps'

		fig._span_text = None  # referência ao texto exibido

		def on_span(xmin, xmax):
			dt = xmax - xmin
			if abs(dt) < 1e-15:
				return
			# Remove texto anterior
			if fig._span_text is not None:
				try: fig._span_text.remove()
				except: pass
			# Exibe ΔT centrado na seleção, no topo do eixo
			ymid = ax.get_ylim()[1]
			fig._span_text = ax.text(
				(xmin + xmax) / 2, ymid, _fmt_dt(dt),
				ha='center', va='top',
				fontsize=10, fontweight='bold',
				bbox=dict(boxstyle='round,pad=0.3', facecolor='steelblue',
						  alpha=0.8, edgecolor='none'),
				color='white', zorder=10,
			)
			fig.canvas.draw()

		def on_dblclick(event):
			if event.dblclick and event.inaxes is ax:
				if fig._span_text is not None:
					try: fig._span_text.remove()
					except: pass
					fig._span_text = None
				fig.canvas.draw()

		from matplotlib.widgets import SpanSelector
		fig._span = SpanSelector(
			ax, on_span, 'horizontal',
			useblit=False,
			props=dict(alpha=0.15, facecolor='steelblue'),
		)
		fig.canvas.mpl_connect('button_press_event', on_dblclick)

		plt.ion()  # Ativa o modo interativo
		# Salva Figura
		self.save_figure(plt,out,path,t,transparent)
		# Exibindo a figura
		plt.show(block=False)
		return

	def format_fft(self,id=0,name='',f = False):
		"""
		Calcula e armazena a Transformada de Fourier (FFT) de uma série de dados.
		
		Args:
			id (int, optional): Índice da série em self.reads. Padrão é 0.
			name (str, optional): Nome da série. Se fornecido, busca por nome ao invés de id.
				Padrão é ''.
			f (str or bool, optional): Título personalizado para o gráfico FFT.
				Se False, usa título padrão. Padrão é False.
		
		Returns:
			None: Modifica a série in-place, adicionando:
				- 'fft': dicionário com 'f' (frequências) e 'A' (amplitudes).
				- 'fft-tittle': título do gráfico FFT (se f fornecido).
		
		Note:
			- Remove o componente DC (frequência zero).
			- Calcula apenas frequências positivas.
		"""
		if name != '':
			_,id = self._find_key(self.reads,name)
		d = self.reads[id]
		
		x = d['x']*d['engNoteX']
		y = d['y']*d['engNoteY']
		
		fft = np.fft.fft(y)
		fft[0] = 0
		fftfreq = np.fft.fftfreq(len(y))*len(y)/(x.max()-x.min())
		self.ifft_data(fft,id,'ac_ripple',f=[fftfreq[1],fftfreq[-1]])

		# ---- Zona de interesse ----
		if self.fftZone is not None and len(self.fftZone) > 0:
			self.fftZone = self.fftZone if isinstance(self.fftZone[0], list) else [self.fftZone]
			for zone in self.fftZone:
				if zone[0] == 'start': zone[0] = fftfreq[1]
				if zone[1] == 'end': zone[1] = np.max(fftfreq)
				self.fft_filter(fft,fftfreq,id,f=zone)

		a = []
		b = []
		for i in range(len(fftfreq)):
			if fftfreq[i] > 0:
				a.append(fftfreq[i])
				b.append(fft[i])
		self.reads[id]['fft']={'f':a,'A':np.abs(b)}
		if f: self.reads[id]['fft-tittle'] = f

	def ifft_data(self,fft,id,name,f=[None,None]):
		# reconstrução no tempo
		y = np.fft.ifft(fft).real
		vpp = np.max(y) - np.min(y)
		vrms = np.sqrt(np.mean(y**2))
		if not name in self.reads[id]:
			self.reads[id][name] = []
		self.reads[id][name].append({
			'vpp': vpp,
			'vrms': vrms,
			'f_min': f[0],
			'f_max': f[1],
		})
	# ---- FILTRO PASSA-FAIXA (f_minHz a f_maxHz) ----
	def fft_filter(self,fft,fftfreq,id,f=[None,None]):
		fft_filtered = fft.copy()
		for i in range(len(fftfreq)):
			if not (f[0] <= abs(fftfreq[i]) <= f[1]):
				fft_filtered[i] = 0
		self.ifft_data(fft_filtered,id,'ac_ripple_filter',f=f)

	def plot_fft(self, t='Minhas Leituras',grid = True,size=(12, 6),axe='linear',out='png',mark=1,path='',transparent=False):
		"""
		Plota o espectro de frequência (FFT) das séries que possuem dados FFT calculados.
		
		Args:
			t (str, optional): Título do gráfico. Se 'Minhas Leituras', usa self.title.
				Padrão é 'Minhas Leituras'.
			grid (bool, optional): Se True, exibe grade. Padrão é True.
			size (tuple, optional): Tamanho da figura (largura, altura) em polegadas.
				Padrão é (12, 6).
			axe (str, optional): Tipo de escala do eixo X: 'linear' ou 'log'. Padrão é 'linear'.
			out (str, optional): Formato de saída: 'png', 'pdf', etc. Padrão é 'png'.
			mark (int, optional): Número de picos de frequência a marcar automaticamente.
				Padrão é 1.
			path (str, optional): Caminho para salvar. Se '', usa self.path. Padrão é ''.
			transparent (bool, optional): Se True, fundo transparente. Padrão é False.
		
		Returns:
			None: Plota e salva o gráfico FFT para cada série com dados FFT.
		
		Note:
			- Apenas séries com chave 'fft' são plotadas.
			- Os picos são marcados automaticamente como p1, p2, etc.
		"""
		for serie in self.reads:
			if t=='Minhas Leituras':
				t = self.title
			if path=='':
				path = self.path
				
			if 'fft-tittle' in serie:
				t = serie['fft-tittle']
			
			if 'fft' in serie:
				plt.subplots(figsize=size)
				plt.title(t)

				num_points = len(serie['fft']['A'])  # número total de pontos na série FFT
				yInterval = [min(serie['fft']['A'])/num_points,max(serie['fft']['A'])/num_points]
				yMeta = auto_scale(yInterval)
				
				if self.fftylabel == "auto":
					self.fftylabel = f"Amplitude [{yMeta['unit']}V]"
					yfator = yMeta['factor']
				else: 
					yfator = 1e-6
					self.fftylabel = "Amplitude [µV]"

				plt.xlabel("Domínio da Frequência [Hz]")
				plt.ylabel(self.fftylabel)

				a=serie['fft']['f']
				factor = 1
				if axe =='log': plt.semilogx()
				else:
					symbol = format_eng_str(max(a))[-1]
					factor = EngNotation[symbol]
					a = [float(i) / factor for i in serie['fft']['f']]
					plt.xlabel("Domínio da Frequência ["+symbol+"Hz]")
				
				# Normalizando a amplitude
				x = np.array(a)
				y = np.array([(amp/yfator) / num_points for amp in serie['fft']['A']])

				largestValuesIndex = np.argsort(y)[-mark:][::-1]
				j=0
				serie['draw']=[]
				for i in largestValuesIndex:
					j+=1

					x_ = x[i]
					y_ = y[i]
					
					cord=[[x_,y_],[None,None]]
					text='p'+str(j)+': '+format_eng_str(x_*factor,0)+'Hz'
					style = '-'
					dir = 'N'
					serie['draw'].append([cord,text,style,dir])
				
				plt.plot(x,y)

				plt.grid(grid,which="both")
				
				temp={'x':x,'y':y}
				area = self._plot_area(temp,axe)
				if serie['data'] != 'None':
					textY = -area['yMax'] / 40
					plt.text(area['xCenter'],textY, serie['data'], ha='center', fontsize=8)
				
				if 'ac_ripple' in serie:
					vpp = format_eng_str(serie['ac_ripple'][0]['vpp'],2)
					text = f"AC Ripple: {vpp}Vpp"
					plt.text(area['xTxt'], area['yMax']*0.9, text,ha=area['ha'], fontsize=10, color='black')

				if self.fftZone != None:
					line = 0.9
					for iZone, vZone in enumerate(serie['ac_ripple_filter']):
						ZoneColor = list(mcolors.BASE_COLORS.keys())[iZone]
						line -= 0.05
						vpp = format_eng_str(vZone['vpp'],2)
						strZonef1 = format_eng_str(vZone['f_min'],0)+"Hz"
						strZonef2 = format_eng_str(vZone['f_max'],0)+"Hz"
						text = f"AC Ripple: {vpp}Vpp in {strZonef1} to {strZonef2}"
						plt.text(area['xTxt'], area['yMax']*line, text,ha=area['ha'], fontsize=10, color=ZoneColor)
						f_min_plot = vZone['f_min'] / factor
						f_max_plot = vZone['f_max'] / factor
						plt.axvspan(f_min_plot, f_max_plot, alpha=0.15, color=ZoneColor)
						plt.axvline(f_min_plot, color=ZoneColor, linestyle='--', linewidth=1)
						plt.axvline(f_max_plot, color=ZoneColor, linestyle='--', linewidth=1)

				for note in serie['draw']:
					a=self._draw_arrow(note,[0,0])
					#plt.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],arrowprops=dict(arrowstyle=a['arrowstyle'], linestyle=a['linestyle']))
					plt.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],ha=a['ha'],va=a['va'],arrowprops=a['props'])
				# Salva a figura
				self.save_figure(plt,out,path,t,transparent)
				# Exibindo a figura
				plt.show(block=False)
		return

	def get_eth_config(self, mode: str):
		"""
		Retorna os parâmetros padrão para o tipo de comunicação Ethernet especificado.

		Args:
				mode (str): Nome do padrão (ex: "100BASE-TX", "1000BASE-T", "10GBASE-T")

		Returns:
				dict: Contém:
						- bitrate (int): bits por segundo
						- num_levels (int): número de níveis PAM
						- symbols_per_eye (int): largura do olho em símbolos
		"""
		mode = mode.upper()

		presets = {
				"10BASE-T":	 {"bitrate": 10_000_000,	"num_levels": 2, "symbols_per_eye": 3},
				"100BASE-TX":   {"bitrate": 100_000_000,   "num_levels": 3, "symbols_per_eye": 3},
				"1000BASE-T":   {"bitrate": 1_000_000_000, "num_levels": 5, "symbols_per_eye": 3},
				"2.5GBASE-T":   {"bitrate": 2_500_000_000, "num_levels": 5, "symbols_per_eye": 2},
				"5GBASE-T":	 {"bitrate": 5_000_000_000, "num_levels": 5, "symbols_per_eye": 2},
				"10GBASE-T":	{"bitrate": 10_000_000_000,"num_levels": 16,"symbols_per_eye": 2}
		}

		if mode not in presets:
				raise ValueError(f"Unsupported Ethernet mode: {mode}")

		return presets[mode]

	def plot_pam(self, t='My Measurements', s=0, grid=True, size=(12, 8), out='png', path='', transparent=False, mode="1000BASE-T"):
		"""
		Plota diagrama de olho PAM (Pulse Amplitude Modulation) para sinais Ethernet.
		
		Args:
			t (str, optional): Título do gráfico. Se 'My Measurements', usa self.title.
				Padrão é 'My Measurements'.
			s (int, optional): Índice da série a usar. Padrão é 0.
			grid (bool, optional): Se True, exibe grade. Padrão é True.
			size (tuple, optional): Tamanho da figura (largura, altura) em polegadas.
				Padrão é (12, 8).
			out (str, optional): Formato de saída: 'png', 'pdf', etc. Padrão é 'png'.
			path (str, optional): Caminho para salvar. Se '', usa self.path. Padrão é ''.
			transparent (bool, optional): Se True, fundo transparente. Padrão é False.
			mode (str, optional): Padrão Ethernet: "10BASE-T", "100BASE-TX", "1000BASE-T",
				"2.5GBASE-T", "5GBASE-T", "10GBASE-T". Padrão é "1000BASE-T".
		
		Returns:
			None: Gera gráfico com 3 subplots:
				- Histograma de distribuição de níveis PAM.
				- Diagrama de olho (eye diagram).
				- Sinal no domínio do tempo.
		
		Note:
			- Usa KMeans para detectar níveis PAM automaticamente.
			- Calcula jitter e diferenças entre níveis.
			- Taxa de amostragem assumida: 2 GS/s.
		"""
		serie = self.reads[0]
		mode = self.get_eth_config(mode)

		# Load signal
		time = serie['x'].to_numpy()
		signal = serie['y'].to_numpy()

		if t == 'My Measurements':
				t = self.title
		if path == '':
				path = self.path

		# --- Detect PAM levels using KMeans ---
		kmeans = KMeans(n_clusters=mode['num_levels'], n_init='auto')
		signal_reshape = signal.reshape(-1, 1)
		kmeans.fit(signal_reshape)
		levels = np.sort(kmeans.cluster_centers_.flatten())

		diffs = np.diff(levels)

		# Derivative to find transitions
		derivative = np.abs(np.diff(signal))
		peaks, _ = find_peaks(derivative, height=np.std(derivative) * 2)
		intervals = np.diff(peaks)
		intervals = intervals[intervals > 1]  # remove false transitions

		# --- Eye diagram parameters ---
		fs = 2_000_000_000  # Sampling rate (Sa/s)
		symbol_rate = mode['bitrate']
		samples_per_symbol = int(fs / symbol_rate)

		if samples_per_symbol < 1:
				raise ValueError(f"Sampling rate ({fs}) too low for bitrate ({symbol_rate})")

		window_samples = samples_per_symbol * mode['symbols_per_eye']
		signal_normalized = signal - np.mean(signal)

		n_eyes = len(signal_normalized) // window_samples
		if n_eyes == 0:
				print("⚠️ Warning: not enough samples to generate eye diagram.")
				eyes = []
		else:
				eyes = np.array([
						signal_normalized[i * window_samples : (i + 1) * window_samples]
						for i in range(n_eyes)
						if (i + 1) * window_samples <= len(signal_normalized)
				])

		# --- Jitter analysis ---
		jitter_val = np.std(intervals) if len(intervals) > 0 else 0.0
		tolerancia_jitter = samples_per_symbol * 0.2
		jitter_str = f"{jitter_val:.2f} samp"
		#if jitter_val > tolerancia_jitter:
		#		jitter_str += " ⚠️"

		# --- Annotation text ---
		info_text = (
				f"PAM levels: {np.round(levels, 2)}\n"
				f"Δ avg: {np.mean(diffs):.3f}, σ: {np.std(diffs):.3f}\n"
				f"Vpp: {np.ptp(signal):.2f}\n"
				f"Jitter: {jitter_str}"
		)

		# --- Layout ---
		fig = plt.figure(figsize=size)
		gs = GridSpec(2, 3, height_ratios=[2, 1], figure=fig)
		ax_hist = fig.add_subplot(gs[0, 0])
		ax_eye = fig.add_subplot(gs[0, 1:])
		ax_signal = fig.add_subplot(gs[1, :])

		# Histogram
		ax_hist.hist(signal, bins=100, density=True, color='gray')
		ax_hist.set_title(f"Signal Level Distribution (PAM-{mode['num_levels']})")
		ax_hist.set_xlabel(serie['labely'])
		ax_hist.set_ylabel("Density")
		ax_hist.grid(grid, which="both")
		ax_hist.text(
				0.02, 0.98, info_text,
				transform=ax_hist.transAxes,
				fontsize=8,
				verticalalignment='top',
				horizontalalignment='left',
				bbox=dict(facecolor='white', edgecolor='gray', boxstyle='round,pad=0.4', alpha=0.8)
		)

		# Eye diagram
		if len(eyes) > 0:
				for line in eyes:
						ax_eye.plot(np.linspace(0, mode['symbols_per_eye'], window_samples), line, color='blue', alpha=0.1)
		ax_eye.set_title(f"Eye Diagram (Bitrate: {mode['bitrate']/1e6:.0f} Mbps)")
		ax_eye.set_xlabel("Time (symbols)")
		ax_eye.set_ylabel(serie['labely'])
		ax_eye.grid(grid, which="both")

		# Time-domain signal
		ax_signal.plot(time, signal, color='darkgreen')
		ax_signal.set_title("Captured Signal (Time Domain)")
		ax_signal.set_xlabel(serie['labelx'])
		ax_signal.set_ylabel(serie['labely'])
		ax_signal.grid(grid, which="both")

		# Finalize
		plt.tight_layout()
		self.save_figure(plt, out, path, t, transparent)
		plt.show(block=False)


	def hold(self,msg= "Press ENTER key to continue...",cont='',abort='q'):
		k = 0
		while(k != cont):
			k = input(msg)
			if k.lower() == abort: exit()
		
	def file_exists(self,n):
		if os.path.exists(n):
			n = n[:-4]
			msg ='\n\n'
			msg+='the file '+n+' already exist\n'
			msg+='type "'+n+'" to continue\n'
			msg+='or press ENTER do abort\n\t#'
			self.hold(msg,n,'')
		return
	
	@staticmethod
	def _grid_recover(detected, period, t_min, t_max, marks_only=False):
		"""Snap detected centers to a phase-locked grid.
		
		Estimates the grid phase robustly via a circular mean of
		(t mod period) across all candidates, then generates the full
		integer-period grid anchored to that phase.
		
		Args:
		    detected   (list[float]): Raw detected center timestamps (s).
		    period     (float): Expected period (s).
		    t_min      (float): Signal start time (s).
		    t_max      (float): Signal end time (s).
		    marks_only (bool): True  → keep only grid points near a
		        detected candidate (data signal with spaces, e.g. E12).
		        False → return the full grid (clock signal, e.g. T12).
		
		Returns:
		    list[float]: Phase-locked center timestamps.
		"""
		if not detected:
			return []
		
		arr = np.array(detected)
		
		# Circular mean of (t mod period) for a robust phase estimate
		# that is immune to missing/extra detections.
		phases     = arr % period
		angles     = 2 * np.pi * phases / period
		mean_angle = np.arctan2(np.mean(np.sin(angles)), np.mean(np.cos(angles)))
		mean_phase = (mean_angle / (2 * np.pi)) * period
		if mean_phase < 0:
			mean_phase += period
		
		# First grid point at or after t_min that carries the recovered phase
		n_start = int(np.ceil((t_min - mean_phase) / period))
		t_ref   = mean_phase + n_start * period
		
		# Full grid within signal range
		n_end = int(np.ceil((t_max - t_ref) / period)) + 1
		grid  = [t_ref + n * period for n in range(n_end)
			if t_ref + n * period <= t_max + period * 0.01]
		
		if not marks_only:
			return grid
		
		# marks_only: keep grid points that have a nearby raw detection
		# (marks present) and discard unoccupied bit slots (spaces).
		half_T = period * 0.45
		return [g for g in grid if any(abs(g - d) < half_T for d in arr)]
	
	def plot_mask(self, s='Signal Name',mode="T12",interface='coaxial',size=(14, 5),out='png',path='',transparent=False):
		for d in self.reads:
			if s == d["name"]:

				# --- Scale factors -------------------------------------------------
				t_scale   = d['engNoteX']
				v_scale   = d['engNoteY']
				x_unit    = d['labelx'][d['labelx'].find('[')+1 : d['labelx'].find(']')]
				y_unit    = d['labely'][d['labely'].find('[')+1 : d['labely'].find(']')]
				time_s    = d['x'].to_numpy() * t_scale
				voltage_v = d['y'].to_numpy() * v_scale

				print(f"\nSignal: {len(time_s)} samples")
				print(f"  Vmax = {voltage_v.max():.3f} {y_unit}   Vmin = {voltage_v.min():.3f} {y_unit}")
				print(f"  Duration = {d['x'].iloc[-1] - d['x'].iloc[0]:.3f} {x_unit}")

				# --- Mode: T12 — 2048 kHz clock (G.703 Section 15) ----------------
				if mode == "T12":
					mask  = G703Clock2048kHz(interface=interface)
					title = f'G.703 T12 — 2048 kHz Clock Mask ({interface}) — {s}'
					mask_label = 'G703 T12 forbidden'

					# Falling zero crossing detection (interpolated, min-sep filtered)
					sign     = np.sign(voltage_v)
					fall_idx = np.where((sign[:-1] >= 0) & (sign[1:] < 0))[0]
					centers_raw = []
					for i in fall_idx:
						v0, v1s = voltage_v[i], voltage_v[i+1]
						t0, t1s = time_s[i],    time_s[i+1]
						centers_raw.append(float(t0 + (-v0 / (v1s - v0)) * (t1s - t0)))
					min_sep = mask.T * 0.8 / 2
					centers = []
					for tc in centers_raw:
						if not centers or (tc - centers[-1]) > min_sep:
							centers.append(tc)
					n_raw   = len(centers)
					centers = CsvScope._grid_recover(
						centers, mask.T, time_s[0], time_s[-1], marks_only=False)
					print(f"\n  Falling zero crossings: {n_raw} detected → {len(centers)} grid-locked")

				# --- Mode: E12 — 2048 kbit/s HDB3 data (G.703 Section 11) ---------
				elif mode == "E12":
					mask  = G703Data2048kbits(interface=interface)
					title = f'G.703 E12 — 2048 kbit/s HDB3 Mask ({interface}) — {s}'
					mask_label = 'G703 E12 forbidden'

					# Pulse center detection: edge-based midpoint method.
					# For each polarity, find the threshold crossing at the leading
					# and trailing edges of every mark pulse, then take the midpoint.
					# Threshold at 40 % of |Vpeak| — enough to ignore noise / space.
					vmax_abs  = np.max(np.abs(voltage_v))
					thr       = 0.4 * vmax_abs

					# ---- interpolated threshold crossings -----------------------
					pos_rise, pos_fall = [], []   # +thr crossings
					neg_fall, neg_rise = [], []   # -thr crossings

					v, t = voltage_v, time_s
					for i in range(len(v) - 1):
						# positive rising  (below to above +thr)
						if v[i] < thr <= v[i + 1]:
							frac = (thr - v[i]) / (v[i + 1] - v[i])
							pos_rise.append(t[i] + frac * (t[i + 1] - t[i]))
						# positive falling (above to below +thr)
						elif v[i] >= thr > v[i + 1]:
							frac = (thr - v[i]) / (v[i + 1] - v[i])
							pos_fall.append(t[i] + frac * (t[i + 1] - t[i]))
						# negative falling (above to below -thr)
						if v[i] > -thr >= v[i + 1]:
							frac = (-thr - v[i]) / (v[i + 1] - v[i])
							neg_fall.append(t[i] + frac * (t[i + 1] - t[i]))
						# negative rising  (below to above -thr)
						elif v[i] <= -thr < v[i + 1]:
							frac = (-thr - v[i]) / (v[i + 1] - v[i])
							neg_rise.append(t[i] + frac * (t[i + 1] - t[i]))

					# ---- pair crossings: each rise with its next fall ------------
					centers = []
					fi = 0
					for tr in pos_rise:                       # positive pulses
						while fi < len(pos_fall) and pos_fall[fi] <= tr:
							fi += 1
						if fi < len(pos_fall):
							centers.append((tr + pos_fall[fi]) / 2)
							fi += 1

					ri = 0
					for tf in neg_fall:                       # negative pulses
						while ri < len(neg_rise) and neg_rise[ri] <= tf:
							ri += 1
						if ri < len(neg_rise):
							centers.append((tf + neg_rise[ri]) / 2)
							ri += 1

					# ---- sort and apply minimum-separation guard -----------------
					centers.sort()
					min_sep  = mask.T * 0.5
					filtered = []
					for c in centers:
						if not filtered or (c - filtered[-1]) > min_sep:
							filtered.append(c)
					centers = filtered
					n_raw   = len(centers)
					centers = CsvScope._grid_recover(
						centers, mask.T, time_s[0], time_s[-1], marks_only=True)
					print(f"\n  Mark pulse centers: {n_raw} detected → {len(centers)} grid-locked")

				else:
					print(f"  [plot_mask] Unknown mode '{mode}'. Supported: T12, E12.")
					return

				if centers:
					print(f"  First 5: {[f'{c/t_scale:.3f} {x_unit}' for c in centers[:5]]}")

				# --- Validate ------------------------------------------------------
				if centers:
					result = mask.validate(time_s, voltage_v, centers)
					print(f"  {result}")
				else:
					print("  No centers detected — check signal amplitude or mask.T.")
					result = None

				# --- Plot ----------------------------------------------------------
				fig, ax = plt.subplots(figsize=size)
				ax.plot(d['x'].to_numpy(), d['y'].to_numpy(),
						color='steelblue', lw=0.8, label='Signal')

				half = mask._half_window
				for i, c in enumerate(centers):
					# Determine pulse polarity to orient the mask correctly
					idx = (time_s >= c - half) & (time_s <= c + half)
					if np.any(idx):
						peak = voltage_v[idx][np.argmax(np.abs(voltage_v[idx]))]
						sign = -1 if peak < 0 else 1
					else:
						sign = 1
					mask.plot(ax, t_center=c, t_scale=t_scale, v_scale=v_scale,
							  color='darkorange', sign=sign,
							  alpha=0.30,# if i == 0 else 0.05,
							  label=mask_label if i == 0 else None)

				if result and result.violations:
					vt = [v.time    / t_scale for v in result.violations[:500]]
					vv = [v.voltage / v_scale for v in result.violations[:500]]
					ax.plot(vt, vv, 'rx', ms=4, label=f'Violations ({result.violation_count})')

				ax.axhline(0, color='gray', lw=0.5, ls='--')
				ax.set_xlabel(d['labelx'])
				ax.set_ylabel(d['labely'])
				ax.set_title(f'{title}\n{result}')
				ax.legend(fontsize=8)
				ax.grid(True, alpha=0.3)
				plt.tight_layout()

				self.save_figure(plt, out, path, s, transparent)
				plt.show(block=False)
