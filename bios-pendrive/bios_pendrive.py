"""BIOS Pendrive - copia os arquivos de BIOS de um pendrive modelo para o PC e
grava pendrives novos a partir do PC, com o equipamento DmOS baixando via TFTP.

Sem argumentos abre a interface gráfica. Linha de comando:
    bios_pendrive.exe info   --ssh 172.22.239.56
    bios_pendrive.exe backup --telnet 172.22.239.100:4006 --tftp-ip 10.0.120.23 --dir C:\\bios
    bios_pendrive.exe write  --serial COM3 --tftp-ip 10.0.120.23 --dir C:\\bios --yes
"""

import argparse
import ctypes
import json
import os
import queue
import socket
import sys
import threading
import time
import traceback

import device
from tftpserver import TftpServer, TftpError

APP_NAME = "BIOS Pendrive"
VERSION = "1.0.0"

# IP configurado na interface do equipamento na ligacao ponto a ponto por
# serial. Mesmo valor usado nas macros do TeraTerm e no http_server.
EQUIP_IP_PADRAO = "192.168.0.25"


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


DEFAULT_DIR = os.path.join(app_dir(), "arquivos_pendrive")
CONFIG_PATH = os.path.join(os.environ.get("APPDATA", app_dir()), "BiosPendrive", "config.json")
LOG_PATH = os.path.join(app_dir(), "bios_pendrive.log")


# =========================================================================
# Utilitários de PC
# =========================================================================
def local_ipv4s():
    """[(ip, nome_da_interface)] das interfaces IPv4 ativas."""
    res = []
    try:
        import psutil

        stats = psutil.net_if_stats()
        for name, addrs in psutil.net_if_addrs().items():
            if name in stats and not stats[name].isup:
                continue
            for a in addrs:
                if a.family == socket.AF_INET and not a.address.startswith(("127.", "169.254.")):
                    res.append((a.address, name))
    except ImportError:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not ip.startswith("127."):
                res.append((ip, ""))
    return res


def wait_local_ip(ip, timeout=25, log=print):
    """Espera um IP aparecer nas interfaces do PC.

    Depois que a interface do equipamento sobe, a placa do PC ainda leva
    alguns segundos para negociar o link e o Windows reativar o IP.
    """
    fim = time.monotonic() + timeout
    while time.monotonic() < fim:
        if any(a == ip for a, _ in local_ipv4s()):
            return True
        time.sleep(1)
    return False


def ip_same_subnet(ref):
    """IP local no mesmo /24 de *ref*, ou None."""
    pre = ref.rsplit(".", 1)[0] + "."
    return next((a for a, _ in local_ipv4s() if a.startswith(pre)), None)


def route_ip_to(host):
    """IP local que o Windows usaria para chegar em host (sem enviar nada)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((socket.gethostbyname(host), 69))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return None


def serial_ports():
    try:
        from serial.tools import list_ports

        return [(p.device, p.description) for p in sorted(list_ports.comports(), key=lambda p: p.device)]
    except ImportError:
        return []


def add_firewall_rule():
    """Libera UDP de entrada para este executável (pede elevação via UAC)."""
    prog = sys.executable
    rule = "BIOS Pendrive TFTP"
    args = (f'/c netsh advfirewall firewall delete rule name="{rule}" & '
            f'netsh advfirewall firewall add rule name="{rule}" dir=in action=allow '
            f'protocol=UDP program="{prog}" enable=yes profile=any')
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", args, None, 0)
    return r > 32


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass


def file_logger(log):
    def _log(msg):
        line = f"{time.strftime('%H:%M:%S')} {msg}"
        log(line)
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d ") + line + "\n")
        except OSError:
            pass
    return _log


# =========================================================================
# Procedimento (compartilhado entre GUI e CLI)
# =========================================================================
def run_job(job, kind, target, user, password, tftp_ip, folder, disk=None, layout="mbr",
            blksize=1468, log=print, progress=None, confirm=None,
            equip_ip=EQUIP_IP_PADRAO, equip_iface="eth0"):
    """job: 'info', 'backup' ou 'write'. confirm(texto) -> bool antes de formatar.

    equip_ip: na conexao serial, IP a configurar na interface do equipamento
        antes do TFTP. None pula esse passo.
    """
    progress = progress or (lambda d, t: None)
    t = device.connect(kind, target, user, password, log)
    dev = device.Device(t, log)
    try:
        host, kernel, ips = dev.info()
        log(f"Conectado: {host}, kernel {kernel}, {', '.join(ips) or 'sem IP'}")
        missing = dev.check_tools()
        if missing:
            raise device.DeviceError("faltam ferramentas no equipamento: " + ", ".join(missing))

        # Serial: a rede do equipamento ainda nao subiu, entao a placa do PC
        # esta sem link e o IP dela nao aparece em local_ipv4s(). Sobe a
        # interface do equipamento e so entao resolve o IP do TFTP.
        if kind == "serial" and equip_ip:
            dev.setup_network(equip_ip, iface=equip_iface)
            alvo = tftp_ip or ip_same_subnet(equip_ip)
            if alvo:
                if wait_local_ip(alvo, 25, log):
                    tftp_ip = alvo
                    log(f"Rede do PC disponivel em {tftp_ip}")
                else:
                    log(f"AVISO: {alvo} nao apareceu nas interfaces do PC em 25 s. "
                        f"Confira o cabo na segunda placa de rede.")
            else:
                log(f"AVISO: nenhum IP do PC na faixa de {equip_ip}. "
                    f"Configure a segunda placa de rede nessa sub-rede.")

        disks = dev.usb_disks()
        if not disks:
            log("Nenhum pendrive USB detectado no equipamento.")
        for d in disks:
            log(f"Pendrive: {dev.describe(d)}  [{d['id']}]")

        if tftp_ip:
            if dev.ping(tftp_ip):
                log(f"Equipamento alcança o PC em {tftp_ip} (ping OK)")
            else:
                log(f"AVISO: equipamento não respondeu ping para {tftp_ip}. "
                    "Pode ser só ICMP bloqueado; o TFTP ainda pode funcionar.")
        if job == "info":
            return disks

        if not tftp_ip:
            raise device.DeviceError("selecione o IP do PC para o TFTP")
        if not disks:
            raise device.DeviceError("conecte um pendrive no equipamento")
        if disk:
            sel = next((d for d in disks if d["dev"] == disk), None)
            if not sel:
                raise device.DeviceError(f"{disk} não é um pendrive USB detectado")
        elif len(disks) == 1:
            sel = disks[0]
        else:
            raise device.DeviceError("mais de um pendrive conectado; escolha qual usar")

        os.makedirs(folder, exist_ok=True)
        with TftpServer(folder, tftp_ip, log=log, allow_write=(job == "backup")) as srv:
            try:
                if job == "backup":
                    dev.backup(sel["dev"], tftp_ip, folder, blksize=blksize, progress=progress)
                elif job == "write":
                    txt = (f"TODO o conteúdo de {dev.describe(sel)} será APAGADO e o pendrive "
                           f"será gravado com os {len(device.list_local_files(folder))} arquivos de\n"
                           f"{folder}\n\nContinuar?")
                    if confirm and not confirm(txt):
                        log("Cancelado pelo usuário.")
                        return None
                    dev.write(sel["dev"], tftp_ip, folder, layout=layout, blksize=blksize,
                              progress=progress)
                else:
                    raise device.DeviceError(f"operação desconhecida: {job}")
            except device.DeviceError as e:
                if "tftp" in str(e) and not srv.completed:
                    log("DICA: nenhuma transferência TFTP chegou ao PC. Confira o IP selecionado "
                        "e o Firewall do Windows (botão 'Liberar no Firewall').")
                raise
        return True
    finally:
        dev.close()


# =========================================================================
# Interface gráfica
# =========================================================================
def run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    cfg = load_config()
    root = tk.Tk()
    root.title(f"{APP_NAME} {VERSION}")
    root.minsize(760, 560)
    q = queue.Queue()
    busy = {"on": False}

    kind = tk.StringVar(value=cfg.get("kind", "ssh"))
    ssh_host = tk.StringVar(value=cfg.get("ssh_host", "172.22.239.56"))
    ssh_port = tk.StringVar(value=cfg.get("ssh_port", "22"))
    tel_host = tk.StringVar(value=cfg.get("tel_host", "172.22.239.100"))
    tel_port = tk.StringVar(value=cfg.get("tel_port", "4006"))
    com_port = tk.StringVar(value=cfg.get("com_port", ""))
    baud = tk.StringVar(value=cfg.get("baud", "115200"))
    user = tk.StringVar(value=cfg.get("user", "root"))
    password = tk.StringVar(value="root")
    tftp_ip = tk.StringVar()
    folder = tk.StringVar(value=cfg.get("folder", DEFAULT_DIR))
    layout = tk.StringVar(value=cfg.get("layout", "MBR + FAT32 (recomendado)"))
    disk = tk.StringVar()
    status = tk.StringVar(value="Pronto.")

    pad = {"padx": 6, "pady": 3}
    main = ttk.Frame(root, padding=8)
    main.pack(fill="both", expand=True)
    main.columnconfigure(0, weight=1)

    # --- conexão
    fc = ttk.LabelFrame(main, text="Conexão com o equipamento", padding=6)
    fc.grid(row=0, column=0, sticky="ew")
    ttk.Radiobutton(fc, text="SSH", variable=kind, value="ssh").grid(row=0, column=0, sticky="w", **pad)
    ttk.Label(fc, text="IP").grid(row=0, column=1, sticky="e")
    ttk.Entry(fc, textvariable=ssh_host, width=18).grid(row=0, column=2, sticky="w", **pad)
    ttk.Label(fc, text="Porta").grid(row=0, column=3, sticky="e")
    ttk.Entry(fc, textvariable=ssh_port, width=7).grid(row=0, column=4, sticky="w", **pad)

    ttk.Radiobutton(fc, text="Telnet (serial remota)", variable=kind, value="telnet").grid(row=1, column=0, sticky="w", **pad)
    ttk.Label(fc, text="IP").grid(row=1, column=1, sticky="e")
    ttk.Entry(fc, textvariable=tel_host, width=18).grid(row=1, column=2, sticky="w", **pad)
    ttk.Label(fc, text="Porta").grid(row=1, column=3, sticky="e")
    ttk.Entry(fc, textvariable=tel_port, width=7).grid(row=1, column=4, sticky="w", **pad)

    ttk.Radiobutton(fc, text="Serial local", variable=kind, value="serial").grid(row=2, column=0, sticky="w", **pad)
    ttk.Label(fc, text="COM").grid(row=2, column=1, sticky="e")
    com_cb = ttk.Combobox(fc, textvariable=com_port, width=16)
    com_cb.grid(row=2, column=2, sticky="w", **pad)
    ttk.Label(fc, text="Baud").grid(row=2, column=3, sticky="e")
    ttk.Combobox(fc, textvariable=baud, width=7, values=["9600", "38400", "57600", "115200"]).grid(row=2, column=4, sticky="w", **pad)

    ttk.Label(fc, text="Usuário").grid(row=0, column=5, sticky="e")
    ttk.Entry(fc, textvariable=user, width=10).grid(row=0, column=6, sticky="w", **pad)
    ttk.Label(fc, text="Senha").grid(row=1, column=5, sticky="e")
    ttk.Entry(fc, textvariable=password, width=10, show="*").grid(row=1, column=6, sticky="w", **pad)

    # --- TFTP / pasta
    ft = ttk.LabelFrame(main, text="PC (servidor TFTP) e pendrive", padding=6)
    ft.grid(row=1, column=0, sticky="ew", pady=6)
    ft.columnconfigure(1, weight=1)
    ttk.Label(ft, text="IP deste PC").grid(row=0, column=0, sticky="e", **pad)
    ip_cb = ttk.Combobox(ft, textvariable=tftp_ip, width=40, state="readonly")
    ip_cb.grid(row=0, column=1, sticky="w", **pad)
    ttk.Label(ft, text="Pasta dos arquivos").grid(row=1, column=0, sticky="e", **pad)
    ttk.Entry(ft, textvariable=folder).grid(row=1, column=1, sticky="ew", **pad)
    ttk.Button(ft, text="...", width=3,
               command=lambda: folder.set(filedialog.askdirectory(initialdir=folder.get()) or folder.get())
               ).grid(row=1, column=2, **pad)
    ttk.Button(ft, text="Abrir", width=6,
               command=lambda: (os.makedirs(folder.get(), exist_ok=True), os.startfile(folder.get()))
               ).grid(row=1, column=3, **pad)
    ttk.Label(ft, text="Pendrive").grid(row=2, column=0, sticky="e", **pad)
    disk_cb = ttk.Combobox(ft, textvariable=disk, width=40, state="readonly")
    disk_cb.grid(row=2, column=1, sticky="w", **pad)
    ttk.Label(ft, text="Formato (gravar)").grid(row=3, column=0, sticky="e", **pad)
    ttk.Combobox(ft, textvariable=layout, width=40, state="readonly",
                 values=["MBR + FAT32 (recomendado)", "FAT32 sem partição"]).grid(row=3, column=1, sticky="w", **pad)

    # --- botões
    fb = ttk.Frame(main)
    fb.grid(row=2, column=0, sticky="ew")
    b_test = ttk.Button(fb, text="Testar conexão")
    b_backup = ttk.Button(fb, text="1) Copiar pendrive → PC")
    b_write = ttk.Button(fb, text="2) Gravar PC → pendrive")
    b_fw = ttk.Button(fb, text="Liberar no Firewall")
    for i, b in enumerate((b_test, b_backup, b_write, b_fw)):
        b.grid(row=0, column=i, padx=4, pady=4, sticky="w")
    buttons = (b_test, b_backup, b_write)

    pb = ttk.Progressbar(main, mode="determinate", maximum=1000)
    pb.grid(row=3, column=0, sticky="ew", pady=4)

    # --- log
    fl = ttk.Frame(main)
    fl.grid(row=4, column=0, sticky="nsew")
    main.rowconfigure(4, weight=1)
    txt = tk.Text(fl, height=16, wrap="word", font=("Consolas", 9))
    sb = ttk.Scrollbar(fl, command=txt.yview)
    txt.configure(yscrollcommand=sb.set, state="disabled")
    txt.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    ttk.Label(main, textvariable=status, anchor="w").grid(row=5, column=0, sticky="ew")

    # --- listas dinâmicas
    ip_map = {}

    def target_host():
        return {"ssh": ssh_host.get(), "telnet": tel_host.get()}.get(kind.get())

    def refresh_ips(prefer=None):
        ips = local_ipv4s()
        ip_map.clear()
        labels = []
        for ip, name in ips:
            lab = f"{ip}   ({name})" if name else ip
            ip_map[lab] = ip
            labels.append(lab)
        ip_cb["values"] = labels
        want = prefer or cfg.get("tftp_ip") or (route_ip_to(target_host()) if target_host() else None)
        pick = next((lab for lab in labels if ip_map[lab] == want), labels[0] if labels else "")
        tftp_ip.set(pick)

    def refresh_coms():
        ports = serial_ports()
        com_cb["values"] = [p for p, _ in ports]
        if not com_port.get() and ports:
            com_port.set(ports[0][0])

    refresh_ips()
    refresh_coms()
    ip_cb.bind("<Button-1>", lambda e: None if ip_cb["values"] else refresh_ips())
    com_cb.configure(postcommand=refresh_coms)

    disk_map = {}

    # --- execução em thread
    def log(msg):
        q.put(("log", msg))

    def logf(msg):
        file_logger(log)(msg)

    def ui_confirm(text):
        ev, ans = threading.Event(), {}
        q.put(("confirm", (text, ev, ans)))
        ev.wait()
        return ans.get("ok", False)

    def conn_params():
        k = kind.get()
        if k == "ssh":
            return k, f"{ssh_host.get().strip()}:{ssh_port.get().strip() or 22}"
        if k == "telnet":
            return k, f"{tel_host.get().strip()}:{tel_port.get().strip() or 23}"
        if not com_port.get():
            raise device.DeviceError("selecione a porta COM")
        return k, f"{com_port.get()}:{baud.get() or 115200}"

    def persist():
        cfg.update(kind=kind.get(), ssh_host=ssh_host.get(), ssh_port=ssh_port.get(),
                   tel_host=tel_host.get(), tel_port=tel_port.get(), com_port=com_port.get(),
                   baud=baud.get(), user=user.get(), folder=folder.get(), layout=layout.get(),
                   tftp_ip=ip_map.get(tftp_ip.get(), ""))
        save_config(cfg)

    def start(job):
        if busy["on"]:
            return
        try:
            k, target = conn_params()
        except device.DeviceError as e:
            messagebox.showerror(APP_NAME, str(e))
            return
        persist()
        ip = ip_map.get(tftp_ip.get())
        lay = "floppy" if layout.get().startswith("FAT32 sem") else "mbr"
        dsk = disk_map.get(disk.get())
        busy["on"] = True
        for b in buttons:
            b.state(["disabled"])
        pb["value"] = 0
        status.set({"info": "Testando...", "backup": "Copiando pendrive → PC...",
                    "write": "Gravando pendrive..."}[job])
        t0 = time.monotonic()

        def prog(done, total):
            q.put(("prog", (done, total, t0)))

        def worker():
            try:
                logf(f"===== {job.upper()} via {k} {target} | TFTP {ip} | {folder.get()}")
                r = run_job(job, k, target, user.get(), password.get(), ip, folder.get(),
                            disk=dsk, layout=lay, log=logf, progress=prog, confirm=ui_confirm)
                if job == "info":
                    q.put(("disks", r))
                    q.put(("done", "Conexão OK."))
                elif r is None:
                    q.put(("done", "Cancelado."))
                else:
                    q.put(("done", f"Concluído em {time.monotonic() - t0:.0f} s."))
            except (device.DeviceError, TftpError, OSError) as e:
                logf(f"ERRO: {e}")
                q.put(("fail", str(e)))
            except Exception as e:
                logf("ERRO inesperado:\n" + traceback.format_exc())
                q.put(("fail", f"{type(e).__name__}: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def pump():
        try:
            while True:
                kind_, data = q.get_nowait()
                if kind_ == "log":
                    txt.configure(state="normal")
                    txt.insert("end", data + "\n")
                    txt.see("end")
                    txt.configure(state="disabled")
                elif kind_ == "prog":
                    done, total, t0 = data
                    pb["value"] = 1000 * done / total if total else 0
                    rate = done / max(0.1, time.monotonic() - t0)
                    status.set(f"{device.human(done)} de {device.human(total)}  ({device.human(rate)}/s)")
                elif kind_ == "disks":
                    disk_map.clear()
                    labels = []
                    for d in data or []:
                        lab = f"{d['dev']}  {d['model']}  {device.human(d['size'])}"
                        disk_map[lab] = d["dev"]
                        labels.append(lab)
                    disk_cb["values"] = labels
                    disk.set(labels[0] if labels else "")
                elif kind_ == "confirm":
                    text, ev, ans = data
                    ans["ok"] = messagebox.askyesno(APP_NAME, text, icon="warning", default="no")
                    ev.set()
                elif kind_ in ("done", "fail"):
                    busy["on"] = False
                    for b in buttons:
                        b.state(["!disabled"])
                    if kind_ == "done":
                        status.set(data)
                        if pb["value"] > 0:
                            pb["value"] = 1000
                    else:
                        status.set("Falhou: " + data.splitlines()[0])
                        messagebox.showerror(APP_NAME, data)
        except queue.Empty:
            pass
        root.after(100, pump)

    def firewall():
        if add_firewall_rule():
            log("Pedido de liberação no Firewall enviado (confirme o UAC).")
        else:
            messagebox.showerror(APP_NAME, "Não foi possível pedir elevação para o netsh.")

    b_test.configure(command=lambda: start("info"))
    b_backup.configure(command=lambda: start("backup"))
    b_write.configure(command=lambda: start("write"))
    b_fw.configure(command=firewall)

    log(f"{APP_NAME} {VERSION}. Pasta: {folder.get()}")
    log("1) Com o pendrive MODELO no equipamento: 'Copiar pendrive → PC'.")
    log("2) Troque pelo pendrive novo: 'Gravar PC → pendrive' (apaga tudo nele).")
    root.after(100, pump)
    root.mainloop()


# =========================================================================
# Linha de comando
# =========================================================================
def _attach_console():
    # O .exe é --windowed; em modo CLI reaproveita o console de quem chamou.
    if sys.stdout is None and os.name == "nt":
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = sys.stdout
            print()


def run_cli(argv):
    p = argparse.ArgumentParser(prog="bios_pendrive", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("job", choices=["info", "backup", "write"])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ssh", metavar="HOST[:PORTA]")
    g.add_argument("--telnet", metavar="HOST:PORTA")
    g.add_argument("--serial", metavar="COMx[:BAUD]")
    p.add_argument("--user", default="root")
    p.add_argument("--password", default="root")
    p.add_argument("--tftp-ip", help="IP deste PC que o equipamento usa (padrão: rota até o host)")
    p.add_argument("--equip-ip", default=EQUIP_IP_PADRAO,
                   help=f"na serial, IP a subir na eth do equipamento antes do TFTP "
                        f"(padrão: {EQUIP_IP_PADRAO}); 'none' pula esse passo")
    p.add_argument("--equip-iface", default="eth0",
                   help="interface do equipamento a subir (padrão: eth0)")
    p.add_argument("--dir", default=DEFAULT_DIR, help="pasta local dos arquivos")
    p.add_argument("--disk", help="ex.: /dev/sda (se houver mais de um pendrive)")
    p.add_argument("--layout", choices=["mbr", "floppy"], default="mbr")
    p.add_argument("--blksize", type=int, default=1468)
    p.add_argument("--yes", action="store_true", help="não pedir confirmação antes de formatar")
    a = p.parse_args(argv)

    kind = "ssh" if a.ssh else "telnet" if a.telnet else "serial"
    target = a.ssh or a.telnet or a.serial
    ip = a.tftp_ip
    if not ip and kind != "serial":
        ip = route_ip_to(target.partition(":")[0])
    log = file_logger(lambda m: print(m, flush=True))

    last = [0]

    def prog(done, total):
        pct = int(100 * done / total) if total else 100
        if pct // 10 != last[0] // 10 or done == total:
            print(f"   {pct}% ({device.human(done)} de {device.human(total)})", flush=True)
        last[0] = pct

    def confirm(text):
        if a.yes:
            return True
        print(text)
        return input("Digite SIM para continuar: ").strip().upper() == "SIM"

    try:
        eq_ip = None if str(a.equip_ip).lower() in ("none", "") else a.equip_ip
        r = run_job(a.job, kind, target, a.user, a.password, ip, a.dir, disk=a.disk,
                    layout=a.layout, blksize=a.blksize, log=log, progress=prog, confirm=confirm,
                    equip_ip=eq_ip, equip_iface=a.equip_iface)
        return 0 if r is not None else 1
    except (device.DeviceError, TftpError, OSError) as e:
        log(f"ERRO: {e}")
        return 2


def main():
    if len(sys.argv) > 1:
        _attach_console()
        sys.exit(run_cli(sys.argv[1:]))
    run_gui()


if __name__ == "__main__":
    main()
