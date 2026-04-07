"""
**File: dirHandle.py**

**Descrição**
    Módulo utilitário para manipulação de diretórios, arquivos e interface com usuário.
    Fornece funções coloridas, validação de nomes e seleção de arquivos.

**Funções Principais**

``ajustar_nome_arquivo(nome)``
    Ajusta string para nome de arquivo válido no Windows.
    
    :param nome: String a ajustar
    :type nome: str
    :return: String ajustada (máximo 255 caracteres)
    :rtype: str
    
    Substituições realizadas:
    - '*' e ':' → '.'
    - '<' e '>' → '-'
    - Caracteres inválidos → '_'

``Aviso(msg, cor='RESET')``
    Imprime mensagem colorida no terminal usando códigos ANSI.
    
    :param msg: Mensagem a exibir
    :type msg: str
    :param cor: Cor desejada (VERMELHO, VERDE, AMARELO, AZUL, RESET)
    :type cor: str

``confirmarErro(assertMSG, abortMSG='')``
    Solicita confirmação do usuário para continuar ou abortar operação.
    
    :param assertMSG: Mensagem que usuário deve digitar para continuar
    :type assertMSG: str
    :param abortMSG: Mensagem para abortar (opcional)
    :type abortMSG: str
    :return: "continue" ou "abort"
    :rtype: str

``contem_todas_substrings(string, lista_substrings)``
    Verifica se string contém todas as substrings da lista.
    
    :param string: String a verificar
    :type string: str
    :param lista_substrings: Lista de substrings
    :type lista_substrings: list
    :return: True se contém todas
    :rtype: bool

``selecioneArquivo(rules, noRules=[], msg='...', dir="local")``
    Permite ao usuário selecionar arquivo de lista filtrada.
    
    :param rules: Substrings que arquivo DEVE conter
    :type rules: list
    :param noRules: Substrings que arquivo NÃO deve conter
    :type noRules: list
    :param msg: Mensagem de prompt
    :type msg: str
    :param dir: Diretório de busca
    :type dir: str
    :return: Caminho do arquivo selecionado
    :rtype: str

**Cores Disponíveis**

- VERMELHO: '[91m'
- VERDE: '[92m'
- AMARELO: '[93m'
- AZUL: '[94m'
- RESET: Reseta cores

See: docs/guia_documentacao.rst
"""

import os
from datetime import datetime
import re
from pprint import pprint

# Códigos ANSI para cores
cores ={
	'VERMELHO':'\033[91m',
	'VERDE':'\033[92m',
	'AMARELO':'\033[93m',
	'AZUL':'\033[94m',
	'RESET':'\033[0m',  # Reseta a cor
	}



def ajustar_nome_arquivo(nome: str) -> str:
	"""
	Ajusta uma string para garantir que seja válida como nome de arquivo no Windows.
	Substitui caracteres específicos por alternativas compatíveis.

	Args:
		nome (str): A string que será ajustada.

	Returns:
		str: A string ajustada, limitada a 255 caracteres.

	Note:
		Regras de substituição:
		- '*' e ':' são substituídos por '.'
		- '<' e '>' são substituídos por '-'
		- Outros caracteres inválidos (/ " \\ | ?) são substituídos por '_'
		- Remove espaços no início e fim.
	"""
	# Substituições específicas
	nome = nome.replace('*', '.').replace(':', '.')
	nome = nome.replace('<', '-').replace('>', '-')
	
	# Regex para os demais caracteres inválidos
	caracteres_invalidos = r'[/"\\|?]'
	nome = re.sub(caracteres_invalidos, '_', nome)
	
	# Remove espaços no início e no fim e limita o tamanho
	return nome.strip()[:255]

def Aviso(msg,cor='RESET'):
	"""
	Imprime mensagem colorida no terminal.
	
	Args:
		msg (str): Mensagem a ser exibida.
		cor (str, optional): Cor da mensagem: 'VERMELHO', 'VERDE', 'AMARELO', 'AZUL', 'RESET'.
			Padrão é 'RESET'.
	
	Returns:
		None: Imprime mensagem formatada com código ANSI de cor.
	"""
	print(f"{cores[cor.upper()]}{msg}{cores['RESET']}")

def data_modificacao_arquivo(caminho_arquivo,path=''):
	timestamp_modificacao = os.path.getmtime(caminho_arquivo)
	data_modificacao = datetime.fromtimestamp(timestamp_modificacao)
	return data_modificacao.replace(microsecond=0)
	
def confirmarErro(assertMSG,abortMSG=''):
	"""
	Solicita confirmação do usuário para continuar ou abortar operação.
	
	Args:
		assertMSG (str): Mensagem que o usuário deve digitar para continuar.
		abortMSG (str, optional): Mensagem que o usuário deve digitar para abortar.
			Se '', não permite abortar. Padrão é ''.
	
	Returns:
		str: "continue" se usuário confirmou, "abort" se abortou.
	
	Note:
		- Loop infinito até receber uma resposta válida.
		- Comparação case-insensitive.
	"""
	while True:
		print(f'\n\tDigite "{assertMSG}" para continuar\n')
		x = input().lower()
		if x == assertMSG.lower(): return "continue"
		if x == abortMSG.lower(): return "abort"

def contem_todas_substrings(string, lista_substrings):
	return all(substring in string for substring in lista_substrings)
	
def nao_contem_todas_substrings(string, lista_substrings):
	if len(lista_substrings) == 0: return True
	return all(substring not in string for substring in lista_substrings)
	
def selecioneArquivo(rules,noRules=[],msg='Selecione um arquivo a ser analisado',dir="local"):
	"""
	Permite ao usuário selecionar um arquivo de uma lista filtrada.
	
	Args:
		rules (list): Lista de substrings que o arquivo DEVE conter.
		noRules (list, optional): Lista de substrings que o arquivo NÃO deve conter.
			Padrão é [].
		msg (str, optional): Mensagem exibida ao usuário. Padrão é 'Selecione um arquivo a ser analisado'.
		dir (str, optional): Diretório de busca: "local" (diretório atual) ou "parent" (diretório pai).
			Padrão é "local".
	
	Returns:
		str or None: Caminho completo do arquivo selecionado, ou None se nenhum arquivo encontrado
			ou usuário cancelar.
	
	Note:
		- Lista arquivos ordenados do mais recente para o mais antigo.
		- Se apenas um arquivo encontrado, seleciona automaticamente.
		- Exibe data de modificação de cada arquivo.
	"""
	path = ''
	if dir == "local":
		files = os.listdir()
	elif dir == 'parent':
		path = os.path.dirname(os.getcwd())+'\\'
		files = os.listdir(path)

	fileList = []
	print("\n")
	for f in files:
		if contem_todas_substrings(f,rules):
			if nao_contem_todas_substrings(f,noRules):
				fileList.append(f)
	return selecioneNaLista(fileList,msg,path)

def selecioneNaLista(fileList=[],msg='Selecione uma opção',path=''):

	if len(fileList) == 0:
		Aviso("\tNenhum Arquivo encontrado\n",'vermelho')
		if confirmarErro("Y") == 'abort': exit()
		else: return None
	
	#Verifica o tamanho do maior nome dos arquivos
	maxName = max(len(file) for file in fileList if file is not None) if fileList else 0
	
	if len(fileList) == 1:
		namefile = fileList[0]
		if "\\" in namefile:
			i = namefile.rfind("\\")
			namefile = namefile[:i + 1] + "\n\t\t" + namefile[i + 1:]
		print(f"\tSelecionado o arquivo {namefile} | {data_modificacao_arquivo(path+fileList[0])}\n")
		return path+fileList[0]
	

	# Primeiro ordenamos a lista de arquivos do mais novo para o mais antigo
	fileList = sorted(
		[f for f in fileList if f is not None],  # Filtra os None
		key=lambda x: os.path.getmtime(path+x),       # Ordena pelo timestamp de modificação
		reverse=True                             # Do mais novo para o mais antigo
	)
	
	fileList.append(None)

	while True:
		print(f"\n\t{msg}\n")
		index = 0
		for file in fileList:
			index += 1
			if file == None:
				print(f"\t({index}) - Sair")
			else:
				namefile = file
				if "\\" in namefile:
					i = namefile.rfind("\\")
					namefile = namefile[:i + 1] + "\n\t\t" + namefile[i + 1:]
				print(f"\t({index}) - {namefile} {(maxName - len(file))*' '} | {data_modificacao_arquivo(path+file)}\n")
		try: index = int(input())-1
		except: print("Digite um número")
		if index<0 or index>=len(fileList): print("\n\tOpção inválida\n")
		else:
			if fileList[index] == None: exit()
			return path+fileList[index]

def selecioneOpcaoNaLista(fileList=[],msg='Selecione uma opção',path=''):

	if len(fileList) == 0:
		Aviso("\tNenhum Arquivo encontrado\n",'vermelho')
		if confirmarErro("Y") == 'abort': exit()
		else: return None
	
	#Verifica o tamanho do maior nome dos arquivos
	maxName = max(len(file) for file in fileList if file is not None) if fileList else 0
	
	if len(fileList) == 1:
		namefile = fileList[0]
		if "\\" in namefile:
			i = namefile.rfind("\\")
			namefile = namefile[:i + 1] + "\n\t\t" + namefile[i + 1:]
		print(f"\tSelecionado o arquivo {namefile}\n")
		return path+fileList[0]
	

	# Primeiro ordenamos a lista de arquivos do mais novo para o mais antigo
	fileList = sorted(fileList)
	fileList.append(None)

	while True:
		print(f"\n\t{msg}\n")
		index = 0
		for file in fileList:
			index += 1
			if file == None:
				print(f"\t({index}) - Sair")
			else:
				namefile = file
				if "\\" in namefile:
					i = namefile.rfind("\\")
					namefile = namefile[:i + 1] + "\n\t\t" + namefile[i + 1:]
				print(f"\t({index}) - {namefile} {(maxName - len(file))*' '}\n")
		try: index = int(input())-1
		except: print("Digite um número")
		if index<0 or index>=len(fileList): print("\n\tOpção inválida\n")
		else:
			if fileList[index] == None: exit()
			return path+fileList[index]