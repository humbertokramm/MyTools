"""
fakeBar.py  --  Leitor de codigo de barras falso, via porta serial.

Simula um leitor de codigo de barras: abre uma porta serial e envia o codigo
digitado, como se tivesse sido lido por um scanner real.

IMPORTANTE -- como funciona no Windows:
    Este script NAO cria a porta serial. Python nao tem como criar um device
    COM; isso exige um driver de kernel. O caminho usual e o com0com, que
    cria um PAR de portas ligadas entre si (ex: CNCA0 <-> CNCB0, ou COM20 <->
    COM21). Tudo que e escrito em uma ponta aparece na outra.

    Fluxo:
        1. Instale o com0com e crie um par (ex: COM20 <-> COM21)
        2. Aponte a sua aplicacao para COM20  (ela pensa que e o leitor)
        3. Abra COM21 aqui no fakeBar e clique em "Simular leitura"

    Sem o par virtual, a lista abaixo mostra apenas as portas fisicas ja
    existentes -- abrir uma delas envia o dado para o hardware, nao para a
    sua aplicacao.

Uso:
    python fakeBar.py

Dependencia: pyserial
"""

import os
import sys
from datetime import datetime

import tkinter as tk
from tkinter import ttk

import serial
import serial.tools.list_ports

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# -----------------------------------------------------------------------
# CONFIGURACAO (padroes da janela)
# -----------------------------------------------------------------------
CONFIG = {
    'baudrate':   9600,      # tipico de leitor de codigo de barras
    'terminator': 'CR',      # a maioria dos leitores encerra com CR (Enter)
    'autosend_s': 2.0,       # intervalo do reenvio automatico
    'serial':     '',        # codigo inicial no campo
    'porta':      'COM16',   # ponta que o fakeBar abre
}

# Pares fisicos em laco (TX<->RX cruzados por cabo). Sao portas fisicas, mas
# funcionam como par virtual: o que sai de uma entra na outra. Declarar aqui
# evita o aviso de "porta fisica" e mostra qual e a ponta da aplicacao.
LOOPBACK_PAIRS = [
    ('COM14', 'COM16'),
]

# Terminador enviado depois do codigo. O leitor real quase sempre manda algo,
# e a aplicacao geralmente usa isso para saber que a leitura acabou.
TERMINATORS = {
    'CR (\\r)':      b'\r',
    'LF (\\n)':      b'\n',
    'CRLF (\\r\\n)': b'\r\n',
    'nenhum':        b'',
}

BAUDRATES = [1200, 2400, 4800, 9600, 19200, 38400, 57600, 115200]

# Descricoes que indicam porta virtual (par de loopback)
VIRTUAL_HINTS = ('com0com', 'virtual', 'vspd', 'eltima', 'null modem', 'nullmodem')
# -----------------------------------------------------------------------


class FakeBarcode:

    def __init__(self, root):
        self.root = root
        self.ser = None
        self._autosend_job = None

        root.title('fakeBar - leitor de codigo de barras falso')
        root.resizable(False, False)

        frame = tk.Frame(root, padx=12, pady=10)
        frame.pack(fill='both', expand=True)

        # ---------------- porta ----------------
        linha_porta = tk.Frame(frame)
        linha_porta.pack(fill='x', pady=(0, 6))

        tk.Label(linha_porta, text='Porta (lado do leitor):').pack(side='left')
        self.porta_var = tk.StringVar()
        self.porta_cb = ttk.Combobox(linha_porta, textvariable=self.porta_var,
                                     width=10, state='readonly')
        self.porta_cb.pack(side='left', padx=4)
        tk.Button(linha_porta, text='Atualizar',
                  command=self.atualizar_portas).pack(side='left', padx=2)

        tk.Label(linha_porta, text='Baud:').pack(side='left', padx=(10, 2))
        self.baud_var = tk.StringVar(value=str(CONFIG['baudrate']))
        ttk.Combobox(linha_porta, textvariable=self.baud_var, width=8,
                     values=[str(b) for b in BAUDRATES],
                     state='readonly').pack(side='left')

        # descricao da porta selecionada (ajuda a ver se e virtual)
        self.desc_label = tk.Label(frame, text='', fg='#666',
                                   anchor='w', wraplength=430, justify='left')
        self.desc_label.pack(fill='x', pady=(0, 6))
        self.porta_cb.bind('<<ComboboxSelected>>', lambda _e: self._mostrar_desc())

        # ---------------- abrir / fechar ----------------
        linha_conn = tk.Frame(frame)
        linha_conn.pack(fill='x', pady=(0, 8))

        self.btn_conn = tk.Button(linha_conn, text='Abrir porta', width=14,
                                  command=self.toggle_porta)
        self.btn_conn.pack(side='left')
        self.status_label = tk.Label(linha_conn, text='fechada', fg='#c62828')
        self.status_label.pack(side='left', padx=8)

        tk.Frame(frame, height=1, bg='#ccc').pack(fill='x', pady=6)

        # ---------------- codigo ----------------
        linha_cod = tk.Frame(frame)
        linha_cod.pack(fill='x', pady=(0, 6))

        tk.Label(linha_cod, text='Codigo / serial:').pack(side='left')
        self.codigo_var = tk.StringVar(value=CONFIG['serial'])
        entry = tk.Entry(linha_cod, textvariable=self.codigo_var, width=30)
        entry.pack(side='left', padx=4)
        entry.bind('<Return>', lambda _e: self.simular_leitura())

        linha_term = tk.Frame(frame)
        linha_term.pack(fill='x', pady=(0, 8))

        tk.Label(linha_term, text='Terminador:').pack(side='left')
        self.term_var = tk.StringVar(value='CR (\\r)')
        ttk.Combobox(linha_term, textvariable=self.term_var, width=14,
                     values=list(TERMINATORS), state='readonly').pack(side='left', padx=4)

        self.auto_var = tk.BooleanVar(value=False)
        tk.Checkbutton(linha_term, text='reenviar a cada',
                       variable=self.auto_var,
                       command=self._toggle_autosend).pack(side='left', padx=(14, 2))
        self.auto_s_var = tk.StringVar(value=str(CONFIG['autosend_s']))
        tk.Entry(linha_term, textvariable=self.auto_s_var, width=5).pack(side='left')
        tk.Label(linha_term, text='s').pack(side='left')

        self.btn_send = tk.Button(frame, text='Simular leitura', height=2,
                                  bg='#e8f5e9', command=self.simular_leitura)
        self.btn_send.pack(fill='x', pady=(2, 8))

        # ---------------- log ----------------
        tk.Label(frame, text='Log:', anchor='w').pack(fill='x')
        self.log_txt = tk.Text(frame, height=9, width=58, font=('Consolas', 8),
                               state='disabled', bg='#fafafa')
        self.log_txt.pack(fill='both', expand=True)

        self.atualizar_portas()
        self._avisar_sem_par_virtual()

        root.protocol('WM_DELETE_WINDOW', self.fechar_app)

    # ------------------------------------------------------------------
    # log
    # ------------------------------------------------------------------
    def log(self, msg, cor=None):
        agora = datetime.now().strftime('%H:%M:%S')
        self.log_txt.config(state='normal')
        self.log_txt.insert('end', f'[{agora}] {msg}\n')
        self.log_txt.see('end')
        self.log_txt.config(state='disabled')

    # ------------------------------------------------------------------
    # portas
    # ------------------------------------------------------------------
    def _portas(self):
        return list(serial.tools.list_ports.comports())

    def atualizar_portas(self):
        portas = self._portas()
        self._desc = {p.device: (p.description or '') for p in portas}
        nomes = [p.device for p in portas]
        self.porta_cb['values'] = nomes
        if nomes and self.porta_var.get() not in nomes:
            # prefere: a porta do CONFIG, depois um laco fisico, depois
            # uma porta virtual, e por fim a primeira da lista
            preferida = CONFIG.get('porta')
            if preferida not in nomes:
                lacos = [n for n in nomes if self._par_loopback(n)]
                virtuais = [n for n in nomes if self._eh_virtual(self._desc[n])]
                preferida = (lacos or virtuais or nomes)[0]
            self.porta_var.set(preferida)
        self._mostrar_desc()
        self.log(f'{len(nomes)} porta(s) encontrada(s)')

    def _eh_virtual(self, desc):
        d = desc.lower()
        return any(h in d for h in VIRTUAL_HINTS)

    def _par_loopback(self, porta):
        """Retorna a outra ponta do laco fisico, ou None se nao houver."""
        for a, b in LOOPBACK_PAIRS:
            if porta == a:
                return b
            if porta == b:
                return a
        return None

    def _mostrar_desc(self):
        p = self.porta_var.get()
        desc = getattr(self, '_desc', {}).get(p, '')
        if not p:
            self.desc_label.config(text='')
            return
        par = self._par_loopback(p)
        if par:
            self.desc_label.config(
                text=f'laco fisico com {par}  --  aponte a sua aplicacao '
                     f'para {par}', fg='#2e7d32')
        elif self._eh_virtual(desc):
            self.desc_label.config(text=f'{desc}  (porta virtual)', fg='#2e7d32')
        else:
            self.desc_label.config(
                text=f'{desc}  -- porta fisica sem par conhecido: o dado vai '
                     f'para o hardware, nao para uma aplicacao local',
                fg='#e65100')

    def _avisar_sem_par_virtual(self):
        portas = set(getattr(self, '_desc', {}))
        # laco fisico declarado e com as duas pontas presentes ja resolve
        for a, b in LOOPBACK_PAIRS:
            if a in portas and b in portas:
                self.log(f'laco fisico disponivel: {a} <-> {b}')
                return
        if not any(self._eh_virtual(d) for d in getattr(self, '_desc', {}).values()):
            self.log('AVISO: nenhum par de portas detectado.')
            self.log('  Use um laco fisico (TX<->RX cruzados) e declare o par')
            self.log('  em LOOPBACK_PAIRS, ou instale um driver de porta virtual.')

    # ------------------------------------------------------------------
    # conexao
    # ------------------------------------------------------------------
    def toggle_porta(self):
        if self.ser and self.ser.is_open:
            self.fechar_porta()
        else:
            self.abrir_porta()

    def abrir_porta(self):
        porta = self.porta_var.get()
        if not porta:
            self.log('ERRO: nenhuma porta selecionada')
            return
        try:
            self.ser = serial.Serial(
                port=porta,
                baudrate=int(self.baud_var.get()),
                timeout=1,
                write_timeout=2,   # evita travar a janela se ninguem le
            )
        except Exception as e:
            self.log(f'ERRO ao abrir {porta}: {e}')
            self.ser = None
            return
        self.btn_conn.config(text='Fechar porta')
        self.status_label.config(text=f'{porta} aberta', fg='#2e7d32')
        self.log(f'{porta} aberta em {self.baud_var.get()} baud')

    def fechar_porta(self):
        self._parar_autosend()
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.btn_conn.config(text='Abrir porta')
        self.status_label.config(text='fechada', fg='#c62828')
        self.log('porta fechada')

    # ------------------------------------------------------------------
    # envio
    # ------------------------------------------------------------------
    def simular_leitura(self):
        if not (self.ser and self.ser.is_open):
            self.log('ERRO: abra a porta antes de simular a leitura')
            return
        codigo = self.codigo_var.get()
        if not codigo:
            self.log('ERRO: informe o codigo / serial')
            return

        term = TERMINATORS.get(self.term_var.get(), b'\r')
        dados = codigo.encode('ascii', errors='replace') + term
        try:
            n = self.ser.write(dados)
            self.ser.flush()
        except serial.SerialTimeoutException:
            self.log('ERRO: timeout na escrita -- a outra ponta esta aberta?')
            return
        except Exception as e:
            self.log(f'ERRO na escrita: {e}')
            return
        self.log(f'enviado ({n} bytes): {dados!r}')

    # ------------------------------------------------------------------
    # reenvio automatico
    # ------------------------------------------------------------------
    def _toggle_autosend(self):
        if self.auto_var.get():
            self._agendar_autosend()
        else:
            self._parar_autosend()

    def _agendar_autosend(self):
        try:
            intervalo = max(0.2, float(self.auto_s_var.get()))
        except ValueError:
            self.log('ERRO: intervalo invalido')
            self.auto_var.set(False)
            return
        self.simular_leitura()
        self._autosend_job = self.root.after(int(intervalo * 1000),
                                             self._agendar_autosend)

    def _parar_autosend(self):
        if self._autosend_job is not None:
            self.root.after_cancel(self._autosend_job)
            self._autosend_job = None
        self.auto_var.set(False)

    # ------------------------------------------------------------------
    def fechar_app(self):
        self.fechar_porta()
        self.root.destroy()


def main():
    root = tk.Tk()
    FakeBarcode(root)
    root.mainloop()


if __name__ == '__main__':
    main()
