#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prototipo de plot termico (2 subplots) para o ThermalDataCollector.

Uso:
    python thermal_plot2.py -p <output/DM4780/AAAAMMDD_HHMMSS>   [--setpoint sp.json] [--save fig.png]

- Subplot de cima: temperaturas (transceivers + sensores) em C, com o setpoint da camara sobreposto.
- Subplot de baixo: velocidade dos fans em RPM real (sem o /100).
- Legendas de transceiver abreviadas: 'four-hundred-g-ethernet 1/1/2' -> 'TCV 400G-02 temp'.
"""
import argparse
import json
import os
import re
import sqlite3
import time
from datetime import datetime

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.widgets import CheckButtons

TS_FMT = "%Y-%m-%d %H:%M:%S"
SP_FMT = "%d/%m/%Y %H:%M"
SP_AUTO_NAMES = ["sp.json", "setpoint.json", "sp_camara.json"]

RATE = {
    "four-hundred-g-ethernet": "400G",
    "two-hundred-g-ethernet": "200G",
    "hundred-gigabit-ethernet": "100G",
    "forty-gigabit-ethernet": "40G",
    "ten-gigabit-ethernet": "10G",
    "gigabit-ethernet": "1G",
}


def natural_key(label):
    """Ordenacao alfabetica 'natural': 'TCV 100G-02' antes de 'TCV 100G-10'."""
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", label)]


def abbrev_tcv(tid):
    """'four-hundred-g-ethernet 1/1/2' -> 'TCV 400G-02 temp'."""
    m = re.match(r"(?P<rate>[a-z-]+)\s+\d+/\d+/(?P<port>\d+)(?::(?P<lane>\d+))?", tid)
    if not m:
        return tid
    rate = RATE.get(m.group("rate"), m.group("rate"))
    label = "TCV {}-{:02d}".format(rate, int(m.group("port")))
    if m.group("lane"):
        label += ".{}".format(m.group("lane"))
    return label + " temp"


def to_float(v):
    """'24.49  C' -> 24.49 ; 'N/A' -> None."""
    if v is None or v == "N/A":
        return None
    if isinstance(v, str):
        v = v.replace("C", "").strip()
        if not v:
            return None
    try:
        return float(v)
    except ValueError:
        return None


def fetch(cur, table, title_col, value_col, conv):
    """Retorna dict {titulo: ([x_datetime], [y])} ordenado no tempo."""
    q = ("SELECT capture.timestamp, {tcol}, {vcol} FROM {t} "
         "JOIN capture ON {t}.capture_id = capture.id "
         "ORDER BY capture.timestamp").format(tcol=title_col, vcol=value_col, t=table)
    groups = {}
    for ts, title, val in cur.execute(q):
        y = conv(val)
        if y is None:
            continue
        x = datetime.strptime(ts, TS_FMT)
        groups.setdefault(title, ([], []))
        groups[title][0].append(x)
        groups[title][1].append(y)
    return groups


def color_cycle():
    cols = []
    for cmap in ("tab20", "tab20b", "tab20c"):
        cols.extend(matplotlib.colormaps[cmap].colors)
    return cols


def load_setpoint(path):
    """Aceita JSON puro ou o formato 'SP = { ... }' (com virgula final tolerada)."""
    with open(path, encoding="utf-8-sig") as f:
        text = f.read()
    text = re.sub(r"^\s*\w+\s*=\s*", "", text)          # remove prefixo 'SP ='
    text = re.sub(r",(\s*[}\]])", r"\1", text)           # remove virgula sobrando antes de } ou ]
    raw = json.loads(text)
    pts = sorted((datetime.strptime(k, SP_FMT), float(v)) for k, v in raw.items())
    return pts


def read_series(db, groups):
    """Le o SQLite e retorna (fan_series, temp_series) como dicts label->(xs, ys),
    ja com a abreviacao dos transceivers e a regra dos sensores de plataforma.

    Sensores de plataforma (CPU Core, PSU..., Switch Fabric Core) SEMPRE entram no
    grupo de temperatura; as leituras 'TCV ...' do environment so entram se
    'temperature_sensor' estiver em groups. Abre conexao propria com timeout, para
    tolerar o coletor gravando ao mesmo tempo (modo ao vivo)."""
    need_fan = "fan" in groups
    need_temp = ("transceiver" in groups) or ("temperature_sensor" in groups)
    con = sqlite3.connect(db, timeout=5.0)
    try:
        cur = con.cursor()
        tcv = fetch(cur, "transceiver", "transceiver_id", "temperature", to_float) \
            if "transceiver" in groups else {}
        all_sensor = fetch(cur, "temperature_sensor", "sensor_name", "temperature", to_float) \
            if need_temp else {}
        fan = fetch(cur, "fan", "fan_id", "speed", to_float) if need_fan else {}
    finally:
        con.close()

    is_tcv_env = re.compile(r"^TCV \d+G \d+/\d+/\d+$")
    sensor = {n: xy for n, xy in all_sensor.items() if not is_tcv_env.match(n)}
    if "temperature_sensor" in groups:
        for n, xy in all_sensor.items():
            if is_tcv_env.match(n):
                sensor[n] = xy

    temp_series = {}
    for tid, xy in tcv.items():
        temp_series[abbrev_tcv(tid)] = xy
    for n, xy in sensor.items():
        temp_series[n] = xy
    return dict(fan), temp_series


def main():
    ap = argparse.ArgumentParser(description="Plot termico 2-subplots (prototipo)")
    ap.add_argument("-p", "--path", required=True,
                    help="Pasta da coleta ou caminho do SQLite.db")
    ap.add_argument("--setpoint",
                    help="JSON com setpoints da camara {{'dd/mm/aaaa HH:MM': valor}}. "
                         "Se omitido, procura automaticamente por {} na pasta da coleta."
                         .format("/".join(SP_AUTO_NAMES)))
    ap.add_argument("-g", "--plot", nargs="*", default=None,
                    choices=["fan", "transceiver", "temperature_sensor"],
                    help="Grupos a plotar (default: todos). Ex: --plot fan temperature_sensor")
    ap.add_argument("--save", help="Salva a figura no PNG informado (headless) em vez de exibir")
    ap.add_argument("--live", action="store_true",
                    help="Atualiza o grafico ao vivo, relendo o banco enquanto a coleta acontece")
    ap.add_argument("--interval", type=float, default=10.0,
                    help="Intervalo (s) entre atualizacoes no modo --live (default: 10)")
    args = ap.parse_args()

    groups = args.plot if args.plot else ["fan", "transceiver", "temperature_sensor"]
    need_fan = "fan" in groups
    need_temp = ("transceiver" in groups) or ("temperature_sensor" in groups)

    coleta_dir = args.path if os.path.isdir(args.path) else os.path.dirname(os.path.abspath(args.path))
    db = args.path
    if os.path.isdir(db):
        db = os.path.join(db, "SQLite.db")
    model = os.path.basename(os.path.dirname(os.path.dirname(os.path.abspath(db)))) or "DmOS"

    setpoint_path = args.setpoint
    if not setpoint_path:
        for name in SP_AUTO_NAMES:
            candidate = os.path.join(coleta_dir, name)
            if os.path.isfile(candidate):
                setpoint_path = candidate
                print("Setpoint detectado automaticamente:", candidate)
                break

    if args.save:
        matplotlib.use("Agg")

    if args.save:
        matplotlib.use("Agg")

    pts = load_setpoint(setpoint_path) if setpoint_path else []

    def any_points(*dicts):
        return any(xy[0] for d in dicts for xy in d.values())

    def safe_read():
        if not os.path.isfile(db):
            return {}, {}
        try:
            return read_series(db, groups)
        except sqlite3.Error as e:
            print("Aviso ao ler o banco:", e)
            return {}, {}

    # Leitura inicial. No modo ao vivo, espera ate haver algum dado (o usuario pode
    # abrir o grafico antes de a coleta comecar a gravar).
    fan_series, temp_series = safe_read()
    if args.live:
        while not any_points(fan_series, temp_series):
            print("Aguardando dados da coleta em", db, "...")
            time.sleep(args.interval)
            fan_series, temp_series = safe_read()

    def current_xmax(fs, ts):
        xs = [max(xy[0]) for d in (fs, ts) for xy in d.values() if xy[0]]
        if xs:
            return max(xs)
        return pts[-1][0] if pts else None

    # Cria os subplots conforme os grupos escolhidos (FAN em cima, temperatura embaixo)
    ax_f = ax_t = None
    if need_fan and need_temp:
        fig, (ax_f, ax_t) = plt.subplots(
            2, 1, sharex=True, figsize=(15, 9),
            gridspec_kw={"height_ratios": [1, 3], "hspace": 0.10})
    elif need_temp:
        fig, ax_t = plt.subplots(figsize=(15, 8))
    else:
        fig, ax_f = plt.subplots(figsize=(15, 6))
    fig.suptitle("{} - Ensaio termico".format(model), fontsize=13, fontweight="bold")

    colors = color_cycle()
    ci = 0
    temp_lines = []   # linhas do subplot de temperatura (para os checkboxes, na ordem)
    fan_lines = []    # linhas do subplot de fan
    fan_map = {}      # label -> Line2D (para atualizar ao vivo sem recriar)
    temp_map = {}

    # --- Fans (RPM real) - subplot superior (ordem alfabetica/natural) ---
    if ax_f is not None:
        for fid in sorted(fan_series, key=natural_key):
            x, y = fan_series[fid]
            ln, = ax_f.plot(x, y, label=fid, color=colors[ci % len(colors)], lw=1.0)
            fan_lines.append(ln)
            fan_map[fid] = ln
            ci += 1
        ax_f.set_ylabel("Fan (RPM)")
        ax_f.grid(True, which="both", ls="-", lw=0.4, alpha=0.25)

    # --- Temperaturas - subplot inferior (ordem alfabetica/natural) ---
    if ax_t is not None:
        for label in sorted(temp_series, key=natural_key):
            x, y = temp_series[label]
            ln, = ax_t.plot(x, y, label=label, color=colors[ci % len(colors)], lw=1.0)
            temp_lines.append(ln)
            temp_map[label] = ln
            ci += 1

    # --- Setpoint da camara ---
    sp_line = None
    if pts:
        # step (degrau em C) no subplot de temperatura, quando existir
        if ax_t is not None:
            xmax = current_xmax(fan_series, temp_series)
            xs = [p[0] for p in pts] + [xmax]
            ys = [p[1] for p in pts] + [pts[-1][1]]
            sp_line, = ax_t.plot(xs, ys, color="black", lw=2.0, ls="--",
                                 label="Setpoint camara", zorder=10)
            temp_lines.append(sp_line)
        # linhas verticais + anotacao (estaticas), so quando o setpoint MUDA de valor
        prev_v = None
        for t, v in pts:
            if v == prev_v:
                continue
            prev_v = v
            if ax_t is not None:
                ax_t.axvline(t, color="black", lw=0.6, ls=":", alpha=0.35, zorder=1)
                ax_t.annotate("{:g}C".format(v), xy=(t, v), xytext=(3, 4),
                              textcoords="offset points", fontsize=7, color="black")
            if ax_f is not None:
                ax_f.axvline(t, color="black", lw=1.4, ls=":", alpha=0.55, zorder=1)
                ax_f.annotate("{:g}C".format(v), xy=(t, 1.0),
                              xycoords=("data", "axes fraction"), xytext=(3, -3),
                              textcoords="offset points", va="top", ha="left",
                              fontsize=7, color="black")

    if ax_t is not None:
        ax_t.set_ylabel("Temperatura (C)")
        ax_t.grid(True, which="both", ls="-", lw=0.4, alpha=0.25)

    # eixo de tempo no subplot mais de baixo
    bottom_ax = ax_t if ax_t is not None else ax_f
    bottom_ax.set_xlabel("Tempo")
    bottom_ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    fig.autofmt_xdate(rotation=30)
    fig.subplots_adjust(left=0.06, right=0.80, top=0.93, bottom=0.12)

    # --- Paineis de checkbox (legenda + liga/desliga), um por subplot ---
    checks = []  # manter referencia viva para os widgets nao serem coletados

    def make_panel(ax, lines, fontsize):
        if ax is None or not lines:
            return
        pos = ax.get_position()
        rax = fig.add_axes([0.815, pos.y0, 0.17, pos.height])
        rax.set_xticks([])
        rax.set_yticks([])
        labels = [ln.get_label() for ln in lines]
        actives = [ln.get_visible() for ln in lines]
        check = CheckButtons(rax, labels, actives)
        for i, ln in enumerate(lines):
            check.labels[i].set_color(ln.get_color())
            check.labels[i].set_fontsize(fontsize)

        def toggle(label):
            idx = labels.index(label)
            lines[idx].set_visible(not lines[idx].get_visible())
            fig.canvas.draw_idle()

        check.on_clicked(toggle)
        checks.append(check)

    make_panel(ax_t, temp_lines, 6)
    make_panel(ax_f, fan_lines, 8)

    def refresh():
        """Rele o banco e atualiza os dados das linhas existentes (sem recriar a
        figura, preservando checkboxes/zoom). Reescala os eixos para o novo range."""
        fs, ts = safe_read()
        for label, ln in fan_map.items():
            if fs.get(label) and fs[label][0]:
                ln.set_data(fs[label][0], fs[label][1])
        for label, ln in temp_map.items():
            if ts.get(label) and ts[label][0]:
                ln.set_data(ts[label][0], ts[label][1])
        if sp_line is not None:
            xmax = current_xmax(fs, ts)
            if xmax is not None:
                sp_line.set_data([p[0] for p in pts] + [xmax],
                                 [p[1] for p in pts] + [pts[-1][1]])
        for ax in (ax_f, ax_t):
            if ax is not None:
                ax.relim()
                ax.autoscale_view()
        fig.canvas.draw_idle()

    if args.save:
        if args.live:            # exercita o caminho de atualizacao (para teste headless)
            refresh()
            refresh()
        fig.savefig(args.save, dpi=110)
        print("Figura salva em", args.save)
    elif args.live:
        print("Modo ao vivo: atualizando a cada {}s. Feche a janela para sair.".format(args.interval))
        plt.ion()
        plt.show(block=False)
        try:
            while plt.fignum_exists(fig.number):
                refresh()
                plt.pause(args.interval)
        except KeyboardInterrupt:
            print("\nEncerrado.")
    else:
        plt.show()


if __name__ == "__main__":
    main()
