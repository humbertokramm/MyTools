#!/usr/bin/env python3
"""
Rail ripple report — pd4302 tester, option 22.4 (Dados de consumo maximo).

Every cycle prints the PSU power table, ISL68127 readings, total system power
and the UCD90120A rail ripple table. The report condenses all cycles into one
table per rail (worst case over the whole run) plus power/temperature stats.

Generates a Yodiz-compatible HTML fragment (inline styles, no
DOCTYPE/head/body/scripts) in the current directory.

Usage:
    python ripple_report.py <teraterm.log> [--title "Task title"]
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')

TS_RE     = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
CYCLE_RE  = re.compile(r'--- Consumo m.ximo ---')
RAIL_HDR  = re.compile(r'\|\s+Rail\s+\|\s+Avg\[V\]')
RAIL_ROW  = re.compile(r'\|\s*(\w+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|'
                       r'\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*(\w+)\s*\|')
PSU_ROW   = re.compile(r'\|\s*(TEMPERATURE_\d|FAN|INPUT_POWER|OUTPUT_POWER|OUTPUT_CURRENT)\s*\|'
                       r'\s*\S+\s*\|\s*([\d.]+)\s*\|')
ISL_RE    = re.compile(r'ISL68127 (\d) Output (Voltage|Current): ([\d.]+)')
TOTAL_RE  = re.compile(r'Total System Power Consumption: ([\d.]+)')
DUT_RE    = re.compile(r'(DM[\w ]+?)\s+-\s+(\d{3}\.\d{4}\.\d+)\s+-\s+(\d+)')
FW_RE     = re.compile(r'VERSION_ID=(\S+)')
COMMIT_RE = re.compile(r'\]\s*commit ([0-9a-f]{40})')
PSU_NC_RE = re.compile(r'PSU (\d) is not Connected')
QSFP_LOAD_RE = re.compile(r'QSFP28 Port \d+ Load Enabled @ ([\d.]+)W')
TRACE_RE  = re.compile(r'stack traceback')


def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


def resolve(arg):
    # Prefer LOG_DIR (authoritative source) so local copies are always refreshed
    p = Path(arg)
    q = LOG_DIR / p.name
    return q if q.exists() else p


def parse(filepath):
    cycles, cur, in_rail = [], None, False
    info = {'dut': None, 'fw': None, 'commit': None, 'psu_nc': set(),
            'qsfp_loads': 0, 'qsfp_w': None, 'tracebacks': []}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.rstrip()
            ts = parse_ts(line)
            if not info['dut'] and (m := DUT_RE.search(line)):
                info['dut'] = f'{m.group(1).strip()} - {m.group(2)} - SN {m.group(3)}'
            if not info['fw'] and (m := FW_RE.search(line)):
                info['fw'] = m.group(1)
            if not info['commit'] and (m := COMMIT_RE.search(line)):
                info['commit'] = m.group(1)[:10]
            if (m := PSU_NC_RE.search(line)):
                info['psu_nc'].add(m.group(1))
            if (m := QSFP_LOAD_RE.search(line)):
                info['qsfp_loads'] += 1
                info['qsfp_w'] = m.group(1)
            if TRACE_RE.search(line):
                info['tracebacks'].append((i, ts))

            if CYCLE_RE.search(line):
                cur = {'ts': ts, 'rails': {}, 'psu': {}, 'isl': {}, 'total': None, 'rail_ts': None}
                cycles.append(cur)
                in_rail = False
                continue
            if cur is None:
                continue
            if RAIL_HDR.search(line):
                in_rail, cur['rail_ts'] = True, ts
                continue
            if in_rail and (m := RAIL_ROW.search(line)):
                name, *vals, status = m.groups()
                avg, mn, mx, sd, rip = map(float, vals)
                cur['rails'][name] = {'avg': avg, 'min': mn, 'max': mx, 'sd': sd,
                                      'rip': rip, 'ok': status == 'OK', 'status': status}
                continue
            if (m := PSU_ROW.search(line)):
                cur['psu'].setdefault(m.group(1), float(m.group(2)))
            if (m := ISL_RE.search(line)):
                cur['isl'][f'{m.group(1)}_{m.group(2)}'] = float(m.group(3))
            if (m := TOTAL_RE.search(line)):
                cur['total'] = float(m.group(1))
    # Keep only cycles that produced a complete ripple table
    complete = [c for c in cycles if c['rails']]
    return complete, info


# ── Yodiz fragment ─────────────────────────────────────────────────────────────

S = {
    'h2':  'font-size:1.05rem;font-weight:700;margin:16px 0 6px 0',
    'h3':  'font-size:.92rem;font-weight:700;margin:14px 0 5px 0',
    'p':   'font-size:.85rem;margin:4px 0 8px 0;line-height:1.5',
    'tbl': 'border-collapse:collapse;margin:6px 0',
    'th':  'text-align:left;padding:4px 10px;background:#f0f0f0;border:1px solid #ddd;font-size:.82rem;white-space:nowrap',
    'thc': 'text-align:center;padding:4px 10px;background:#f0f0f0;border:1px solid #ddd;font-size:.82rem;white-space:nowrap',
    'td':  'padding:4px 10px;border:1px solid #ddd;font-size:.82rem;font-family:Consolas,monospace',
    'tdr': 'padding:4px 10px;border:1px solid #ddd;font-size:.82rem;text-align:right;font-family:Consolas,monospace',
    'note':'font-size:.78rem;color:#666;margin:4px 0',
}
OK_STYLE  = 'color:#2e7d32;background:#e8f5e9;font-weight:700'
BAD_STYLE = 'color:#c62828;background:#ffebee;font-weight:700'


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def th(s, c=False): return f'<th style="{S["thc" if c else "th"]}">{s}</th>'
def td(s):  return f'<td style="{S["td"]}">{esc(s)}</td>'
def tdr(s): return f'<td style="{S["tdr"]}">{esc(s)}</td>'
def tdst(ok, text):
    return f'<td style="{S["tdr"]};{OK_STYLE if ok else BAD_STYLE}">{esc(text)}</td>'


def avg(v):
    return sum(v) / len(v) if v else None


def fmt_dur(sec):
    h, rem = divmod(int(sec), 3600)
    return f'{h}h{rem // 60:02d}min'


def build(cycles, info, logname, title):
    t0, t1 = cycles[0]['rail_ts'], cycles[-1]['rail_ts']
    dur = (t1 - t0).total_seconds() if t0 and t1 else 0
    period_s = dur / (len(cycles) - 1) if len(cycles) > 1 else 0
    rails = list(cycles[0]['rails'])
    n_bad_cycles = sum(1 for c in cycles if not all(r['ok'] for r in c['rails'].values()))

    p = [f'<h2 style="{S["h2"]}">{esc(title)}</h2>']
    meta = [f'<b>Log:</b> {esc(logname)}',
            f'<b>Período:</b> {t0:%d/%m %H:%M} → {t1:%d/%m %H:%M} ({fmt_dur(dur)})']
    if info['dut']:    meta.append(f'<b>DUT:</b> {esc(info["dut"])}')
    if info['fw']:     meta.append(f'<b>FW:</b> {esc(info["fw"])}')
    if info['commit']: meta.append(f'<b>Lua:</b> {esc(info["commit"])}')
    p.append(f'<p style="{S["p"]}">' + ' &nbsp;|&nbsp; '.join(meta) + '</p>')

    cond = [f'Opção 22.4 (Dados de consumo máximo) em modo contínuo, '
            f'{len(cycles)} ciclos de ~{period_s:.0f} s']
    if info['qsfp_loads']:
        cond.append(f'placa estressada antes pela opção 32 (QSFP28 loads @ {info["qsfp_w"]} W)')
    if info['psu_nc']:
        cond.append('PSU ' + ', '.join(sorted(info['psu_nc'])) + ' não conectada')
    p.append(f'<p style="{S["p"]}"><b>Condição:</b> ' + '; '.join(cond) + '.</p>')

    # Summary
    p.append(f'<h3 style="{S["h3"]}">Resumo</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Ciclos")}{th("Rails")}'
             f'{th("Ciclos com rail fora de OK")}</tr><tr>{tdr(len(cycles))}{tdr(len(rails))}'
             f'{tdst(n_bad_cycles == 0, n_bad_cycles)}</tr></table>')

    # Per-rail worst case
    hour = 3600
    first = [c for c in cycles if (c['rail_ts'] - t0).total_seconds() < hour]
    last  = [c for c in cycles if (t1 - c['rail_ts']).total_seconds() < hour]
    p.append(f'<h3 style="{S["h3"]}">Rail ripple — pior caso em {len(cycles)} ciclos</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Rail")}{th("Avg[V] mín–máx", True)}'
             f'{th("Min[%] pior", True)}{th("Max[%] pior", True)}{th("Std.Dev.[mV] máx", True)}'
             f'{th("Ripple[%] méd", True)}{th("Ripple[%] máx", True)}'
             f'{th("Ripple[%] méd 1ª h → última h", True)}{th("Status", True)}</tr>')
    for r in rails:
        rows = [c['rails'][r] for c in cycles if r in c['rails']]
        a = [x['avg'] for x in rows]
        rip = [x['rip'] for x in rows]
        n_nok = sum(not x['ok'] for x in rows)
        r_first = avg([c['rails'][r]['rip'] for c in first if r in c['rails']])
        r_last  = avg([c['rails'][r]['rip'] for c in last if r in c['rails']])
        p.append(f'<tr>{td(r)}{tdr(f"{min(a):.3f}–{max(a):.3f}")}'
                 f'{tdr(f"{min(x["min"] for x in rows):.3f}")}'
                 f'{tdr(f"{max(x["max"] for x in rows):.3f}")}'
                 f'{tdr(f"{max(x["sd"] for x in rows):.3f}")}'
                 f'{tdr(f"{avg(rip):.3f}")}{tdr(f"{max(rip):.3f}")}'
                 f'{tdr(f"{r_first:.3f} → {r_last:.3f}")}'
                 f'{tdst(n_nok == 0, "OK" if n_nok == 0 else f"{n_nok} fora")}</tr>')
    p.append('</table>')
    p.append(f'<p style="{S["note"]}">Min/Max[%]: desvio em relação à média do rail. '
             f'Status conforme avaliação do próprio script (UCD90120A). '
             f'1ª h / última h: média do ripple na primeira e na última hora, para ver deriva.</p>')

    # Power and temperature
    stats = [
        ('Consumo total do sistema', 'W', [c['total'] for c in cycles]),
        ('PSU 0 potência de entrada', 'W', [c['psu'].get('INPUT_POWER') for c in cycles]),
        ('PSU 0 corrente de saída', 'A', [c['psu'].get('OUTPUT_CURRENT') for c in cycles]),
        ('PSU 0 TEMPERATURE_1', '°C', [c['psu'].get('TEMPERATURE_1') for c in cycles]),
        ('PSU 0 TEMPERATURE_2', '°C', [c['psu'].get('TEMPERATURE_2') for c in cycles]),
        ('PSU 0 TEMPERATURE_3', '°C', [c['psu'].get('TEMPERATURE_3') for c in cycles]),
        ('PSU 0 FAN', 'RPM', [c['psu'].get('FAN') for c in cycles]),
    ]
    for n in ('1', '2', '3'):
        stats.append((f'ISL68127 {n} corrente de saída', 'A', [c['isl'].get(f'{n}_Current') for c in cycles]))
    p.append(f'<h3 style="{S["h3"]}">Potência e temperatura</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Medida")}{th("mín", True)}'
             f'{th("méd", True)}{th("máx", True)}</tr>')
    for name, unit, vals in stats:
        v = [x for x in vals if x is not None]
        if not v:
            continue
        f = (lambda x: f'{x:.0f}') if unit == 'RPM' else (lambda x: f'{x:.1f}')
        p.append(f'<tr>{td(f"{name} ({unit})")}{tdr(f(min(v)))}{tdr(f(avg(v)))}{tdr(f(max(v)))}</tr>')
    p.append('</table>')

    # Out-of-OK detail
    bad = [(c, r, v) for c in cycles for r, v in c['rails'].items() if not v['ok']]
    if bad:
        p.append(f'<h3 style="{S["h3"]}">Leituras fora de OK</h3>')
        p.append(f'<table style="{S["tbl"]}"><tr>{th("Horário")}{th("Rail")}{th("Avg[V]")}'
                 f'{th("Min[%]")}{th("Max[%]")}{th("Ripple[%]")}{th("Status")}</tr>')
        for c, r, v in bad[:50]:
            p.append(f'<tr>{td(f"{c["rail_ts"]:%d/%m %H:%M:%S}")}{td(r)}{tdr(v["avg"])}'
                     f'{tdr(v["min"])}{tdr(v["max"])}{tdr(v["rip"])}{tdst(False, v["status"])}</tr>')
        p.append('</table>')
    return ''.join(p)


def main():
    args = sys.argv[1:]
    title = 'Rail Ripple — consumo máximo'
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

    cycles, info = parse(fp)
    if not cycles:
        print('Nenhuma tabela de ripple encontrada.')
        sys.exit(1)
    n_bad = sum(1 for c in cycles if not all(r['ok'] for r in c['rails'].values()))
    print(f'Ciclos: {len(cycles)} | {cycles[0]["rail_ts"]:%d/%m %H:%M} -> '
          f'{cycles[-1]["rail_ts"]:%d/%m %H:%M} | ciclos com rail fora de OK: {n_bad}')
    for ln, ts in info['tracebacks']:
        print(f'  traceback Lua na linha {ln} ({ts:%d/%m %H:%M:%S})')

    out = Path.cwd() / (fp.stem + '_ripple_task.html')
    out.write_text(build(cycles, info, fp.name, title), encoding='utf-8')
    print(f'\nFragmento Yodiz: {out}')
    os.startfile(out)


if __name__ == '__main__':
    main()
