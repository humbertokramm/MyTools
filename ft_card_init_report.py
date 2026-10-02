#!/usr/bin/env python3
"""
ft_card_init report — checks Marvell initialization on every boot of a
rebootTF.lua reboot loop.

Each boot (Welcome to pd*_ft) must reach "RESPOSTA(eq:ft_card_init): 55".
Any other value, or a boot without a response, counts as a failure.

Generates a Yodiz-compatible HTML fragment (inline styles, no
DOCTYPE/head/body/scripts) in the current directory.

Usage:
    python ft_card_init_report.py <teraterm.log> [--title "Task title"]
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')
EXPECTED = '55'

TS_RE      = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
BOOT_RE    = re.compile(r'Welcome to (pd\w+)!')
LOGIN_RE   = re.compile(r'login: root')
LUA_RE     = re.compile(r'# lua rebootTF\.lua')
RESP_RE    = re.compile(r'RESPOSTA\(eq:ft_card_init\):\s*(\S+)')
DUT_RE     = re.compile(r'(DM[\w ]+?)\s+-\s+(\d{3}\.\d{4}\.\d+)\s+-\s+(\d+)')
COMMIT_RE  = re.compile(r'^commit ([0-9a-f]{40})')
FW_RE      = re.compile(r'VERSION_ID=(\S+)')

# Marvell init milestones printed by ft_card_init
STEPS = [
    ('appdemo', re.compile(r"Initializing AppDemo connection")),
    ('pcie',    re.compile(r'Initializing Marvell PCIe')),
    ('profile', re.compile(r'Initializing Marvell Profile\s+(\S+)')),
    ('ports',   re.compile(r'Configuring Marvell ports')),
    ('sfp',     re.compile(r"Removing SFP transceivers")),
]

# Boots whose login->response span is shorter than this are scrollback
# replayed by Tera Term when logging started: their timestamps are fake.
REPLAY_MAX_S = 5
GRID_COLS    = 25


def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


def resolve(arg):
    # Prefer LOG_DIR (authoritative source) so local copies are always refreshed
    p = Path(arg)
    q = LOG_DIR / p.name
    return q if q.exists() else p


def new_boot(lineno, ts):
    return {'line': lineno, 'boot_ts': ts, 'login_ts': None, 'lua_ts': None,
            'resp_ts': None, 'resp': None, 'resp_line': None, 'steps': {},
            'profile': None}


def parse(filepath):
    boots, cur = [], None
    info = {'dut': None, 'commit': None, 'fw': None}
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        for i, raw in enumerate(fh, 1):
            line = raw.rstrip()
            ts = parse_ts(line)
            if BOOT_RE.search(line):
                cur = new_boot(i, ts)
                boots.append(cur)
                continue
            if cur is None:
                continue
            if cur['login_ts'] is None and LOGIN_RE.search(line):
                cur['login_ts'] = ts
            elif cur['lua_ts'] is None and LUA_RE.search(line):
                cur['lua_ts'] = ts
            m = RESP_RE.search(line)
            if m and cur['resp'] is None:
                cur['resp'], cur['resp_ts'], cur['resp_line'] = m.group(1), ts, i
            for key, rx in STEPS:
                m = rx.search(line)
                if m and key not in cur['steps']:
                    cur['steps'][key] = ts
                    if key == 'profile':
                        cur['profile'] = m.group(1)
            if not info['dut'] and (m := DUT_RE.search(line)):
                info['dut'] = f'{m.group(1).strip()} - {m.group(2)} - SN {m.group(3)}'
            if not info['commit'] and (m := COMMIT_RE.search(TS_STRIP(line))):
                info['commit'] = m.group(1)[:10]
            if not info['fw'] and (m := FW_RE.search(line)):
                info['fw'] = m.group(1)

    for b in boots:
        b['replay'] = bool(b['login_ts'] and b['resp_ts'] and
                           (b['resp_ts'] - b['login_ts']).total_seconds() < REPLAY_MAX_S)
        if b['resp'] == EXPECTED:
            b['status'] = 'pass'
        elif b['resp'] is not None:
            b['status'] = 'fail'
        else:
            b['status'] = 'pending'   # decided below
    # A boot without a response is a failure, except the last one (may be running)
    for b in boots[:-1]:
        if b['status'] == 'pending':
            b['status'] = 'fail'
    return boots, info


def TS_STRIP(line):
    return re.sub(r'^\[[^\]]{10,30}\]\s*', '', line)


def secs(a, b):
    return (b - a).total_seconds() if a and b else None


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


def fmt_s(v):
    return '-' if v is None else f'{v:.0f}s'


def build(boots, info, logname, title):
    done  = [b for b in boots if b['status'] != 'pending']
    n_ok  = sum(b['status'] == 'pass' for b in done)
    n_bad = sum(b['status'] == 'fail' for b in done)
    real  = [b for b in done if not b['replay']]
    ts_all = [b['boot_ts'] for b in boots if b['boot_ts'] and not b['replay']]
    period = (f'{min(ts_all):%d/%m/%Y %H:%M} → {max(ts_all):%d/%m/%Y %H:%M}'
              if ts_all else '-')

    p = [f'<h2 style="{S["h2"]}">{esc(title)}</h2>']
    meta = [f'<b>Log:</b> {esc(logname)}', f'<b>Período:</b> {period}']
    if info['dut']:    meta.append(f'<b>DUT:</b> {esc(info["dut"])}')
    if info['fw']:     meta.append(f'<b>FW:</b> {esc(info["fw"])}')
    if info['commit']: meta.append(f'<b>Lua:</b> {esc(info["commit"])}')
    p.append(f'<p style="{S["p"]}">' + ' &nbsp;|&nbsp; '.join(meta) + '</p>')
    p.append(f'<p style="{S["p"]}">Critério: em cada boot, <code>ft_card_init</code> '
             f'deve responder <b>{EXPECTED}</b> (Marvell inicializado).</p>')

    p.append(f'<h3 style="{S["h3"]}">Resumo</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Boots")}{th("OK")}{th("Falhas")}</tr>'
             f'<tr>{tdc(len(done))}{tds("pass", n_ok)}'
             f'{tds("fail" if n_bad else "pass", n_bad)}</tr></table>')

    # Compact grid: one coloured cell per boot
    p.append(f'<h3 style="{S["h3"]}">Boots</h3>')
    cell = ('width:26px;height:20px;padding:0;border:1px solid #fff;font-size:.68rem;'
            'text-align:center;font-weight:600')
    p.append(f'<table style="{S["tbl"]}">')
    for row in range(0, len(boots), GRID_COLS):
        p.append('<tr>')
        for n, b in enumerate(boots[row:row + GRID_COLS], row + 1):
            c, bg = COLORS[b['status']]
            if b['status'] == 'pass' and b['replay']:
                bg = '#c8e6c9'
            tip = f'Boot {n} | resp={b["resp"] or "-"}'
            if not b['replay'] and b['boot_ts']:
                tip += f' | {b["boot_ts"]:%d/%m %H:%M:%S} | {fmt_s(secs(b["lua_ts"], b["resp_ts"]))}'
            p.append(f'<td title="{esc(tip)}" style="{cell};color:{c};background:{bg}">{n}</td>')
        p.append('</tr>')
    p.append('</table>')
    p.append(f'<p style="{S["note"]}">'
             f'<span style="background:#e8f5e9;color:#2e7d32;padding:0 6px">verde</span> = 55 &nbsp; '
             f'<span style="background:#ffebee;color:#c62828;padding:0 6px">vermelho</span> = falha &nbsp; '
             f'<span style="background:#f5f5f5;color:#9e9e9e;padding:0 6px">cinza</span> = em andamento</p>')

    # Timing statistics per Marvell init step (real-time boots only)
    spans = [('ft_card_init (total)', lambda b: secs(b['lua_ts'], b['resp_ts'])),
             ('AppDemo connection',   lambda b: secs(b['steps'].get('appdemo'), b['steps'].get('pcie'))),
             ('Marvell PCIe',         lambda b: secs(b['steps'].get('pcie'), b['steps'].get('profile'))),
             ('Marvell Profile',      lambda b: secs(b['steps'].get('profile'), b['steps'].get('ports'))),
             ('Marvell ports',        lambda b: secs(b['steps'].get('ports'), b['steps'].get('sfp')))]
    ok_real = [b for b in real if b['status'] == 'pass']
    if ok_real:
        p.append(f'<h3 style="{S["h3"]}">Tempos de inicialização ({len(ok_real)} boots)</h3>')
        p.append(f'<table style="{S["tbl"]}"><tr>{th("Etapa")}{th("mín")}{th("méd")}{th("máx")}</tr>')
        for name, fn in spans:
            v = [x for x in (fn(b) for b in ok_real) if x is not None]
            if v:
                p.append(f'<tr>{td(name)}{tdc(fmt_s(min(v)))}'
                         f'{tdc(fmt_s(sum(v) / len(v)))}{tdc(fmt_s(max(v)))}</tr>')
        p.append('</table>')

    notes = []
    if any(b['replay'] for b in boots):
        notes.append('Boots em verde-claro foram despejados do buffer do Tera Term ao iniciar o log: '
                     'resposta válida, mas fora das estatísticas de tempo.')
    for n in notes:
        p.append(f'<p style="{S["note"]}">{n}</p>')

    fails = [(i, b) for i, b in enumerate(boots, 1) if b['status'] == 'fail']
    if fails:
        p.append(f'<h3 style="{S["h3"]}">Falhas</h3>')
        for i, b in fails:
            why = (f'resposta {esc(b["resp"])} (linha {b["resp_line"]})' if b['resp']
                   else 'sem RESPOSTA(eq:ft_card_init) antes do próximo boot')
            p.append(f'<p style="{S["p"]}"><b>Boot #{i}</b> (linha {b["line"]}): {why}</p>')
    return ''.join(p)


def main():
    args = sys.argv[1:]
    title = 'Stress I2C Marvell vs EEPROM — inicialização do Marvell (ft_card_init)'
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

    boots, info = parse(fp)
    for n, b in enumerate(boots, 1):
        t = secs(b['lua_ts'], b['resp_ts'])
        print(f'  Boot {n:3d} | linha {b["line"]:6d} | resp={b["resp"] or "-":>3} | '
              f'{"buffer" if b["replay"] else fmt_s(t):>6} | {LABEL[b["status"]]}')
    n_bad = sum(b['status'] == 'fail' for b in boots)
    print(f'Total: {len(boots)} boots | {n_bad} falha(s)')

    out = Path.cwd() / (fp.stem + '_ft_card_init_task.html')
    out.write_text(build(boots, info, fp.name, title), encoding='utf-8')
    print(f'\nFragmento Yodiz: {out}')
    os.startfile(out)


if __name__ == '__main__':
    main()
