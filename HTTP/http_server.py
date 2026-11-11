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

# Conexoes com a console do equipamento, as mesmas do updateLua.ttl (pasta
# TFTP). SSH nao serve: durante o reset/GRUB/ONIE so a console responde.
#   host/portas : servidor de terminal (ser2net) e portas dele
#   servidor    : IP deste PC que vai na URL quando a descoberta automatica
#                 (ip_servidor) nao acha nenhum -- o do telnet vem do DHCP
#   equip       : IP padrao do equipamento (serial: ponto a ponto fixo). No
#                 telnet e o IP que cada um reservou, digitado na janela.
#   gateway     : rota default no equipamento (None: mesma rede do PC)
CENARIOS = {
    "Serial (PC direto)": {
        "tipo":     "serial",
        "servidor": "192.168.0.15",
        "equip":    "192.168.0.25",
        "mascara":  "255.255.255.0",
        "gateway":  None,
    },
    "Telnet LIEM": {
        "tipo":     "telnet",
        "host":     "172.22.239.100",
        "portas":   [str(p) for p in range(4001, 4009)],
        "servidor": "10.0.120.23",
        "equip":    "",
        "mascara":  "255.255.0.0",
        "gateway":  "172.22.239.1",
    },
    "Telnet Sala 35": {
        "tipo":     "telnet",
        "host":     "172.22.227.201",
        "portas":   [str(p) for p in range(4000, 4008)],
        "servidor": "10.0.120.23",
        "equip":    "",
        "mascara":  "255.255.0.0",
        "gateway":  "172.22.227.254",
    },
}

COM_PADRAO  = "13"
BAUD_PADRAO = "115200"


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


def ip_rota_para(destino):
    """IP local que o Windows usaria para chegar em *destino* (nada e enviado)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect((destino, 80))
            return s.getsockname()[0]
    except OSError:
        return None


def ip_servidor(cen, equip_ip):
    """IP deste PC que o equipamento *equip_ip* alcanca.

    Telnet: o equipamento esta em outra rede, entao vale a interface pela
    qual o PC roteia ate ele -- segue o DHCP sozinho. Serial: a ligacao e
    direta e a placa pode estar sem link; vale o IP local da mesma /24 do
    equipamento. Sem nenhum dos dois, fica o IP fixo do cenario.
    """
    locais = ips_locais()
    if cen["tipo"] == "serial":
        pre = (equip_ip or cen["equip"]).rsplit(".", 1)[0] + "."
        return next((ip for ip in sorted(locais) if ip.startswith(pre)),
                    cen["servidor"])
    # Sem IP do equipamento, o caminho ate o servidor de terminal serve: a
    # rede do equipamento e alcancada pela mesma interface.
    ip = ip_rota_para(equip_ip or cen["host"])
    return ip if ip and ip in locais else cen["servidor"]


# -------------------------------
# servidor HTTP (reiniciavel)
# -------------------------------
class Servidor:
    """Servidor HTTP que pode trocar de porta sem reiniciar o programa.

    Escuta em todas as interfaces (0.0.0.0) de proposito: nos cenarios de
    telnet o equipamento acessa pelo IP corporativo e no serial pelo IP da
    rede direta. Amarrar num IP so obrigaria a reiniciar ao trocar de
    cenario -- e falharia se aquela interface estivesse fora do ar. O IP que
    vai na URL vem de ip_servidor(), nao do bind.
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

TTPMACRO   = r"C:\Program Files\teraterm5\ttpmacro.exe"
MACRO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "auto_install.ttl")


def conexao_teraterm(cen, com=None, baud=None, porta_tel=None):
    """Parametro do 'connect' do TeraTerm, como no updateLua.ttl."""
    if cen["tipo"] == "serial":
        return f"/C={com} /BAUD={baud}"
    return f"{cen['host']} /T=1 /P={porta_tel}"


def gerar_macro(conexao, equip_ip, mascara, gateway, ip_pc, url):
    """Texto da macro: conecta, para no GRUB, entra no ONIE e instala *url*.

    So ASCII: o TeraTerm le a macro na codepage do Windows.
    """
    rota = (f"wait 'ONIE:/ #'\nsendln 'ip route add default via {gateway}'\n"
            if gateway else "")
    return f"""; Gerada pelo http_server.py -- sobrescrita a cada instalacao
connect '{conexao}'
testlink
if result <> 2 then
    messagebox 'Nao conectou: {conexao}' 'ONIE'
    end
endif
dispstr #13#10 '*** Reinicie o equipamento: a macro espera o GRUB' #13#10

wait 'GNU GRUB'
sendln 'c'
sendln 'c'

; o GRUB perde caracteres digitados rapido
wait 'grub>'
str = 'onie_rescue_bootcmd'
strlen str
len = result
for i 1 len
    strcopy str i 1 ch
    send ch
    mpause 30
next
mpause 100
sendln ''

wait 'Please press Enter to activate this console.'
sendln ''

wait 'ONIE:/ #'
sendln 'ifconfig eth0 {equip_ip} netmask {mascara} up'
{rota}
; depois do reset o link leva alguns segundos ate passar trafego. As aspas
; no meio do REDE_FIM evitam casar com o eco do proprio comando.
wait 'ONIE:/ #'
; O laco tem limite proprio: sem ele, se a rede nao subir o shell fica
; preso no until e o onie-nos-install digitado depois nunca roda.
sendln "n=0; until ping -c1 {ip_pc} >/dev/null 2>&1 || [ $n -ge 12 ]; do n=$((n+1)); sleep 1; done; echo REDE_''FIM"
timeout = 600
wait 'REDE_FIM'
timeout = 0
wait 'ONIE:/ #'

sendln 'onie-nos-install {url}'
"""


def executar_macro(texto):
    with open(MACRO_PATH, "w", encoding="ascii", errors="replace", newline="\r\n") as f:
        f.write(texto)
    subprocess.Popen([TTPMACRO, MACRO_PATH])

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
    porta_var = tk.StringVar(
        value=str(porta_ini or cfg.get("porta", PORTA_PADRAO)))
    com_var   = tk.StringVar(value=cfg.get("com", COM_PADRAO))
    baud_var  = tk.StringVar(value=cfg.get("baud", BAUD_PADRAO))
    tel_var   = tk.StringVar()           # porta do servidor de terminal
    equip_var = tk.StringVar()           # IP do equipamento
    # IP do equipamento lembrado por cenario+porta: no telnet cada um usa o
    # IP que reservou, e cada porta e um equipamento.
    ips_equip = cfg.setdefault("ips_equip", {})

    linha_cen = tk.Frame(frame)
    linha_cen.pack(pady=(0, 2))
    tk.Label(linha_cen, text="Conexao:").pack(side="left")
    tk.OptionMenu(linha_cen, cenario_var, *nomes_cenario).pack(side="left")
    tk.Label(linha_cen, text="HTTP:").pack(side="left", padx=(8, 2))
    tk.Entry(linha_cen, textvariable=porta_var, width=6).pack(side="left")
    tk.Button(linha_cen, text="Aplicar",
              command=lambda: aplicar_cenario()).pack(side="left", padx=4)

    # segunda linha: muda conforme serial ou telnet
    linha_con = tk.Frame(frame)
    linha_con.pack(pady=(0, 4))
    f_serial = tk.Frame(linha_con)
    tk.Label(f_serial, text="COM:").pack(side="left")
    tk.Entry(f_serial, textvariable=com_var, width=4).pack(side="left")
    tk.Label(f_serial, text="Baud:").pack(side="left", padx=(6, 2))
    tk.OptionMenu(f_serial, baud_var, "9600", "38400", "57600", "115200").pack(side="left")
    f_tel = tk.Frame(linha_con)
    host_lbl = tk.Label(f_tel, text="")
    host_lbl.pack(side="left")
    tk.Label(f_tel, text="Porta:").pack(side="left", padx=(6, 2))
    tel_menu = tk.OptionMenu(f_tel, tel_var, "")
    tel_menu.pack(side="left")
    f_ip = tk.Frame(linha_con)
    f_ip.pack(side="left")
    tk.Label(f_ip, text="IP do equip:").pack(side="left", padx=(10, 2))
    equip_entry = tk.Entry(f_ip, textvariable=equip_var, width=15)
    equip_entry.pack(side="left")
    dica_ip = tk.Label(f_ip, text="(o seu, reservado)", fg="gray")

    # info servidor
    info = tk.Label(frame, text="")
    info.pack(pady=(0, 10))

    def cen_atual():
        return CENARIOS[cenario_var.get()]

    def chave_equip():
        cen = cen_atual()
        return (cenario_var.get() if cen["tipo"] == "serial"
                else f"{cen['host']}:{tel_var.get()}")

    def ip_equip():
        return equip_var.get().strip()

    def _carrega_ip_equip(*_):
        equip_var.set(ips_equip.get(chave_equip(), cen_atual()["equip"]))

    def _guarda_ip_equip(*_):
        ips_equip[chave_equip()] = ip_equip()
        save_config(cfg)
        aplicar_cenario()

    equip_entry.bind("<FocusOut>", _guarda_ip_equip)
    equip_entry.bind("<Return>", _guarda_ip_equip)

    def _monta_conexao():
        """Mostra COM/baud ou servidor/porta e refaz a lista de portas."""
        cen = cen_atual()
        f_serial.pack_forget()
        f_tel.pack_forget()
        if cen["tipo"] == "serial":
            f_serial.pack(side="left", before=f_ip)
            dica_ip.pack_forget()
        else:
            host_lbl.config(text=f"Servidor: {cen['host']}")
            menu = tel_menu["menu"]
            menu.delete(0, "end")
            for p in cen["portas"]:
                menu.add_command(label=p, command=lambda v=p: tel_var.set(v))
            salva = cfg.get("portas_tel", {}).get(cenario_var.get())
            tel_var.set(salva if salva in cen["portas"] else cen["portas"][0])
            f_tel.pack(side="left", before=f_ip)
            dica_ip.pack(side="left", padx=4)
        _carrega_ip_equip()

    def _troca_porta_tel(*_):
        cfg.setdefault("portas_tel", {})[cenario_var.get()] = tel_var.get()
        _carrega_ip_equip()
        aplicar_cenario()

    def aplicar_cenario():
        """Aplica cenario e porta HTTP: religa o servidor e refaz a lista."""
        cen = cen_atual()
        try:
            porta = int(porta_var.get())
        except ValueError:
            info.config(text="Porta invalida", fg="red")
            return

        if servidor.porta != porta:
            try:
                servidor.start(porta)
            except OSError as e:
                info.config(text=f"Nao foi possivel abrir a porta {porta}: {e}",
                            fg="red")
                return

        # Avisa se o IP nao existe nesta maquina -- so acontece quando a
        # descoberta caiu no IP fixo do cenario (cabo fora, VPN caida).
        ip = ip_servidor(cen, ip_equip())
        if not ip_equip():
            info.config(text=f"Servidor: http://{ip}:{porta}  "
                             f"(informe o IP do equipamento)", fg="red")
        elif ip in ips_locais():
            info.config(text=f"Servidor: http://{ip}:{porta}", fg="green")
        else:
            info.config(text=f"Servidor: http://{ip}:{porta}  "
                             f"(IP nao encontrado nesta maquina)", fg="red")

        cfg["cenario"] = cenario_var.get()
        cfg["porta"] = porta
        cfg["com"] = com_var.get()
        cfg["baud"] = baud_var.get()
        save_config(cfg)
        atualizar_lista()

    def _troca_cenario(*_):
        _monta_conexao()
        aplicar_cenario()

    cenario_var.trace_add("write", _troca_cenario)
    _monta_conexao()
    tel_var.trace_add("write", _troca_porta_tel)

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

        if not arquivos:
            tk.Label(lista_frame, text="Nenhuma imagem .bin na pasta; use Atualizar.",
                     fg="gray").pack()

        for arquivo in arquivos:
            linha = tk.Frame(lista_frame)
            linha.pack(fill="x", pady=2)
            tk.Button(linha, text="Instalar (TeraTerm)",
                      command=lambda a=arquivo: instalar(a)).pack(side="left")
            tk.Label(linha, text=arquivo, anchor="w").pack(side="left", padx=6)

    def instalar(arquivo):
        """Gera a macro com a conexao e a rede atuais e abre o TeraTerm."""
        cen = cen_atual()
        equip = ip_equip()
        if not equip:
            info.config(text="Informe o IP do equipamento antes de instalar", fg="red")
            return
        ip_pc = ip_servidor(cen, equip)
        url = f"http://{ip_pc}:{servidor.porta}/{arquivo}"
        con = conexao_teraterm(cen, com_var.get().strip(), baud_var.get(),
                               tel_var.get())
        try:
            executar_macro(gerar_macro(con, equip, cen["mascara"],
                                       cen["gateway"], ip_pc, url))
        except OSError as e:
            info.config(text=f"Erro ao abrir o TeraTerm: {e}", fg="red")
            return
        info.config(text=f"Macro aberta ({con}): reinicie o equipamento. "
                         f"Instala {url}", fg="green")

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