#!/usr/bin/env python3
"""
Verify reboot report — rebootTF.lua reboot loop running the full verify
(Test Report) on every boot, usually inside the climatic chamber.

A boot passes when ft_card_init answers 55 and every Test Report item is OK.
A boot that reboots without printing the Test Report counts as a failure;
the last boot of a live log is shown as "em andamento".

Each boot also gets the chamber PV/SP (controller reading) at that moment, read
from the chamber monitor history (http://172.22.239.100/camara, 1 sample/min,
kept 31 days). Without that history the report is built as before.

Generates a Yodiz-compatible HTML fragment (inline styles, no
DOCTYPE/head/body/scripts) in the current directory.

Usage:
    python verify_reboot_report.py <teraterm.log> [--title "..."] [--ref "Temp 1"] [--sem-camara]
    --ref        : sensor used for the temperature-band table (default: Temp 1)
    --sem-camara : do not query the chamber history
"""

import os
import re
import sys
import shutil
from pathlib import Path
from datetime import datetime

import camara_hist

LOG_DIR   = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')
GRID_COLS = 25
BAND_C    = 10      # temperature band width (°C)

CAMARA    = 'Câmara PV'     # key used in each boot's temps

TS_RE      = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
BOOT_RE    = re.compile(r'Welcome to (pd\w+)!')
LOGIN_RE   = re.compile(r'login: root')
RESP_RE    = re.compile(r'RESPOSTA\(eq:ft_card_init\):\s*(\S+)')
REPORT_RE  = re.compile(r'Test Report!')
ITEM_RE    = re.compile(r'\[(OK|ERROR)\]\s+([A-Za-z][\w()%\s\-]*?)\s*:\s*(OK|ERROR)\s*$')
FINISH_RE  = re.compile(r'Device Test Finished')
TEMP_RE    = re.compile(r'\]\s*\[Info\]\s+Temp = (-?[\d.]+) degrees')
LM86_RE    = re.compile(r'LM86 (Local|Remote)\s+Temp = (-?[\d.]+)')
MVL_RE     = re.compile(r'Marvell Device Temp = (-?[\d.]+)')
PKG_RE     = re.compile(r'Core Package id 0 temperature is (-?[\d.]+)')
RAIL_ROW   = re.compile(r'\|\s*(\w+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|'
                        r'\s*([-\d.]+)\s*\|\s*([-\d.]+)\s*\|\s*(\w+)\s*\|')
PING_RE    = re.compile(r'(\d+) packets transmitted, (\d+) received')
TOTAL_RE   = re.compile(r'Total System Power Consumption: ([\d.]+)')
DUT_RE     = re.compile(r'(DM[\w ]+?)\s+-\s+(\d{3}\.\d{4}\.\d+)\s+-\s+(\d+)')
FW_RE      = re.compile(r'VERSION_ID=(\S+)')
COMMIT_RE  = re.compile(r'\]\s*commit ([0-9a-f]{40})')


def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


def resolve(arg):
    # Prefer LOG_DIR (authoritative source) so local copies are always refreshed
    p = Path(arg)
    q = LOG_DIR / p.name
    return q if q.exists() else p


def new_boot(n, ts, line):
    return {'n': n, 'ts': ts, 'line': line, 'login_ts': None, 'resp': None,
            'report': {}, 'in_report': False, 'finished': False, 'temps': {},
            'rails': {}, 'ping_lost': [], 'total': None, 'report_ts': None}


def parse(filepath):
    boots, cur = [], None
    info = {'dut': None, 'fw': None, 'commit': None}
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

            if BOOT_RE.search(line):
                cur = new_boot(len(boots) + 1, ts, i)
                boots.append(cur)
                continue
            # Log attached after the board already booted: login opens the boot
            if LOGIN_RE.search(line) and (cur is None or cur['login_ts']):
                cur = new_boot(len(boots) + 1, ts, i)
                boots.append(cur)
            if cur is None:
                continue
            t = cur['temps']
            if cur['login_ts'] is None and LOGIN_RE.search(line):
                cur['login_ts'] = ts
            if cur['resp'] is None and (m := RESP_RE.search(line)):
                cur['resp'] = m.group(1)
            if (m := TEMP_RE.search(line)):
                key = 'Temp 1' if 'Temp 1' not in t else 'Temp 2'
                t.setdefault(key, float(m.group(1)))
            if (m := LM86_RE.search(line)):
                t.setdefault(f'LM86 {m.group(1)}', float(m.group(2)))
            if (m := MVL_RE.search(line)):
                t.setdefault('Marvell', float(m.group(1)))
            if (m := PKG_RE.search(line)):
                t.setdefault('SoM Package', float(m.group(1)))
            if (m := RAIL_ROW.search(line)):
                cur['rails'][m.group(1)] = {'rip': float(m.group(6)), 'ok': m.group(7) == 'OK'}
            if not cur['in_report'] and (m := PING_RE.search(line)):
                cur['ping_lost'].append(int(m.group(1)) - int(m.group(2)))
            if (m := TOTAL_RE.search(line)):
                cur['total'] = float(m.group(1))
            if REPORT_RE.search(line):
                cur['in_report'], cur['report_ts'] = True, ts
                continue
            if cur['in_report'] and (m := ITEM_RE.search(TS_STRIP(line))):
                cur['report'][m.group(2).strip()] = m.group(3) == 'OK'
            if FINISH_RE.search(line):
                cur['finished'] = True

    for idx, b in enumerate(boots):
        last = idx == len(boots) - 1
        b['bad_items'] = [k for k, ok in b['report'].items() if not ok]
        if b['resp'] is not None and b['resp'] != '55':
            b['bad_items'].insert(0, f'ft_card_init={b["resp"]}')
        if not b['report'] and not b['bad_items']:
            b['status'] = 'pending' if last else 'fail'
            if not last:
                b['bad_items'] = ['sem Test Report (reboot antes do fim)']
        else:
            b['status'] = 'fail' if b['bad_items'] else 'pass'
    return boots, info


def TS_STRIP(line):
    return re.sub(r'^\[[^\]]{10,30}\]\s*', '', line)


# ── Chamber history ────────────────────────────────────────────────────────────

def load_camara(boots):
    """Chamber samples covering the log ([] when the monitor is unreachable)."""
    ts = [b['ts'] for b in boots if b['ts']]
    if not ts:
        return []
    samples, erro = camara_hist.carregar(min(ts), max(ts))
    if erro:
        print(f'Aviso: histórico da câmara indisponível ({erro}); relatório sem a câmara.')
    return samples


def attach_camara(boots, samples):
    """Puts the chamber PV of the nearest sample in each boot's temps."""
    n = 0
    for b in boots:
        s = camara_hist.mais_proxima(samples, b['login_ts'] or b['ts'])  # temps read after login
        if s:
            b['temps'][CAMARA] = s.pv
            b['cam_sp'] = s.sp
            n += 1
    return n


# ── Yodiz fragment ─────────────────────────────────────────────────────────────

S = {
    'h2':  'font-size:1.05rem;font-weight:700;margin:16px 0 6px 0',
    'h3':  'font-size:.92rem;font-weight:700;margin:14px 0 5px 0',
    'p':   'font-size:.85rem;margin:4px 0 8px 0;line-height:1.5',
    'tbl': 'border-collapse:collapse;margin:6px 0',
    'th':  'text-align:left;padding:4px 10px;background:#f0f0f0;border:1px solid #ddd;font-size:.82rem;white-space:nowrap',
    'td':  'padding:4px 10px;border:1px solid #ddd;font-size:.82rem',
    'tdr': 'padding:4px 10px;border:1px solid #ddd;font-size:.82rem;text-align:right',
    'note':'font-size:.78rem;color:#666;margin:4px 0',
}
COLORS = {'pass': ('#2e7d32', '#e8f5e9'), 'fail': ('#c62828', '#ffebee'),
          'pending': ('#9e9e9e', '#f5f5f5')}
LABEL  = {'pass': 'OK', 'fail': 'FALHA', 'pending': 'em andamento'}


def esc(s):
    return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def th(s):  return f'<th style="{S["th"]}">{s}</th>'
def td(s):  return f'<td style="{S["td"]}">{esc(s)}</td>'
def tdr(s): return f'<td style="{S["tdr"]}">{esc(s)}</td>'
def tds(st, text):
    c, bg = COLORS[st]
    return f'<td style="{S["tdr"]};color:{c};background:{bg};font-weight:700">{esc(text)}</td>'


def avg(v):
    return sum(v) / len(v) if v else None


def fmt_dur(sec):
    h, rem = divmod(int(sec), 3600)
    return f'{h}h{rem // 60:02d}min'


def band_table(done, ref, titulo):
    refd = [b for b in done if ref in b['temps']]
    if not refd:
        return []
    lo = int(min(b['temps'][ref] for b in refd) // BAND_C) * BAND_C
    hi = int(max(b['temps'][ref] for b in refd) // BAND_C) * BAND_C
    p = [f'<h3 style="{S["h3"]}">{esc(titulo)}</h3>',
         f'<table style="{S["tbl"]}"><tr>{th("Faixa (°C)")}{th("Boots")}'
         f'{th("OK")}{th("Falhas")}</tr>']
    for b0 in range(lo, hi + 1, BAND_C):
        bb = [b for b in refd if b0 <= b['temps'][ref] < b0 + BAND_C]
        if not bb:
            continue
        nf = sum(b['status'] == 'fail' for b in bb)
        p.append(f'<tr>{td(f"{b0} a {b0 + BAND_C}")}{tdr(len(bb))}'
                 f'{tdr(len(bb) - nf)}{tds("fail" if nf else "pass", nf)}</tr>')
    p.append('</table>')
    return p


def build(boots, info, logname, title, ref, samples=()):
    done  = [b for b in boots if b['status'] != 'pending']
    fails = [b for b in done if b['status'] == 'fail']
    ts = [b['ts'] for b in boots if b['ts']]
    span = (max(ts) - min(ts)).total_seconds() if len(ts) > 1 else 0

    p = [f'<h2 style="{S["h2"]}">{esc(title)}</h2>']
    meta = [f'<b>Log:</b> {esc(logname)}',
            f'<b>Período:</b> {min(ts):%d/%m %H:%M} → {max(ts):%d/%m %H:%M} ({fmt_dur(span)})']
    if info['dut']:    meta.append(f'<b>DUT:</b> {esc(info["dut"])}')
    if info['fw']:     meta.append(f'<b>FW:</b> {esc(info["fw"])}')
    if info['commit']: meta.append(f'<b>Lua:</b> {esc(info["commit"])}')
    if samples:
        perfis = camara_hist.perfis(samples)
        pv = [s.pv for s in samples]
        cam = f'PV de {min(pv):.1f} a {max(pv):.1f} °C'
        if perfis:
            cam = f'perfil {", ".join(perfis)}, ' + cam
        meta.append(f'<b>Câmara:</b> {esc(cam)}')
    p.append(f'<p style="{S["p"]}">' + ' &nbsp;|&nbsp; '.join(meta) + '</p>')
    n_items = max((len(b['report']) for b in done), default=0)
    p.append(f'<p style="{S["p"]}"><b>Critério:</b> a cada boot, <code>ft_card_init</code> = 55 '
             f'e todos os {n_items} itens do Test Report em OK.</p>')

    # Summary
    cyc = [(b2['ts'] - b1['ts']).total_seconds() for b1, b2 in zip(boots, boots[1:])
           if b1['ts'] and b2['ts']]
    p.append(f'<h3 style="{S["h3"]}">Resumo</h3>')
    p.append(f'<table style="{S["tbl"]}"><tr>{th("Boots")}{th("OK")}{th("Falhas")}'
             f'{th("Duração do ciclo (méd)")}</tr><tr>{tdr(len(done))}'
             f'{tds("pass", len(done) - len(fails))}{tds("fail" if fails else "pass", len(fails))}'
             f'{tdr(f"{avg(cyc) / 60:.1f} min" if cyc else "-")}</tr></table>')

    # Grid
    p.append(f'<h3 style="{S["h3"]}">Boots</h3>')
    cell = ('width:26px;height:20px;padding:0;border:1px solid #fff;font-size:.68rem;'
            'text-align:center;font-weight:600')
    p.append(f'<table style="{S["tbl"]}">')
    for row in range(0, len(boots), GRID_COLS):
        p.append('<tr>')
        for b in boots[row:row + GRID_COLS]:
            c, bg = COLORS[b['status']]
            tip = f'Boot {b["n"]}'
            if b['ts']:
                tip += f' | {b["ts"]:%d/%m %H:%M}'
            if ref in b['temps']:
                tip += f' | {ref}={b["temps"][ref]:.1f} C'
            if CAMARA in b['temps'] and ref != CAMARA:
                tip += f' | câmara={b["temps"][CAMARA]:.1f} C'
                if b.get('cam_sp') is not None:
                    tip += f' (SP {b["cam_sp"]:.1f})'
            if b['bad_items']:
                tip += ' | ' + ', '.join(b['bad_items'])
            p.append(f'<td title="{esc(tip)}" style="{cell};color:{c};background:{bg}">{b["n"]}</td>')
        p.append('</tr>')
    p.append('</table>')
    p.append(f'<p style="{S["note"]}">'
             f'<span style="background:#e8f5e9;color:#2e7d32;padding:0 6px">verde</span> = OK &nbsp; '
             f'<span style="background:#ffebee;color:#c62828;padding:0 6px">vermelho</span> = falha &nbsp; '
             f'<span style="background:#f5f5f5;color:#9e9e9e;padding:0 6px">cinza</span> = em andamento</p>')

    # Failures by item
    if fails:
        count = {}
        for b in fails:
            for it in b['bad_items']:
                count.setdefault(it, []).append(b)
        com_cam = ref != CAMARA and any(CAMARA in b['temps'] for b in fails)
        p.append(f'<h3 style="{S["h3"]}">Itens com falha</h3>')
        p.append(f'<table style="{S["tbl"]}"><tr>{th("Item")}{th("Ocorrências")}'
                 f'{th("Boots")}{th(f"{esc(ref)} nos boots (°C)")}'
                 + (th('Câmara nos boots (°C)') if com_cam else '') + '</tr>')
        for it, bl in sorted(count.items(), key=lambda x: -len(x[1])):
            temps = [f'{b["temps"][ref]:.1f}' for b in bl if ref in b['temps']]
            linha = (f'<tr>{td(it)}{tdr(f"{len(bl)}/{len(done)}")}'
                     f'{td(", ".join(str(b["n"]) for b in bl))}{td(", ".join(temps) or "-")}')
            if com_cam:
                cam = [f'{b["temps"][CAMARA]:.1f}' if CAMARA in b['temps'] else '-' for b in bl]
                linha += td(', '.join(cam))
            p.append(linha + '</tr>')
        p.append('</table>')

    # Temperature coverage
    sensors = []
    for b in done:
        for k in b['temps']:
            if k not in sensors:
                sensors.append(k)
    if sensors:
        p.append(f'<h3 style="{S["h3"]}">Temperaturas no início do verify</h3>')
        p.append(f'<table style="{S["tbl"]}"><tr>{th("Sensor")}{th("mín")}{th("máx")}'
                 f'{th("méd nos boots OK")}{th("méd nos boots com falha")}</tr>')
        for s in sensors:
            v  = [b['temps'][s] for b in done if s in b['temps']]
            vo = [b['temps'][s] for b in done if s in b['temps'] and b['status'] == 'pass']
            vf = [b['temps'][s] for b in fails if s in b['temps']]
            f = lambda x: '-' if x is None else f'{x:.1f}'
            p.append(f'<tr>{td(s)}{tdr(f(min(v)))}{tdr(f(max(v)))}'
                     f'{tdr(f(avg(vo)))}{tdr(f(avg(vf)))}</tr>')
        p.append('</table>')

        # Boots per temperature band: reference sensor, then chamber PV
        p += band_table(done, ref, f'Boots por faixa de temperatura ({ref})')
        if ref != CAMARA:
            p += band_table(done, CAMARA, 'Boots por faixa de temperatura da câmara (PV)')

    # Measurements along the run
    rails = []
    for b in done:
        for r in b['rails']:
            if r not in rails:
                rails.append(r)
    lost  = [x for b in done for x in b['ping_lost']]
    total = [b['total'] for b in done if b['total']]
    if rails or lost or total:
        p.append(f'<h3 style="{S["h3"]}">Medidas ao longo dos boots</h3>')
        p.append(f'<table style="{S["tbl"]}"><tr>{th("Medida")}{th("mín")}{th("méd")}{th("máx")}</tr>')
        if total:
            p.append(f'<tr>{td("Consumo total do sistema (W)")}{tdr(f"{min(total):.1f}")}'
                     f'{tdr(f"{avg(total):.1f}")}{tdr(f"{max(total):.1f}")}</tr>')
        if lost:
            p.append(f'<tr>{td("MGMT ping quick test: pacotes perdidos")}{tdr(min(lost))}'
                     f'{tdr(f"{avg(lost):.1f}")}{tdr(max(lost))}</tr>')
        for r in rails:
            v = [b['rails'][r]['rip'] for b in done if r in b['rails']]
            p.append(f'<tr>{td(f"Ripple {r} (%)")}{tdr(f"{min(v):.3f}")}'
                     f'{tdr(f"{avg(v):.3f}")}{tdr(f"{max(v):.3f}")}</tr>')
        p.append('</table>')

    nota = (f'Temperaturas lidas no início do verify de cada boot. '
            f'Faixas de {BAND_C} °C pelo sensor {esc(ref)}.')
    n_cam = sum(CAMARA in b['temps'] for b in done)
    if n_cam:
        nota += (f' Câmara PV = temperatura medida pelo controlador da câmara no momento '
                 f'do login, com leitura em {n_cam} de {len(done)} boots.')
    p.append(f'<p style="{S["note"]}">{nota}</p>')
    return ''.join(p)


def main():
    args = sys.argv[1:]
    title = 'Reboots com verify — câmara climática'
    ref = 'Temp 1'
    usar_camara = '--sem-camara' not in args
    if not usar_camara:
        args.remove('--sem-camara')
    for opt in ('--title', '--ref'):
        if opt in args:
            k = args.index(opt)
            if opt == '--title':
                title = args[k + 1]
            else:
                ref = args[k + 1]
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
    if not boots:
        print('Nenhum boot encontrado.')
        sys.exit(1)
    samples = load_camara(boots) if usar_camara else []
    if usar_camara:
        n = attach_camara(boots, samples)
        print(f'Câmara: {len(samples)} leituras no período, {n} de {len(boots)} boots com leitura')
    for b in boots:
        tmp = ' '.join(f'{k}={v:.1f}' for k, v in list(b['temps'].items())[:3])
        if CAMARA in b['temps']:
            tmp += f' câmara={b["temps"][CAMARA]:.1f}'
        print(f'  Boot {b["n"]:4d} | {b["ts"]:%d/%m %H:%M:%S} | itens={len(b["report"]):3d} | '
              f'{LABEL[b["status"]]:12s} | {tmp} {"| " + ", ".join(b["bad_items"]) if b["bad_items"] else ""}')
    n_bad = sum(b['status'] == 'fail' for b in boots)
    print(f'Total: {len(boots)} boots | {n_bad} falha(s)')

    out = Path.cwd() / (fp.stem + '_verify_task.html')
    out.write_text(build(boots, info, fp.name, title, ref, samples), encoding='utf-8')
    print(f'\nFragmento Yodiz: {out}')
    os.startfile(out)


if __name__ == '__main__':
    main()
