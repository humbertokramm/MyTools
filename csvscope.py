"""
**File: csvscope.py**

**Descrição**
    Classe para processamento e visualização de dados de osciloscópios e instrumentos de medição.
    Suporta múltiplos formatos (ROHDE, Tektronix, Master Tool) com análises avançadas.

**Classe Principal**

``class csvscope``
    
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
    
    ``getEng(nota, s=False)``
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
    - pyvisa
    - dirHandle

See: docs/guia_documentacao.rst
"""

import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np
import csv
from copy import copy,deepcopy
from scipy.signal import welch
from scipy.signal import find_peaks
from scipy import signal
import os
import datetime
from pprint import pprint
import pyvisa
import optparse
import requests
import time
import dirHandle as dh
import re
from sklearn.cluster import KMeans
from pathlib import Path
from engMath import *



class csvscope:
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
		self.fftZone = [None,None]
		
	def __str__(self):
		return self.title

	def filtro(self,name='ch1',fc=1e3,ordem=2,overwrite=True,corte=0.2):
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
			i= self.getOrder().index(name)
		except:
			print('não foi encontrada uma lista com o nome '+str(name))
			return
		T=self.reads[i]['x'].iat[1]-self.reads[i]['x'].iat[0]
		fs = 1/(T*self.reads[i]['engNoteX'])
		# filtro passa-baixas Butterworth
		b, a = signal.butter(ordem, fc/(fs/2), btype='low')
		# Aplicar o filtro ao sinal
		sinal_filtrado = signal.lfilter(b, a, self.reads[i]['y'])
		sinal_filtrado=pd.DataFrame(sinal_filtrado)
		if overwrite:
			corte = int(len(sinal_filtrado)*(corte/100))
			self.reads[i]['data'] += f'[Filtered with order {ordem} Butterworth @ {getEngSTR(fc,2)}Hz]'
			self.reads[i]['y'] = sinal_filtrado[corte:]
			self.reads[i]['x'] = self.reads[i]['x'][corte:]
		return self.reads[i]['x']*self.reads[i]['engNoteX'],sinal_filtrado*self.reads[i]['engNoteY']

	def filtroInterno(self,df,filtro=[1e3,4]):
		fc = filtro[0]
		ordem = filtro[1]
		T=df['x'].iat[1]-df['x'].iat[0]
		fs = 1/(T*df['engNoteX'])
		# filtro passa-baixas Butterworth
		b, a = signal.butter(ordem, fc/(fs/2), btype='low')
		# Aplicar o filtro ao sinal
		sinal_filtrado = signal.lfilter(b, a, df['y'])
		sinal_filtrado=pd.DataFrame(sinal_filtrado)
		df['y'] = sinal_filtrado[sinal_filtrado.columns[0]]
		df['x'] = df['x'].reset_index(drop = True)

	def detectBrandFile(self, f):
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

	def MtoolCSV(self,f):
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

	def TektronixCSV(self,f):
		df = pd.read_csv(f, header=None)
		labely = df[1][6]
		df = df.drop(df.columns[[0, 1, 2,5]], axis=1)
		df.columns = ['in s',labely]
		return df

	def loadUSBVisa(self,file):
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
					data = linha.split(": ", 1)[1].strip()
		
		# Ler dataframe ignorando comentários
		df = pd.read_csv(file, comment="#", encoding='latin-1')
		df.columns = ['in s',"ch1 in V"]
		return df, instrumento, data

	def readFile(self, f,data):
		if type(f) != type(" "): f = str(f)
		i = f.lower().find('.csv')
		if i > 0:
			f = f[:i]+'.csv'
		else:
			f = f+'.csv'
		
		brd = self.detectBrandFile(f)
		info = os.stat(f).st_ctime
		info = datetime.datetime.fromtimestamp(info)
		info = str(info)[:16]


		if brd == 'TDS3052B':
			df = pd.read_csv(f)
			df = df.rename(columns={'TDS3052B in s':'in s'})
		elif brd[:3] == 'TDS':
			df = self.TektronixCSV(f)
		elif brd == 'Master Tool':
			df = self.MtoolCSV(f)
		elif brd == 'USB.VISA':
			df,brd,info = self.loadUSBVisa(f)
		else: df = pd.read_csv(f)
		data['data'] = brd +' - '+ info
		return df

	def manualTable(self,x,y,dados):
		table = [x,y]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		return df

	def formatLinhaH(self, y,n='serie',color=False,config=[]):
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
		dados = self.setData(n,config,'Line H')
		if color: dados['color']=color
		#lx=config['label x'] if 'label x' in config else 'Tempo[ms]'
		#ly=config['label y'] if 'label y' in config else 'Tensão[V]'
		#pln=config['plane'] if 'plane' in config else 1

		if not isinstance(y, (int, float)):
			print('ERROR formatLinhaH: Entre com um número válido em y')
			return 'nan'

		table = [[None,None],[y,y]]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		
		# Manipula as escala
		self.handleScales(dados,df)
		self.areaGraf4(dados)
		self.reads.append(dados)
		return dados

	def formatLinhaV(self, x,n='serie',color=False,config=[]):
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
		dados = self.setData(n,config,'Line V')
		if color: dados['color']=color

		if not isinstance(x, (int, float)):
			print('ERROR formatLinhaV: Entre com um número válido em x')
			return 'nan'

		table = [[x,x],[None,None]]
		df = pd.DataFrame(table)
		df = df.transpose()
		df.columns = ['in s', 'CH1 in V']
		dados['data'] = 'None'
		
		# Manipula as escala
		self.handleScales(dados,df)
		self.areaGraf4(dados)
		self.reads.append(dados)
		return dados

	def getOrder(self):
		"""
		Retorna lista com os nomes de todas as séries carregadas, na ordem atual.
		
		Returns:
			list: Lista de strings com os nomes das séries.
		"""
		list = []
		for n in self.reads:
			list.append(n['name'])
		return list

	def setOrder(self,names='nan',index='nan'):
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
				v,_= self.findkey(temp,n)
				if not v == None: self.reads.append(v)
			return True
		else: return False

	def setData(self, n,config,modo):
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
			'engNoteX':getEng(lx),
			'engNoteY':getEng(ly),
			'engNoteXstr':getEng(lx,'str'),
			'engNoteYstr':getEng(ly,'str'),
			'symbolX':getEng(lx,'symbol'),
			'symbolY':getEng(ly,'symbol'),
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

	def handleScales(self, d,df,o=0,gain=None,c=1):
		lx = d['labelx']
		ly = d['labely']
		ot = d['offset time']
		g = gain if gain != None else d['gain']
		d['x'] = df[df.columns[0]].astype(float)*(1/getEng(lx))+ot*(1/getEng(lx))
		d['y'] = df[df.columns[c]].astype(float)*g*(1/getEng(ly))+o*(1/getEng(ly))

	def handleCuts(self,df,config):
		coi=config['cutoff in'] if 'cutoff in' in config else 'nan'
		coo=config['cutoff out'] if 'cutoff out' in config else 'nan'
		# Verificar se a coluna 'in s' existe
		if 'in s' not in df.columns:
			df.rename(columns={df.columns[0]: 'in s'}, inplace=True)
		# selecting rows based on condition
		if not coi =='nan': df = df.loc[df['in s'] >= coi]
		if not coo =='nan': df = df.loc[df['in s'] <= coo]
		return df

	def format(self, f='TRC01',g=None,o=0,c=1,x=[],y=[],n='nan',color=False,config=[],filtro=0):
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
		dados = self.setData(n,config,'signal')
		if color: dados['color']=color
		
		# carrega o dataframe
		if len(x)==0: df = self.readFile(f,dados)
		else: df = self.manualTable(x,y,dados)
		
		# verifica o tamanho
		if(c+1 > len(df.columns)):
			print('ERROR format: Sua planilha de dados possui menos colunas do que o requisitado')
			print(df)
			return 'nan'
		# define o nome da série se vier em branco
		if n == 'nan':
			dados['name'] = df.columns[c]
		# Manipula os cortes
		df = self.handleCuts(df,config)
		if type(df) == type('nan'): return 'nan'
		
		samplingPeriod  = df.iloc[1,0]-df.iloc[0,0]
		samplingFrequency = 1/samplingPeriod
		samplingPeriod = getEngSTR(samplingPeriod)+'s'
		samplingFrequency = getEngSTR(samplingFrequency)+'Hz'

		# Manipula as escala
		self.handleScales(dados,df,o,g,c)
		self.areaGraf4(dados)
		if type(filtro) == type([]):
			self.filtroInterno(dados,filtro)
		self.getAnotations(dados)
		self.reads.append(dados)
		
		dados['samplingPeriod'] = samplingPeriod
		dados['samplingFrequency'] = samplingFrequency
		dados['data'] = 'Sampling Period: '+dados['samplingPeriod'] +' - '+ dados['data']

		return dados

	def getAnotations(self, dados):
		for busca in ['note','findY','findT']:
				if busca in dados:
					for n in dados[busca]:
						self.anotation(n,dados,busca)

	def findkey(self,list,value,key='name'):
		for i,dictio in enumerate(list):
			if key in dictio:
				if dictio[key] == value:
					return dictio,i
		return None,None

	def findkey2(self,col,value,n):
		index = -1
		for row in col:
			index += 1
			for i in row:
				if i[4]==value:
					if i[1][:len(n)] == n:
						return i[0][0],index
		return None,None

	def drawDelay(self, s1,n1,s2,n2,u='s',name=''):
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
		cord1,indexLabel = self.findkey2(self.yDf['draw'],s1,n1)
		cord2,indexLabel = self.findkey2(self.yDf['draw'],s2,n2)
		s_,_ = self.findkey(self.reads,s1)

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
		
		if u == 's': text = name + ' = '+getValue(dt,s_,'x')
		if u == 'Hz': text = name + ' = '+getValue(1/dt,s_,'f')
		if u == 'bps': text = name + ' = '+getValue(1/dt,s_,'bps')
		style = '-'
		dir = 'NE'
		xo=cord1[0] if cord1[0] < cord2[0] else cord2[0]
		cordT = [[xo+dt/2,y],[None,None]]
		self.yDf['draw'][indexLabel].append([meio,text,style,dir,n1])

	def findNote(self,list, value,key='name'):
		for i in range(len(list)):
			if key in list[i]:
				for point in range(len(list[i][key])):
					if list[i][key][point][1][:len(value)] == value:
						return i,point
		return None,None

	def interpolateDF(self,df,sampleTarget=1000):
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

	def setAnotationDir(self,n,dir,newname=''):
		# Função para procurar e substituir com base no primeiro item da lista
		def setL(lista, string_verificacao, substituto):
			for i in range(len(lista)):
				if lista[i][1].startswith(string_verificacao):
					lista[i][3] = substituto
			return lista
		# Aplicar a função a cada linha do DataFrame
		self.yDf['draw'] = self.yDf.apply(lambda row: setL(row['draw'], n, dir), axis=1)
	
	def handleNoteName(self, d):
		if type(d) == type({}):
			especificName = list(d.keys())[0]
			d = d[especificName]
		else:
			self.indexNote += 1
			especificName = 'p'+str(self.indexNote)
		return d, especificName

	def anotation(self, d,s,n):
		indexLabel = self.yDf.index[self.yDf['label'] == s['labely']].tolist()[0]
		name = s['name']
		if not 'info' in s: s['info']={}
		x = self.interpolateDF(s['x'])
		y = self.interpolateDF(s['y'])
		if len(x) == 0: return print('ERROR ANOTATION: '+name+" has no signal")
		d, id = self.handleNoteName(d)
		if n == 'note':
			if d == 'Vmáx':
				i = y.idxmax()
				y = y[i]
				x = x[i]
				cord=[[x,y],[None,None]]
				text=d+ ': '+getValue(y,s,'y')
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
				text=d+ ': '+getValue(y,s,'y')
				style = '->'
				dir = 'N'
				s['info'][d]=[y,text]
				self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
				return
				
			elif d == 'RMS':
				rms = np.sqrt((y**2).mean())
				meio = int(len(y)/2)
				cord=[[x[meio],y[meio]],[None,None]]
				text=d+ ': '+getValue(rms,s,'y',casas=4)
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
				text=d+ ': '+getValue(y2-y1,s,'y')
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
				text=d_+ ': '+getValue(dt,s,'x')
				if d == 'transition in f':
					text=d+ ': '+getValue(1/dt,s,'f')
					s['info'][d]=[1/dt,text]
				elif d == 'slew rate':
					text=d+ ': '+getValue(dV/dt,s,'v/t')
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
			text=id+' ('+getValue(x,s,'x')+' , '+getValue(y,s,'y')+')'
			style = '->'
			dir = 'NE'
			s['info'].append([id,y,text])
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
				print('not find t '+str(d)+' in '+name+' just '+str(x)+' p['+str(i)+'] diff = '+getValue(diff,s,'x'))
				return
			cord=[[x,y],[None,None]]
			text=id+' ('+getValue(x,s,'x')+' , '+getValue(y,s,'y')+')'
			style = '->'
			dir = 'NE'
			s['info'][id]=[y,text]
			self.yDf['draw'][indexLabel].append([cord,text,style,dir,name])
			return
		return

	def areaGraf(self, serie,area=None):
		min = 0
		max = 1
		x = 0
		y = 1

		if area == None:
			area =  [[serie['x'].min(),serie['y'].min()], [serie['x'].max(),serie['y'].max()],[2,1]]
			return area

		if area[min][y] >= serie['y'].min(): area[min][y] = serie['y'].min()
		if area[min][x] >= serie['x'].min(): area[min][x] = serie['x'].min()
		if area[max][y] <= serie['y'].max(): area[max][y] = serie['y'].max()
		if area[max][x] <= serie['x'].max(): area[max][x] = serie['x'].max()
		return area

	def areaGraf4(self, serie):
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

	def plotNotes(self,f,ax,i):#,notes):
		factor= 0.05
		figsize = f.get_size_inches()
		rate= figsize[1]/figsize[0]
		deltax = self.yDf['xAr'][i]*factor*rate
		deltay = self.yDf['yAr'][i]*factor
		#for note in notes:
		#print('plotNotes()')
		#pprint(self.yDf['draw'])
		for note in self.yDf['draw'][i]:
			#print('for note in self.yDf')
			#pprint(note)
			a=self.arrow(note,[deltax,deltay])
			ax.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],ha=a['ha'],va=a['va'],arrowprops=a['props'])

	def arrow(self, n,d=0):
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

	def rolling_rms(self, x, N):
		return (pd.DataFrame(abs(x)**2).rolling(N).mean()) **0.5

	def completeLines(self):
		# trata o sinal
		for serie in self.reads:
			indexLabel = self.yDf.index[self.yDf['label'] == serie['labely']].tolist()[0]
			if 'type' in serie:
				if serie['type'] == 'Line H':
					serie['x'] = [self.yDf['xMin'][indexLabel],self.yDf['xMax'][indexLabel]]
				if serie['type'] == 'Line V':
					serie['y'] = [self.yDf['yMin'][indexLabel],self.yDf['yMax'][indexLabel]]

	def seriePlot(self,ax,serie):
		if 'color' in serie:
			ax.plot(serie['x'], serie['y'], linewidth=2.0,label=self.handleLabel(serie['name']),color=serie['color'])
		else:
			ax.plot(serie['x'], serie['y'], linewidth=2.0,label=self.handleLabel(serie['name']))
		ax.set_ylabel(serie['labely'])
		ax.legend()

	def salvaFigura(self,obj,out='png',path='',t='nan',transparent=False):
		filenames = []
		if type([]) == type(out):
			for o in out:
				filenames.append(path+t+'.'+o)
		elif out == '':
			filenames.append(t+'.png')
			filenames.append(t+'.pdf')
		else: filenames.append(path+t+'.'+out)
		
		for filename in filenames:
			obj.savefig(dh.ajustar_nome_arquivo(filename), bbox_inches='tight', pad_inches=0, transparent=transparent)

	def handleLabel(self,texto):
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

	def handleMask(self,ax):
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
		self.completeLines()
		
		# Inicia a plotagem
		fig, ax = plt.subplots(figsize=size)#,axes_class=axisartist.Axes)
		ax.set_title(t)
		self.plotNotes(fig,ax,0)
		
		if len(self.yDf)>1:
			ax2 = ax.twinx() # Create another axes that shares the same x-axis as ax.
			self.plotNotes(fig,ax2,1)
		
		ax = self.handleMask(ax)
		
		# Percorre plota as séries
		for serie in self.reads:
			indexLabel = self.yDf.index[self.yDf['label'] == serie['labely']].tolist()[0]
			#if serie['labely'] == self.ySeries[0]:
			if indexLabel == 0:
				self.seriePlot(ax,serie)
			else:
				self.seriePlot(ax2,serie)
			ax.set_xlabel(serie['labelx'])
			ax.grid(grid)
			
			if serie['data'] != 'None': data = serie['data']
			else: data = 'None'
			if 'loc_legend' in serie: loc_legend = serie['loc_legend']
			if 'loc_legend2' in serie: loc_legend2 = serie['loc_legend2']

		if loc_legend != None: ax.legend(loc=loc_legend)
		if loc_legend2 != None: ax2.legend(loc=loc_legend2)
		if data != 'None':
			ax.annotate(data,xy=(0.5,1e-2),xycoords='axes fraction', ha='center', fontsize=8)

		plt.ion()  # Ativa o modo interativo
		# Salva Figura
		self.salvaFigura(plt,out,path,t,transparent)
		# Exibindo a figura
		plt.show(block=False)
		return

	def formatFFT(self,id=0,name='',f = False):
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
			_,id = self.findkey(self.reads,name)
		d = self.reads[id]
		
		x = d['x']*d['engNoteX']
		y = d['y']*d['engNoteY']
		
		fft = np.fft.fft(y)
		fft[0] = 0
		fftfreq = np.fft.fftfreq(len(y))*len(y)/(x.max()-x.min())
		self.fftData(np.fft.ifft(fft).real,id,'ac_ripple')

		y_filtered = False
		if self.fftZone != [None,None]:
			# ---- FILTRO PASSA-FAIXA (f_minHz a f_maxHz) ----
			f_min = self.fftZone[0]
			f_max = self.fftZone[1]
			fft_filtered = fft.copy()
			for i in range(len(fftfreq)):
				if not (f_min <= abs(fftfreq[i]) <= f_max):
					fft_filtered[i] = 0
			# reconstrução no tempo (sinal filtrado)
			y_filtered = np.fft.ifft(fft_filtered).real
			self.fftData(y_filtered,id,'ac_ripple_filter')

		a = []
		b = []
		for i in range(len(fftfreq)):
			if fftfreq[i] > 0:
				a.append(fftfreq[i])
				b.append(fft[i])
		self.reads[id]['fft']={'f':a,'A':np.abs(b)}
		if f: self.reads[id]['fft-tittle'] = f

	def fftData(self, y,id,name):
		vpp = np.max(y) - np.min(y)
		vrms = np.sqrt(np.mean(y**2))
		self.reads[id][name] = {
			'vpp': vpp,
			'vrms': vrms,
		}


	def plotFFT(self, t='Minhas Leituras',grid = True,size=(12, 6),axe='linear',out='png',mark=1,path='',transparent=False):
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
				plt.xlabel("Domínio da Frequência [Hz]")
				plt.ylabel("Amplitude [µV]")

				a=serie['fft']['f']
				factor = 1
				if axe =='log': plt.semilogx()
				else:
					symbol = getEngSTR(max(a))[-1]
					factor = EngNotation[symbol]
					a = [float(i) / factor for i in serie['fft']['f']]
					plt.xlabel("Domínio da Frequência ["+symbol+"Hz]")
				
				# Normalizando a amplitude
				num_points = len(serie['fft']['A'])  # número total de pontos na série FFT
				x = np.array(a)
				y = np.array([amp*1e6 / num_points for amp in serie['fft']['A']])

				largestValuesIndex = np.argsort(y)[-mark:][::-1]
				j=0
				serie['draw']=[]
				for i in largestValuesIndex:
					j+=1

					x_ = x[i]
					y_ = y[i]
					
					cord=[[x_,y_],[None,None]]
					text='p'+str(j)+': '+getEngSTR(x_*factor,0)+'Hz'
					style = '-'
					dir = 'N'
					serie['draw'].append([cord,text,style,dir])
				
				plt.plot(x,y)
				
				# ---- Zona de interesse ----
				if self.fftZone != [None,None]:
					f_min = self.fftZone[0]
					f_max = self.fftZone[1]
					f_min_plot = f_min / factor
					f_max_plot = f_max / factor
					plt.axvspan(f_min_plot, f_max_plot, alpha=0.15, color='blue')
					plt.axvline(f_min_plot, color='blue', linestyle='--', linewidth=1)
					plt.axvline(f_max_plot, color='blue', linestyle='--', linewidth=1)
				# ------

				plt.grid(grid,which="both")
				
				temp={'x':x,'y':y}
				area = self.areaGraf(temp)
				if serie['data'] != 'None':
					if axe =='linear': textX=(area[1][0]-area[0][0])/2+area[0][0]
					else: textX=np.sqrt(area[1][0])*np.sqrt(area[0][0])
					textY = -area[1][1] / 40
					plt.text(textX,textY, serie['data'], ha='center', fontsize=8)
				
				if 'ac_ripple' in serie:
					vpp_mv = serie['ac_ripple']['vpp'] * 1e3
					text = f"AC Ripple: {vpp_mv:.2f} mVpp"
					plt.text(area[0][0], area[1][1]*0.9, text, fontsize=10, color='red')
				if 'ac_ripple_filter' in serie:
					vpp_mv = serie['ac_ripple_filter']['vpp'] * 1e3
					strZonef1 = getEngSTR(self.fftZone[0],0)+"Hz"
					strZonef2 = getEngSTR(self.fftZone[1],0)+"Hz"
					text = f"AC Ripple: {vpp_mv:.2f} mVpp in {strZonef1} to {strZonef2}"
					plt.text(area[0][0], area[1][1]*0.85, text, fontsize=10, color='blue')

				for note in serie['draw']:
					#a=self.arrow(note,[area[2][1],area[2][1]])
					a=self.arrow(note,[0,0])
					#plt.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],arrowprops=dict(arrowstyle=a['arrowstyle'], linestyle=a['linestyle']))
					plt.annotate(a['txt'], xy=a['xy'],xytext=a['xytext'],ha=a['ha'],va=a['va'],arrowprops=a['props'])
				# Salva a figura
				self.salvaFigura(plt,out,path,t,transparent)
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
				"10BASE-T":     {"bitrate": 10_000_000,    "num_levels": 2, "symbols_per_eye": 3},
				"100BASE-TX":   {"bitrate": 100_000_000,   "num_levels": 3, "symbols_per_eye": 3},
				"1000BASE-T":   {"bitrate": 1_000_000_000, "num_levels": 5, "symbols_per_eye": 3},
				"2.5GBASE-T":   {"bitrate": 2_500_000_000, "num_levels": 5, "symbols_per_eye": 2},
				"5GBASE-T":     {"bitrate": 5_000_000_000, "num_levels": 5, "symbols_per_eye": 2},
				"10GBASE-T":    {"bitrate": 10_000_000_000,"num_levels": 16,"symbols_per_eye": 2}
		}

		if mode not in presets:
				raise ValueError(f"Unsupported Ethernet mode: {mode}")

		return presets[mode]

	def plotPAM(self, t='My Measurements', s=0, grid=True, size=(12, 8), out='png', path='', transparent=False, mode="1000BASE-T"):
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
		self.salvaFigura(plt, out, path, t, transparent)
		plt.show(block=False)


	def hold(self,msg= "Press ENTER key to continue...",cont='',abort='q'):
		k = 0
		while(k != cont):
			k = input(msg)
			if k.lower() == abort: exit()
		
	def checkExistFile(self,n):
		if os.path.exists(n):
			n = n[:-4]
			msg ='\n\n'
			msg+='the file '+n+' already exist\n'
			msg+='type "'+n+'" to continue\n'
			msg+='or press ENTER do abort\n\t#'
			self.hold(msg,n,'')
		return
	
	def getTDS3052BTrace(self,ip='',C='ch1',f='temp'):
		"""
		Obtém dados de um ou mais canais do osciloscópio TDS3052B via HTTP e salva em CSV.
		
		Args:
			ip (str): Endereço IP do TDS3052B (ex: "192.168.1.100"). Obrigatório.
			C (str or list, optional): Canal(s) a ler: 'ch1', 'ch2', etc., ou lista de canais.
				Padrão é 'ch1'.
			f (str, optional): Nome base do arquivo CSV (sem extensão). Padrão é 'temp'.
		
		Returns:
			None: Salva arquivo CSV com dados dos canais e imprime progresso.
		
		Note:
			- Usa requisições HTTP POST para obter dados do instrumento.
			- Cada canal leva aproximadamente 25 segundos.
			- Se múltiplos canais, combina todos em um único CSV.
		"""
		if type(C) == type(''): C = [C]
		if ip == '': return print('ERROR: set ip')
		
		i = f.lower().find('.csv')
		if i > 0:
			f = f[:i]+'.csv'
		else:
			f = f+'.csv'
		
		self.checkExistFile(f)
		
		df_novo = []
		for c in C:
			print('Reading '+c+ ' - expecting 25 seconds')
			inicio = time.time()
			url = 'http://' + ip + '/getwfm.isf'
			x = requests.post(url, data= {'command':'select:'+c+' on\r\n','wfmsend':'Get'},headers={'Content-Type': 'text/plain'})
			fim = time.time()
			
			canal = x.text.split('\r\n')
			# Dividir cada elemento da lista em duas partes
			lista_dividida = [elemento.split(',') for elemento in canal]
			print(str(round(fim - inicio,2))+' s')
			# Criar DataFrame do Pandas
			df_novo.append(pd.DataFrame(lista_dividida, columns=['TDS3052B in s',c.upper()+' in V']))
			
		df = df_novo[0]
		for d in range(1,len(df_novo)):
			df[C[d].upper()+' in V'] = df_novo[d][C[d].upper()+' in V']

		# Excluir linhas vazias
		df = df.dropna(how='any')
		print(df)
		df.to_csv(f, index=False)
		
	
	def SetInstrument(self, ip = '',usb='',id=''):
		"""
		Configura conexão com instrumento via PyVISA (TCP/IP, USB ou ID direto).
		
		Args:
			ip (str, optional): Endereço IP do instrumento (ex: "192.168.1.100").
				Padrão é ''.
			usb (str, optional): Identificador USB do instrumento. Padrão é ''.
			id (str, optional): ID completo do instrumento no formato PyVISA.
				Padrão é ''.
		
		Returns:
			int: Índice do instrumento na lista self.inst, ou None em caso de erro.
		
		Note:
			- Pelo menos um dos parâmetros (ip, usb ou id) deve ser fornecido.
			- Verifica a conexão enviando comando ``*IDN?`` e imprime a resposta.
		"""
	
		# Checa se veio um nome
		if not ip == '':
			device = 'TCPIP::'+ip+'::INSTR'
		elif not usb == '':
			device = 'USB0::'+usb+'::INSTR'
		elif not id == '':
			device = id
		else: return print('ERROR: set device location/ip')
		
		# Criar o gestor de recursos do PyVISA
		rm = pyvisa.ResourceManager()
		
		# Criar o gestor de recursos do PyVISA
		self.inst.append( {'device': device })
		idx = len(self.inst)-1
		self.inst[idx]['obj'] = rm
		
		# abre a conexão
		inst = self.inst[idx]['obj'].open_resource(self.inst[idx]['device'])
		
		# Checa o device
		print(idx,inst.query('*IDN?'))
		inst.close()
		
		return idx
	
	def GetInstrumentTrace(self,f='TRACE',idx=0,c=1):
		"""
		Obtém dados de um canal do osciloscópio conectado e salva em arquivo CSV.
		
		Args:
			f (str, optional): Nome base do arquivo CSV (sem extensão). Padrão é 'TRACE'.
			idx (int, optional): Índice do instrumento em self.inst. Padrão é 0.
			c (int or str, optional): Canal a ler (1-10) ou 'M' para Math. Padrão é 1.
		
		Returns:
			None: Salva arquivo CSV com nome 'f_CHc.csv' e imprime confirmação.
		
		Note:
			- O instrumento deve ter sido configurado previamente com SetInstrument().
			- Os dados são salvos como valores brutos, um por linha.
		"""
		# Checa se o canal é válido
		if c < 1 or c > 10: return print('ERROR: set valid channel')
		
		# abre a conexão
		inst = self.inst[idx]['obj'].open_resource(self.inst[idx]['device'])

		# Obtém os dados do Math ou do canal
		if c == 0 or c == 'M':
			dados_onda = inst.query('MATH:DATA?')  # Comando para obter dados de Math
		else:
			dados_onda = inst.query(f'CHAN{c}:DATA?')

		# obtém dados
		dados_onda = inst.query(f'CHAN{c}:DATA?')
		 
		# Processar os dados recebidos (remover caracteres desnecessários e dividir por vírgula)
		dados_onda = dados_onda.strip().split(',')
		 
		# Salvar os dados em um arquivo CSV
		nome_arquivo_csv = f +'_CH'+ str(c) + '.csv'
		with open(nome_arquivo_csv, 'w', newline='') as arquivo_csv:
				escritor_csv = csv.writer(arquivo_csv)
				for valor in dados_onda:
						escritor_csv.writerow([valor])
		 
		# Fechar a conexão com o osciloscopio
		inst.close()
		
		print(f"Dados da onda do canal {c} salvos em {nome_arquivo_csv}")
		
	
	def GetInstrumentConfig(self,idx=0,c=1):
		# abre a conexão
		inst = self.inst[idx]['obj'].open_resource(self.inst[idx]['device'])
		
		# Extract the required values
		print(inst.query(f'CHAN{c}:DATA:XINC?'))
		print(inst.query(f'CHAN{c}:DATA:XOR?'))
		print(inst.query(f'CHAN{c}:DATA:YINC?'))
		print(inst.query(f'CHAN{c}:DATA:YOR?'))
		print(inst.query(f'CHAN{c}:SCAL?'))
		print(inst.query(f'CHAN{c}:RANG?'))
		print(inst.query(f'CHAN{c}:OFFS?'))
		
		
	def SetInstrumentConfig(self,idx=0,c=1):
		"""
		Configura parâmetros de um canal do osciloscópio conectado.
		
		Args:
			idx (int, optional): Índice do instrumento em self.inst. Padrão é 0.
			c (int, optional): Canal a configurar (1-10). Padrão é 1.
		
		Returns:
			None: Envia comandos SCPI para configurar o canal.
		
		Note:
			- Configura escala do canal para 10.
			- Configura número de pontos para máximo (DMAX).
			- O instrumento deve ter sido configurado previamente com SetInstrument().
		"""
		# abre a conexão
		inst = self.inst[idx]['obj'].open_resource(self.inst[idx]['device'])
		# ajusta configuração
		inst.write(f'CHAN{c}:SCAL 10')
		inst.write(f'CHAN{c}:DATA:POIN DMAX')
		inst.close()