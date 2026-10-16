#!/usr/bin/env python3
"""
MGMT ping flood report — rebootTF.lua loop test on the eth (MGMT) port.

Each loop runs a quick test (short pings) followed by the 60 s MGMT Ping
Flood. A loop passes when every ping result and every Test Report item is OK.

Generates a Yodiz-compatible HTML fragment (inline styles, no
DOCTYPE/head/body/scripts) in the current directory.

Usage:
    python flood_report.py <teraterm.log> [--title "Task title"]
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

LOG_DIR   = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')
GRID_COLS = 25

TS_RE      = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
START_RE   = re.compile(r'#\s+\w+ Tests!\s+#')
END_RE     = re.compile(r'=== LOOP TEST ===\s*(\d+)\s+Total de erros\s+(\d+)')
FLOOD_RE   = re.compile(r'MGMT Ping Flood Status')
PING_RE    = re.compile(r'\[(OK|ERROR)\]\s+(\d+) packets transmitted, (\d+) received.*?'
                        r'([\d.]+)% packet loss, time (\d+)ms')
LIMIT_RE   = re.compile(r'Maximum (\d+) Packets Lost')
REPORT_RE  = re.compile(r'\[(OK|ERROR)\]\s+(\w+)\s+:\s+(OK|ERROR)')
MVL_TEMP_RE = re.compile(r'Marvell Device Temp = ([\d.]+)')
DUT_RE     = re.compile(r'(DM[\w ]+?)\s+-\s+(\d{3}\.\d{4}\.\d+)\s+-\s+(\d+)')
FW_RE      = re.compile(r'VERSION_ID=(\S+)')
COMMIT_RE  = re.compile(r'\]\s*commit ([0-9a-f]{40})')
IFACE_RE   = re.compile(r'# ifconfig (\w+) ([\d.]+)')


def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


def resolve(arg):
    # Prefer LOG_DIR (authoritative source) so local copies are always refreshed
    p = Path(arg)
    q = LOG_DIR / p.name
    return q if q.exists() else p


def new_loop(n, ts):
    return {'n': n, 'start_ts': ts, 'end_ts': None, 'quick': [], 'flood': None,
            'limit_quick': None, 'limit_flood': None, 'report': {},
            'mvl_temp': None, 'errors_total': None, 'done': False}


def parse(filepath):
    loops, cur, in_flood = [], None, False
    info = {'dut': None, 'fw': None, 'commit': None, 'iface': None}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        for raw in fh:
            line = raw.rstrip()
            ts = parse_ts(line)
            if not info['dut'] and (m := DUT_RE.search(line)):
                info['dut'] = f'{m.group(1).strip()} - {m.group(2)} - SN {m.group(3)}'
            if not info['fw'] and (m := FW_RE.search(line)):
                info['fw'] = m.group(1)
            if not info['commit'] and (m := COMMIT_RE.search(line)):
                info['commit'] = m.group(1)[:10]
            if not info['iface'] and (m := IFACE_RE.search(line)):
                info['iface'] = f'{m.group(1)} ({m.group(2)})'

            if START_RE.search(line):
                cur, in_flood = new_loop(len(loops), ts), False
                loops.append(cur)
                continue
            if cur is None:
                continue
            if (m := END_RE.search(line)):
                cur['end_ts'], cur['errors_total'], cur['done'] = ts, int(m.group(2)), True
                cur = None
                continue
            if FLOOD_RE.search(line):
                in_flood = True
            if (m := PING_RE.search(line)):
                r = {'ok': m.group(1) == 'OK', 'tx': int(m.group(2)), 'rx': int(m.group(3)),
                     'loss': float(m.group(4)), 'ms': int(m.group(5))}
                r['lost'] = r['tx'] - r['rx']
                if in_flood:
                    cur['flood'] = r
                else:
                    cur['quick'].append(r)
            if (m := LIMIT_RE.search(line)):
                cur['limit_flood' if in_flood else 'limit_quick'] = int(m.group(1))
            if (m := REPORT_RE.search(line)):
                cur['report'][m.group(2)] = m.group(3) == 'OK'
            if cur['mvl_temp'] is None and (m := MVL_TEMP_RE.search(line)):
                cur['mvl_temp'] = float(m.group(1))

    for l in loops:
        if not l['done']:
            l['status'] = 'pending'
            continue
        pings_ok = all(q['ok'] for q in l['quick']) and l['flood'] is not None and l['flood']['ok']
        report_ok = bool(l['report']) and all(l['report'].values())
        l['status'] = 'pass' if pings_ok and report_ok else 'fail'
    return loops, info


# ── Yodiz fragment ─────────────────────────────────────────────────────────────

S = {
    'h2':  'font-size:1.05rem;font-weight:700;margin:16px 0 6px 0',
    'h3':  'font-size:.92rem;font-weight:700;margin:14px 0 5px 0',
    'p':   'font-size:.85rem;margin:4px 0 8px 0;line-height:1.5',
    'tbl': 'border-collapse:collapse;margin:6px 0',
    'th':  'text-align:left;padding:4px 10px;background:#f0f0f0;border:1px solid #ddd;font-size:.82rem;white-space:nowrap',
    'td':  'padding:4px 10px;border:1px solid #ddd;font-size:.82rem',
    'tdc': 'padding:4px 10px;border:1px solid #ddd;font-size:.82rem;text-align:center',
    'note':'font-size:.78rem;color:#666;margin:4px 0',
}
COLORS = {'pass': ('#2e7d32', '#e8f5e9'), 'fail': ('#c62828', '#ffebee'),
          'pending': ('#9e9e9e', '#f5f5f5')}
LABEL  = {'pass': 'OK', 'fail': 'FALHA', 'pending': 'em andamento'}


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def th(s):  return f'<th style="{S["th"]}">{s}</th>'
def td(s):  return f'<td style="{S["td"]}">{esc(s)}</td>'
def tdc(s): return f'<td style="{S["tdc"]}">{esc(s)}</td>'
def tds(st, text=None):
    c, bg = COLORS[st]
    return (f'<td style="{S["tdc"]};color:{c};background:{bg};font-weight:700">'
            f'{esc(LABEL[st] if text is None else text)}</td>')


def num(v):
    return f'{v:,}'.replace(',', '.')


def mma(vals, fmt):
    vals = [v for v in vals if v is not None]
    if not vals:
        return ['-'] * 3
    return [fmt(min(vals)), fmt(sum(vals) / len(vals)), fmt(max(vals))]


def build(loops, info, logname, title):
    done  = [l for l in loops if l['status'] != 'pending']
    n_bad = sum(l['status'] == 'fail' for l in done)
    floods = [l['flood'] for l in done if l['flood']]
    ts_all = [l['start_ts'] for l in loops if l['start_ts']]
    period = (f'{min(ts_all):%d/%m/%Y %H:%M} → {max(ts_all):%d/%m/%Y %H:%M}'
              if ts_all else '-')

    p = [f'<h2 style="{S["h2"]}">{esc(title)}</h2>']
    meta = [f'<b>Log:</b> {esc(logname)}', f'<b>Período:</b> {period}']
    if info['dut']:    meta.append(f'<b>DUT:</b> {esc(info["dut"])}')
    if info['iface']:  meta.append(f'<b>Porta:</b> {esc(info["iface"])}')
    if info['fw']:     meta.append(f'<b>FW:</b> {esc(info["fw"])}')
    if info['commit']: meta.append(f'<b>Lua:</b> {esc(info["commit"])}')
    p.append(f'<p style="{S["p"]}">' + ' &nbsp;|&nbsp; '.join(meta) + '</p>')

    lim_q = next((l['limit_quick'] for l in done if l['limit_quick']), None)
    lim_f = next((l['limit_flood'] for l in done if l['limit_flood']), None)
    dur_f = next((l['flood']['ms'] // 1000 for l in done if l['flood']), None)
    crit = []
    if lim_q: crit.append(f'quick test: máx. {lim_q} pacotes perdidos por ping')
    if lim_f: crit.append(f'flood{f" de {dur_f} s" if dur_f else ""}: máx. {num(lim_f)} pacotes perdidos')
    if crit:
        p.append(f'<p style="{S["p"]}"><b>Critério:</b> ' + '; '.join(crit) + '.</p>')

    # Summary
    p.append(f'<h3 style="{S["h3"]}">Resumo</h3>')
    tot_tx = sum(f['tx'] for f in floods)
    tot_lost = sum(f['lost'] for f in floods)
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Loops")}{th("OK")}{th("Falhas")}'
             f'{th("Pacotes enviados (flood)")}{th("Pacotes perdidos (flood)")}</tr>'
             f'<tr>{tdc(len(done))}{tds("pass", len(done) - n_bad)}'
             f'{tds("fail" if n_bad else "pass", n_bad)}{tdc(num(tot_tx))}'
             f'{tdc(f"{num(tot_lost)} ({tot_lost / tot_tx * 100:.5f}%)" if tot_tx else "-")}'
             f'</tr></table>')

    # Compact grid
    p.append(f'<h3 style="{S["h3"]}">Loops</h3>')
    cell = ('width:26px;height:20px;padding:0;border:1px solid #fff;font-size:.68rem;'
            'text-align:center;font-weight:600')
    p.append(f'<table style="{S["tbl"]}">')
    for row in range(0, len(loops), GRID_COLS):
        p.append('<tr>')
        for l in loops[row:row + GRID_COLS]:
            c, bg = COLORS[l['status']]
            tip = f'Loop {l["n"]}'
            if l['start_ts']:
                tip += f' | {l["start_ts"]:%d/%m %H:%M:%S}'
            if l['flood']:
                tip += f' | flood: {l["flood"]["lost"]} perdidos de {num(l["flood"]["tx"])}'
            p.append(f'<td title="{esc(tip)}" style="{cell};color:{c};background:{bg}">{l["n"]}</td>')
        p.append('</tr>')
    p.append('</table>')
    p.append(f'<p style="{S["note"]}">'
             f'<span style="background:#e8f5e9;color:#2e7d32;padding:0 6px">verde</span> = OK &nbsp; '
             f'<span style="background:#ffebee;color:#c62828;padding:0 6px">vermelho</span> = falha &nbsp; '
             f'<span style="background:#f5f5f5;color:#9e9e9e;padding:0 6px">cinza</span> = em andamento</p>')

    # Statistics
    quick = [q for l in done for q in l['quick']]
    p.append(f'<h3 style="{S["h3"]}">Estatísticas por loop</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Medida")}{th("mín")}{th("méd")}{th("máx")}'
             f'{th("Limite")}</tr>')
    rows = [
        ('Flood: pacotes enviados',  [f['tx'] for f in floods],   lambda v: num(round(v)), '-'),
        ('Flood: pacotes perdidos',  [f['lost'] for f in floods], lambda v: f'{v:.1f}'.rstrip('0').rstrip('.'),
         num(lim_f) if lim_f else '-'),
        ('Flood: perda (%)',         [f['loss'] for f in floods], lambda v: f'{v:.5f}%', '-'),
        ('Quick test: pacotes perdidos', [q['lost'] for q in quick],
         lambda v: f'{v:.1f}'.rstrip('0').rstrip('.'), str(lim_q) if lim_q else '-'),
        ('Temperatura Marvell',      [l['mvl_temp'] for l in done], lambda v: f'{v:.1f} °C', '-'),
    ]
    for name, vals, fmt, lim in rows:
        if any(v is not None for v in vals):
            p.append(f'<tr>{td(name)}' + ''.join(tdc(x) for x in mma(vals, fmt)) + f'{tdc(lim)}</tr>')
    p.append('</table>')

    # Failures
    fails = [l for l in done if l['status'] == 'fail']
    if fails:
        p.append(f'<h3 style="{S["h3"]}">Falhas</h3>')
        for l in fails:
            why = [k for k, ok in l['report'].items() if not ok]
            if l['flood'] and not l['flood']['ok']:
                why.append(f'flood: {l["flood"]["lost"]} perdidos de {num(l["flood"]["tx"])}')
            for q in l['quick']:
                if not q['ok']:
                    why.append(f'quick test: {q["lost"]} perdidos de {q["tx"]}')
            if l['flood'] is None:
                why.append('sem resultado do flood')
            when = f'{l["start_ts"]:%d/%m %H:%M:%S}' if l['start_ts'] else '-'
            p.append(f'<p style="{S["p"]}"><b>Loop {l["n"]}</b> ({when}): {esc("; ".join(why))}</p>')
    return ''.join(p)


def main():
    args = sys.argv[1:]
    title = 'MGMT Ping Flood — tráfego na porta eth'
    if '--title' in args:
        k = args.index('--title')
        title = args[k + 1]
        del args[k:k + 2]
    if not args:
        print(__doc__)
        sys.exit(1)

    fp = resolve(args[0])
    if not fp.exists():
        print(f'Arquivo não encontrado: {fp}')
        sys.exit(1)
    local = Path.cwd() / fp.name
    if fp.resolve() != local.resolve():
        shutil.copy2(fp, local)
        print(f'Log copiado para: {local}')
        fp = local

    loops, info = parse(fp)
    for l in loops:
        f = l['flood']
        fl = f'{f["lost"]:3d}/{f["tx"]}' if f else '-'
        print(f'  Loop {l["n"]:4d} | flood perdidos {fl:>12} | {LABEL[l["status"]]}')
    n_bad = sum(l['status'] == 'fail' for l in loops)
    print(f'Total: {len(loops)} loops | {n_bad} falha(s)')

    out = Path.cwd() / (fp.stem + '_flood_task.html')
    out.write_text(build(loops, info, fp.name, title), encoding='utf-8')
    print(f'\nFragmento Yodiz: {out}')
    os.startfile(out)


if __name__ == '__main__':
    main()
