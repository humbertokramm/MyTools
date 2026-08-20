import os
import subprocess
import argparse
import requests
import warnings
warnings.filterwarnings("ignore", message="Unverified HTTPS request")
import dirHandle as dh
from pprint import pprint
import shutil
import zipfile
import git
from git import Repo, exc

# Códigos ANSI para cores
RED = '\033[91m'
RESET = '\033[0m'


REPOS_ = 'C:\\Projetos'
# Lê a variável de ambiente
LIBS_ = os.getenv("PYTHONPATH")
print([LIBS_])


def parse_arguments():
    parser = argparse.ArgumentParser(description='Verifica repositórios Git em pastas específicas.')
    parser.add_argument('-f', action='store_true', help=f'Percorre todas as pastas em {REPOS_}')
    return parser.parse_args()

def get_folders(arg_f):
    if arg_f:
        # Retorna todas as pastas em C:\Projetos
        dirs  = [os.path.join(REPOS_, d) for d in os.listdir(REPOS_) if os.path.isdir(os.path.join(REPOS_, d))]
        dirs.append(os.path.normpath(LIBS_))   # append muta a lista e retorna None
        return dirs
    else:
        # Lista de pastas padrão
        return [LIBS_]

def check_folder_exists(folder):
    if not os.path.exists(folder):
        print(f'A pasta {folder} não existe. Pulando...')
        return False
    return True

def display_modified_files(folder):
    # Verifica se há alterações não commitadas
    status_result = subprocess.run(['git', 'status', '--porcelain'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    status_output = status_result.stdout.decode()

    # Lista de arquivos com alterações
    modified_files = [line[3:] for line in status_output.splitlines() if line]  # Ignora linhas vazias

    if modified_files:
        print(f'Existem alterações não commitadas em {folder}:')
        for file in modified_files:
            print(RED + file + RESET)  # Exibe os arquivos em vermelho
        return True
    return False

def check_updates(folder):
    # Verifica se há atualizações pendentes
    subprocess.run(['git', 'fetch'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Compara as branches locais e remotas
    result_diff = subprocess.run(['git', 'status', '-uno'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    # Se houver atualizações, faz o pull
    if "Your branch is behind" in result_diff.stdout.decode() or "Updates to be pulled" in result_diff.stdout.decode():
        print(f'Atualizações encontradas em {folder}. Fazendo pull...')
        pull_result = subprocess.run(['git', 'pull'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(pull_result.stdout.decode())  # Exibe a saída do pull
        return True
    else:
        print(80*' ', end='\r')
        print(f'Nenhuma atualização pendente em {folder}', end='\r')
    return False

def check_and_pull(folder):
    modfi = False
    updat = False
    if check_folder_exists(folder):
        os.chdir(folder)
        modfi = display_modified_files(folder)
        updat = check_updates(folder)
    return modfi or updat


def check_site(url):
    try:
        # Faz uma requisição HEAD, que é mais leve (pega só os cabeçalhos) e desabilita a verificação SSL
        response = requests.head(url, verify=False, allow_redirects=True)
        print(f"O site {url} retornou código de status: {response.status_code}")
        
        # Se a resposta foi um redirecionamento, mostre a URL para onde está redirecionando
        if response.status_code == 302:
            print(f"Redirecionado para: {response.headers['Location']}")
            
    except requests.exceptions.RequestException as e:
        print(f"Erro ao acessar o site: {e}")
        exit()

def list_files(diretorio):
    """
    Verifica se o diretório existe e imprime os arquivos dentro dele.
    
    :param diretorio: caminho da pasta a verificar
    """
    if not os.path.exists(diretorio):
        print(f"O diretório '{diretorio}' não existe.")
        return

    print(f"Arquivos em '{diretorio}':")
    arquivos = os.listdir(diretorio)
    if not arquivos:
        print("  (nenhum arquivo encontrado)")
        return False
    else:
        for arq in arquivos:
            caminho = os.path.join(diretorio, arq)
            if os.path.isfile(caminho):
                print("  ", arq)
        return True

def copy_files(origem, destino, extensoes=None):
    """
    Copia arquivos de 'origem' para 'destino'.
    
    :param origem: diretório de onde os arquivos serão copiados
    :param destino: diretório para onde os arquivos serão copiados
    :param extensoes: tupla/lista de extensões (ex: (".sch", ".schdoc")) ou None para copiar tudo
    """
    if not os.path.exists(destino):
        os.makedirs(destino)  # cria se não existir

    if list_files(destino):
        dh.print_colored('Files above already exist in destination, type "Y/y" to continue', 'YELLOW')
        a = input()
        if a.lower() != 'y':
            return

    for root, _, files in os.walk(origem):
        for f in files:
            if extensoes is None or f.lower().endswith(tuple(extensoes)):
                caminho_origem = os.path.join(root, f)
                caminho_destino = os.path.join(destino, f)
                shutil.copy2(caminho_origem, caminho_destino)
                print(f"Copiado: {caminho_origem}\n\tpara -> {caminho_destino}")


def main():
	holdLoop = True
	while holdLoop:
		check_site("https://gerrit.ped.datacom.net.br")
		hold = False
		args = parse_arguments()
		folders = get_folders(args.f)

		for folder in folders:
				h = check_and_pull(folder)
				if h: hold = True
		a = ''
		if hold: a = input("\n\tPressione ENTER para fechar ou Y/y para checar novamente\n\t")
		if a == '': holdLoop = False

if __name__ == '__main__':
    main()
