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

TFTP_DIR        = r"C:\Testes\TFTP"
TFTP_LP_RBF     = os.path.join(TFTP_DIR, "LP.rbf")
INSTALL_LUA_BAT = os.path.join(TFTP_DIR, "install Lua.bat")

PORTA_PADRAO = 8081

# Cenarios de conexao, espelhando as opcoes do updateLua.ttl (pasta TFTP).
#   servidor : IP deste PC que o equipamento enxerga -- e o que vai na URL
#   gateway  : rota default a configurar no equipamento
#   equip    : IPs a atribuir ao equipamento (um por slot/porta do terminal
#              server; no caso serial so existe um)
CENARIOS = {
    "Serial (PC direto)": {
        "servidor": "192.168.0.15",
        "gateway":  "192.168.0.15",
        "equip":    ["192.168.0.25"],
    },
    "Telnet LIEM": {
        "servidor": "10.0.120.23",
        "gateway":  "172.22.239.1",
        "equip":    [f"172.22.239.{n}" for n in range(51, 59)],
    },
    "Telnet Sala 35": {
        "servidor": "10.0.120.23",
        "gateway":  "172.22.227.254",
        "equip":    [f"172.22.227.{n}" for n in range(51, 59)],
    },
}


def ips_locais():
    """IPv4 configurados nesta maquina, para conferir o IP do cenario."""
    import socket
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    return ips


# -------------------------------
# servidor HTTP (reiniciavel)
# -------------------------------
class Servidor:
    """Servidor HTTP que pode trocar de porta sem reiniciar o programa.

    Escuta em todas as interfaces (0.0.0.0) de proposito: nos cenarios de
    telnet o equipamento acessa pelo IP corporativo e no serial pelo IP da
    rede direta. Amarrar num IP so obrigaria a reiniciar ao trocar de
    cenario -- e falharia se aquela interface estivesse fora do ar. O IP que
    vai na URL vem do cenario, nao do bind.
    """

    def __init__(self):
        self.httpd = None
        self.porta = None

    def start(self, porta):
        self.stop()
        self.httpd = HTTPServer(("", porta), SimpleHTTPRequestHandler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.porta = porta
        print(f"servidor ouvindo em 0.0.0.0:{porta}")

    def stop(self):
        if self.httpd is not None:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None

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
# GUI
# -------------------------------
def start_gui(servidor, cenario_ini=None, porta_ini=None):

    # ---------------- GUI ----------------
    root = tk.Tk()
    root.title("ONIE Install Links")

    cfg = load_config()

    frame = tk.Frame(root)
    frame.pack(padx=10, pady=10)

    # ---------------- cenario de conexao ----------------
    nomes_cenario = list(CENARIOS)
    cenario_var = tk.StringVar(
        value=cenario_ini or cfg.get("cenario", nomes_cenario[0]))
    if cenario_var.get() not in CENARIOS:
        cenario_var.set(nomes_cenario[0])
    slot_var  = tk.StringVar()
    porta_var = tk.StringVar(
        value=str(porta_ini or cfg.get("porta", PORTA_PADRAO)))

    linha_cen = tk.Frame(frame)
    linha_cen.pack(pady=(0, 4))
    tk.Label(linha_cen, text="Conexao:").pack(side="left")
    tk.OptionMenu(linha_cen, cenario_var, *nomes_cenario).pack(side="left")

    tk.Label(linha_cen, text="Equip:").pack(side="left", padx=(8, 2))
    slot_menu = tk.OptionMenu(linha_cen, slot_var, "")
    slot_menu.pack(side="left")

    tk.Label(linha_cen, text="Porta:").pack(side="left", padx=(8, 2))
    tk.Entry(linha_cen, textvariable=porta_var, width=6).pack(side="left")
    tk.Button(linha_cen, text="Aplicar",
              command=lambda: aplicar_cenario()).pack(side="left", padx=4)

    # info servidor
    info = tk.Label(frame, text="")
    info.pack(pady=(0, 10))

    def cen_atual():
        return CENARIOS[cenario_var.get()]

    def ip_equip():
        return slot_var.get() or cen_atual()["equip"][0]

    def _popular_slots():
        """Refaz a lista de IPs de equipamento do cenario selecionado."""
        equip = cen_atual()["equip"]
        menu = slot_menu["menu"]
        menu.delete(0, "end")
        for ip in equip:
            menu.add_command(label=ip,
                             command=lambda v=ip: (slot_var.set(v),
                                                   atualizar_lista()))
        if slot_var.get() not in equip:
            slot_var.set(equip[0])

    def aplicar_cenario():
        """Aplica cenario e porta: religa o servidor e refaz os comandos."""
        cen = cen_atual()
        try:
            porta = int(porta_var.get())
        except ValueError:
            info.config(text="Porta invalida", fg="red")
            return

        _popular_slots()

        if servidor.porta != porta:
            try:
                servidor.start(porta)
            except OSError as e:
                info.config(text=f"Nao foi possivel abrir a porta {porta}: {e}",
                            fg="red")
                return

        # Avisa se o IP do cenario nao existe nesta maquina -- costuma ser
        # cabo fora, VPN caida ou IP trocado pelo DHCP.
        ip = cen["servidor"]
        if ip in ips_locais():
            info.config(text=f"Servidor: http://{ip}:{porta}", fg="green")
        else:
            info.config(text=f"Servidor: http://{ip}:{porta}  "
                             f"(IP nao encontrado nesta maquina)", fg="red")

        cfg["cenario"] = cenario_var.get()
        cfg["porta"] = porta
        save_config(cfg)
        atualizar_lista()

    cenario_var.trace_add("write", lambda *_: aplicar_cenario())

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

        def task():
            status, arquivo = check_update(tipo, projeto)

            if status == "OK":
                status_version.config(text=f"Atualizado: {arquivo}", fg="green")
            elif status == "UPDATE":
                status_version.config(text=f"Novo disponível: {arquivo}", fg="orange")
            else:
                status_version.config(text="Erro ao verificar", fg="red")

            atualizar_lista()

        threading.Thread(target=task, daemon=True).start()

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
            atualizar_lista()
        threading.Thread(target=task, daemon=True).start()

    def atualizar_fpga():
        projeto = fpga_var.get()
        status_fpga.config(text="Baixando...", fg="black")
        def task():
            sucesso = update_fpga_local(projeto)
            if sucesso:
                status_fpga.config(text="FPGA atualizado | LP.rbf → TFTP", fg="green")
                atualizar_lista()
            else:
                status_fpga.config(text="Erro no download FPGA", fg="red")
        threading.Thread(target=task, daemon=True).start()

    def macro_install_lp():
        """Dispara o 'install Lua.bat' do TFTP (abre Tftpd64 + macro TeraTerm)."""
        if not os.path.exists(TFTP_LP_RBF):
            status_fpga.config(text="LP.rbf nao encontrado no TFTP", fg="red")
            return
        if not os.path.exists(INSTALL_LUA_BAT):
            status_fpga.config(text="install Lua.bat nao encontrado", fg="red")
            return
        try:
            # CREATE_NO_WINDOW: o bat roda oculto (sem console piscando).
            # O Tftpd64 e o TeraTerm sao lancados por 'start' dentro do bat,
            # entao abrem normalmente como janelas proprias.
            subprocess.Popen(
                ["cmd", "/c", INSTALL_LUA_BAT],
                cwd=os.path.dirname(INSTALL_LUA_BAT),
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            status_fpga.config(text="Macro Install LP disparada", fg="green")
        except Exception as e:
            status_fpga.config(text=f"Erro ao disparar macro: {e}", fg="red")

    tk.Button(frame, text="Verificar FPGA", command=verificar_fpga).pack(pady=2)

    linha_btn_fpga = tk.Frame(frame)
    linha_btn_fpga.pack(pady=2)
    tk.Button(linha_btn_fpga, text="Atualizar FPGA",
              command=atualizar_fpga).pack(side="left", padx=2)
    tk.Button(linha_btn_fpga, text="Macro Install LP",
              command=macro_install_lp).pack(side="left", padx=2)

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
            if os.path.isfile(f) and f.lower().endswith(".bin") and f != "latest.bin"
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

            # comandos, montados a partir do cenario selecionado
            cen = cen_atual()
            cmd_rescue   = "onie_rescue_bootcmd"
            cmd_ifconfig = (f"ifconfig eth0 {ip_equip()} "
                            f"netmask 255.255.255.0 up")
            cmd_route    = f"ip route add default via {cen['gateway']}"
            cmd_install  = (f"onie-nos-install "
                            f"http://{cen['servidor']}:{servidor.porta}/{arquivo}")

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
                        command=lambda: executar_macro(
                            "latest.bin", cen_atual()["servidor"], servidor.porta)
                    ).pack(side="left", padx=5)

            # cria as linhas do procedimento, na ordem de execucao
            criar_linha(cmd_rescue)
            criar_linha(cmd_ifconfig)
            criar_linha(cmd_route)
            criar_linha(cmd_install, is_install=True)

    # inicializa cenario, servidor e lista
    aplicar_cenario()

    root.mainloop()
    servidor.stop()


# -------------------------------
# MAIN
# -------------------------------
# O cenario e a porta sao escolhidos na janela e ficam salvos no config, por
# isso nao ha mais argumento obrigatorio. Opcionalmente da para abrir ja num
# cenario/porta:  python http_server.py "Telnet LIEM" 80
if __name__ == "__main__":
    cenario_ini = sys.argv[1] if len(sys.argv) > 1 else None
    porta_ini = None
    if len(sys.argv) > 2:
        try:
            porta_ini = int(sys.argv[2])
        except ValueError:
            print("Valor da porta deve ser numero.")
            sys.exit(1)

    if cenario_ini is not None and cenario_ini not in CENARIOS:
        print(f'Cenario desconhecido: "{cenario_ini}"')
        print("Disponiveis: " + " | ".join(CENARIOS))
        sys.exit(1)

    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # serve a pasta HTTP

    servidor = Servidor()
    try:
        start_gui(servidor, cenario_ini, porta_ini)
    finally:
        servidor.stop()