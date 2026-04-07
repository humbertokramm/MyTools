import time
from selectcom import abrir_porta


def read_until(ser, expected, timeout=120):

    buffer = ""
    start = time.time()
    print(f"Esperando:\n{expected}")

    while time.time() - start < timeout:

        if ser.in_waiting:
            data = ser.read(ser.in_waiting).decode(errors="ignore")
            buffer += data

            print(data, end="")  # log

            if expected in buffer:
                return True

    return False


def executar_instalacao(porta, baudrate, ip, arquivo):

    ser = abrir_porta(porta, baudrate)

    if not ser:
        print("Erro ao abrir porta")
        return False

    print("Aguardando boot...")

    #if not read_until(ser, "before booting or"):
    if not read_until(ser, "+----------------------------------------------------------------------------+"):
        
        print("Timeout boot")
        return False

    ser.write(b"c\n")

    if not read_until(ser, "grub>"):
        print("Timeout GRUB")
        return False

    ser.write(b"onie_rescue_bootcmd\n")

    if not read_until(ser, "Please press Enter to activate this console."):
        print("Timeout console")
        return False

    ser.write(b"\n")

    if not read_until(ser, "ONIE:/"):
        print("Timeout ONIE")
        return False

    ser.write(b"ifconfig eth0 192.168.0.25 netmask 255.255.255.0 up\n")

    if not read_until(ser, "ONIE:/"):
        print("Timeout ifconfig")
        return False

    cmd = f"onie-nos-install http://{ip}/{arquivo}\n"
    ser.write(cmd.encode())

    print("Instalação iniciada...")

    if read_until(ser, "Verifying image checksum"):
        print("Verificando imagem...")

    if read_until(ser, "OK."):
        print("Instalação concluída com sucesso 🚀")
        return True

    return False