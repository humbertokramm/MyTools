import sys
import os
import threading
import tkinter as tk
from http.server import SimpleHTTPRequestHandler, HTTPServer

from intranetVersionChecker import check_update, update_local


# -------------------------------
# servidor HTTP
# -------------------------------
def run_server(IP, PORT):
    Handler = SimpleHTTPRequestHandler
    httpd = HTTPServer((IP, PORT), Handler)

    print("running server...")
    print("IP:", IP, "| Port:", PORT)

    httpd.handle_request()

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

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    # info servidor
    info = tk.Label(frame, text=f"Servidor: http://{IP}:{PORT}")
    info.pack(pady=(0, 10))

    # ---------------- configuração ----------------
    tipo_var = tk.StringVar(value="FT")
    projeto_var = tk.StringVar(value="4201")

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

    # botões
    tk.Button(frame, text="Verificar versão", command=verificar_versao).pack(pady=2)
    tk.Button(frame, text="Atualizar", command=atualizar).pack(pady=2)

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
            def criar_linha(texto):

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

            # cria as 3 linhas
            criar_linha(cmd_rescue)
            criar_linha(cmd_ifconfig)
            criar_linha(cmd_install)

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