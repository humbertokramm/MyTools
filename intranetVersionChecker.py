import urllib.request
import urllib.parse
import re
import os
import ssl


FPGA_LIST_URL = (
    "https://jenkins.ped.datacom.net.br"
    "/job/+develop_doc+dm-sw-lp/Module_documentation/logic_list.html"
)


# -------------------------------
# FPGA — listar releases remotos
# -------------------------------
def get_fpga_releases(projeto):
    """Retorna lista de arquivos .zip release para o projeto FPGA dado.

    Filtra apenas entradas com 'release' no nome, ordena pelo campo de
    data embutido (YY-MM-DD) e retorna do mais antigo ao mais recente.
    """
    projeto = str(projeto).lstrip("pPdD")   # aceita "3407" ou "pd3407"

    try:
        context = ssl._create_unverified_context()
        response = urllib.request.urlopen(FPGA_LIST_URL, timeout=10, context=context)
        html = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        print("Erro ao acessar Jenkins FPGA:", e)
        return []

    # Extrai todos os hrefs que apontam para .zip do projeto
    hrefs = re.findall(r'href="([^"]*pd' + projeto + r'[^"]*\.zip)"', html, re.IGNORECASE)

    # Mantém só os releases
    releases = [h for h in hrefs if "release" in h.lower()]

    # Resolve cada href para URL absoluta + extrai nome do arquivo
    entries = {}
    for href in releases:
        url = urllib.parse.urljoin(FPGA_LIST_URL, href)
        name = os.path.basename(urllib.parse.urlparse(url).path)
        entries[name] = url   # dedup por nome, mantém última URL

    # Ordena pelo campo de data no nome: ..._release_NN_YY-MM-DD_HHhMMmin.zip
    def _sort_key(name):
        m = re.search(r'(\d{2}-\d{2}-\d{2}_\d{2}h\d{2})', name)
        return m.group(1) if m else name

    return [(n, entries[n]) for n in sorted(entries, key=_sort_key)]


def get_latest_fpga(projeto):
    """Retorna (filename, url) do release mais recente para o projeto FPGA."""
    releases = get_fpga_releases(projeto)
    return releases[-1] if releases else None


# -------------------------------
# FPGA — verificar atualização
# -------------------------------
def check_fpga_update(projeto, path="."):
    """Verifica se o release mais recente já está baixado localmente.

    Returns:
        ("OK",     filename)  — já atualizado
        ("UPDATE", filename)  — há versão mais nova disponível
        ("ERROR",  None)      — falha ao acessar o servidor
    """
    entry = get_latest_fpga(projeto)
    if not entry:
        return "ERROR", None

    nome_zip, _ = entry
    nome_rbf = os.path.splitext(nome_zip)[0] + ".rbf"

    locais_rbf = [f for f in os.listdir(path) if f.lower().endswith(".rbf")]
    if nome_rbf in locais_rbf:
        return "OK", nome_rbf
    return "UPDATE", nome_rbf


# -------------------------------
# FPGA — baixar e limpar antigos
# -------------------------------
def update_fpga_local(projeto, path="."):
    """Baixa o release FPGA mais recente, extrai o .rbf e remove arquivos antigos."""
    import zipfile

    projeto_norm = str(projeto).lstrip("pPdD")
    entry = get_latest_fpga(projeto_norm)

    if not entry:
        print("Erro ao obter versão FPGA remota")
        return False

    nome, url = entry
    nome_base = os.path.splitext(nome)[0]   # ex: pd3407f00_0x0A_cyc10lp_release_03_...
    nome_rbf  = nome_base + ".rbf"

    locais_zip = [f for f in os.listdir(path) if f.lower().endswith(".zip")]
    locais_rbf = [f for f in os.listdir(path) if f.lower().endswith(".rbf")]

    # Se o .rbf final já existe, não precisa baixar de novo
    if nome_rbf in locais_rbf:
        print("FPGA já atualizado:", nome_rbf)
        return True

    # Baixa o zip
    destino_zip = os.path.join(path, nome)
    if nome not in locais_zip:
        print("Baixando FPGA:", nome)
        try:
            context = ssl._create_unverified_context()
            with urllib.request.urlopen(url, timeout=60, context=context) as resp, \
                 open(destino_zip, "wb") as f:
                f.write(resp.read())
            print("Download FPGA concluído")
        except Exception as e:
            print("Erro no download FPGA:", e)
            return False

    # Extrai o .rbf com o mesmo nome base do zip
    print("Extraindo:", nome_rbf)
    try:
        with zipfile.ZipFile(destino_zip) as zf:
            # Localiza o membro correto (pode estar numa subpasta dentro do zip)
            membros = [m for m in zf.namelist() if os.path.basename(m) == nome_rbf]
            if not membros:
                print(f"Arquivo {nome_rbf} não encontrado dentro do zip")
                return False
            membro = membros[0]
            # Extrai direto para path sem recriar subpastas
            data = zf.read(membro)
            with open(os.path.join(path, nome_rbf), "wb") as f:
                f.write(data)
        print("Extração concluída:", nome_rbf)
    except Exception as e:
        print("Erro na extração:", e)
        return False

    # Remove .zip e .rbf antigos do mesmo projeto
    for f in locais_zip:
        if f"pd{projeto_norm}" in f.lower():
            try:
                os.remove(os.path.join(path, f))
                print("Removido:", f)
            except Exception as e:
                print("Erro ao remover:", f, e)

    for f in locais_rbf:
        if f"pd{projeto_norm}" in f.lower() and f != nome_rbf:
            try:
                os.remove(os.path.join(path, f))
                print("Removido:", f)
            except Exception as e:
                print("Erro ao remover:", f, e)

    return True


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