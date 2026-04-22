import os
import glob
import time
from selectcom import selecionar_e_abrir_porta
import subprocess
import sys
import dirHandle as dh
from datetime import datetime

import argparse

# ================= CONFIG =================
DIRETORIO_LOCAL = "."
DESTINO_REMOTO = "."
DELIMITADOR = "__END_OF_LUA_837462__"
DELAY_LINHA = 0.003
BAUDRATE = 115200
# ==========================================


def ajustar_data_hora(ser):
    agora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"Ajustando data/hora: {agora}")

    ser.write(f'date -s "{agora}"\n'.encode())
    time.sleep(0.5)

    ser.write(b'hwclock -w\n')
    time.sleep(0.5)


port = None
if len(sys.argv) == 2:
    port = sys.argv[1].upper()


print("=== DEPLOY SERIAL DE ARQUIVOS LUA ===\n")

ser = selecionar_e_abrir_porta(BAUDRATE,port)

if ser is None:
    print("Encerrando.")
    exit()

ajustar_data_hora(ser)




def enviar_linha(cmd, delay=0.2):
    ser.write((cmd + "\n").encode("utf-8"))
    time.sleep(delay)


def esperar_prompt(timeout=5):
    fim = time.time() + timeout
    buffer = ""

    while time.time() < fim:
        if ser.in_waiting:
            buffer += ser.read(ser.in_waiting).decode(errors="ignore")
            if "#" in buffer or "$" in buffer:
                return True
        time.sleep(0.1)

    return False


print("Procurando arquivos .lua...\n")

arquivos = glob.glob(os.path.join(DIRETORIO_LOCAL, "*.lua"))

if not arquivos:
    print("Nenhum arquivo .lua encontrado.")
    ser.close()
    exit()

for caminho in arquivos:
    nome = os.path.basename(caminho)
    remoto = f"{DESTINO_REMOTO}/{nome}".replace("//", "/")

    print(f"Enviando {nome}...")

    # Remove remoto
    enviar_linha(f"rm -f {remoto}", 0.1)

    # Inicia HEREDOC
    enviar_linha(f"cat > {remoto} << '{DELIMITADOR}'", 0.2)

    # Lê conteúdo
    with open(caminho, "r", encoding="utf-8") as f:
        conteudo = f.read()

    # Garante newline final
    conteudo = conteudo.rstrip("\n") + "\n"

    # Envia conteúdo
    for linha in conteudo.splitlines(True):
        ser.write(linha.encode("utf-8"))
        time.sleep(DELAY_LINHA)

    # Finaliza HEREDOC
    enviar_linha(DELIMITADOR, 0.3)

    # Aguarda prompt
    if esperar_prompt():
        print(f"{nome} enviado com sucesso.\n")
    else:
        print(f"⚠ Prompt não detectado após envio de {nome}\n")

print("Transferência concluída.")
porta = ser.port
ser.close()
time.sleep(0.5)

usar_putty_gui = "-p" in sys.argv
try:
    if usar_putty_gui:
        dh.Aviso(f"Abrindo terminal externo\n",'verde')
        # Abre PuTTY GUI
        subprocess.Popen([
            r"C:\Program Files\PuTTY\putty.exe",
            "-serial",
            porta,
            "-sercfg",
            f"{BAUDRATE},8,n,1,N"
        ])
    else:
        # Abre no próprio CMD usando plink
        dh.Aviso(f"Abrindo terminal serial...\n",'verde')
        print("#")
        subprocess.run([
                "plink",
                "-serial",
                porta,
                "-sercfg",
                f"{BAUDRATE},8,n,1,N"
            ]
        )
except:
    dh.Aviso("Terminal fechado",'vermelho')