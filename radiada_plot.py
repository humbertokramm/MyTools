"""
radiada_plot.py  --  Analise de emissao radiada (Agilent N9010A CSV)

Uso -- arquivo unico:
    python radiada_plot.py <eut.csv> <amb.csv> [<limit.csv>]

Uso -- combinar sub-bandas (glob pattern):
    python radiada_plot.py "*EUT*.csv" "*Ambiente*.csv" [<limit.csv>]
    python radiada_plot.py "C:/pasta/*EUT*.csv" "C:/pasta/*Ambiente*.csv" limit.csv
"""

import sys
import os
import glob
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.widgets import SpanSelector


# -----------------------------------------------------------------------
# Parsing
# -----------------------------------------------------------------------

def _parse_csv(path):
    """Retorna (meta, freq_hz, amp_dbuv) de um CSV Agilent N9010A trace."""
    meta = {}
    freq, amp = [], []
    in_data = False
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line == 'DATA':
                in_data = True
                continue
            if not in_data:
                parts = line.split(',', 1)
                if len(parts) == 2:
                    meta[parts[0].strip()] = parts[1].strip()
            else:
                parts = line.split(',')
                if len(parts) >= 2:
                    try:
                        freq.append(float(parts[0]))
                        amp.append(float(parts[1]))
                    except ValueError:
                        pass
    return meta, np.array(freq), np.array(amp)


def _parse_limit(path):
    """Retorna (freq_hz, lim_dbuv) de um CSV de limite Agilent (X eixo em MHz)."""
    _, freq_mhz, lim = _parse_csv(path)
    return freq_mhz * 1e6, lim


# -----------------------------------------------------------------------
# Multi-file stitch
# -----------------------------------------------------------------------

def _resolve_paths(pattern):
    """Expande glob pattern ou retorna lista com o arquivo unico."""
    if '*' in pattern or '?' in pattern:
        paths = sorted(glob.glob(pattern))
        if not paths:
            raise FileNotFoundError('Nenhum arquivo encontrado para: ' + pattern)
        return paths
    return [pattern]


def stitch_csvs(paths):
    """Combina multiplos CSVs de sub-bandas em um unico trace.

    Os arquivos sao ordenados pela frequencia inicial e concatenados.
    Retorna (meta, freq_hz, amp_dbuv) como _parse_csv, porem com
    resolucao equivalente a soma de todos os segmentos.
    """
    segments = []
    for p in paths:
        meta, f, a = _parse_csv(p)
        segments.append((f[0], f, a, meta))

    segments.sort(key=lambda s: s[0])

    all_freq = np.concatenate([s[1] for s in segments])
    all_amp  = np.concatenate([s[2] for s in segments])

    # usa metadata do primeiro segmento como base
    base_meta = segments[0][3].copy()
    base_meta['Start Frequency'] = str(all_freq[0])
    base_meta['Stop Frequency']  = str(all_freq[-1])
    base_meta['Number of Points'] = str(len(all_freq))
    base_meta['_stitched'] = str(len(segments)) + ' segmentos'

    print('Stitched: {} arquivos, {} pontos  ({:.0f}-{:.0f} MHz)'.format(
        len(segments), len(all_freq),
        all_freq[0] / 1e6, all_freq[-1] / 1e6
    ))
    return base_meta, all_freq, all_amp


def _load_trace(path_or_pattern):
    """Carrega um trace: string (arquivo ou glob) ou lista de caminhos."""
    if isinstance(path_or_pattern, (list, tuple)):
        paths = sorted(path_or_pattern)
    else:
        paths = _resolve_paths(path_or_pattern)
    if len(paths) == 1:
        return _parse_csv(paths[0])
    return stitch_csvs(paths)


def _interp_limit(freq_hz, lim_freq_hz, lim_amp):
    """Interpola limite na grade de frequência do trace (log em freq, conforme Agilent)."""
    log_f     = np.log10(freq_hz)
    log_lim_f = np.log10(lim_freq_hz)
    return np.interp(log_f, log_lim_f, lim_amp)


# -----------------------------------------------------------------------
# Detecção de picos acima do limite
# -----------------------------------------------------------------------

def _find_peaks(freq_mhz, net, lim, min_sep_mhz=1.0):
    """Retorna índices dos picos mais altos de cada grupo que excede o limite."""
    margin = net - lim
    exceed_idx = np.where(margin > 0)[0]
    if len(exceed_idx) == 0:
        return []

    df_mhz = float(freq_mhz[1] - freq_mhz[0])
    min_sep_pts = max(1, int(min_sep_mhz / df_mhz))

    peaks = []
    grp = [exceed_idx[0]]
    for i in exceed_idx[1:]:
        if i - grp[-1] <= min_sep_pts:
            grp.append(i)
        else:
            peaks.append(grp[int(np.argmax(margin[grp]))])
            grp = [i]
    peaks.append(grp[int(np.argmax(margin[grp]))])
    return peaks


def _print_peaks(freq_mhz, net, lim, peaks):
    print(f"\n{'Freq (MHz)':>12}  {'EUT-Amb (dBuV)':>14}  {'Limite (dBuV)':>13}  {'Margem (dB)':>11}")
    print("-" * 56)
    for p in sorted(peaks, key=lambda i: -(net - lim)[i]):
        m = net[p] - lim[p]
        print(f"{freq_mhz[p]:>12.3f}  {net[p]:>14.1f}  {lim[p]:>13.1f}  {m:>+11.1f}")
    print()


# -----------------------------------------------------------------------
# Plot
# -----------------------------------------------------------------------

_PALETTES = [
    # Máx  — amarelo (igual ao instrumento), cinza escuro Amb, laranja Net
    dict(eut='#ffd166', amb='#666666', net='#f4a261', ls='-', lw=1.2),
    # Méd  — ciano   (igual ao instrumento), cinza médio Amb, verde Net
    dict(eut='#26c6da', amb='#999999', net='#81c784', ls='-', lw=0.9),
]

def _lbl(prefix, suffix):
    return prefix + (' ' + suffix if suffix else '')


def _fmt_freq(f):
    if f >= 1000:    return f"{f:.6g} GHz" if f >= 1000 else f"{f:.6g} MHz"
    if f >= 1:       return f"{f:.6g} MHz"
    if f >= 1e-3:    return f"{f*1e3:.6g} kHz"
    return                  f"{f*1e6:.6g} Hz"

def _fmt_span(fmin, fmax):
    df = fmax - fmin
    if df >= 1:      delta = f"ΔF = {df:.4g} MHz"
    elif df >= 1e-3: delta = f"ΔF = {df*1e3:.4g} kHz"
    else:            delta = f"ΔF = {df*1e6:.4g} Hz"
    return f"{_fmt_freq(fmin)}  →  {_fmt_freq(fmax)}\n{delta}"


def analyze(trace_sets, limit_path=None):
    """
    trace_sets: list of (eut_path, amb_path, label)
    label: 'Máx', 'Méd', '' etc.
    Picos e violações são marcados sobre o primeiro conjunto (geralmente Máx).
    """
    BG    = '#1c1c1c'
    GRID  = '#2e2e2e'
    SPINE = '#555'
    TXT   = '#cccccc'

    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(SPINE)
    ax.tick_params(colors=TXT, which='both')
    ax.xaxis.label.set_color(TXT)
    ax.yaxis.label.set_color(TXT)
    ax.title.set_color('#eeeeee')

    loaded = []
    for i, (eut_p, amb_p, lbl) in enumerate(trace_sets):
        _, f_eut, a_eut = _load_trace(eut_p)
        _, f_amb, a_amb = _load_trace(amb_p)
        if not np.array_equal(f_eut, f_amb):
            a_amb = np.interp(f_eut, f_amb, a_amb)
        net = a_eut - a_amb
        freq_mhz = f_eut / 1e6
        pal = _PALETTES[i % len(_PALETTES)]
        loaded.append((freq_mhz, f_eut, a_eut, a_amb, net, pal, lbl))

    all_lines = {}

    for freq_mhz, _, a_eut, a_amb, net, pal, lbl in loaded:
        ls, lw = pal['ls'], pal['lw']
        l_amb, = ax.plot(freq_mhz, a_amb, color=pal['amb'], lw=0.7, alpha=0.5,
                         ls=ls, label=_lbl('Ambiente', lbl))
        l_eut, = ax.plot(freq_mhz, a_eut, color=pal['eut'], lw=0.8, alpha=0.8,
                         ls=ls, label=_lbl('EUT', lbl))
        l_net, = ax.plot(freq_mhz, net,   color=pal['net'], lw=lw,
                         ls=ls, label=_lbl('EUT - Ambiente', lbl))
        all_lines[_lbl('Ambiente', lbl)]      = l_amb
        all_lines[_lbl('EUT', lbl)]           = l_eut
        all_lines[_lbl('EUT - Ambiente', lbl)] = l_net

    # ── Limite e picos (sobre o primeiro conjunto) ───────────────────────
    if limit_path and os.path.isfile(limit_path):
        freq_mhz0, f_eut0, _, _, net0, _, _ = loaded[0]
        lim_freq_hz, lim_amp = _parse_limit(limit_path)
        lim = _interp_limit(f_eut0, lim_freq_hz, lim_amp)

        l_lim, = ax.plot(freq_mhz0, lim, color='#e63946', lw=1.5, ls='--', label='Limite')
        all_lines['Limite'] = l_lim

        exceed = net0 > lim
        if exceed.any():
            ax.fill_between(freq_mhz0, net0, lim, where=exceed,
                            color='#e63946', alpha=0.20, zorder=2)

        peaks = _find_peaks(freq_mhz0, net0, lim)
        if peaks:
            ax.scatter(freq_mhz0[peaks], net0[peaks],
                       color='#e63946', s=18, zorder=5, label='_nolegend_')
            _print_peaks(freq_mhz0, net0, lim, peaks)
        else:
            print("\nNenhum pico acima do limite.\n")

    # ── Eixos ────────────────────────────────────────────────────────────
    ax.set_xscale('log')
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(
        lambda x, _: f'{int(x)}' if x == int(x) else f'{x:.0f}'
    ))
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())

    def _lp(p):
        if isinstance(p, (list, tuple)):
            return '{} arq.'.format(len(p))
        return os.path.basename(p) if '*' not in str(p) else str(p)

    eut0_p, amb0_p, _ = trace_sets[0]
    ax.set_title('Emissão Radiada  —  ' + _lp(eut0_p) + '  vs  ' + _lp(amb0_p),
                 color='#eeeeee')
    ax.set_xlabel('Frequência (MHz)')
    ax.set_ylabel('Amplitude (dBuV)')
    ax.grid(True, which='major', color=GRID, lw=0.8)
    ax.grid(True, which='minor', color=GRID, lw=0.3)
    ax.set_xlim(loaded[0][0][0], loaded[0][0][-1])

    # ── Legenda interativa ───────────────────────────────────────────────
    leg = ax.legend(loc='upper right',
                    facecolor='#2a2a2a', edgecolor=SPINE, labelcolor=TXT)
    mapa = {}
    for ll in leg.get_lines():
        ll.set_picker(5)
        orig = all_lines.get(ll.get_label())
        if orig:
            mapa[ll] = orig

    def on_pick(event):
        orig = mapa.get(event.artist)
        if orig:
            vis = not orig.get_visible()
            orig.set_visible(vis)
            event.artist.set_alpha(1.0 if vis else 0.2)
            fig.canvas.draw()

    fig.canvas.mpl_connect('pick_event', on_pick)

    # ── SpanSelector  ΔF ────────────────────────────────────────────────
    fig._span_text = None
    fig._span_rect = None

    def on_span(xmin, xmax):
        if abs(xmax - xmin) < 1e-9:
            return
        for attr in ('_span_text', '_span_rect'):
            obj = getattr(fig, attr)
            if obj is not None:
                try:
                    obj.remove()
                except Exception:
                    pass
        ymid = ax.get_ylim()[1]
        fig._span_rect = ax.axvspan(xmin, xmax, alpha=0.15,
                                    color='steelblue', zorder=1)
        fig._span_text = ax.text(
            np.sqrt(xmin * xmax), ymid, _fmt_span(xmin, xmax),
            ha='center', va='top', fontsize=10, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='steelblue',
                      alpha=0.85, edgecolor='none'),
            color='white', zorder=10,
        )
        fig.canvas.draw()

    def on_dblclick(event):
        if event.dblclick and event.inaxes is ax:
            for attr in ('_span_text', '_span_rect'):
                obj = getattr(fig, attr)
                if obj is not None:
                    try:
                        obj.remove()
                    except Exception:
                        pass
                    setattr(fig, attr, None)
            fig.canvas.draw()

    fig._span = SpanSelector(ax, on_span, 'horizontal', useblit=False,
                             props=dict(alpha=0.12, facecolor='steelblue'))
    fig.canvas.mpl_connect('button_press_event', on_dblclick)

    plt.tight_layout()
    plt.show()


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

def _find_in_folder(folder):
    """Varre a pasta por CSVs, detecta pares Máx/Méd por sufixo no nome.

    Retorna (trace_sets, limit_path) onde trace_sets é uma lista de
    (eut_path_ou_lista, amb_path_ou_lista, label).
    """
    csvs = sorted(glob.glob(os.path.join(folder, '*.csv')))
    if not csvs:
        raise FileNotFoundError('Nenhum CSV encontrado em: ' + folder)

    def _pick(pool, *keys):
        return [p for p in pool
                if any(k in os.path.basename(p).lower() for k in keys)]

    eut_all = _pick(csvs, 'eut')
    amb_all = _pick(csvs, 'ambiente')
    lim_all = _pick(csvs, 'limite', 'limit')

    if not eut_all:
        raise FileNotFoundError('Nenhum CSV com "EUT" no nome em: ' + folder)
    if not amb_all:
        raise FileNotFoundError('Nenhum CSV com "Ambiente" no nome em: ' + folder)

    eut_max = _pick(eut_all, '- max', '_max')
    eut_med = _pick(eut_all, '- med', '_med', '- avg', '_avg')
    amb_max = _pick(amb_all, '- max', '_max')
    amb_med = _pick(amb_all, '- med', '_med', '- avg', '_avg')

    def _wrap(files):
        return files[0] if len(files) == 1 else files

    trace_sets = []
    if eut_max and amb_max:
        trace_sets.append((_wrap(eut_max), _wrap(amb_max), 'Máx'))
    if eut_med and amb_med:
        trace_sets.append((_wrap(eut_med), _wrap(amb_med), 'Méd'))
    if not trace_sets:
        trace_sets = [(_wrap(eut_all), _wrap(amb_all), '')]

    lim = lim_all[0] if lim_all else None

    print('Conjuntos : {}'.format(', '.join(lbl for _, _, lbl in trace_sets) or '1'))
    print('EUT       : {} arquivo(s)'.format(len(eut_all)))
    print('Ambiente  : {} arquivo(s)'.format(len(amb_all)))
    print('Limite    : {}'.format(os.path.basename(lim) if lim else 'não encontrado'))
    return trace_sets, lim


def _gui_pick():
    """Abre seletor de pasta tkinter e retorna (trace_sets, limit_path)."""
    import tkinter as tk
    from tkinter import filedialog, messagebox

    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)

    folder = filedialog.askdirectory(title='Selecione a pasta com os CSVs')
    if not folder:
        sys.exit(0)

    try:
        trace_sets, lim = _find_in_folder(folder)
    except FileNotFoundError as e:
        messagebox.showerror('Erro', str(e))
        root.destroy()
        sys.exit(1)

    root.destroy()
    return trace_sets, lim


if __name__ == '__main__':
    if len(sys.argv) == 2 and os.path.isdir(sys.argv[1]):
        trace_sets, limit_path = _find_in_folder(sys.argv[1])
    elif len(sys.argv) >= 3:
        eut_path   = sys.argv[1]
        amb_path   = sys.argv[2]
        limit_path = sys.argv[3] if len(sys.argv) > 3 else None
        trace_sets = [(eut_path, amb_path, '')]
    else:
        trace_sets, limit_path = _gui_pick()

    analyze(trace_sets, limit_path)
