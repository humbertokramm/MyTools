#!/usr/bin/env python3
"""
Tera Term Log Analyzer — Datacom PD-series climatic chamber loop tests
Generates a self-contained HTML report with temperature charts and failure timeline.

Works for any PD product that uses the rebootTF.lua pattern:
    <device> login: root
    ...
    lua rebootTF.lua <ip>
    ...
    [Info] #  <ProductName> Tests!  #
    ...
    [OK/ERROR] TestName : OK/ERROR
    ...
    Fim do teste: Iniciando o reboot

New in this version:
    - Extracts Mainboard SN and MAC address from each loop
    - Parses Lua Version commit/AuthorDate block
    - Collects boot sequences (Welcome to pd*_ft → login: root)
    - Cross-compares boot sequences: flags truncated boots and unexpected [FAILED] events

Usage:
    python analyze_loop_test.py <log_file.log>
"""

import os
import re
import sys
import json
from datetime import datetime
from pathlib import Path


# ── Timestamp ──────────────────────────────────────────────────────────────────

TS_RE       = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
TS_STRIP_RE = re.compile(r'^\[[^\]]{10,30}\]\s*')  # remove Tera Term timestamp prefix

def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


# ── Boot analysis ──────────────────────────────────────────────────────────────

def analyze_boot(boot_lines):
    """
    Extract systemd status events from the boot window
    (lines between 'Welcome to pd*_ft' and 'login: root').

    Returns (ok_count, failures_list):
        ok_count      — number of [ OK ] / [  OK  ] events observed
        failures_list — list of [FAILED] event descriptions
    """
    ok_count = 0
    failures = []

    for raw in boot_lines:
        stripped = TS_STRIP_RE.sub('', raw.strip())
        m = re.match(r'\[\s*(OK|FAILED|!!|\*\*)\s*\]\s+(.*)', stripped)
        if m:
            status = m.group(1).strip()
            desc   = m.group(2).strip()
            if status == 'OK':
                ok_count += 1
            elif status == 'FAILED':
                failures.append(desc)

    return ok_count, failures


def compute_boot_stats(loops):
    """
    Analyse boot sequences across all loops; mutate each loop dict in place,
    adding: boot_ok, boot_failures, boot_status, boot_unexpected.

    Returns ref_ok (median [ OK ] count from loops with boot data).

    boot_status values:
        'ok'      — boot looks normal
        'fail'    — unexpected [FAILED] events OR boot is <60% of reference length
        'unknown' — no boot data captured for this loop (e.g. first loop in file)
    """
    for loop in loops:
        ok, fails = analyze_boot(loop.get('boot_lines', []))
        loop['boot_ok']       = ok
        loop['boot_failures'] = fails

    booted = [l for l in loops if l['boot_ok'] > 0]
    if not booted:
        for l in loops:
            l['boot_status']     = 'unknown'
            l['boot_unexpected'] = []
        return 0

    # Median [ OK ] count as the reference for "normal" boot
    ok_counts = sorted(l['boot_ok'] for l in booted)
    ref_ok    = ok_counts[len(ok_counts) // 2]

    # Failures seen in >50% of boots are considered expected (hardware quirk)
    all_fails = {}
    for l in booted:
        for f in set(l['boot_failures']):
            all_fails[f] = all_fails.get(f, 0) + 1
    expected = {f for f, c in all_fails.items() if c / len(booted) > 0.5}

    for loop in loops:
        if loop['boot_ok'] == 0:
            loop['boot_status']     = 'unknown'
            loop['boot_unexpected'] = []
            continue
        unexpected = [f for f in loop['boot_failures'] if f not in expected]
        short_boot = loop['boot_ok'] < ref_ok * 0.6
        loop['boot_status']     = 'fail' if (unexpected or short_boot) else 'ok'
        loop['boot_unexpected'] = unexpected

    return ref_ok


# ── Temperature extraction ─────────────────────────────────────────────────────

def extract_temperatures(lines, start, end):
    """
    Scan lines[start:end] for temperature readings.
    Returns dict: sensor_name -> celsius_value (last seen wins).

    Handles formats produced by platf-scripts-lua:
      [Info]    LM75 Temperature: 35.50C           (pd2960, generic)
      [Info]    ADM1032 Local Temperature: 32.0C   (pd2960)
      [Info]    Maple Unit 0 Temperature: 55.0C    (pd2960)
      [Info]    Switch Temperature: 44.5 C.        (pd3900)
      [Info]    temperature monitor 2: current: 51.4C   (pd4202 BCM)
      [OK]      Core Package id 0 temperature is 37.0 Celsius  (pd4202 CPU)
      [OK]      Core Core 4 temperature is 31.0 Celsius        (pd4202 CPU)
      Temp1: 40.06 C   (inside PSU PMBUS INFO block)
    """
    sensors  = {}
    psu_slot = None

    for raw in lines[start:end]:
        line = raw.strip()

        # PSU slot context (for lines without [Info] prefix)
        m = re.search(r'PMBUS INFO \(slot:\s*(\d+)', line)
        if m:
            psu_slot = int(m.group(1))

        # ── BCM/Trident temperature monitor ─────────────────────────────────
        m = re.search(r'temperature monitor (\d+):\s*current:\s*(\d+\.?\d*)C', line)
        if m:
            sensors[f'BCM mon{m.group(1)}'] = float(m.group(2))
            continue

        # ── Intel CPU (SoM) ──────────────────────────────────────────────────
        m = re.search(
            r'(Package id \d+|Core \d+|temp\d+)\s+temperature\s+is\s+(\d+\.?\d*)\s*Celsius',
            line, re.IGNORECASE
        )
        if m:
            sensors[f'CPU {m.group(1)}'] = float(m.group(2))
            continue

        # ── PSU PMBUS Temp1 / Temp2 / Temp3 ─────────────────────────────────
        m = re.search(r'\bTemp([123]):\s*(\d+\.?\d*)\s*C\b', line)
        if m and psu_slot is not None:
            sensors[f'PSU{psu_slot} T{m.group(1)}'] = float(m.group(2))
            continue

        # ── Generic "[Info] <Label> Temperature: X.XC" ──────────────────────
        # Covers: LM75, ADM1032 Local, ADM1032 Remote, ISL68127, Maple Unit N,
        #         Switch, QSFP N, SFP GPON N, SFP28 N, etc.
        m = re.search(
            r'\[(?:Info|OK)\]\s+'
            r'([\w\s\d_/()\-]+?)\s+'
            r'[Tt]emperature:\s*'
            r'(\d+\.?\d*)\s*C',
            line
        )
        if m:
            name = m.group(1).strip()
            sensors[name] = float(m.group(2))
            continue

        # ── "[Info] Switch Temperature: X.X C." (pd3900 style) ──────────────
        m = re.search(
            r'\[Info\]\s+([\w\s\d_/()\-]+?)\s+[Tt]emperature:\s*(\d+\.?\d*)\s*C',
            line
        )
        if m:
            name = m.group(1).strip()
            sensors.setdefault(name, float(m.group(2)))

    return sensors


# ── Log parser ─────────────────────────────────────────────────────────────────

def parse_log(filepath):
    """
    Parse a Tera Term rebootTF-style log into a list of loop dicts.

    Loop lifecycle:
        1. 'Welcome to pd*_ft'     → boot window starts (collected in boot_buf)
        2. '<device> login: root'  → login_time; boot_lines saved to new loop
        3. 'PD<product> Tests!'    → test_start  (banner inside lua)
        4. test + report runs
        5. 'Fim do teste: ...'     → end_time  (from rebootTF.lua)
        6. reboot → BIOS → back to 1

    Each loop dict contains:
        device, login_time, test_start, end_time
        sensors       — temperature dict (extracted after parsing)
        errors        — [ERROR] items from test report
        serial_number — Mainboard SN
        mac_address   — Base MAC Address
        lua_commit    — short SHA from 'Lua Version' block
        lua_date      — AuthorDate from 'Lua Version' block
        boot_lines    — raw lines from 'Welcome to' through 'login: root'
        boot_ok       — filled by compute_boot_stats()
        boot_failures — filled by compute_boot_stats()
        boot_status   — filled by compute_boot_stats()
        boot_unexpected — filled by compute_boot_stats()
    """
    loops    = []
    cur      = None
    raw_buf  = []
    boot_buf = []
    in_boot  = False
    lua_state      = 0
    lua_commit_tmp = None

    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()

    ERR_RE        = re.compile(r'\[ERROR\]\s+([\w_()\s\-]+?)\s*:\s*ERROR')
    LOGIN_RE      = re.compile(r'\]\s*([\w][\w\d._-]+)\s+login:\s+root\b')
    BOOT_START_RE = re.compile(r'Welcome to \w+_ft\b')

    for raw in lines:
        line = raw.rstrip('\n')
        ts   = parse_ts(line)

        # ── Boot window tracking ──────────────────────────────────────────────
        # Collect lines from "Welcome to pd*_ft" until "login: root".
        # These lines belong to the NEXT loop's boot sequence.
        if not in_boot and BOOT_START_RE.search(line):
            in_boot  = True
            boot_buf = [raw]
        elif in_boot:
            boot_buf.append(raw)  # login: root line lands here too, then loop resets below

        # ── New loop: device just rebooted, showing login prompt ──────────────
        if LOGIN_RE.search(line):
            if cur is not None:
                cur['_lines'] = raw_buf[:]
                loops.append(cur)
            hostname = re.search(r'\]\s*([\w][\w\d._-]*)\s+login:', line)
            cur = dict(
                device        = hostname.group(1) if hostname else 'unknown',
                login_time    = ts,
                test_start    = None,
                end_time      = None,
                sensors       = {},
                errors        = [],
                in_report     = False,
                serial_number = None,
                mac_address   = None,
                lua_commit    = None,
                lua_date      = None,
                boot_lines    = boot_buf[:],   # captured before reset
                _lines        = [],
            )
            boot_buf       = []
            in_boot        = False
            lua_state      = 0
            lua_commit_tmp = None
            raw_buf        = [raw]
            continue

        if cur is None:
            continue

        raw_buf.append(raw)

        # ── Test banner: product name detected ────────────────────────────────
        m = re.search(r'#\s+([\w\d]+)\s+Tests!\s+#', line)
        if m and ts and cur['test_start'] is None:
            cur['test_start'] = ts
            cur['product']    = m.group(1)

        # ── Test Report section ───────────────────────────────────────────────
        if 'Test Report!' in line:
            cur['in_report'] = True

        if cur['in_report'] and '[ERROR]' in line:
            em = ERR_RE.search(line)
            if em:
                err = em.group(1).strip()
                if err and err not in cur['errors']:
                    cur['errors'].append(err)

        # ── Loop end ──────────────────────────────────────────────────────────
        if 'Fim do teste: Iniciando o reboot' in line and ts:
            cur['end_time'] = ts

        # ── Serial Number / MAC Address ───────────────────────────────────────
        if cur['serial_number'] is None:
            m = re.search(
                r'Mainboard SN:\s*(\w+)\s*-\s*Base MAC Address:\s*([\w:]+)',
                line
            )
            if m:
                cur['serial_number'] = m.group(1)
                cur['mac_address']   = m.group(2)

        # ── Lua Version block (3-line state machine) ──────────────────────────
        # Line 1: "Lua Version"
        # Line 2: "commit       cb81f8ae... (SHA1)"
        # Line 3: "AuthorDate:  Thu May 14 09:22:34 2026 -0300"
        if lua_state == 0:
            if re.search(r'\bLua Version\b', line):
                lua_state = 1
        elif lua_state == 1:
            m = re.search(r'commit\s+([0-9a-f]{7,40})', line, re.IGNORECASE)
            if m:
                lua_commit_tmp = m.group(1)[:8]   # keep short SHA
                lua_state = 2
            else:
                lua_state = 0  # unexpected line — reset
        elif lua_state == 2:
            m = re.search(r'AuthorDate:\s*(.+)', line)
            if m and cur['lua_commit'] is None:
                cur['lua_commit'] = lua_commit_tmp
                cur['lua_date']   = m.group(1).strip()
            lua_state = 0

    # Last loop (may be in progress)
    if cur is not None:
        cur['_lines'] = raw_buf[:]
        loops.append(cur)

    # Extract temperatures for each loop
    for loop in loops:
        raw_lines = loop.pop('_lines', [])
        loop['sensors'] = extract_temperatures(raw_lines, 0, len(raw_lines))

    return loops


# ── Sensor normalization & chart series selection ──────────────────────────────

def normalize_sensors(loops):
    """
    Build the global sensor list: sensors that appear in >=50% of loops.
    BCM monitors  → averaged into 'BCM avg'.
    CPU Core N    → averaged into 'CPU Cores avg'.
    CPU Package id 0 kept as-is.
    Returns ordered list of up to 8 sensor keys.
    """
    n = len(loops)
    if n == 0:
        return []

    for loop in loops:
        s = loop['sensors']

        bcm_vals  = [v for k, v in s.items() if k.startswith('BCM mon')]
        core_vals = [v for k, v in s.items() if re.match(r'CPU Core \d+', k)]

        for k in list(s.keys()):
            if k.startswith('BCM mon') or re.match(r'CPU Core \d+', k):
                del s[k]

        if bcm_vals:
            s['BCM avg'] = round(sum(bcm_vals) / len(bcm_vals), 1)
        if core_vals:
            s['CPU Cores avg'] = round(sum(core_vals) / len(core_vals), 1)

    counts = {}
    for loop in loops:
        for k in loop['sensors']:
            counts[k] = counts.get(k, 0) + 1

    threshold = max(1, n * 0.5)
    common    = sorted((k for k, c in counts.items() if c >= threshold),
                       key=lambda k: -counts[k])

    priority = ['CPU Package id 0', 'CPU Cores avg', 'BCM avg',
                'PSU0 T1', 'PSU1 T1', 'LM75', 'ADM1032 Local',
                'Maple Unit 0', 'Maple Unit 1', 'Switch']
    ordered  = [k for k in priority if k in common]
    ordered += [k for k in common  if k not in ordered]
    return ordered[:8]


# ── Helpers ────────────────────────────────────────────────────────────────────

def avg(lst):
    return round(sum(lst) / len(lst), 1) if lst else None

def fmt(v):
    return f'{v:.1f}C' if v is not None else '-'

def duration_str(start, end):
    if not start or not end:
        return '-'
    s = int((end - start).total_seconds())
    return f'{s // 60}m {s % 60:02d}s'

def loop_status(loop):
    errs = loop['errors']
    if not errs:
        return 'pass'
    if all('GNSS' in e for e in errs):
        return 'warn'
    return 'fail'

def lua_date_short(raw_date):
    """Convert 'Thu May 14 09:22:34 2026 -0300' to '2026-05-14'."""
    try:
        clean = re.sub(r'\s+[+-]\d{4}$', '', raw_date).strip()
        d = datetime.strptime(clean, '%a %b %d %H:%M:%S %Y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return raw_date[:10]


# ── Color palette ──────────────────────────────────────────────────────────────

COLORS = [
    ('#1565c0', 'rgba(21,101,192,.07)'),
    ('#e65100', 'rgba(230,81,0,.07)'),
    ('#2e7d32', 'rgba(46,125,50,.07)'),
    ('#6a1b9a', 'rgba(106,27,154,.07)'),
    ('#00838f', 'rgba(0,131,143,.07)'),
    ('#c62828', 'rgba(198,40,40,.07)'),
    ('#4527a0', 'rgba(69,39,160,.07)'),
    ('#558b2f', 'rgba(85,139,47,.07)'),
]


# ── HTML template ──────────────────────────────────────────────────────────────

HTML = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>{product} Loop Test — {filename}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.0.1/dist/chartjs-plugin-annotation.min.js"></script>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:14px}}
.wrap{{max-width:1260px;margin:0 auto;padding:24px}}
h1{{font-size:1.35rem;color:#0d1b2a;margin-bottom:3px}}
.sub{{font-size:.82rem;color:#666;margin-bottom:20px}}
.cards{{display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap}}
.card{{background:#fff;border-radius:8px;padding:14px 18px;flex:1;min-width:120px;
       box-shadow:0 1px 4px rgba(0,0,0,.09)}}
.card .v{{font-size:1.9rem;font-weight:700}}
.card .l{{font-size:.73rem;color:#888;margin-top:2px}}
.card.pass .v{{color:#2e7d32}}.card.warn .v{{color:#e65100}}.card.fail .v{{color:#c62828}}
.card.boot-ok .v{{color:#2e7d32}}.card.boot-fail .v{{color:#c62828}}.card.boot-none .v{{color:#9e9e9e}}
.box{{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.09);margin-bottom:20px}}
.box h2{{font-size:.95rem;margin-bottom:14px;color:#333;border-bottom:1px solid #eee;padding-bottom:8px}}
.ch-wrap{{position:relative;height:340px}}
.ch-wrap2{{position:relative;height:200px}}
.tl{{display:flex;flex-direction:column}}
.row{{display:flex;align-items:flex-start;border-bottom:1px solid #f4f4f4;padding:9px 0}}
.row:last-child{{border-bottom:none}}
.num{{width:30px;min-width:30px;height:30px;border-radius:50%;display:flex;align-items:center;
       justify-content:center;font-size:.74rem;font-weight:700;color:#fff;margin-right:12px;flex-shrink:0}}
.num.pass{{background:#2e7d32}}.num.warn{{background:#e65100}}.num.fail{{background:#c62828}}
.body{{flex:1}}
.times{{font-size:.79rem;color:#555}}
.dur{{font-size:.72rem;color:#bbb;margin-left:8px}}
.tags{{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}}
.tag{{font-size:.71rem;padding:2px 8px;border-radius:10px;background:#f0f0f0;color:#444}}
.tag.bk-ok{{background:#e8f5e9;color:#2e7d32}}
.tag.bk-fail{{background:#ffebee;color:#c62828;font-weight:600}}
.tag.bk-warn{{background:#fff3e0;color:#e65100}}
.errs{{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px}}
.eb{{font-size:.7rem;padding:2px 8px;border-radius:4px;font-family:monospace}}
.eb.gnss{{background:#fff3e0;color:#e65100}}.eb.crit{{background:#ffebee;color:#c62828}}
table{{width:100%;border-collapse:collapse;font-size:.8rem}}
th{{text-align:left;padding:8px 10px;background:#f5f5f5;border-bottom:2px solid #ddd;white-space:nowrap}}
td{{padding:7px 10px;border-bottom:1px solid #eee}}
tr:hover td{{background:#fafafa}}
.pill{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.71rem;font-weight:600}}
.pill.pass{{background:#e8f5e9;color:#2e7d32}}
.pill.warn{{background:#fff3e0;color:#e65100}}
.pill.fail{{background:#ffebee;color:#c62828}}
.pill.ok{{background:#e8f5e9;color:#2e7d32}}
.pill.unknown{{background:#f5f5f5;color:#9e9e9e}}
td.ec{{white-space:normal;font-family:monospace;font-size:.7rem;max-width:320px}}
td.boot-fail{{background:#fff5f5;color:#c62828;font-weight:700}}
td.boot-ok{{color:#2e7d32}}
td.boot-unknown{{color:#9e9e9e}}
.boot-list{{font-size:.8rem;color:#555;margin:10px 0 0 4px;list-style:disc inside}}
.boot-list li{{margin-bottom:3px}}
.info-ok{{font-size:.82rem;color:#2e7d32;margin-top:8px}}
</style>
</head>
<body>
<div class="wrap">
  <h1>{product} — Loop Test Report</h1>
  <div class="sub">{filename} &nbsp;|&nbsp; {date_range} &nbsp;|&nbsp; {n} loops &nbsp;|&nbsp; {device}{extra_info}</div>

  <div class="cards">
    <div class="card"><div class="v">{n}</div><div class="l">Loops totais</div></div>
    <div class="card pass"><div class="v">{n_pass}</div><div class="l">Aprovados</div></div>
    <div class="card warn"><div class="v">{n_warn}</div><div class="l">Aviso (so GNSS)</div></div>
    <div class="card fail"><div class="v">{n_fail}</div><div class="l">Falha critica</div></div>
    <div class="card {boot_card_cls}"><div class="v">{n_boot_fail}</div><div class="l">Boot anomalo</div></div>
  </div>

  <div class="box">
    <h2>Temperaturas ao longo do tempo</h2>
    <div class="ch-wrap"><canvas id="ch"></canvas></div>
  </div>

  <div class="box">
    <h2>Boot &mdash; servicos iniciados por loop</h2>
    <div class="ch-wrap2"><canvas id="ch2"></canvas></div>
    {boot_anomaly_html}
  </div>

  <div class="box">
    <h2>Timeline de loops</h2>
    <div class="tl">{tl_rows}</div>
  </div>

  <div class="box">
    <h2>Tabela resumo</h2>
    <table>
      <thead><tr>
        <th>#</th><th>Login</th><th>Inicio teste</th><th>Fim</th><th>Duracao</th>
        {sensor_headers}
        <th>Boot OK</th><th>Status</th><th>Erros</th>
      </tr></thead>
      <tbody>{tb_rows}</tbody>
    </table>
  </div>
</div>

<script>
const D      = {chart_json};
const labels = D.map(d => d.label);
const series = {series_json};
const colors = {colors_json};

// Vertical loop-boundary annotations, coloured by test status
const ann = {{}};
D.forEach((d, i) => {{
  ann['v'+i] = {{
    type: 'line', xMin: i, xMax: i,
    borderColor: d.status==='fail' ? 'rgba(198,40,40,.4)' :
                 d.status==='warn' ? 'rgba(230,81,0,.18)' : 'rgba(0,0,0,.06)',
    borderWidth: d.status==='fail' ? 2 : 1,
    borderDash: [4,4],
    label: {{
      display: d.status==='fail',
      content: 'FALHA', position: 'start',
      color: '#c62828', font: {{size:9, weight:'bold'}},
      backgroundColor: 'rgba(255,235,238,.9)', padding: 2,
    }},
  }};
}});

new Chart(document.getElementById('ch'), {{
  type: 'line',
  data: {{
    labels,
    datasets: series.map((name, i) => ({{
      label: name,
      data: D.map(d => d.temps[name] ?? null),
      borderColor: colors[i][0],
      backgroundColor: colors[i][1],
      pointRadius: 5, tension: .3, fill: false,
      spanGaps: true,
    }})),
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    interaction: {{mode:'index', intersect:false}},
    plugins: {{
      legend: {{position:'top', labels:{{font:{{size:11}}}}}},
      annotation: {{annotations: ann}},
      tooltip: {{
        callbacks: {{
          afterBody(items) {{
            const d = D[items[0].dataIndex];
            if (!d.errors.length) return [];
            return ['', 'Erros:', ...d.errors.map(e => '  • '+e)];
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ticks:{{font:{{size:10}}, maxRotation:45}}}},
      y: {{
        title:{{display:true, text:'Temperatura (C)', font:{{size:11}}}},
        ticks:{{font:{{size:10}}}}
      }}
    }}
  }}
}});

// ── Boot sequence chart ───────────────────────────────────────────────────────
(function() {{
  const BOOT   = {boot_json};
  const REF_OK = {ref_ok};
  if (!BOOT.some(d => d.ok > 0)) return;

  const annot = REF_OK > 0 ? {{
    refLine: {{
      type: 'line', yMin: REF_OK, yMax: REF_OK,
      borderColor: '#e65100', borderWidth: 2, borderDash: [6, 3],
      label: {{
        display: true, content: 'Ref: ' + REF_OK, position: 'end',
        backgroundColor: 'rgba(255,243,224,.9)', color: '#e65100',
        font: {{size: 10}}, padding: 3,
      }}
    }}
  }} : {{}};

  new Chart(document.getElementById('ch2'), {{
    type: 'bar',
    data: {{
      labels: BOOT.map(d => 'L' + d.loop),
      datasets: [{{
        label: 'Servicos [ OK ] no boot',
        data: BOOT.map(d => d.ok > 0 ? d.ok : null),
        backgroundColor: BOOT.map(d =>
          d.status === 'fail'    ? 'rgba(198,40,40,.75)' :
          d.status === 'unknown' ? 'rgba(200,200,200,.4)' :
          'rgba(46,125,50,.65)'),
        borderColor: BOOT.map(d =>
          d.status === 'fail'    ? '#c62828' :
          d.status === 'unknown' ? '#ccc'    : '#2e7d32'),
        borderWidth: 1,
      }}]
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      plugins: {{
        legend: {{display: false}},
        tooltip: {{
          callbacks: {{
            afterBody(ctx) {{
              const d = BOOT[ctx[0].dataIndex];
              if (!d.unexpected || !d.unexpected.length) return [];
              return ['', 'Falhas:', ...d.unexpected.map(f => '  • ' + f)];
            }}
          }}
        }},
        annotation: {{annotations: annot}},
      }},
      scales: {{
        x: {{ticks: {{font: {{size: 10}}, maxRotation: 45}}}},
        y: {{
          title: {{display: true, text: 'Servicos iniciados', font: {{size: 11}}}},
          ticks: {{font: {{size: 10}}}}, beginAtZero: true,
        }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>
"""


# ── Report builder ─────────────────────────────────────────────────────────────

def build(loops, filepath, sensor_keys, ref_ok):
    n_pass      = sum(1 for l in loops if loop_status(l) == 'pass')
    n_warn      = sum(1 for l in loops if loop_status(l) == 'warn')
    n_fail      = sum(1 for l in loops if loop_status(l) == 'fail')
    n_boot_fail = sum(1 for l in loops if l.get('boot_status') == 'fail')

    # Product / device from first loop that has it
    product = next((l.get('product', '') for l in loops if l.get('product')), 'PD??')
    device  = next((l.get('device',  '') for l in loops if l.get('device')),  'unknown')

    # SN / MAC
    sn  = next((l['serial_number'] for l in loops if l.get('serial_number')), None)
    mac = next((l['mac_address']   for l in loops if l.get('mac_address')),   None)

    # ── Lua version tracking ─────────────────────────────────────────────────
    # Build ordered list of (loop_idx, commit, date) for loops with a version.
    lua_seen = [(i, l['lua_commit'], l.get('lua_date', ''))
                for i, l in enumerate(loops) if l.get('lua_commit')]

    # Loops where the commit differs from the previous known version (transitions).
    lua_transitions = set()   # loop indices that introduce a new version
    prev_lua = None
    for idx, commit, _ in lua_seen:
        if prev_lua is not None and commit != prev_lua:
            lua_transitions.add(idx)
        prev_lua = commit

    # First and last unique versions for the subtitle
    lua_first = lua_seen[0]  if lua_seen else None
    lua_last  = lua_seen[-1] if lua_seen else None

    extra_parts = []
    if sn:
        extra_parts.append(f'SN: {sn}')
    if mac:
        extra_parts.append(f'MAC: {mac}')
    if lua_first:
        date_str = lua_date_short(lua_first[2]) if lua_first[2] else ''
        if lua_transitions:
            # Show transition: v1 → v2
            lua_label = (f'Lua: {lua_first[1]} &rarr; {lua_last[1]}'
                         f'<span style="color:#e65100;font-weight:600"> (atualizado)</span>')
        else:
            lua_label = f'Lua: {lua_first[1]}' + (f' ({date_str})' if date_str else '')
        extra_parts.append(lua_label)
    extra_info = (' &nbsp;|&nbsp; ' + ' &nbsp;|&nbsp; '.join(extra_parts)) if extra_parts else ''

    times = [l['login_time'] for l in loops if l['login_time']]
    date_range = (f"{min(times).strftime('%d/%m/%Y %H:%M')} &rarr; "
                  f"{max(times).strftime('%H:%M')}") if times else '-'

    boot_card_cls = 'boot-fail' if n_boot_fail > 0 else 'boot-none' if ref_ok == 0 else 'boot-ok'

    # ── Temperature chart data ───────────────────────────────────────────────
    chart = []
    for l in loops:
        chart.append(dict(
            label  = l['login_time'].strftime('%H:%M') if l['login_time'] else '?',
            temps  = {k: l['sensors'].get(k) for k in sensor_keys},
            status = loop_status(l),
            errors = l['errors'],
        ))

    # ── Boot chart data ──────────────────────────────────────────────────────
    boot_data = [dict(
        loop       = i + 1,
        ok         = l.get('boot_ok', 0),
        status     = l.get('boot_status', 'unknown'),
        unexpected = l.get('boot_unexpected', []),
    ) for i, l in enumerate(loops)]

    # ── Boot anomaly detail HTML ─────────────────────────────────────────────
    anomalies = [(i, l) for i, l in enumerate(loops) if l.get('boot_status') == 'fail']
    if anomalies:
        items = []
        for i, l in anomalies:
            ok    = l.get('boot_ok', 0)
            unexp = l.get('boot_unexpected', [])
            if unexp:
                detail = f'{ok} OK | Falhas inesperadas: {", ".join(unexp)}'
            else:
                detail = f'boot curto ({ok} OK vs ref {ref_ok})'
            items.append(f'<li><strong>Loop {i+1}</strong>: {detail}</li>')
        boot_anomaly_html = f'<ul class="boot-list">{"".join(items)}</ul>'
    elif ref_ok > 0:
        boot_anomaly_html = '<p class="info-ok">Todos os boots concluiram normalmente.</p>'
    else:
        boot_anomaly_html = '<p style="font-size:.82rem;color:#9e9e9e">Sequencia de boot nao capturada neste log.</p>'

    # ── Timeline rows ────────────────────────────────────────────────────────
    tl = []
    for i, l in enumerate(loops):
        st  = loop_status(l)
        t0  = l['login_time'].strftime('%H:%M:%S') if l['login_time'] else '-'
        t1  = l['end_time'].strftime('%H:%M:%S')   if l['end_time']   else '...em andamento'
        dur = duration_str(l['test_start'] or l['login_time'], l['end_time'])

        tags_html = ''.join(
            f'<span class="tag">{k}: {fmt(l["sensors"].get(k))}</span>'
            for k in sensor_keys if l['sensors'].get(k) is not None
        )

        # Boot status tag
        bst   = l.get('boot_status', 'unknown')
        b_ok  = l.get('boot_ok', 0)
        b_unx = l.get('boot_unexpected', [])
        if bst == 'unknown' or b_ok == 0:
            boot_tag = ''
        elif bst == 'fail':
            fail_detail = ', '.join(b_unx) if b_unx else f'curto ({b_ok} OK)'
            boot_tag = f'<span class="tag bk-fail">Boot FALHA: {fail_detail}</span>'
        else:
            boot_tag = f'<span class="tag bk-ok">Boot: {b_ok} OK</span>'

        # Lua version change tag
        if i in lua_transitions:
            new_commit = l.get('lua_commit', '?')
            new_date   = lua_date_short(l.get('lua_date', '')) if l.get('lua_date') else ''
            lua_tag = (f'<span class="tag bk-warn">'
                       f'Lua atualizado: {new_commit}'
                       + (f' ({new_date})' if new_date else '') +
                       f'</span>')
        else:
            lua_tag = ''

        errs_html = ''.join(
            f'<span class="eb {"gnss" if "GNSS" in e else "crit"}">{e}</span>'
            for e in l['errors']
        )
        tl.append(
            f'<div class="row">'
            f'<div class="num {st}">{i+1}</div>'
            f'<div class="body">'
            f'<span class="times">{t0} &rarr; {t1}</span>'
            f'<span class="dur">({dur})</span>'
            f'<div class="tags">{tags_html}{boot_tag}{lua_tag}</div>'
            + (f'<div class="errs">{errs_html}</div>' if errs_html else '') +
            f'</div></div>'
        )

    # ── Table rows ───────────────────────────────────────────────────────────
    sensor_hdrs = ''.join(f'<th>{k}</th>' for k in sensor_keys)

    tb = []
    for i, l in enumerate(loops):
        st  = loop_status(l)
        t0  = l['login_time'].strftime('%H:%M:%S')  if l['login_time']  else '-'
        ts_ = l['test_start'].strftime('%H:%M:%S')  if l['test_start']  else '-'
        t1  = l['end_time'].strftime('%H:%M:%S')    if l['end_time']    else '...'
        dur = duration_str(l['test_start'] or l['login_time'], l['end_time'])
        lbl = {'pass': 'OK', 'warn': 'AVISO', 'fail': 'FALHA'}[st]

        sensor_cells = ''.join(
            f'<td>{fmt(l["sensors"].get(k))}</td>' for k in sensor_keys
        )

        # Boot cell
        bst    = l.get('boot_status', 'unknown')
        b_ok_v = l.get('boot_ok', 0)
        if bst == 'unknown' or b_ok_v == 0:
            boot_cell = '<td class="boot-unknown">-</td>'
        elif bst == 'fail':
            boot_cell = f'<td class="boot-fail">{b_ok_v}</td>'
        else:
            boot_cell = f'<td class="boot-ok">{b_ok_v}</td>'

        errs = ', '.join(l['errors']) if l['errors'] else '-'

        # Lua version change pill (only at transition loops)
        if i in lua_transitions:
            lua_pill = f'<span class="pill warn">Lua {l.get("lua_commit","?")}</span> '
        else:
            lua_pill = ''

        tb.append(
            f'<tr>'
            f'<td>{i+1}</td><td>{t0}</td><td>{ts_}</td><td>{t1}</td><td>{dur}</td>'
            + sensor_cells +
            boot_cell +
            f'<td>{lua_pill}<span class="pill {st}">{lbl}</span></td>'
            f'<td class="ec">{errs}</td>'
            f'</tr>'
        )

    colors_used = COLORS[:len(sensor_keys)]

    html = HTML.format(
        product          = product,
        filename         = Path(filepath).name,
        date_range       = date_range,
        n                = len(loops),
        n_pass           = n_pass,
        n_warn           = n_warn,
        n_fail           = n_fail,
        device           = device,
        extra_info       = extra_info,
        boot_card_cls    = boot_card_cls,
        n_boot_fail      = n_boot_fail,
        boot_anomaly_html= boot_anomaly_html,
        tl_rows          = '\n'.join(tl),
        sensor_headers   = sensor_hdrs,
        tb_rows          = '\n'.join(tb),
        chart_json       = json.dumps(chart,     ensure_ascii=False),
        series_json      = json.dumps(sensor_keys, ensure_ascii=False),
        colors_json      = json.dumps(colors_used, ensure_ascii=False),
        boot_json        = json.dumps(boot_data,  ensure_ascii=False),
        ref_ok           = ref_ok,
    )

    out = Path(filepath).with_name(Path(filepath).stem + '_report.html')
    out.write_text(html, encoding='utf-8')
    return out


# ── Entry point ────────────────────────────────────────────────────────────────

TERATERM_DIR = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')

def resolve_log_path(arg):
    """
    Aceita caminho completo ou apenas o nome do arquivo.
    Tenta, em ordem:
      1. Caminho dado (absoluto ou relativo ao CWD)
      2. TERATERM_DIR / nome
      3. Troca .txt <-> .log e repete 1 e 2
    """
    ext_swap = {'.txt': '.log', '.log': '.txt'}
    p = Path(arg)

    candidates = [p, TERATERM_DIR / p.name]
    alt = p.with_suffix(ext_swap.get(p.suffix.lower(), ''))
    if alt != p:
        candidates += [alt, TERATERM_DIR / alt.name]

    for c in candidates:
        if c.exists():
            return c

    return p   # retorna original para gerar mensagem de erro descritiva


def main():
    if len(sys.argv) < 2:
        print('Uso: analyze_loop_test <arquivo.log>')
        print(f'     (busca automatica em {TERATERM_DIR} se nao encontrar o caminho)')
        sys.exit(1)

    fp = resolve_log_path(sys.argv[1])
    if not fp.exists():
        print(f'Arquivo nao encontrado: {fp}')
        sys.exit(1)

    print(f'Analisando: {fp}')

    loops = parse_log(fp)
    print(f'Loops encontrados: {len(loops)}')

    sensor_keys = normalize_sensors(loops)
    print(f'Sensores detectados: {", ".join(sensor_keys) or "(nenhum)"}')

    ref_ok = compute_boot_stats(loops)
    if ref_ok > 0:
        print(f'Boot de referencia: {ref_ok} servicos [ OK ]')

    # Global SN / Lua info
    sn  = next((l['serial_number'] for l in loops if l.get('serial_number')), None)
    mac = next((l['mac_address']   for l in loops if l.get('mac_address')),   None)
    lua_cmt  = next((l['lua_commit'] for l in loops if l.get('lua_commit')), None)
    lua_date = next((l['lua_date']   for l in loops if l.get('lua_date')),   None)
    if sn:
        print(f'Serial Number: {sn}  MAC: {mac}')
    if lua_cmt:
        print(f'Lua commit: {lua_cmt}  ({lua_date_short(lua_date) if lua_date else "?"})')
    print()

    tst_labels  = {'pass': 'OK   ', 'warn': 'AVISO', 'fail': 'FALHA'}
    boot_labels = {'ok': 'BOOT OK  ', 'fail': 'BOOT FAIL', 'unknown': '         '}
    for i, l in enumerate(loops):
        st   = loop_status(l)
        bst  = l.get('boot_status', 'unknown')
        t0   = l['login_time'].strftime('%H:%M:%S') if l['login_time'] else '-'
        dur  = duration_str(l['test_start'] or l['login_time'], l['end_time'])
        temps = '  '.join(f'{k}={fmt(l["sensors"].get(k))}' for k in sensor_keys[:3])
        b_ok  = l.get('boot_ok', 0)
        boot_str = f'{boot_labels[bst]}({b_ok})'
        print(f'  Loop {i+1:2d} | {t0} | {tst_labels[st]} | {boot_str} | {dur} | {temps}')
        if st == 'fail':
            for e in l['errors']:
                print(f'             ! {e}')
        if bst == 'fail':
            for f in l.get('boot_unexpected', []):
                print(f'             ~ boot: {f}')

    out = build(loops, fp, sensor_keys, ref_ok)
    print(f'\nRelatorio: {out}')
    os.startfile(out)


if __name__ == '__main__':
    main()
