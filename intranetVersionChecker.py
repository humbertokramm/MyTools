import urllib.request
import re
import os
import ssl


# -------------------------------
# montar URL
# -------------------------------
def build_url(tipo, projeto):

    projeto = str(projeto)

    if tipo.upper() == "FT":
        return f"https://builds.ped.datacom.net.br/nightly/pd{projeto}_ft/images/"

    elif tipo.upper() == "DMOS":
        return f"https://buildroot.ped.datacom.net.br/buildroot/images/pd{projeto}/"

    else:
        raise ValueError("Tipo deve ser 'FT' ou 'DMOS'")


# -------------------------------
# obter .bin remoto
# -------------------------------
def get_remote_bins(tipo, projeto):

    url = build_url(tipo, projeto)

    try:
        context = ssl._create_unverified_context()

        response = urllib.request.urlopen(url, timeout=5, context=context)
        html = response.read().decode()

        arquivos = re.findall(r'href="([^"]+\.bin)"', html)

        return sorted(arquivos)

    except Exception as e:
        print("Erro ao acessar servidor:", e)
        return []


# -------------------------------
# pegar mais recente
# -------------------------------
def get_latest_remote(tipo, projeto):

    arquivos = get_remote_bins(tipo, projeto)

    if not arquivos:
        return None

    return arquivos[-1]


# -------------------------------
# arquivos locais
# -------------------------------
def get_local_bins(path=".", projeto=None):

    arquivos = [
        f for f in os.listdir(path)
        if os.path.isfile(os.path.join(path, f))
        and f.lower().endswith(".bin")
    ]

    # opcional: filtrar por projeto
    if projeto:
        arquivos = [f for f in arquivos if f"pd{projeto}" in f]

    return arquivos


# -------------------------------
# verificar atualização
# -------------------------------
def check_update(tipo, projeto, path="."):

    remoto = get_latest_remote(tipo, projeto)

    if not remoto:
        return "ERROR", None

    locais = get_local_bins(path, projeto)

    if remoto in locais:
        return "OK", remoto
    else:
        return "UPDATE", remoto


# -------------------------------
# atualizar (download + limpeza)
# -------------------------------
def update_local(tipo, projeto, path="."):

    url_base = build_url(tipo, projeto)
    nome = get_latest_remote(tipo, projeto)

    if not nome:
        print("Erro ao obter versão remota")
        return False

    locais = get_local_bins(path, projeto)

    if nome in locais:
        print("Já atualizado:", nome)
        return True

    url = url_base + nome
    destino = os.path.join(path, nome)

    print("Baixando:", nome)

    try:
        context = ssl._create_unverified_context()

        with urllib.request.urlopen(url, context=context) as response, open(destino, 'wb') as f:
            f.write(response.read())

        print("Download concluído")

    except Exception as e:
        print("Erro no download:", e)
        return False

    # remover versões antigas
    for f in locais:
        if f != nome:
            try:
                os.remove(os.path.join(path, f))
                print("Removido:", f)
            except Exception as e:
                print("Erro ao remover:", f, e)

    return True


# -------------------------------
# teste standalone
# -------------------------------
if __name__ == "__main__":

    tipo = "FT"      # ou "DMOS"
    #tipo = "DMOS"
    projeto = "4201"

    status, arquivo = check_update(tipo, projeto)

    if status == "OK":
        print("✔ Atualizado:", arquivo)

    elif status == "UPDATE":
        print("⚠ Nova versão:", arquivo)
        update_local(tipo, projeto)

    else:
        print("✖ Erro")