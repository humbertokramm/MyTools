"""
radiada_plot.py  —  Análise de emissão radiada (Agilent N9010A CSV)

Uso:
    python radiada_plot.py <eut.csv> <amb.csv> [<limit.csv>]
"""

import sys
import os
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

def _fmt_df(df):
    if df >= 1:      return f"ΔF = {df:.4g} MHz"
    if df >= 1e-3:   return f"ΔF = {df*1e3:.4g} kHz"
    return               f"ΔF = {df*1e6:.4g} Hz"


def analyze(eut_path, amb_path, limit_path=None):
    _, f_eut, a_eut = _parse_csv(eut_path)
    _, f_amb, a_amb = _parse_csv(amb_path)

    if not np.array_equal(f_eut, f_amb):
        a_amb = np.interp(f_eut, f_amb, a_amb)

    freq_mhz = f_eut / 1e6
    net = a_eut - a_amb

    lim = None
    if limit_path and os.path.isfile(limit_path):
        lim_freq_hz, lim_amp = _parse_limit(limit_path)
        lim = _interp_limit(f_eut, lim_freq_hz, lim_amp)

    # ── Figura ──────────────────────────────────────────────────────────
    BG     = '#1c1c1c'
    GRID   = '#2e2e2e'
    SPINE  = '#555'
    TXT    = '#cccccc'

    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_edgecolor(SPINE)
    ax.tick_params(colors=TXT, which='both')
    ax.xaxis.label.set_color(TXT)
    ax.yaxis.label.set_color(TXT)
    ax.title.set_color('#eeeeee')

    # traces
    l_amb, = ax.plot(freq_mhz, a_amb, color='#777777', lw=0.7, alpha=0.6, label='Ambiente')
    l_eut, = ax.plot(freq_mhz, a_eut, color='#4ea8de', lw=0.8, alpha=0.8, label='EUT')
    l_net, = ax.plot(freq_mhz, net,   color='#f4a261', lw=1.2,             label='EUT - Ambiente')

    if lim is not None:
        ax.plot(freq_mhz, lim, color='#e63946', lw=1.5, ls='--', label='Limite')

        exceed = net > lim
        if exceed.any():
            ax.fill_between(freq_mhz, net, lim, where=exceed,
                            color='#e63946', alpha=0.20, zorder=2)

        peaks = _find_peaks(freq_mhz, net, lim)
        if peaks:
            ax.scatter(freq_mhz[peaks], net[peaks],
                       color='#e63946', s=18, zorder=5, label='_nolegend_')
            _print_peaks(freq_mhz, net, lim, peaks)
        else:
            print("\nNenhum pico acima do limite.\n")

    # ── Eixos ────────────────────────────────────────────────────────────
    ax.set_xscale('log')
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(
        lambda x, _: f'{int(x)}' if x == int(x) else f'{x:.0f}'
    ))
    ax.xaxis.set_minor_formatter(ticker.NullFormatter())

    eut_name = os.path.basename(eut_path)
    amb_name = os.path.basename(amb_path)
    ax.set_title(f'Emissão Radiada  —  {eut_name}  vs  {amb_name}', color='#eeeeee')
    ax.set_xlabel('Frequência (MHz)')
    ax.set_ylabel('Amplitude (dBuV)')
    ax.grid(True, which='major', color=GRID, lw=0.8)
    ax.grid(True, which='minor', color=GRID, lw=0.3)
    ax.set_xlim(freq_mhz[0], freq_mhz[-1])

    # ── Legenda interativa ───────────────────────────────────────────────
    leg = ax.legend(loc='upper right',
                    facecolor='#2a2a2a', edgecolor=SPINE, labelcolor=TXT)
    mapa = {}
    label_to_line = {l.get_label(): l
                     for l in ax.get_lines()
                     if not l.get_label().startswith('_')}
    for ll in leg.get_lines():
        ll.set_picker(5)
        orig = label_to_line.get(ll.get_label())
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

    def on_span(xmin, xmax):
        df = xmax - xmin
        if abs(df) < 1e-9:
            return
        if fig._span_text is not None:
            try:
                fig._span_text.remove()
            except Exception:
                pass
        ymid = ax.get_ylim()[1]
        fig._span_text = ax.text(
            np.sqrt(xmin * xmax), ymid, _fmt_df(df),
            ha='center', va='top', fontsize=10, fontweight='bold',
            bbox=dict(boxstyle='round,pad=0.3', facecolor='steelblue',
                      alpha=0.85, edgecolor='none'),
            color='white', zorder=10,
        )
        fig.canvas.draw()

    def on_dblclick(event):
        if event.dblclick and event.inaxes is ax:
            if fig._span_text is not None:
                try:
                    fig._span_text.remove()
                except Exception:
                    pass
                fig._span_text = None
            fig.canvas.draw()

    fig._span = SpanSelector(ax, on_span, 'horizontal', useblit=False,
                             props=dict(alpha=0.12, facecolor='steelblue'))
    fig.canvas.mpl_connect('button_press_event', on_dblclick)

    plt.tight_layout()
    plt.show()


# -----------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(f"Uso: python {sys.argv[0]} <eut.csv> <amb.csv> [<limit.csv>]")
        sys.exit(1)

    eut_path   = sys.argv[1]
    amb_path   = sys.argv[2]
    limit_path = sys.argv[3] if len(sys.argv) > 3 else None

    analyze(eut_path, amb_path, limit_path)
