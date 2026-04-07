"""
**File: plotcsv.py**

**Descrição**
    Script para plotagem automática de múltiplos arquivos CSV.
    Utiliza csvscope para visualização de dados.

**Funções Principais**

``listar_arquivos_csv()``
    Lista todos os arquivos CSV no diretório atual.
    
    :return: Lista de nomes de arquivos .csv
    :rtype: list

``plota(f)``
    Plota arquivo CSV específico.
    
    :param f: Nome do arquivo CSV
    :type f: str
    
    Canais plotados:
    - ch1: Canal 1
    - ch2: Canal 2

**Fluxo de Execução**
    1. Lista arquivos CSV
    2. Para cada arquivo, cria objeto csvscope
    3. Formata e plota dados
    4. Exibe gráfico

**Dependências**
    - csvscope

See: docs/guia_documentacao.rst
"""

import sys
sys.path.append("C:\\Altium\\scripts")
from csvscope import csvscope
import os

def listar_arquivos_csv():
	# Obtém a lista de todos os arquivos no diretório atual.
	arquivos = os.listdir()

	# Filtra a lista para apenas arquivos .csv.
	arquivos_csv = [arquivo for arquivo in arquivos if arquivo.lower().endswith(".csv")]

	return arquivos_csv

def plota(f):
	CS = csvscope(f) # cria o objeto
	CS.format(f=f,n='ch1')
	CS.format(f=f,n='ch2',c=2)
	CS.plot()	# imprime o gráfico


if __name__ == "__main__":
	arquivos_csv = listar_arquivos_csv()
	for arquivo in arquivos_csv:
		print(arquivo)
		plota(arquivo)

input('pressione ENTER para continuar')