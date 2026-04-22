import serial
import serial.tools.list_ports
import time


BAUDRATE_PADRAO = 115200


def listar_portas(noPrint = False,port=None):
    portas = list(serial.tools.list_ports.comports())
    if noPrint: return portas
    
    if not portas:
        print("Nenhuma porta serial encontrada.")
        return []

    print("\nPortas seriais disponíveis:\n")
    match=None
    for i, porta in enumerate(portas):
        #print(f"[{i}] {porta.device}")
        print(f"     {i} -> {porta.device}\t{porta.description}",end="\t")
        print(f"Brand: {porta.manufacturer}")
        if port == porta.device: match = i
        #print(f"     HWID      : {porta.hwid}")
        #print()

    return portas,match

def abrir_porta(porta, baudrate=BAUDRATE_PADRAO):
    try:
        ser = serial.Serial(porta, baudrate, timeout=1)
        time.sleep(2)
        return ser

    except serial.SerialException as e:
        msg = str(e)

        if "PermissionError" in msg or "Acesso negado" in msg:
            print(f"\n⚠  A porta {porta} está em uso por outro programa.")
            print("Feche o programa que está usando a porta e tente novamente.\n")
        else:
            print(f"\n⚠  Não foi possível abrir {porta}")
            print(f"Erro: {e}\n")

        return None


def selecionar_e_abrir_porta(baudrate=BAUDRATE_PADRAO,port=None):
    while True:
        portas,match = listar_portas(port=port)

        if not portas:
            return None
            
        try:
            if match != None:
                escolha  = match
            else: escolha = int(input("Selecione o número da porta desejada: "))
            if 0 <= escolha < len(portas):
                porta = portas[escolha].device
                ser = abrir_porta(porta, baudrate)

                if ser:
                    print(f"\n✅ Porta {porta} aberta com sucesso!\n")
                    return ser
                else:
                    continuar = input("Deseja tentar outra porta? (s/n): ").lower()
                    if continuar != "s":
                        return None
            else:
                print("Número inválido.\n")

        except ValueError:
            print("Digite um número válido.\n")