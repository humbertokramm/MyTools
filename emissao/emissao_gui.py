"""
emissao_gui.py  --  Emissao radiada e conduzida numa janela so: captura no
N9010A e analise dos graficos.

    python emissao_gui.py

A sequencia de captura esta em emissao_captura.py e o plot em
emissao_analise.py; a leitura dos CSVs vem do radiada_plot.py.

Compativel com Python 3.8 (o exe roda no Windows 7).
"""

import json
import os
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import matplotlib
matplotlib.use('TkAgg')
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure

import emissao_analise as an
import emissao_captura as cap

APP = 'Emissão Radiada e Conduzida'
BASE = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False)
                                       else __file__))
CONFIG_FILE = os.path.join(BASE, 'emissao_gui.json')
ENSAIOS = ('Radiada', 'Conduzida')


def load_config():
    try:
        with open(CONFIG_FILE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def bandas_txt(bandas):
    """[(30e6, 130e6), ...] -> '30-130; ...' em MHz."""
    return '; '.join('{:g}-{:g}'.format(a / 1e6, b / 1e6) for a, b in bandas)


def bandas_de(txt):
    """Inverso de bandas_txt. ValueError se o texto nao fizer sentido."""
    bandas = []
    for parte in txt.replace(',', ';').split(';'):
        if not parte.strip():
            continue
        a, b = (float(x) * 1e6 for x in parte.split('-'))
        if not 0 < a < b:
            raise ValueError(parte)
        bandas.append((a, b))
    if not bandas:
        raise ValueError('nenhuma banda')
    return bandas


def _beep(seq):
    try:
        import winsound
        for freq, ms in seq:
            winsound.Beep(freq, ms)
    except Exception:
        pass


class OperadorGUI(cap.Operador):
    """Liga a sequencia (thread de captura) a janela, por uma fila."""

    def __init__(self, fila):
        self.fila = fila
        self.abortar = threading.Event()
        self._libera = threading.Event()
        self._resposta = None

    def _espera(self, msg):
        self._libera.clear()
        self.fila.put(msg)
        while not self._libera.wait(0.2):
            if self.abortar.is_set():
                raise cap.Cancelado()
        if self.abortar.is_set():
            raise cap.Cancelado()
        return self._resposta

    def responde(self, valor=None):
        self._resposta = valor
        self._libera.set()

    def prompt(self, texto, pular=False):
        return self._espera(('prompt', (texto, pular)))

    def confirma(self, texto):
        return self._espera(('confirma', texto))

    def log(self, texto):
        self.fila.put(('log', texto))

    def progresso(self, i, n):
        self.fila.put(('prog', (i, n)))

    def cancelado(self):
        return self.abortar.is_set()

    def alerta(self):
        _beep([(800, 800)])

    def ok(self):
        _beep([(1000, 300), (2000, 600)])


class _SaidaNaFila:
    """Os print() do sa.py e do radiada_plot.py vao para o log da janela."""

    def __init__(self, fila):
        self.fila = fila

    def write(self, s):
        if s.strip():
            self.fila.put(('log', s.rstrip()))

    def flush(self):
        pass


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = load_config()
        self.fila = queue.Queue()
        self.op = None
        self.medidas = {}          # iid da arvore -> medida (folhas)
        self.grupos = {}           # iid de uma execucao (hora) -> [medidas]
        # pontos marcados na analise [[freq_MHz, valor]], comuns a todos os graficos
        self.marcas = [list(m) for m in self.cfg.get('marcas', [])]
        root.title(APP)
        try:        # no exe o icone vem embutido (sys._MEIPASS)
            root.iconbitmap(os.path.join(
                getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))),
                'emissao.ico'))
        except tk.TclError:
            pass
        root.minsize(1000, 680)
        sys.stdout = _SaidaNaFila(self.fila)

        nb = ttk.Notebook(root)
        nb.pack(fill='both', expand=True)
        self.nb = nb
        self.aba_cap = ttk.Frame(nb, padding=8)
        self.aba_an = ttk.Frame(nb, padding=8)
        nb.add(self.aba_cap, text='Captura')
        nb.add(self.aba_an, text='Análise')
        self._monta_captura()
        self._monta_analise()
        root.protocol('WM_DELETE_WINDOW', self._fechar)
        root.after(100, self._poll)
        self.atualiza_arvore()

    # ------------------------------------------------------------------
    # Captura
    # ------------------------------------------------------------------
    def _monta_captura(self):
        c, f = self.cfg, self.aba_cap
        f.columnconfigure(1, weight=1)
        pad = dict(padx=4, pady=3)

        self.ip = tk.StringVar(value=c.get('ip', '192.168.0.30'))
        self.ensaio = tk.StringVar(value=c.get('ensaio', 'Radiada'))
        self.classe = tk.StringVar(value=c.get('classe', 'A'))
        self.raiz = tk.StringVar(value=c.get('raiz', r'T:\1berto\Medidas'))
        self.n = tk.StringVar()
        # cenarios: opcoes fixas marcadas + extras digitados (separados por ;)
        def marcas_de(chave, opcoes, padrao):
            salvo = c.get(chave, padrao)
            return {o: tk.BooleanVar(value=o in salvo) for o in opcoes}
        self.tens_sel = marcas_de('tensoes_sel', cap.TENSOES_PADRAO, cap.TENSOES_PADRAO)
        self.tens_extra = tk.StringVar(value=c.get('tensao_extra', ''))
        self.slot_sel = marcas_de('slots_sel', cap.SLOTS_PADRAO, cap.SLOTS_PADRAO)
        self.slot_extra = tk.StringVar(value=c.get('slot_extra', ''))
        self.pol_sel = marcas_de('pols_sel', cap.POLS, cap.POLS)
        self.amb_modo = tk.StringVar(value=cap.modo_ambiente(c.get('amb_modo', cap.AMB_CADA)))
        self.amb_n = tk.StringVar(value=str(c.get('amb_n', 3)))
        self.ordens = {e: [d for d in c.get('ordem', {}).get(e, []) if d in cap.DIMENSOES[e]]
                       for e in ENSAIOS}
        for e in ENSAIOS:          # completa com o que faltar (config antiga)
            self.ordens[e] += [d for d in cap.DIMENSOES[e] if d not in self.ordens[e]]
        self.bandas = tk.StringVar()
        self.state = tk.StringVar()

        def linha(r, rotulo):
            lb = ttk.Label(f, text=rotulo)
            lb.grid(row=r, column=0, sticky='e', **pad)
            fr = ttk.Frame(f)
            fr.grid(row=r, column=1, sticky='ew', **pad)
            fr.rotulo = lb             # para esconder a linha inteira
            return fr

        fr = linha(0, 'Analisador (IP)')
        ttk.Entry(fr, textvariable=self.ip, width=16).pack(side='left')
        self.bt_testar = ttk.Button(fr, text='Testar conexão', command=self._testar)
        self.bt_testar.pack(side='left', padx=6)
        self.lb_idn = ttk.Label(fr, text='')
        self.lb_idn.pack(side='left')

        fr = linha(1, 'Ensaio')
        for e in ENSAIOS:
            ttk.Radiobutton(fr, text=e, variable=self.ensaio, value=e,
                            command=self._troca_ensaio).pack(side='left', padx=(0, 10))
        ttk.Label(fr, text='Classe').pack(side='left', padx=(10, 2))
        cb = ttk.Combobox(fr, textvariable=self.classe, values=['A', 'B'], width=3,
                          state='readonly')
        cb.pack(side='left')
        cb.bind('<<ComboboxSelected>>', lambda e: self._troca_ensaio())
        ttk.Label(fr, text='Varreduras (média)').pack(side='left', padx=(14, 2))
        ttk.Entry(fr, textvariable=self.n, width=5).pack(side='left')

        fr = linha(2, 'Pasta das medidas')
        ttk.Entry(fr, textvariable=self.raiz).pack(side='left', fill='x', expand=True)
        ttk.Button(fr, text='...', width=3, command=self._escolhe_raiz).pack(side='left', padx=4)

        def opcoes(fr, sel, extra, dica):
            for o, v in sel.items():
                ttk.Checkbutton(fr, text=o, variable=v,
                                command=self._resumo).pack(side='left', padx=(0, 8))
            if extra is not None:
                ttk.Label(fr, text='Outra:').pack(side='left', padx=(6, 2))
                ttk.Entry(fr, textvariable=extra, width=18).pack(side='left')
                ttk.Label(fr, text=dica, foreground='gray').pack(side='left', padx=6)

        opcoes(linha(3, 'Tensões'), self.tens_sel, self.tens_extra,
               '(mais de uma: separe por ;)')
        opcoes(linha(4, 'Slots da PSU'), self.slot_sel, self.slot_extra,
               '(nenhum marcado: equipamento sem slot)')
        self.fr_pol = linha(5, 'Polarização')
        opcoes(self.fr_pol, self.pol_sel, None, '')

        self.fr_amb = fr = linha(6, 'Ambiente')
        ttk.Label(fr, text='depois do EUT:').pack(side='left', padx=(0, 6))
        for valor, texto in ((cap.AMB_CADA, 'em cada combinação'),
                             (cap.AMB_POL, 'por polarização:'),
                             (cap.AMB_NAO, 'não medir')):
            ttk.Radiobutton(fr, text=texto, variable=self.amb_modo, value=valor,
                            command=self._resumo).pack(side='left', padx=(0, 4))
            if valor == cap.AMB_POL:
                ttk.Spinbox(fr, from_=1, to=20, textvariable=self.amb_n, width=3,
                            command=self._resumo).pack(side='left')
                ttk.Label(fr, text='medição(ões)').pack(side='left', padx=(2, 12))

        fr = linha(7, 'Ordem das trocas')
        self.lst_ordem = tk.Listbox(fr, height=3, width=14, exportselection=False,
                                    activestyle='none')
        self.lst_ordem.pack(side='left')
        bts = ttk.Frame(fr)
        bts.pack(side='left', padx=4)
        ttk.Button(bts, text='▲', width=3, command=lambda: self._move_ordem(-1)).pack()
        ttk.Button(bts, text='▼', width=3, command=lambda: self._move_ordem(1)).pack()
        info = ttk.Frame(fr)
        info.pack(side='left', padx=6, fill='x', expand=True)
        ttk.Label(info, text='a de cima troca menos vezes; a de baixo, a cada combinação',
                  foreground='gray').pack(anchor='w')
        self.lb_resumo = ttk.Label(info, text='')
        self.lb_resumo.pack(anchor='w', pady=(4, 0))
        for v in (self.tens_extra, self.slot_extra, self.amb_n):
            v.trace_add('write', lambda *a: self._resumo())

        fr = linha(8, 'Bandas (MHz)')
        ttk.Entry(fr, textvariable=self.bandas).pack(side='left', fill='x', expand=True)
        self.bandas.trace_add('write', lambda *a: self._resumo())
        fr = linha(9, 'State no analisador')
        ttk.Entry(fr, textvariable=self.state).pack(side='left', fill='x', expand=True)

        fr = linha(10, '')
        self.bt_iniciar = ttk.Button(fr, text='Iniciar captura', command=self._iniciar)
        self.bt_iniciar.pack(side='left')
        self.bt_abortar = ttk.Button(fr, text='Abortar', command=self._abortar,
                                     state='disabled')
        self.bt_abortar.pack(side='left', padx=6)

        # aviso ao operador: pisca ate ele confirmar
        self.aviso = tk.Label(f, text='', font=('', 14, 'bold'), height=3, relief='groove',
                              wraplength=980, justify='center')
        self.aviso.grid(row=11, column=0, columnspan=2, sticky='ew', pady=(8, 2))
        bts = ttk.Frame(f)
        bts.grid(row=12, column=0, columnspan=2)
        self.bt_continuar = ttk.Button(bts, text='Continuar (Enter)', command=self._continuar,
                                       state='disabled')
        self.bt_continuar.pack(side='left')
        self.bt_pular = ttk.Button(bts, text='Pular esta combinação', command=self._pular,
                                   state='disabled')
        self.bt_pular.pack(side='left', padx=8)
        self.root.bind('<Return>', lambda e: self._continuar())

        self.pb = ttk.Progressbar(f, maximum=100)
        self.pb.grid(row=13, column=0, columnspan=2, sticky='ew', pady=6)
        fr = ttk.Frame(f)
        fr.grid(row=14, column=0, columnspan=2, sticky='nsew')
        f.rowconfigure(14, weight=1)
        self.txt = tk.Text(fr, height=12, state='disabled', wrap='word')
        sb = ttk.Scrollbar(fr, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        sb.pack(side='right', fill='y')
        self.txt.pack(side='left', fill='both', expand=True)

        self._ensaio_mostrado = None
        self._troca_ensaio()

    def _chave(self):
        return '{}/{}'.format(self.ensaio.get(), self.classe.get())

    def _guarda_ensaio(self):
        """Guarda n, bandas e state do ensaio/classe que estava na tela."""
        if self._ensaio_mostrado:
            self.cfg.setdefault('ensaios', {})[self._ensaio_mostrado] = dict(
                n=self.n.get(), bandas=self.bandas.get(), state=self.state.get())

    def _troca_ensaio(self):
        self._guarda_ensaio()
        e, cl = self.ensaio.get(), self.classe.get()
        salvo = self.cfg.get('ensaios', {}).get(self._chave(), {})
        self.n.set(salvo.get('n', str(cap.VARREDURAS[e])))
        self.bandas.set(salvo.get('bandas', bandas_txt(cap.BANDAS[e])))
        self.state.set(salvo.get('state', cap.STATES[e][cl]))
        for fr in (self.fr_pol, self.fr_amb):          # so na radiada
            for w in (fr, fr.rotulo):
                w.grid() if e == 'Radiada' else w.grid_remove()
        self._ensaio_mostrado = self._chave()
        self._mostra_ordem()

    # cenarios ---------------------------------------------------------
    @staticmethod
    def _lista(sel, extra):
        """Opcoes marcadas + extras digitados, prontos para o nome do arquivo."""
        res = [o for o, v in sel.items() if v.get()]
        for x in extra.get().split(';') if extra is not None else []:
            x = cap.limpa_nome(x)
            if x and x not in res:
                res.append(x)
        return res

    def _mostra_ordem(self):
        self.lst_ordem.delete(0, 'end')
        for i, d in enumerate(self.ordens[self.ensaio.get()]):
            self.lst_ordem.insert('end', '{}. {}'.format(i + 1, d))
        self._resumo()

    def _move_ordem(self, passo):
        sel = self.lst_ordem.curselection()
        ordem = self.ordens[self.ensaio.get()]
        if not sel:
            return
        i, j = sel[0], sel[0] + passo
        if 0 <= j < len(ordem):
            ordem[i], ordem[j] = ordem[j], ordem[i]
            self._mostra_ordem()
            self.lst_ordem.selection_set(j)

    def _cenarios(self):
        """(tensoes, slots, pols, combinacoes) do que esta marcado na tela."""
        tensoes = self._lista(self.tens_sel, self.tens_extra)
        slots = self._lista(self.slot_sel, self.slot_extra)
        pols = self._lista(self.pol_sel, None)
        e = self.ensaio.get()
        valores = {'Polarização': pols, 'Slot': slots, 'Tensão': tensoes}
        combos = cap.combinacoes(self.ordens[e], valores)
        return tensoes, slots, pols, combos

    def _resumo(self):
        """Quantas combinacoes e capturas a execucao vai ter."""
        if not hasattr(self, 'lb_resumo'):
            return
        tensoes, slots, pols, combos = self._cenarios()
        try:
            bandas = bandas_de(self.bandas.get())
        except ValueError:
            bandas = []
        if not tensoes or (self.ensaio.get() == 'Radiada' and not pols) or not bandas:
            self.lb_resumo.config(text='Marque ao menos uma tensão'
                                  + (' e uma polarização' if self.ensaio.get() == 'Radiada'
                                     else '') + '.', foreground='#c0392b')
            return
        if self.ensaio.get() == 'Radiada':
            try:
                amb_n = max(1, int(self.amb_n.get()))
            except ValueError:
                amb_n = 1
            capt = cap.plano_radiada(combos, pols, cap.etapas_radiada(bandas),
                                     self.amb_modo.get(), amb_n)
        else:
            capt = len(combos) * 2 * len(bandas)
        self.lb_resumo.config(text='{} combinação(ões), {} captura(s)'.format(
            len(combos), capt), foreground='')

    def _escolhe_raiz(self):
        d = filedialog.askdirectory(title='Pasta das medidas', initialdir=self.raiz.get())
        if d:
            self.raiz.set(os.path.normpath(d))
            self.atualiza_arvore()

    def _persiste(self):
        self._guarda_ensaio()
        self.cfg.update(ip=self.ip.get(), ensaio=self.ensaio.get(), classe=self.classe.get(),
                        raiz=self.raiz.get(),
                        tensoes_sel=[o for o, v in self.tens_sel.items() if v.get()],
                        tensao_extra=self.tens_extra.get(),
                        slots_sel=[o for o, v in self.slot_sel.items() if v.get()],
                        slot_extra=self.slot_extra.get(),
                        pols_sel=[o for o, v in self.pol_sel.items() if v.get()],
                        amb_modo=self.amb_modo.get(), amb_n=self.amb_n.get(),
                        ordem=self.ordens, marcas=self.marcas,
                        trava_amp=self.trava_amp.get(), trava_freq=self.trava_freq.get())
        save_config(self.cfg)

    def _log(self, texto):
        self.txt.configure(state='normal')
        self.txt.insert('end', texto + '\n')
        self.txt.see('end')
        self.txt.configure(state='disabled')

    def _conecta(self, ip):
        """Roda na thread de captura: nao pode ler os campos da janela."""
        from sa import SA                 # so aqui: o pyvisa demora a carregar
        return SA('TCPIP0::' + ip + '::inst0::INSTR', overwrite=True)

    def _testar(self):
        self.lb_idn.config(text='conectando...', foreground='black')
        self.bt_testar.state(['disabled'])
        ip = self.ip.get().strip()

        def tarefa():
            try:
                sa = self._conecta(ip)
                idn = sa.inst.query('*IDN?').strip()
                self.fila.put(('log', 'VISA: {}'.format(getattr(sa.rm, 'visalib', '?'))))
                sa.close()
                self.fila.put(('idn', (idn, 'green')))
            except Exception as e:
                self.fila.put(('idn', ('falhou: ' + str(e), 'red')))

        threading.Thread(target=tarefa, daemon=True).start()

    def _iniciar(self):
        if self.op is not None:
            return
        e, classe = self.ensaio.get(), self.classe.get()
        try:
            n = int(self.n.get())
            bandas = bandas_de(self.bandas.get())
        except ValueError as err:
            messagebox.showerror(APP, 'Varreduras ou bandas inválidas: {}'.format(err))
            return
        raiz, state = self.raiz.get().strip(), self.state.get().strip()
        tensoes, slots, pols, combos = self._cenarios()
        ordem = list(self.ordens[e])
        if not tensoes:
            messagebox.showerror(APP, 'Marque ou digite ao menos uma tensão.')
            return
        if e == 'Radiada':
            if not pols:
                messagebox.showerror(APP, 'Marque ao menos uma polarização.')
                return
            modo = self.amb_modo.get()
            try:
                amb_n = int(self.amb_n.get())
                if amb_n < 1:
                    raise ValueError
            except ValueError:
                messagebox.showerror(APP, 'Número de medições de ambiente inválido.')
                return
            seq = lambda sa, op: cap.radiada(sa, op, raiz, classe, n, tensoes, slots, pols,
                                             ordem, modo, amb_n, bandas, state=state)
        else:
            seq = lambda sa, op: cap.conduzida(sa, op, raiz, classe, n, tensoes, slots,
                                               ordem, bandas, state=state)
        self._persiste()
        ip = self.ip.get().strip()
        self.op = op = OperadorGUI(self.fila)
        self.bt_iniciar.state(['disabled'])
        self.bt_abortar.state(['!disabled'])
        self.pb['value'] = 0
        self._log('=' * 60)
        self._log('{} classe {}: {} combinação(ões), nesta ordem:'.format(
            e, classe, len(combos)))
        for k, c in enumerate(combos):
            self._log('  {:2d}. {}'.format(k + 1, '  '.join(v for v in c.values() if v)))
        self._log('Conectando em {} ...'.format(ip))

        def tarefa():
            sa, pasta = None, None
            try:
                sa = self._conecta(ip)
                op.log('VISA: {}'.format(getattr(sa.rm, 'visalib', '?')))
                pasta = seq(sa, op)
                op.log('\nConcluído. Arquivos em: ' + pasta)
            except cap.Cancelado:
                op.log('\nAbortado pelo operador.')
            except Exception as err:
                op.log('\nERRO: {}'.format(err))
            finally:
                if sa is not None:
                    try:
                        sa.set_fullscreen(False)
                    except Exception:
                        pass
                    sa.close()
                self.fila.put(('fim', pasta))

        threading.Thread(target=tarefa, daemon=True).start()

    def _abortar(self):
        if self.op is not None and messagebox.askyesno(APP, 'Abortar a captura?'):
            self.op.abortar.set()
            self._some_aviso()

    # aviso piscando
    def _mostra_aviso(self, texto, pular=False):
        self._aviso_on = True
        self.aviso.config(text=texto)
        self.bt_continuar.state(['!disabled'])
        self.bt_pular.state(['!disabled'] if pular else ['disabled'])
        self.nb.select(self.aba_cap)
        self.root.deiconify()
        self.root.lift()
        self.bt_continuar.focus_set()
        self._pisca(0)

    def _pisca(self, i):
        if not getattr(self, '_aviso_on', False):
            return
        bg, fg = (('#c0392b', '#ffe66d'), ('#f1c40f', '#000000'))[i % 2]
        self.aviso.config(bg=bg, fg=fg)
        self.root.after(500, self._pisca, i + 1)

    def _some_aviso(self):
        self._aviso_on = False
        self.aviso.config(text='', bg=self.root.cget('bg'))
        self.bt_continuar.state(['disabled'])
        self.bt_pular.state(['disabled'])

    def _continuar(self):
        if getattr(self, '_aviso_on', False) and self.op is not None:
            self._some_aviso()
            self.op.responde()

    def _pular(self):
        """Segue para a proxima combinacao sem medir esta."""
        if not (getattr(self, '_aviso_on', False) and self.op is not None
                and self.bt_pular.instate(['!disabled'])):
            return
        if not messagebox.askyesno(
                APP, 'Pular esta combinação e seguir para a próxima?\n\n'
                     'Ela fica sem medir; a lista das puladas sai no log no fim.'):
            return
        self._some_aviso()
        self.op.responde(cap.PULAR)

    # ------------------------------------------------------------------
    # Analise
    # ------------------------------------------------------------------
    def _monta_analise(self):
        f = self.aba_an
        f.columnconfigure(1, weight=1)
        f.rowconfigure(0, weight=1)

        esq = ttk.Frame(f)
        esq.grid(row=0, column=0, sticky='ns', padx=(0, 6))
        esq.rowconfigure(1, weight=1)
        bts = ttk.Frame(esq)
        bts.grid(row=0, column=0, columnspan=2, sticky='ew', pady=(0, 4))
        ttk.Button(bts, text='Atualizar', command=self.atualiza_arvore).pack(side='left')
        ttk.Button(bts, text='Abrir pasta...', command=self._abre_pasta).pack(side='left', padx=4)
        ttk.Button(bts, text='Excluir', command=self._excluir).pack(side='left')
        self.arv = ttk.Treeview(esq, show='tree', selectmode='browse')
        self.arv.column('#0', width=260)
        sb = ttk.Scrollbar(esq, command=self.arv.yview)
        self.arv.configure(yscrollcommand=sb.set)
        self.arv.grid(row=1, column=0, sticky='ns')
        sb.grid(row=1, column=1, sticky='ns')
        self.arv.bind('<<TreeviewSelect>>', self._seleciona)
        self.arv.bind('<Delete>', lambda e: self._excluir())

        dir_ = ttk.Frame(f)
        dir_.grid(row=0, column=1, sticky='nsew')
        dir_.columnconfigure(0, weight=1)
        dir_.rowconfigure(1, weight=1)
        self.fig = Figure(figsize=(9, 5), dpi=100, facecolor=an.BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=dir_)
        topo = ttk.Frame(dir_)
        topo.grid(row=0, column=0, sticky='ew')
        barra = ttk.Frame(topo)
        barra.pack(fill='x')
        self.toolbar = NavigationToolbar2Tk(self.canvas, barra, pack_toolbar=False)
        self.toolbar.pack(side='left')
        ttk.Button(barra, text='Salvar PNG', command=self._salva_png).pack(side='right')
        ttk.Button(barra, text='Salvar todos...',
                   command=self._salva_todos).pack(side='right', padx=4)
        # ao trocar de grafico, mantem a escala que esta na tela
        opc = ttk.Frame(topo)
        opc.pack(fill='x', pady=(2, 0))
        self.trava_amp = tk.BooleanVar(value=bool(self.cfg.get('trava_amp')))
        self.trava_freq = tk.BooleanVar(value=bool(self.cfg.get('trava_freq')))
        ttk.Checkbutton(opc, text='Travar amplitude', variable=self.trava_amp).pack(side='left')
        ttk.Checkbutton(opc, text='Travar frequência',
                        variable=self.trava_freq).pack(side='left', padx=8)
        self.bt_marcas = ttk.Button(opc, command=self._limpa_marcas)
        self.bt_marcas.pack(side='left')
        ttk.Label(opc, text='clique = marca um ponto (clique nela remove)   |   '
                            'arraste = ΔF, duplo clique limpa   |   legenda liga/desliga',
                  foreground='gray').pack(side='right')
        self._atualiza_marcas(salva=False)
        self.canvas.get_tk_widget().grid(row=1, column=0, sticky='nsew')

        cols = ('curva', 'freq', 'valor', 'limite', 'margem')
        self.tab = ttk.Treeview(dir_, columns=cols, show='headings', height=7)
        for col, titulo, w in zip(cols, ('Curva', 'Freq (MHz)', 'Valor (dBuV)',
                                         'Limite (dBuV)', 'Margem (dB)'),
                                  (180, 100, 100, 100, 100)):
            self.tab.heading(col, text=titulo)
            self.tab.column(col, width=w, anchor='w' if col == 'curva' else 'e')
        # Tk 8.6.9 (o do Python 3.8) ignora a cor das tags do Treeview; tirar
        # do estilo as regras '!disabled'/'!selected' devolve a cor
        estilo = ttk.Style()
        for opcao in ('foreground', 'background'):
            estilo.map('Treeview', **{opcao: [
                e for e in estilo.map('Treeview', query_opt=opcao)
                if e[:2] != ('!disabled', '!selected')]})
        self.tab.tag_configure('fora', foreground='#c0392b')
        self.tab.grid(row=2, column=0, sticky='ew', pady=(6, 0))
        self.lb_tab = ttk.Label(dir_, text='', foreground='gray')
        self.lb_tab.grid(row=3, column=0, sticky='w')
        self.medida_atual = None

    def atualiza_arvore(self, selecionar=None):
        """Refaz a arvore; *selecionar* e uma pasta a abrir (ex.: recem-capturada).

        Ensaio > data > hora da execucao > medida. As medidas sem subpasta
        de hora (capturas antigas) ficam direto embaixo da data.
        """
        self.arv.delete(*self.arv.get_children())
        self.medidas, self.grupos = {}, {}
        nos = {}
        alvo = None
        for m in an.lista_medidas(self.raiz.get()):
            pai = ''
            niveis = [(m['tipo'], m['tipo']), (m['tipo'] + m['data'], m['data'])]
            if m['hora']:
                niveis.append((m['tipo'] + m['data'] + m['hora'], m['hora']))
            for chave, texto in niveis:
                if chave not in nos:
                    nos[chave] = self.arv.insert(pai, 'end', text=texto, open=True)
                pai = nos[chave]
            iid = self.arv.insert(pai, 'end', text=m['nome'])
            self.medidas[iid] = m
            if m['hora']:
                self.grupos.setdefault(pai, []).append(m)
            if selecionar and alvo is None and os.path.normcase(m['pasta']) == \
                    os.path.normcase(selecionar):
                alvo = iid
        if alvo:
            self.arv.see(alvo)
            self.arv.selection_set(alvo)

    def _excluir(self):
        """Apaga a medida selecionada, ou a execucao (hora) inteira."""
        sel = self.arv.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in self.medidas:
            alvos = [self.medidas[iid]]
            oque = 'a medida "{}"'.format(alvos[0]['nome'])
        elif iid in self.grupos:
            alvos = self.grupos[iid]
            oque = 'a execução das {} ({} medidas)'.format(self.arv.item(iid, 'text'),
                                                           len(alvos))
        else:
            messagebox.showinfo(APP, 'Selecione uma medida ou uma execução (hora) '
                                     'para excluir.')
            return
        arquivos = [p for m in alvos for p in an.arquivos_de(m)]
        m0 = alvos[0]
        if not messagebox.askyesno(
                APP, 'Excluir {} de {} {}?\n\n{} arquivo(s) em\n{}\n\n'
                     'Não vai para a lixeira: não dá para desfazer.'.format(
                         oque, m0['tipo'], m0['data'], len(arquivos), m0['pasta']),
                icon='warning', default='no'):
            return
        try:
            for m in alvos:
                an.exclui(m, self.raiz.get())
        except (OSError, ValueError) as e:
            messagebox.showerror(APP, 'Não foi possível excluir:\n{}'.format(e))
        if self.medida_atual in alvos:
            self.medida_atual = None
            self.fig.clear()
            self.canvas.draw_idle()
            self.tab.delete(*self.tab.get_children())
            self.lb_tab.config(text='')
        self.atualiza_arvore()

    def _abre_pasta(self):
        d = filedialog.askdirectory(title='Pasta com os CSVs de uma medida',
                                    initialdir=self.raiz.get())
        if not d:
            return
        d = os.path.normpath(d)
        # layout novo: aceita a pasta das medidas, a do ensaio ou Traces/Imagens
        base = d
        if os.path.basename(d).lower() in ('traces', 'imagens'):
            base = os.path.dirname(os.path.dirname(d))
        elif os.path.basename(d) in ENSAIOS:
            base = os.path.dirname(d)
        novos = an.medidas_novas(base)
        grupos = an.grupos_conduzida(d)
        if novos:
            itens = sorted(novos, key=lambda m: (m['tipo'] != 'Radiada', m['data'], m['hora']),
                           reverse=False)
            for m in itens:
                m['nome'] = '{} {} {}  {}'.format(m['tipo'][:3], m['data'], m['hora'], m['nome'])
        elif grupos:
            itens = [dict(tipo='Conduzida', data='', hora='', pasta=d, chave=k,
                          nome='{} - {}'.format(*k)) for k in sorted(grupos)]
        else:
            itens = [dict(tipo='Radiada', data='', hora='', pasta=d, chave=None,
                          nome=os.path.basename(d))]
        pai = self.arv.insert('', 0, text=d, open=True)
        for m in itens:
            self.medidas[self.arv.insert(pai, 'end', text=m['nome'])] = m
        self.arv.selection_set(self.arv.get_children(pai)[0])

    def _seleciona(self, _=None):
        sel = self.arv.selection()
        m = self.medidas.get(sel[0]) if sel else None
        if m is None:
            return
        # escala que esta na tela, para repetir no proximo grafico se travada
        xlim = ylim = None
        if self.fig.axes and self.medida_atual is not None:
            if self.trava_freq.get():
                xlim = self.fig.axes[0].get_xlim()
            if self.trava_amp.get():
                ylim = self.fig.axes[0].get_ylim()
        try:
            tabela = an.plota(self.fig, m, self.marcas, self._atualiza_marcas)
        except Exception as e:
            messagebox.showerror(APP, 'Não foi possível plotar {}:\n{}'.format(m['nome'], e))
            return
        # o "Home" da barra volta para a escala cheia; a travada entra depois
        ax = self.fig.axes[0]
        self.toolbar.update()
        self.toolbar.push_current()
        x0, x1 = ax.get_xlim()
        if xlim and xlim[0] < x1 and xlim[1] > x0:      # so se a faixa existe aqui
            ax.set_xlim(xlim)
        if ylim:
            ax.set_ylim(ylim)
        if xlim or ylim:
            self.toolbar.push_current()
            self.canvas.draw_idle()
        self.medida_atual = m
        self.tab.delete(*self.tab.get_children())
        for curva, fq, v, lim, mg in tabela:
            self.tab.insert('', 'end', tags=('fora',) if mg > 0 else (),
                            values=(curva, '{:.3f}'.format(fq), '{:.1f}'.format(v),
                                    '{:.1f}'.format(lim), '{:+.1f}'.format(mg)))
        fora = sum(1 for r in tabela if r[4] > 0)
        self.lb_tab.config(text=(
            '{} pico(s) acima do limite; {} a menos de {:g} dB dele.'.format(
                fora, len(tabela) - fora, an.JANELA_DB) if tabela
            else 'Nenhum pico a menos de {:g} dB do limite (ou medida sem limite).'.format(
                an.JANELA_DB)))

    def _atualiza_marcas(self, salva=True):
        """Depois de marcar/desmarcar um ponto: contador no botao e config."""
        n = len(self.marcas)
        self.bt_marcas.config(text='Limpar marcas ({})'.format(n) if n else 'Limpar marcas',
                              state='normal' if n else 'disabled')
        if salva:
            self.cfg['marcas'] = self.marcas
            save_config(self.cfg)

    def _limpa_marcas(self):
        del self.marcas[:]
        redesenha = getattr(self.fig, '_emissao_marcas', None)
        if redesenha and self.fig.axes:
            redesenha()
            self.canvas.draw_idle()
        self._atualiza_marcas()

    @staticmethod
    def _nome_png(m):
        """'Radiada - V - 48 (full band) - 2026-11-16 12h45.png': o que a arvore
        mostra, com a data e a hora no fim."""
        partes = [m['tipo'], m['nome'],
                  ' '.join(x for x in (m['data'], m['hora'].replace(':', 'h')) if x)]
        nome = ' - '.join(x for x in partes if x) + '.png'
        return ''.join('_' if c in '\\/:*?"<>|' else c for c in nome)

    def _salva_png(self):
        m = self.medida_atual
        if m is None:
            return
        path = filedialog.asksaveasfilename(
            title='Salvar gráfico', initialdir=self.cfg.get('pasta_png') or m['pasta'],
            initialfile=self._nome_png(m), defaultextension='.png',
            filetypes=[('PNG', '*.png')])
        if path:
            self.fig.savefig(path, dpi=150, facecolor=self.fig.get_facecolor())

    def _folhas(self, iid):
        """Medidas do ramo *iid* da arvore (a propria, se for uma medida)."""
        if iid in self.medidas:
            return [self.medidas[iid]]
        return [m for filho in self.arv.get_children(iid) for m in self._folhas(filho)]

    def _salva_todos(self):
        """Exporta os graficos do ramo selecionado para uma pasta so.

        Todos saem com a escala que esta na tela e com as marcas, no tamanho
        do grafico da janela. A frequencia da tela so e usada nas medidas que
        tem essa faixa (como na trava de frequencia).
        """
        sel = self.arv.selection()
        alvos = self._folhas(sel[0]) if sel else []
        if not alvos:
            messagebox.showinfo(APP, 'Selecione na árvore o ramo a exportar: um ensaio, '
                                     'uma data, uma execução (hora) ou uma medida.')
            return
        xlim = ylim = None
        if self.fig.axes and self.medida_atual is not None:
            xlim, ylim = self.fig.axes[0].get_xlim(), self.fig.axes[0].get_ylim()
        ramo = ' > '.join(reversed([self.arv.item(i, 'text') for i in self._caminho(sel[0])]))
        pasta = filedialog.askdirectory(
            title='Pasta para os {} gráfico(s) de "{}"'.format(len(alvos), ramo),
            initialdir=self.cfg.get('pasta_png') or self.raiz.get())
        if not pasta:
            return
        pasta = os.path.normpath(pasta)
        existem = [m for m in alvos if os.path.exists(os.path.join(pasta, self._nome_png(m)))]
        if existem and not messagebox.askyesno(
                APP, '{} de {} arquivo(s) já existem em\n{}\n\nSubstituir?'.format(
                    len(existem), len(alvos), pasta), icon='warning'):
            return
        self.cfg['pasta_png'] = pasta
        save_config(self.cfg)

        fig = Figure(figsize=self.fig.get_size_inches(), dpi=100, facecolor=an.BG)
        FigureCanvasAgg(fig)
        erros = []
        self.root.config(cursor='watch')
        try:
            for k, m in enumerate(alvos):
                self.lb_tab.config(text='Salvando {}/{}: {}'.format(k + 1, len(alvos),
                                                                   self._nome_png(m)))
                self.root.update_idletasks()
                try:
                    an.plota(fig, m, list(self.marcas))
                    ax = fig.axes[0]
                    x0, x1 = ax.get_xlim()
                    if xlim and xlim[0] < x1 and xlim[1] > x0:
                        ax.set_xlim(xlim)
                    if ylim:
                        ax.set_ylim(ylim)
                    fig.savefig(os.path.join(pasta, self._nome_png(m)), dpi=150,
                                facecolor=fig.get_facecolor())
                except Exception as e:
                    erros.append('{}: {}'.format(self._nome_png(m), e))
        finally:
            self.root.config(cursor='')
        ok = len(alvos) - len(erros)
        self.lb_tab.config(text='{} gráfico(s) salvos em {}'.format(ok, pasta))
        if erros:
            messagebox.showwarning(APP, '{} gráfico(s) salvos em\n{}\n\nNão saíram:\n{}'.format(
                ok, pasta, '\n'.join(erros[:10])))
        else:
            messagebox.showinfo(APP, '{} gráfico(s) salvos em\n{}'.format(ok, pasta))

    def _caminho(self, iid):
        """iids de *iid* ate a raiz da arvore."""
        cam = []
        while iid:
            cam.append(iid)
            iid = self.arv.parent(iid)
        return cam

    # ------------------------------------------------------------------
    # Fila da thread de captura
    # ------------------------------------------------------------------
    def _poll(self):
        try:
            while True:
                tipo, dado = self.fila.get_nowait()
                if tipo == 'log':
                    self._log(dado)
                elif tipo == 'prog':
                    i, n = dado
                    self.pb['value'] = 100.0 * i / n if n else 0
                elif tipo == 'prompt':
                    texto, pular = dado
                    self._log('\n>>> ' + texto)
                    _beep([(800, 400)])
                    self._mostra_aviso(texto, pular)
                elif tipo == 'confirma':
                    _beep([(800, 400)])
                    self.root.deiconify()
                    self.root.lift()
                    r = messagebox.askyesnocancel(
                        APP, dado + '\n\nCancelar: aborta a sequência.')
                    if r is None:
                        self.op.abortar.set()
                    self.op.responde(r)
                elif tipo == 'idn':
                    self.lb_idn.config(text=dado[0], foreground=dado[1])
                    self.bt_testar.state(['!disabled'])
                elif tipo == 'fim':
                    self.op = None
                    self._some_aviso()
                    self.bt_iniciar.state(['!disabled'])
                    self.bt_abortar.state(['disabled'])
                    if dado:
                        self.atualiza_arvore(selecionar=dado)
                        self.nb.select(self.aba_an)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _fechar(self):
        if self.op is not None:
            if not messagebox.askyesno(APP, 'Há uma captura em andamento. Abortar e sair?'):
                return
            self.op.abortar.set()
        self._persiste()
        self.root.destroy()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
