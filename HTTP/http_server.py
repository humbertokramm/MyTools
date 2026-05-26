import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import threading
import tkinter as tk
from http.server import SimpleHTTPRequestHandler, HTTPServer
import subprocess
from intranetVersionChecker import check_update, update_local, check_fpga_update, update_fpga_local

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "http_server_config.json")

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(data):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass



# -------------------------------
# Macro do teraterm
# -------------------------------

def executar_macro(arquivo,IP,PORT):

    install_cmd = f"onie-nos-install http://{IP}:{PORT}/{arquivo}"

    with open("insertImage.ttl", "r") as f:
        conteudo = f.read()

    conteudo = conteudo.replace("INSTALL_CMD", install_cmd)

    macro_path = "C:\\Testes\\MyTools\\HTTP\\auto_install.ttl"

    with open(macro_path, "w") as f:
        f.write(conteudo)

    # caminho do ttermpro (ajusta se necessário)
    tterm = r"C:\\Program Files\\teraterm5\\ttpmacro.exe"

    subprocess.Popen([tterm, macro_path, "13", "115200"])

# -------------------------------
# servidor HTTP
# -------------------------------
def run_server(IP, PORT):
    Handler = SimpleHTTPRequestHandler
    httpd = HTTPServer((IP, PORT), Handler)

    print("running server...")
    print("IP:", IP, "| Port:", PORT)

    #httpd.handle_request()
    httpd.serve_forever()

    print("server stopped...")
    exit()


# -------------------------------
# GUI
# -------------------------------
def start_gui(IP, PORT):

    BASE_LINK = f"onie-nos-install http://{IP}:{PORT}/"

    def copiar_link(nome_arquivo):

        link = BASE_LINK + nome_arquivo

        root.clipboard_clear()
        root.clipboard_append(link)
        root.update()

        print("Copiado:", link)

    # ---------------- GUI ----------------
    root = tk.Tk()
    root.title("ONIE Install Links")

    cfg = load_config()

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    # info servidor
    info = tk.Label(frame, text=f"Servidor: http://{IP}:{PORT}")
    info.pack(pady=(0, 10))

    # ---------------- configuração firmware ----------------
    tipo_var = tk.StringVar(value=cfg.get("tipo", "FT"))
    projeto_var = tk.StringVar(value=cfg.get("projeto", "4201"))

    linha_config = tk.Frame(frame)
    linha_config.pack(pady=5)

    tk.Label(linha_config, text="Tipo:").pack(side="left")
    tk.OptionMenu(linha_config, tipo_var, "FT", "DMOS").pack(side="left")

    tk.Label(linha_config, text="Projeto:").pack(side="left")
    tk.Entry(linha_config, textvariable=projeto_var, width=6).pack(side="left")

    # ---------------- status versão ----------------
    status_version = tk.Label(frame, text="Status: aguardando")
    status_version.pack(pady=5)

    # ---------------- funções ----------------
    def _save_fw_config(*_):
        cfg["tipo"] = tipo_var.get()
        cfg["projeto"] = projeto_var.get()
        save_config(cfg)

    tipo_var.trace_add("write", _save_fw_config)
    projeto_var.trace_add("write", _save_fw_config)

    def verificar_versao():

        tipo = tipo_var.get()
        projeto = projeto_var.get()

        status_version.config(text="Verificando...")

        status, arquivo = check_update(tipo, projeto)

        if status == "OK":
            status_version.config(text=f"Atualizado: {arquivo}", fg="green")

        elif status == "UPDATE":
            status_version.config(text=f"Novo disponível: {arquivo}", fg="orange")

        else:
            status_version.config(text="Erro ao verificar", fg="red")

    def atualizar():

        tipo = tipo_var.get()
        projeto = projeto_var.get()

        

        def task():
            sucesso = update_local(tipo, projeto)

            if sucesso:
                status_version.config(text=f"Atualizado com sucesso", fg="green")
                atualizar_lista()  # refresh lista
            else:
                status_version.config(text="Erro no download", fg="red")

        threading.Thread(target=task, daemon=True).start()

    # botões firmware
    tk.Button(frame, text="Verificar versão", command=verificar_versao).pack(pady=2)
    tk.Button(frame, text="Atualizar", command=atualizar).pack(pady=2)

    # ---------------- separador ----------------
    tk.Frame(frame, height=1, bg="gray").pack(fill="x", pady=8)

    # ---------------- configuração FPGA ----------------
    tk.Label(frame, text="FPGA", font=("", 9, "bold")).pack()

    fpga_var = tk.StringVar(value=cfg.get("fpga_projeto", "3407"))

    linha_fpga = tk.Frame(frame)
    linha_fpga.pack(pady=3)
    tk.Label(linha_fpga, text="Projeto FPGA:").pack(side="left")
    fpga_entry = tk.Entry(linha_fpga, textvariable=fpga_var, width=6)
    fpga_entry.pack(side="left")

    status_fpga = tk.Label(frame, text="Status: aguardando")
    status_fpga.pack(pady=3)

    def _save_fpga_projeto(*_):
        cfg["fpga_projeto"] = fpga_var.get()
        save_config(cfg)

    fpga_entry.bind("<FocusOut>", _save_fpga_projeto)
    fpga_entry.bind("<Return>", _save_fpga_projeto)

    def verificar_fpga():
        projeto = fpga_var.get()
        status_fpga.config(text="Verificando...", fg="black")
        def task():
            status, arquivo = check_fpga_update(projeto)
            if status == "OK":
                status_fpga.config(text=f"Atualizado: {arquivo}", fg="green")
            elif status == "UPDATE":
                status_fpga.config(text=f"Novo disponível: {arquivo}", fg="orange")
            else:
                status_fpga.config(text="Erro ao verificar", fg="red")
        threading.Thread(target=task, daemon=True).start()

    def atualizar_fpga():
        projeto = fpga_var.get()
        status_fpga.config(text="Baixando...", fg="black")
        def task():
            sucesso = update_fpga_local(projeto)
            if sucesso:
                status_fpga.config(text="FPGA atualizado", fg="green")
                atualizar_lista()
            else:
                status_fpga.config(text="Erro no download FPGA", fg="red")
        threading.Thread(target=task, daemon=True).start()

    tk.Button(frame, text="Verificar FPGA", command=verificar_fpga).pack(pady=2)
    tk.Button(frame, text="Atualizar FPGA", command=atualizar_fpga).pack(pady=2)

    # ---------------- separador ----------------
    tk.Frame(frame, height=1, bg="gray").pack(fill="x", pady=8)

    # ---------------- lista de arquivos ----------------
    lista_frame = tk.Frame(frame)
    lista_frame.pack(pady=10)

    def atualizar_lista():

        for widget in lista_frame.winfo_children():
            widget.destroy()

        arquivos = sorted(
            f for f in os.listdir(".")
            if os.path.isfile(f) and f.lower().endswith(".bin")
        )

        for arquivo in arquivos:

            bloco = tk.Frame(lista_frame)
            bloco.pack(fill="x", pady=6)

            # nome do arquivo
            label = tk.Label(bloco, text=arquivo, anchor="w")
            label.pack(anchor="w")

            def copiar(texto):
                root.clipboard_clear()
                root.clipboard_append(texto)
                root.update()
                print("Copiado:", texto)

            # comandos
            cmd_rescue = "onie_rescue_bootcmd"
            cmd_ifconfig = f"ifconfig eth0 192.168.0.25 netmask 255.255.255.0 up"
            cmd_install = BASE_LINK + arquivo

            # função helper pra linha
            def criar_linha(texto, is_install=False):

                linha = tk.Frame(bloco)
                linha.pack(anchor="w", pady=1)

                tk.Button(
                    linha,
                    text="Copiar",
                    command=lambda t=texto: copiar(t),
                    width=8
                ).pack(side="left")

                tk.Label(
                    linha,
                    text=texto,
                    anchor="w"
                ).pack(side="left", padx=5)

                # 🔥 botão novo
                if is_install:
                    tk.Button(
                        linha,
                        text="Auto (TeraTerm)",
                        command=lambda a=arquivo: executar_macro(a,host,porta)
                    ).pack(side="left", padx=5)

            # cria as 3 linhas
            criar_linha(cmd_rescue)
            criar_linha(cmd_ifconfig)
            criar_linha(cmd_install, is_install=True)

    # inicializa lista
    atualizar_lista()

    root.mainloop()


# -------------------------------
# MAIN
# -------------------------------
class Error(Exception):
    pass


try:
    if len(sys.argv) == 3:

        host = sys.argv[1]
        porta = int(sys.argv[2])

        threading.Thread(
            target=run_server,
            args=(host, porta),
            daemon=True
        ).start()

        start_gui(host, porta)

    else:
        raise Error

except Error:
    print(f"Uso: python {sys.argv[0]} <ip> <porta>")
    print(f"Ex: python {sys.argv[0]} 192.168.0.15 8081")

except ValueError:
    print("Valor da porta deve ser número.")