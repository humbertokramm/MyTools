import os
import tkinter as tk

IP = "192.168.0.15"
PORT = "8081"

BASE_LINK = f"onie-nos-install http://{IP}:{PORT}/"

def copiar_link(nome_arquivo):
    link = BASE_LINK + nome_arquivo
    root.clipboard_clear()
    root.clipboard_append(link)
    root.update()
    print("Copiado:", link)

root = tk.Tk()
root.title("Arquivos ONIE")

frame = tk.Frame(root)
frame.pack(padx=10, pady=10)

arquivos = [f for f in os.listdir(".") if os.path.isfile(f) and f.lower().endswith(".bin")]

for arquivo in arquivos:
    
    linha = tk.Frame(frame)
    linha.pack(fill="x", pady=2)

    label = tk.Label(linha, text=arquivo, anchor="w", width=40)
    label.pack(side="left")

    botao = tk.Button(
        linha,
        text="Copiar link",
        command=lambda a=arquivo: copiar_link(a)
    )
    botao.pack(side="right")



root.mainloop()

