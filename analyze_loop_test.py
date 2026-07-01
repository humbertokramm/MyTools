#!/usr/bin/env python3
"""
Tera Term Log Analyzer — Datacom PD-series climatic chamber loop tests
Generates a self-contained HTML report with temperature charts and failure timeline.

New in v3:
    - Test results matrix (per-loop x per-test grid)
    - DPLL clock reference table (all 10 REFs per loop)
    - BCM Test 143 timing + pass/fail tracking
    - AVS voltage chart (sensors 2/5/6)
    - Bug investigation cards: BG-2323, BG-2136, BG-2109

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
TS_STRIP_RE = re.compile(r'^\[[^\]]{10,30}\]\s*')

# ── DUT identification patterns ────────────────────────────────────────────────

MAINBOARD_IDENT_RE = re.compile(
    r'\]\s*(DM[\w\s+]*?)\s+-\s+(\d{3}\.\d{4}\.\d+)\s+-\s+(\d+)'
)
PSU_DC_RE    = re.compile(r'PSU DC:\s+(\S+)\s+(.*\S)')
PSU_AC_RE    = re.compile(r'PSU AC:\s+(\S+)\s+(.*\S)')
FAN_TRAY_RE  = re.compile(r'FAN Tray (\d+):\s+([\d.]+)\s+-\s+(\d+),\s*HV\s*=\s*(\d+)')
MAX34460_RE  = re.compile(r'MAX34460 CRC read (0x[0-9A-Fa-f]+)')
ZL_FW_RE     = re.compile(r'ZL30733.*Device Firmware Version read (0x[0-9A-Fa-f]+)')
ZL_CFG_RE    = re.compile(r'Device Custom Config Version read (0x[0-9A-Fa-f]+)')
GNSS_VER_RE  = re.compile(r'Device Firmware Version read (LC\w+)\s+correctly')
FPGA_DATE_RE = re.compile(r'Mainboard FPGA Release Date:\s*(.+)')

# ── New patterns for extended parsing ─────────────────────────────────────────

# Named test result lines from the Test Report section
# e.g. "[OK]    Testing_ZL30733 : OK"  or  "[ERROR]    Testing_GNSS_Antenna : ERROR"
NAMED_TEST_RE = re.compile(
    r'\[(OK|ERROR)\]\s+(Testing[\w_()\s\-]+?)\s*:\s*(OK|ERROR)',
    re.IGNORECASE
)

# DPLL table row: "| REF_0P | 24.576 MHz | OK | OK | OK | OK | OK |"
DPLL_ROW_RE = re.compile(
    r'\|\s*(REF_[0-4][PN])\s*\|\s*([\d.]+\s*[kMGT]?Hz)\s*\|'
    r'\s*(OK|--|\w+)\s*\|\s*(OK|--|\w+)\s*\|\s*(OK|--|\w+)\s*\|'
    r'\s*(OK|--|\w+)\s*\|\s*(OK|--|\w+)\s*\|?'
)

# BCM Test 143 final result line
# e.g. "Test 143: Pass=1 Fail=0"
BCM143_RESULT_RE = re.compile(
    r'[Tt]est\s*[\(]?143[\)]?\s*[:\-]?\s*[Pp]ass\s*=\s*(\d+)\s+[Ff]ail\s*=\s*(\d+)'
)

# BCM Test 143 start (when SDK issues the test)
BCM143_START_RE = re.compile(
    r'(?:test run|running test|Starting test|bcm_test_run)\s*[\(]?143[\)]?'
    r'|Test\s+\(143\)',
    re.IGNORECASE
)

# AVS voltage sensor reading
# e.g. "Voltage monitor 2 =  0.827 V"  or  "Sensor 2: 0.827 V"
AVS_SENSOR_RE = re.compile(
    r'(?:[Vv]oltage\s+monitor|[Ss]ensor)\s+(\d+)\s*[:\-=]\s*([\d.]+)\s*V\b'
)

# BCM PLL lock status line
# e.g. "CORE_PLL0_LOCK_STATUS = 1"
BCM_PLL_RE = re.compile(r'(\w+PLL\w*(?:_LOCK(?:_STATUS)?)?)\s*=\s*([01])\b')


def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


# ── Boot analysis ──────────────────────────────────────────────────────────────

def analyze_boot(boot_lines):
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

    ok_counts = sorted(l['boot_ok'] for l in booted)
    ref_ok    = ok_counts[len(ok_counts) // 2]

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
    sensors  = {}
    psu_slot = None

    for raw in lines[start:end]:
        line = raw.strip()

        m = re.search(r'PMBUS INFO \(slot:\s*(\d+)', line)
        if m:
            psu_slot = int(m.group(1))

        m = re.search(r'temperature monitor (\d+):\s*current:\s*(\d+\.?\d*)C', line)
        if m:
            sensors[f'BCM mon{m.group(1)}'] = float(m.group(2))
            continue

        m = re.search(
            r'(Package id \d+|Core \d+|temp\d+)\s+temperature\s+is\s+(\d+\.?\d*)\s*Celsius',
            line, re.IGNORECASE
        )
        if m:
            sensors[f'CPU {m.group(1)}'] = float(m.group(2))
            continue

        m = re.search(r'\bTemp([123]):\s*(\d+\.?\d*)\s*C\b', line)
        if m and psu_slot is not None:
            sensors[f'PSU{psu_slot} T{m.group(1)}'] = float(m.group(2))
            continue

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

        m = re.search(
            r'\[Info\]\s+([\w\s\d_/()\-]+?)\s+[Tt]emperature:\s*(\d+\.?\d*)\s*C',
            line
        )
        if m:
            name = m.group(1).strip()
            sensors.setdefault(name, float(m.group(2)))

    return sensors


# ── Log parser ─────────────────────────────────────────────────────────────────

LOOP_MARKER_RE = re.compile(r'=== LOOP TEST ===\s*(\d+)\s+Total de erros\s+(\d+)')

def _new_loop_dict(device='unknown', prev=None):
    """Create a fresh per-loop dict; inherit static DUT fields from prev if given."""
    d = dict(
        device            = device,
        login_time        = None,
        test_start        = None,
        end_time          = None,
        sensors           = {},
        errors            = [],
        in_report         = False,
        serial_number     = None,
        mac_address       = None,
        lua_commit        = None,
        lua_date          = None,
        boot_lines        = [],
        _lines            = [],
        mainboard_product = None,
        mainboard_pn      = None,
        psu_dc_model      = None,
        psu_dc_sn         = None,
        psu_ac_model      = None,
        psu_ac_sn         = None,
        fan_trays         = {},
        max34460_crc      = None,
        zl30733_fw        = None,
        zl30733_cfg       = None,
        gnss_ver          = None,
        fpga_date         = None,
        test_results      = {},
        dpll_refs         = {},
        bcm143_pass       = None,
        bcm143_fail       = None,
        bcm143_start_ts   = None,
        bcm143_end_ts     = None,
        bcm143_duration_s = None,
        avs               = {},
        product           = None,
    )
    # Inherit static DUT info from previous loop (only set once at startup)
    if prev:
        for k in ('device', 'serial_number', 'mac_address',
                  'mainboard_product', 'mainboard_pn',
                  'psu_dc_model', 'psu_dc_sn',
                  'psu_ac_model', 'psu_ac_sn',
                  'fan_trays', 'max34460_crc',
                  'zl30733_fw', 'zl30733_cfg',
                  'gnss_ver', 'fpga_date',
                  'lua_commit', 'lua_date',
                  'product'):
            if prev.get(k):
                d[k] = prev[k]
    return d


def parse_log(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()

    # Auto-detect mode: count === LOOP TEST === vs login: root occurrences
    n_lua_loops = sum(1 for l in lines if '=== LOOP TEST ===' in l)
    n_logins    = sum(1 for l in lines
                      if re.search(r'\]\s*\w[\w\d._-]+\s+login:\s+root\b', l))
    lua_loop_mode = (n_lua_loops > n_logins)

    loops    = []
    cur      = None
    raw_buf  = []
    boot_buf = []
    in_boot  = False
    lua_state      = 0
    lua_commit_tmp = None
    in_report      = False
    device         = 'unknown'

    ERR_RE        = re.compile(r'\[ERROR\]\s+([\w_()\s\-]+?)\s*:\s*ERROR')
    LOGIN_RE      = re.compile(r'\]\s*([\w][\w\d._-]+)\s+login:\s+root\b')
    BOOT_START_RE = re.compile(r'Welcome to \w+_ft\b')
    # BCM143 start: "dsh -c \"test run 143\""
    BCM143_DSH_RE = re.compile(r'dsh\s+-c\s+"test run 143"', re.IGNORECASE)

    for raw in lines:
        line = raw.rstrip('\n')
        ts   = parse_ts(line)

        # ── Boot window tracking (reboot mode) ────────────────────────────────
        if not lua_loop_mode:
            if not in_boot and BOOT_START_RE.search(line):
                in_boot  = True
                boot_buf = [raw]
            elif in_boot:
                boot_buf.append(raw)

        # ── Login: always capture device name ────────────────────────────────
        m_login = LOGIN_RE.search(line)
        if m_login:
            hostname = re.search(r'\]\s*([\w][\w\d._-]*)\s+login:', line)
            if hostname:
                device = hostname.group(1)

            if not lua_loop_mode:
                # Reboot mode: login starts a new loop
                if cur is not None:
                    cur['_lines'] = raw_buf[:]
                    loops.append(cur)
                cur = _new_loop_dict(device)
                cur['login_time'] = ts
                cur['boot_lines'] = boot_buf[:]
                boot_buf   = []
                in_boot    = False
                in_report  = False
                lua_state  = 0
                lua_commit_tmp = None
                raw_buf    = [raw]
                continue
            else:
                # Lua-loop mode: login is just a global header event
                if cur is None:
                    cur = _new_loop_dict(device)
                    cur['login_time'] = ts
                    raw_buf = [raw]
                else:
                    cur['device'] = device
                continue

        # ── Lua-loop mode: === LOOP TEST === N starts a new loop ──────────────
        if lua_loop_mode:
            m_lm = LOOP_MARKER_RE.search(line)
            if m_lm:
                loop_num   = int(m_lm.group(1))
                erros_sofar = int(m_lm.group(2))
                if cur is not None and loop_num > 0:
                    # Save the just-completed loop
                    cur['_lines'] = raw_buf[:]
                    loops.append(cur)
                    cur = _new_loop_dict(device, prev=cur)
                elif cur is None:
                    cur = _new_loop_dict(device)
                cur['login_time'] = ts
                cur['lua_loop_num'] = loop_num
                cur['erros_sofar']  = erros_sofar
                in_report  = False
                lua_state  = 0
                lua_commit_tmp = None
                raw_buf    = [raw]
                continue

        if cur is None:
            continue

        raw_buf.append(raw)

        stripped = TS_STRIP_RE.sub('', line.strip())

        # ── Test banner ───────────────────────────────────────────────────────
        m = re.search(r'#\s+([\w\d]+)\s+Tests!\s+#', line)
        if m and ts and cur['test_start'] is None:
            cur['test_start'] = ts
            if not cur.get('product'):
                cur['product'] = m.group(1)

        # ── Test Report section ───────────────────────────────────────────────
        if 'Test Report!' in line:
            in_report = True
            cur['in_report'] = True

        if in_report and '[ERROR]' in line:
            em = ERR_RE.search(line)
            if em:
                err = em.group(1).strip()
                if err and err not in cur['errors']:
                    cur['errors'].append(err)

        # Named test results — capture from report section
        if in_report:
            m = NAMED_TEST_RE.search(stripped)
            if m:
                tname = m.group(2).strip()
                tstatus = m.group(1).lower()
                cur['test_results'][tname] = tstatus
                # BCM143 pass/fail derived from test result (no explicit Pass=N line)
                if 'BCM_Test_Run' in tname or 'BCM Test Run' in tname:
                    if tstatus == 'ok':
                        cur['bcm143_pass'] = cur.get('bcm143_pass') or 1
                        cur['bcm143_fail'] = cur.get('bcm143_fail') or 0
                    else:
                        cur['bcm143_pass'] = cur.get('bcm143_pass') or 0
                        cur['bcm143_fail'] = (cur.get('bcm143_fail') or 0) + 1
                    # Compute timing if start was captured
                    if ts and cur['bcm143_start_ts'] and cur['bcm143_end_ts'] is None:
                        cur['bcm143_end_ts'] = ts
                        cur['bcm143_duration_s'] = int(
                            (ts - cur['bcm143_start_ts']).total_seconds()
                        )

        # ── Loop end ──────────────────────────────────────────────────────────
        if 'Fim do teste: Iniciando o reboot' in line and ts:
            cur['end_time'] = ts
            in_report = False
        if 'Device Test Finished Correctly' in line and ts:
            cur['end_time'] = ts
            in_report = False

        # ── Serial / MAC ──────────────────────────────────────────────────────
        if cur['serial_number'] is None:
            m = re.search(
                r'Mainboard SN:\s*(\w+)\s*-\s*Base MAC Address:\s*([\w:]+)',
                line
            )
            if m:
                cur['serial_number'] = m.group(1)
                cur['mac_address']   = m.group(2)

        # ── DUT identification ────────────────────────────────────────────────
        if cur['mainboard_product'] is None:
            m = MAINBOARD_IDENT_RE.search(line)
            if m:
                cur['mainboard_product'] = m.group(1).strip()
                cur['mainboard_pn']      = m.group(2)

        if cur['psu_dc_model'] is None:
            m = PSU_DC_RE.search(line)
            if m:
                cur['psu_dc_model'] = m.group(1).strip()
                cur['psu_dc_sn']    = m.group(2).strip()

        if cur['psu_ac_model'] is None:
            m = PSU_AC_RE.search(line)
            if m:
                cur['psu_ac_model'] = m.group(1).strip()
                cur['psu_ac_sn']    = m.group(2).strip()

        m = FAN_TRAY_RE.search(line)
        if m:
            tray = int(m.group(1))
            if tray not in cur['fan_trays']:
                cur['fan_trays'][tray] = {
                    'pn': m.group(2),
                    'sn': int(m.group(3)),
                    'hv': int(m.group(4)),
                }

        if cur['max34460_crc'] is None:
            m = MAX34460_RE.search(line)
            if m: cur['max34460_crc'] = m.group(1)

        if cur['zl30733_fw'] is None:
            m = ZL_FW_RE.search(line)
            if m: cur['zl30733_fw'] = m.group(1)

        if cur['zl30733_cfg'] is None:
            m = ZL_CFG_RE.search(line)
            if m: cur['zl30733_cfg'] = m.group(1)

        if cur['gnss_ver'] is None:
            m = GNSS_VER_RE.search(line)
            if m: cur['gnss_ver'] = m.group(1)

        if cur['fpga_date'] is None:
            m = FPGA_DATE_RE.search(line)
            if m: cur['fpga_date'] = m.group(1).strip()

        # ── Lua Version block ─────────────────────────────────────────────────
        if lua_state == 0:
            if re.search(r'\bLua Version\b', line):
                lua_state = 1
        elif lua_state == 1:
            m = re.search(r'commit\s+([0-9a-f]{7,40})', line, re.IGNORECASE)
            if m:
                lua_commit_tmp = m.group(1)
                lua_state = 2
            else:
                lua_state = 0
        elif lua_state == 2:
            m = re.search(r'AuthorDate:\s*(.+)', line)
            if m and cur['lua_commit'] is None:
                cur['lua_commit'] = lua_commit_tmp
                cur['lua_date']   = m.group(1).strip()
            lua_state = 0

        # ── DPLL table rows ───────────────────────────────────────────────────
        m = DPLL_ROW_RE.search(line)
        if m:
            ref_name = m.group(1)
            freq     = m.group(2).strip()
            cols     = [m.group(i).strip() for i in range(3, 8)]
            cur['dpll_refs'][ref_name] = {'freq': freq, 'cols': cols}

        # ── BCM Test 143 timing ───────────────────────────────────────────────
        if cur['bcm143_start_ts'] is None and BCM143_DSH_RE.search(line):
            cur['bcm143_start_ts'] = ts

        # Explicit Pass=N Fail=N line (some log formats have this)
        m = BCM143_RESULT_RE.search(stripped)
        if m:
            cur['bcm143_pass'] = int(m.group(1))
            cur['bcm143_fail'] = int(m.group(2))
            if ts and cur['bcm143_start_ts'] and cur['bcm143_end_ts'] is None:
                cur['bcm143_end_ts'] = ts
                cur['bcm143_duration_s'] = int(
                    (ts - cur['bcm143_start_ts']).total_seconds()
                )

        # ── AVS voltage sensors ───────────────────────────────────────────────
        m = AVS_SENSOR_RE.search(stripped)
        if m:
            cur['avs'][m.group(1)] = float(m.group(2))

    # Last loop (may be in progress)
    if cur is not None:
        cur['_lines'] = raw_buf[:]
        loops.append(cur)

    for loop in loops:
        raw_lines = loop.pop('_lines', [])
        loop['sensors'] = extract_temperatures(raw_lines, 0, len(raw_lines))

    return loops


# ── Sensor normalization ───────────────────────────────────────────────────────

def normalize_sensors(loops):
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
    try:
        clean = re.sub(r'\s+[+-]\d{4}$', '', raw_date).strip()
        d = datetime.strptime(clean, '%a %b %d %H:%M:%S %Y')
        return d.strftime('%Y-%m-%d')
    except Exception:
        return raw_date[:10]


# ── Extended data helpers ──────────────────────────────────────────────────────

# Canonical order for DPLL references
DPLL_ORDER = ['REF_0P', 'REF_0N', 'REF_1P', 'REF_1N',
              'REF_2P', 'REF_2N', 'REF_3P', 'REF_3N',
              'REF_4P', 'REF_4N']

# Tests highlighted for BG investigation
BUG_TESTS = {
    'BG-2323': ['Testing_BCM_Test_Run', 'Testing BCM Test Run'],
    'BG-2136': [],   # DPLL-based, not test_results
    'BG-2109': ['Testing_GNSS_Antenna', 'Testing_GNSS', 'Testing_LC29T_Module'],
}


def dpll_ref_ok(ref_data):
    """True if all 5 columns of a DPLL ref entry are 'OK'."""
    return all(c.upper() == 'OK' for c in ref_data['cols'])


def build_test_matrix(loops):
    """Return (all_tests_ordered, matrix) where matrix[i][test] = 'ok'|'error'|'-'."""
    name_set = {}
    for loop in loops:
        for k in loop['test_results']:
            name_set[k] = name_set.get(k, 0) + 1
    # Sort by frequency desc, then alpha
    all_tests = sorted(name_set, key=lambda k: (-name_set[k], k))
    return all_tests


def build_bug_cards(loops):
    """Return list of (bug_id, title, detail_lines, status_cls) for the bug section."""
    n = len(loops)
    completed = [l for l in loops if l.get('bcm143_pass') is not None]
    cards = []

    # ── BG-2323: BCM Test 143 failures ───────────────────────────────────────
    if completed:
        total_pass = sum(l['bcm143_pass'] for l in completed)
        total_fail = sum(l['bcm143_fail'] for l in completed)
        durs = [l['bcm143_duration_s'] for l in completed if l['bcm143_duration_s']]
        dur_str = f'{min(durs)}–{max(durs)}s' if durs else '?'
        fail_loops = [i+1 for i, l in enumerate(loops) if (l.get('bcm143_fail') or 0) > 0]
        if total_fail == 0:
            st = 'ok'
            verdict = 'SEM OCORRÊNCIAS nesta sessão'
        else:
            st = 'fail'
            verdict = f'FALHA em {total_fail} execuções — loops: {fail_loops}'
        cards.append((
            'BG-2323',
            '[DM4780-4DX] Erro shell test 143 na TB platf-3',
            [
                f'{len(completed)}/{n} loops com resultado | Pass={total_pass} Fail={total_fail}',
                f'Duração: {dur_str}',
            ],
            st,
            verdict,
        ))
    else:
        cards.append((
            'BG-2323',
            '[DM4780-4DX] Erro shell test 143 na TB platf-3',
            ['Resultado BCM Test 143 não detectado no log'],
            'unknown',
            'DADOS INSUFICIENTES',
        ))

    # ── BG-2136: REF_3P / REF_3N lock instability ────────────────────────────
    ref3_data = []
    for i, l in enumerate(loops):
        r3p = l['dpll_refs'].get('REF_3P')
        r3n = l['dpll_refs'].get('REF_3N')
        ref3_data.append({
            'loop': i+1,
            'ref3p_ok': dpll_ref_ok(r3p) if r3p else None,
            'ref3n_ok': dpll_ref_ok(r3n) if r3n else None,
            'ref3p_freq': r3p['freq'] if r3p else '?',
            'ref3n_freq': r3n['freq'] if r3n else '?',
        })

    loops_with_dpll = [d for d in ref3_data if d['ref3p_ok'] is not None]
    if loops_with_dpll:
        p_ok  = sum(1 for d in loops_with_dpll if d['ref3p_ok'])
        n_ok  = sum(1 for d in loops_with_dpll if d['ref3n_ok'])
        nd    = len(loops_with_dpll)
        p_fail_loops = [d['loop'] for d in loops_with_dpll if not d['ref3p_ok']]
        n_fail_loops = [d['loop'] for d in loops_with_dpll if d['ref3n_ok'] is False]
        if p_ok == nd and n_ok == nd:
            st      = 'ok'
            verdict = 'SEM INSTABILIDADE nesta sessão'
        else:
            st      = 'fail'
            verdict = 'INSTABILIDADE DETECTADA'
        freq3p = loops_with_dpll[0]['ref3p_freq']
        freq3n = loops_with_dpll[0]['ref3n_freq']
        details = [
            f'REF_3P ({freq3p}): {p_ok}/{nd} loops OK' +
            (f' — falhas loops {p_fail_loops}' if p_fail_loops else ''),
            f'REF_3N ({freq3n}): {n_ok}/{nd} loops OK' +
            (f' — falhas loops {n_fail_loops}' if n_fail_loops else ''),
        ]
    else:
        st      = 'unknown'
        verdict = 'DADOS INSUFICIENTES'
        details = ['Tabela DPLL não detectada no log']

    cards.append(('BG-2136',
                  'Instabilidade no Lock/Unlock do clock REF3 (25 MHz)',
                  details, st, verdict))

    # ── BG-2109: GNSS failure after over-temperature ──────────────────────────
    gnss_data = []
    bcm_temps = []
    for i, l in enumerate(loops):
        gnss_ok = None
        for k, v in l['test_results'].items():
            if 'GNSS' in k.upper() or 'LC29T' in k.upper():
                gnss_ok = (v == 'ok')
        # BCM temperature peak for this loop (from sensors dict before normalization)
        bcm_mon_vals = [v for k, v in l['sensors'].items() if 'BCM' in k]
        peak = max(bcm_mon_vals) if bcm_mon_vals else None
        gnss_data.append({'loop': i+1, 'gnss_ok': gnss_ok, 'bcm_peak': peak})
        if peak: bcm_temps.append(peak)

    loops_with_gnss = [d for d in gnss_data if d['gnss_ok'] is not None]
    if loops_with_gnss:
        g_ok = sum(1 for d in loops_with_gnss if d['gnss_ok'])
        ng   = len(loops_with_gnss)
        max_t = max(bcm_temps) if bcm_temps else None
        gnss_fail_loops = [d['loop'] for d in loops_with_gnss if not d['gnss_ok']]
        if g_ok == ng:
            st      = 'ok'
            verdict = 'SEM FALHAS GNSS nesta sessão'
        else:
            st      = 'fail'
            verdict = f'FALHA GNSS em loops {gnss_fail_loops}'
        details = [
            f'GNSS: {g_ok}/{ng} loops OK',
            f'BCM temp máx: {max_t:.1f}°C' if max_t else 'BCM temp: N/D',
        ]
    else:
        st      = 'unknown'
        verdict = 'DADOS INSUFICIENTES'
        details = ['Teste GNSS não detectado no log']

    cards.append(('BG-2109',
                  '[DM4780] Falha GNSS após sobretemperatura',
                  details, st, verdict))

    return cards


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

AVS_COLORS = [
    ('#1565c0', 'rgba(21,101,192,.15)'),
    ('#e65100', 'rgba(230,81,0,.15)'),
    ('#2e7d32', 'rgba(46,125,50,.15)'),
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
.wrap{{max-width:1320px;margin:0 auto;padding:24px}}
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
.ch-wrap3{{position:relative;height:200px}}
.ch-wrap4{{position:relative;height:220px}}
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
.dut-tbl{{width:auto;border-collapse:separate;border-spacing:6px 5px;margin-top:-4px}}
.dut-tbl td{{padding:1px 4px;border:none;background:transparent}}
.dk{{font-size:.72rem;color:#888;white-space:nowrap;text-align:right}}
.dv{{font-size:.82rem;font-family:'Consolas',monospace;color:#1a1a2e;padding-right:14px}}
.box-hdr{{display:flex;align-items:center;justify-content:space-between;
          margin-bottom:14px;padding-bottom:8px;border-bottom:1px solid #eee}}
.box-hdr h2{{margin-bottom:0;padding-bottom:0;border-bottom:none;font-size:.95rem;color:#333}}
.btn-copy{{font-size:.72rem;padding:3px 11px;border:1px solid #d0d0d0;border-radius:4px;
           background:#fafafa;color:#666;cursor:pointer;transition:all .15s;white-space:nowrap}}
.btn-copy:hover,.btn-copy.copied{{background:#e8f5e9;border-color:#2e7d32;color:#2e7d32}}
/* ── Bug cards ────────────────────────────────────────────────────────────── */
.bug-grid{{display:flex;gap:12px;flex-wrap:wrap}}
.bug-card{{flex:1;min-width:260px;border-radius:8px;border:1px solid #e0e0e0;
           padding:14px 16px;background:#fafafa}}
.bug-id{{font-size:.72rem;font-weight:700;font-family:monospace;color:#666;margin-bottom:3px}}
.bug-title{{font-size:.82rem;font-weight:600;color:#333;margin-bottom:8px;line-height:1.3}}
.bug-detail{{font-size:.78rem;color:#666;line-height:1.6;margin-bottom:10px}}
.bug-status{{font-size:.78rem;font-weight:700;padding:3px 10px;border-radius:4px;
             display:inline-block}}
.bug-status.ok{{background:#e8f5e9;color:#2e7d32}}
.bug-status.fail{{background:#ffebee;color:#c62828}}
.bug-status.unknown{{background:#f5f5f5;color:#9e9e9e}}
.bug-card.fail{{border-color:#ffcdd2;background:#fff8f8}}
.bug-card.ok{{border-color:#c8e6c9}}
/* ── Test matrix ──────────────────────────────────────────────────────────── */
.matrix-tbl th{{text-align:center;font-size:.73rem;padding:5px 8px}}
.matrix-tbl td{{text-align:center;font-size:.73rem;padding:5px 8px;white-space:nowrap}}
.matrix-tbl .test-name{{text-align:left;font-family:monospace;font-size:.73rem;white-space:nowrap}}
.mc-ok{{background:#e8f5e9;color:#2e7d32;font-weight:600;border-radius:3px}}
.mc-error{{background:#ffebee;color:#c62828;font-weight:600;border-radius:3px}}
.mc-miss{{color:#ccc}}
/* ── DPLL table ───────────────────────────────────────────────────────────── */
.dpll-tbl th{{font-size:.73rem;padding:5px 8px;text-align:center}}
.dpll-tbl td{{font-size:.73rem;padding:5px 8px;text-align:center;white-space:nowrap}}
.dpll-tbl .ref-name{{font-family:monospace;font-weight:600;text-align:left}}
.dpll-tbl .freq{{font-family:monospace;color:#666}}
.dpll-ok{{color:#2e7d32;font-weight:600}}
.dpll-err{{color:#c62828;font-weight:700;background:#ffebee}}
.dpll-ref3{{background:#fff8e1}}
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

  {dut_info_html}

  {bug_section_html}

  <div class="box">
    <h2>Temperaturas ao longo do tempo</h2>
    <div class="ch-wrap"><canvas id="ch"></canvas></div>
  </div>

  {test_matrix_html}

  {dpll_table_html}

  {bcm143_section_html}

  {avs_section_html}

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

// ── Boot chart ────────────────────────────────────────────────────────────────
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

// ── BCM Test 143 timing chart ─────────────────────────────────────────────────
(function() {{
  const B143 = {bcm143_json};
  if (!B143.some(d => d.dur !== null)) return;
  const el = document.getElementById('ch3');
  if (!el) return;
  new Chart(el, {{
    type: 'bar',
    data: {{
      labels: B143.map(d => 'L' + d.loop),
      datasets: [{{
        label: 'Duração (s)',
        data: B143.map(d => d.dur),
        backgroundColor: B143.map(d =>
          d.fail > 0 ? 'rgba(198,40,40,.75)' : 'rgba(21,101,192,.65)'),
        borderColor: B143.map(d => d.fail > 0 ? '#c62828' : '#1565c0'),
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
              const d = B143[ctx[0].dataIndex];
              return [`Pass=${{d.pass}}  Fail=${{d.fail}}`];
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ticks: {{font: {{size: 10}}}}}},
        y: {{
          title: {{display: true, text: 'Segundos', font: {{size: 11}}}},
          ticks: {{font: {{size: 10}}}}, beginAtZero: true,
        }}
      }}
    }}
  }});
}})();

// ── AVS Voltage chart ──────────────────────────────────────────────────────────
(function() {{
  const AVS = {avs_json};
  const AVSC = {avs_colors_json};
  if (!AVS.sensors.length) return;
  const el = document.getElementById('ch4');
  if (!el) return;
  new Chart(el, {{
    type: 'line',
    data: {{
      labels: AVS.labels,
      datasets: AVS.sensors.map((s, i) => ({{
        label: 'Sensor ' + s,
        data: AVS.values[i],
        borderColor: AVSC[i % AVSC.length][0],
        backgroundColor: AVSC[i % AVSC.length][1],
        pointRadius: 5, tension: .3, fill: false, spanGaps: true,
      }})),
    }},
    options: {{
      responsive: true, maintainAspectRatio: false,
      interaction: {{mode:'index', intersect:false}},
      plugins: {{
        legend: {{position:'top', labels:{{font:{{size:11}}}}}},
        annotation: {{annotations: {{
          lo: {{type:'line',yMin:0.808,yMax:0.808,borderColor:'rgba(198,40,40,.4)',
                borderDash:[4,4],borderWidth:1,
                label:{{display:true,content:'-2%',position:'start',
                       color:'#c62828',font:{{size:9}},padding:2}}}},
          hi: {{type:'line',yMin:0.842,yMax:0.842,borderColor:'rgba(198,40,40,.4)',
                borderDash:[4,4],borderWidth:1,
                label:{{display:true,content:'+2%',position:'start',
                       color:'#c62828',font:{{size:9}},padding:2}}}},
          nom: {{type:'line',yMin:0.825,yMax:0.825,borderColor:'rgba(46,125,50,.5)',
                 borderDash:[6,3],borderWidth:1.5,
                 label:{{display:true,content:'0.825V',position:'end',
                        color:'#2e7d32',font:{{size:9}},padding:2}}}},
        }}}},
      }},
      scales: {{
        x: {{ticks:{{font:{{size:10}},maxRotation:45}}}},
        y: {{
          title:{{display:true,text:'Tensão (V)',font:{{size:11}}}},
          ticks:{{font:{{size:10}}}},
        }}
      }}
    }}
  }});
}})();

// ── DUT copy ──────────────────────────────────────────────────────────────────
const DUT_HTML = {dut_copy_html_js};
const DUT_TEXT = {dut_copy_text_js};
function copyDUT(btn) {{
  const flash = () => {{
    const orig = btn.textContent;
    btn.textContent = '✓ Copiado!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = orig; btn.classList.remove('copied'); }}, 1800);
  }};
  try {{
    const item = new ClipboardItem({{
      'text/html':  new Blob([DUT_HTML], {{type: 'text/html'}}),
      'text/plain': new Blob([DUT_TEXT], {{type: 'text/plain'}}),
    }});
    navigator.clipboard.write([item]).then(flash).catch(() =>
      navigator.clipboard.writeText(DUT_TEXT).then(flash)
        .catch(() => prompt('Copie o texto abaixo:', DUT_TEXT))
    );
  }} catch(e) {{
    navigator.clipboard.writeText(DUT_TEXT).then(flash)
      .catch(() => prompt('Copie o texto abaixo:', DUT_TEXT));
  }}
}}
</script>
</body>
</html>
"""


# ── Section builders ───────────────────────────────────────────────────────────

def build_bug_section_html(loops):
    cards = build_bug_cards(loops)
    parts = []
    for bug_id, title, details, st, verdict in cards:
        detail_html = '<br>'.join(details)
        parts.append(
            f'<div class="bug-card {st}">'
            f'<div class="bug-id">{bug_id}</div>'
            f'<div class="bug-title">{title}</div>'
            f'<div class="bug-detail">{detail_html}</div>'
            f'<span class="bug-status {st}">{verdict}</span>'
            f'</div>'
        )
    return (
        '<div class="box">'
        '<h2>Investigação de Bugs</h2>'
        '<div class="bug-grid">' + ''.join(parts) + '</div>'
        '</div>'
    )


def build_test_matrix_html(loops):
    all_tests = build_test_matrix(loops)
    if not all_tests:
        return ''

    n = len(loops)
    # Header: "#" + loop numbers
    hdr_cells = '<th class="test-name">Teste</th>'
    for i in range(n):
        hdr_cells += f'<th>L{i+1}</th>'

    rows = []
    for tname in all_tests:
        cells = f'<td class="test-name">{tname}</td>'
        for l in loops:
            v = l['test_results'].get(tname)
            if v == 'ok':
                cells += '<td class="mc-ok">OK</td>'
            elif v == 'error':
                cells += '<td class="mc-error">ERR</td>'
            else:
                cells += '<td class="mc-miss">-</td>'
        rows.append(f'<tr>{cells}</tr>')

    return (
        '<div class="box">'
        '<h2>Resultados por teste</h2>'
        '<div style="overflow-x:auto"><table class="matrix-tbl">'
        f'<thead><tr>{hdr_cells}</tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody>'
        '</table></div></div>'
    )


def build_dpll_table_html(loops):
    # Collect all REF names seen across loops
    all_refs = []
    for ref in DPLL_ORDER:
        if any(ref in l['dpll_refs'] for l in loops):
            all_refs.append(ref)

    if not all_refs:
        return ''

    n = len(loops)

    # Header row — one column per loop
    hdr = '<th class="ref-name">REF</th><th class="freq">Freq</th>'
    for i in range(n):
        hdr += f'<th style="text-align:center;min-width:38px">L{i+1}</th>'

    rows = []
    for ref in all_refs:
        is_ref3 = ref in ('REF_3P', 'REF_3N')
        bg = ' style="background:#fff8e1"' if is_ref3 else ''
        freq = next(
            (l['dpll_refs'][ref]['freq'] for l in loops if ref in l['dpll_refs']),
            '?'
        )
        cells = f'<td class="ref-name"{bg}>{ref}</td><td class="freq">{freq}</td>'
        for l in loops:
            ref_data = l['dpll_refs'].get(ref)
            if ref_data:
                all_ok = all(c.upper() == 'OK' for c in ref_data['cols'])
                fail_flags = [c for c in ref_data['cols'] if c.upper() != 'OK']
                if all_ok:
                    cells += '<td class="dpll-ok" title="5/5 OK">OK</td>'
                else:
                    cells += f'<td class="dpll-err" title="{", ".join(fail_flags)}">ERR</td>'
            else:
                cells += '<td class="mc-miss">-</td>'
        rows.append(f'<tr>{cells}</tr>')

    note = ('<p style="font-size:.76rem;color:#888;margin-top:10px">'
            'REF_3P e REF_3N destacados (BG-2136). '
            'Cada célula sintetiza 5 flags (SCM/CFM/GST/PFM/Lock) — passe o mouse sobre ERR para ver qual falhou.</p>')

    return (
        '<div class="box">'
        '<h2>DPLL — Referências ZL3073x</h2>'
        '<div style="overflow-x:auto"><table class="dpll-tbl">'
        f'<thead><tr>{hdr}</tr></thead>'
        '<tbody>' + ''.join(rows) + '</tbody>'
        '</table></div>'
        + note +
        '</div>'
    )


def build_bcm143_section_html(loops):
    data = [dict(
        loop=i+1,
        dur=l.get('bcm143_duration_s'),
        pass_=l.get('bcm143_pass', 0) or 0,
        fail=l.get('bcm143_fail', 0) or 0,
    ) for i, l in enumerate(loops)]

    has_data = any(d['dur'] is not None or d['pass_'] > 0 for d in data)
    if not has_data:
        return ''

    # Summary line
    durs = [d['dur'] for d in data if d['dur'] is not None]
    total_fail = sum(d['fail'] for d in data)
    dur_note = f'Duração: {min(durs)}–{max(durs)}s' if durs else ''
    fail_note = ('Todas as execuções: Pass=1 Fail=0' if total_fail == 0
                 else f'<span style="color:#c62828;font-weight:700">FALHA em {total_fail} execuções!</span>')

    bcm143_js = json.dumps([
        {'loop': d['loop'], 'dur': d['dur'], 'pass': d['pass_'], 'fail': d['fail']}
        for d in data
    ])

    return (
        '<div class="box">'
        f'<h2>BCM Test 143 — SER Internal <small style="font-size:.76rem;font-weight:400;color:#888">'
        f'(BG-2323) &nbsp; {dur_note} &nbsp; {fail_note}</small></h2>'
        '<div class="ch-wrap3"><canvas id="ch3"></canvas></div>'
        '</div>'
        f'<script>// bcm143 inline\nconst _b143={bcm143_js};</script>'
    )


def build_avs_section_html(loops):
    # Collect all sensor IDs
    all_sensors = sorted({sid for l in loops for sid in l['avs']}, key=lambda x: int(x) if x.isdigit() else 999)
    if not all_sensors:
        return ''

    labels = [f'L{i+1}' for i in range(len(loops))]
    values = [[l['avs'].get(sid) for l in loops] for sid in all_sensors]

    avs_data = {'labels': labels, 'sensors': all_sensors, 'values': values}
    avs_js   = json.dumps(avs_data, ensure_ascii=False)
    avc_js   = json.dumps(AVS_COLORS[:len(all_sensors)], ensure_ascii=False)

    # Check bounds
    all_vals = [v for row in values for v in row if v is not None]
    if all_vals:
        in_range = all(0.808 <= v <= 0.842 for v in all_vals)
        range_note = ('Todos os valores dentro de ±2% de 0.825V'
                      if in_range else
                      '<span style="color:#c62828;font-weight:700">VALORES FORA DE ±2% DETECTADOS!</span>')
    else:
        range_note = ''

    return (
        f'<div class="box">'
        f'<h2>AVS Tensão BCM &nbsp;<small style="font-size:.76rem;font-weight:400;color:#888">'
        f'Alvo 0.825V ±2% (0.808–0.842V) &nbsp; {range_note}</small></h2>'
        f'<div class="ch-wrap4"><canvas id="ch4"></canvas></div>'
        f'</div>'
        f'<script>const _avsD={avs_js};const _avsC={avc_js};</script>'
    )


# ── Report builder ─────────────────────────────────────────────────────────────

def build(loops, filepath, sensor_keys, ref_ok):
    n_pass      = sum(1 for l in loops if loop_status(l) == 'pass')
    n_warn      = sum(1 for l in loops if loop_status(l) == 'warn')
    n_fail      = sum(1 for l in loops if loop_status(l) == 'fail')
    n_boot_fail = sum(1 for l in loops if l.get('boot_status') == 'fail')

    product = next((l.get('product', '') for l in loops if l.get('product')), 'PD??')
    device  = next((l.get('device',  '') for l in loops if l.get('device')),  'unknown')

    sn  = next((l['serial_number'] for l in loops if l.get('serial_number')), None)
    mac = next((l['mac_address']   for l in loops if l.get('mac_address')),   None)

    lua_seen = [(i, l['lua_commit'], l.get('lua_date', ''))
                for i, l in enumerate(loops) if l.get('lua_commit')]
    lua_transitions = set()
    prev_lua = None
    for idx, commit, _ in lua_seen:
        if prev_lua is not None and commit != prev_lua:
            lua_transitions.add(idx)
        prev_lua = commit

    lua_first = lua_seen[0]  if lua_seen else None
    lua_last  = lua_seen[-1] if lua_seen else None

    extra_parts = []
    if sn:
        extra_parts.append(f'SN: {sn}')
    if mac:
        extra_parts.append(f'MAC: {mac}')
    if lua_first:
        date_str = lua_date_short(lua_first[2]) if lua_first[2] else ''
        sha_short_first = lua_first[1][:8]
        sha_short_last  = lua_last[1][:8] if lua_last else sha_short_first
        if lua_transitions:
            lua_label = (f'Lua: {sha_short_first} &rarr; {sha_short_last}'
                         f'<span style="color:#e65100;font-weight:600"> (atualizado)</span>')
        else:
            lua_label = f'Lua: {sha_short_first}' + (f' ({date_str})' if date_str else '')
        extra_parts.append(lua_label)
    extra_info = (' &nbsp;|&nbsp; ' + ' &nbsp;|&nbsp; '.join(extra_parts)) if extra_parts else ''

    def _first(key):
        return next((l[key] for l in loops if l.get(key)), None)

    mb_product = _first('mainboard_product')
    mb_pn      = _first('mainboard_pn')
    psu_dc_mdl = _first('psu_dc_model')
    psu_dc_sn_ = _first('psu_dc_sn')
    psu_ac_mdl = _first('psu_ac_model')
    psu_ac_sn_ = _first('psu_ac_sn')
    max34460   = _first('max34460_crc')
    zl_fw      = _first('zl30733_fw')
    zl_cfg     = _first('zl30733_cfg')
    gnss       = _first('gnss_ver')
    fpga_date  = _first('fpga_date')
    lua_sha1   = _first('lua_commit')
    lua_dt     = _first('lua_date')

    fan_trays_global = {}
    for l in loops:
        for tidx, tdata in l.get('fan_trays', {}).items():
            fan_trays_global.setdefault(tidx, tdata)

    # ── Copy button payload ──────────────────────────────────────────────────
    copy_lines = []
    dt_min = min((l['login_time'] for l in loops if l['login_time']), default=None)
    dt_max = max((l['login_time'] for l in loops if l['login_time']), default=None)
    dr_plain = (f"{dt_min.strftime('%d/%m/%Y %H:%M')} -> {dt_max.strftime('%H:%M')}"
                if dt_min else '-')
    fail_loops = [str(i+1) for i, l in enumerate(loops) if loop_status(l) == 'fail']
    fail_str   = (f" — falhas: Loop {', '.join(fail_loops)}" if fail_loops else " — sem falhas")
    copy_lines.append(f"{product} — {len(loops)} loops — {dr_plain}{fail_str}")
    if mb_product:
        copy_lines.append(f"{mb_product}  PN {mb_pn or '-'}  SN {sn or '-'}  MAC {mac or '-'}")
    if fpga_date:
        copy_lines.append(f"FPGA: {fpga_date}")
    if psu_dc_mdl:
        copy_lines.append(f"PSU DC: {psu_dc_mdl}  S/N {psu_dc_sn_ or '-'}")
    if psu_ac_mdl:
        copy_lines.append(f"PSU AC: {psu_ac_mdl}  S/N {psu_ac_sn_ or '-'}")
    for tidx in sorted(fan_trays_global):
        t = fan_trays_global[tidx]
        copy_lines.append(f"FAN Tray {tidx}: {t['pn']}  SN {t['sn']}  HV {t['hv']}")
    fw_parts_txt = []
    if max34460: fw_parts_txt.append(f"MAX34460: {max34460}")
    if zl_fw:    fw_parts_txt.append(f"ZL30733 FW: {zl_fw}")
    if zl_cfg:   fw_parts_txt.append(f"ZL30733 Cfg: {zl_cfg}")
    if gnss:     fw_parts_txt.append(f"GNSS: {gnss}")
    if fw_parts_txt:
        copy_lines.append("  ".join(fw_parts_txt))
    if lua_sha1:
        date_cp = lua_date_short(lua_dt) if lua_dt else ''
        copy_lines.append(f"Lua: {lua_sha1}" + (f"  ({date_cp})" if date_cp else ""))
    dut_copy_text_js = json.dumps("\n".join(copy_lines), ensure_ascii=False)

    if any([mb_product, psu_dc_mdl, psu_ac_mdl, fan_trays_global,
            max34460, zl_fw, gnss, lua_sha1]):
        rows = []
        if mb_product:
            rows.append(
                f'<tr>'
                f'<td class="dk">Mainboard</td><td class="dv">{mb_product}</td>'
                f'<td class="dk">PN</td><td class="dv">{mb_pn or "-"}</td>'
                f'<td class="dk">SN</td><td class="dv">{sn or "-"}</td>'
                f'<td class="dk">MAC</td><td class="dv">{mac or "-"}</td>'
                f'</tr>'
            )
        if fpga_date:
            rows.append(
                f'<tr><td class="dk">FPGA</td><td class="dv" colspan="7">{fpga_date}</td></tr>'
            )
        if psu_dc_mdl:
            rows.append(
                f'<tr>'
                f'<td class="dk">PSU DC</td><td class="dv">{psu_dc_mdl}</td>'
                f'<td class="dk">S/N</td><td class="dv" colspan="5">{psu_dc_sn_ or "-"}</td>'
                f'</tr>'
            )
        if psu_ac_mdl:
            rows.append(
                f'<tr>'
                f'<td class="dk">PSU AC</td><td class="dv">{psu_ac_mdl}</td>'
                f'<td class="dk">S/N</td><td class="dv" colspan="5">{psu_ac_sn_ or "-"}</td>'
                f'</tr>'
            )
        for tidx in sorted(fan_trays_global):
            t = fan_trays_global[tidx]
            rows.append(
                f'<tr>'
                f'<td class="dk">FAN Tray {tidx}</td><td class="dv">{t["pn"]}</td>'
                f'<td class="dk">SN</td><td class="dv">{t["sn"]}</td>'
                f'<td class="dk">HV</td><td class="dv">{t["hv"]}</td>'
                f'</tr>'
            )
        if max34460:
            rows.append(f'<tr><td class="dk">MAX34460 CRC</td><td class="dv">{max34460}</td></tr>')
        if zl_fw or zl_cfg:
            zl_cells = ''
            if zl_fw:  zl_cells += f'<td class="dk">ZL30733 FW</td><td class="dv">{zl_fw}</td>'
            if zl_cfg: zl_cells += f'<td class="dk">ZL30733 Cfg</td><td class="dv">{zl_cfg}</td>'
            rows.append(f'<tr>{zl_cells}</tr>')
        if gnss:
            rows.append(f'<tr><td class="dk">GNSS</td><td class="dv">{gnss}</td></tr>')
        if lua_sha1:
            date_disp = lua_date_short(lua_dt) if lua_dt else ''
            rows.append(
                f'<tr>'
                f'<td class="dk">Lua commit</td>'
                f'<td class="dv" colspan="5" style="font-size:.78rem">{lua_sha1}</td>'
                f'<td class="dk">data</td><td class="dv">{date_disp}</td>'
                f'</tr>'
            )

        KS = ('style="font-size:.8rem;color:#888;white-space:nowrap;'
              'padding:2px 4px 2px 8px;text-align:right"')
        VS = ('style="font-size:.85rem;font-family:Consolas,monospace;'
              'padding:2px 12px 2px 4px"')
        hr = []
        if mb_product:
            hr.append(
                f'<tr><td {KS}>Mainboard</td><td {VS}>{mb_product}</td>'
                f'<td {KS}>PN</td><td {VS}>{mb_pn or "-"}</td>'
                f'<td {KS}>SN</td><td {VS}>{sn or "-"}</td>'
                f'<td {KS}>MAC</td><td {VS}>{mac or "-"}</td></tr>'
            )
        if fpga_date:
            hr.append(f'<tr><td {KS}>FPGA</td><td {VS} colspan="7">{fpga_date}</td></tr>')
        if psu_dc_mdl:
            hr.append(
                f'<tr><td {KS}>PSU DC</td><td {VS}>{psu_dc_mdl}</td>'
                f'<td {KS}>S/N</td><td {VS} colspan="5">{psu_dc_sn_ or "-"}</td></tr>'
            )
        if psu_ac_mdl:
            hr.append(
                f'<tr><td {KS}>PSU AC</td><td {VS}>{psu_ac_mdl}</td>'
                f'<td {KS}>S/N</td><td {VS} colspan="5">{psu_ac_sn_ or "-"}</td></tr>'
            )
        for tidx in sorted(fan_trays_global):
            t = fan_trays_global[tidx]
            hr.append(
                f'<tr><td {KS}>FAN Tray {tidx}</td><td {VS}>{t["pn"]}</td>'
                f'<td {KS}>SN</td><td {VS}>{t["sn"]}</td>'
                f'<td {KS}>HV</td><td {VS}>{t["hv"]}</td></tr>'
            )
        if max34460:
            hr.append(f'<tr><td {KS}>MAX34460 CRC</td><td {VS}>{max34460}</td></tr>')
        if zl_fw or zl_cfg:
            zl_hr = ''
            if zl_fw:  zl_hr += f'<td {KS}>ZL30733 FW</td><td {VS}>{zl_fw}</td>'
            if zl_cfg: zl_hr += f'<td {KS}>ZL30733 Cfg</td><td {VS}>{zl_cfg}</td>'
            hr.append(f'<tr>{zl_hr}</tr>')
        if gnss:
            hr.append(f'<tr><td {KS}>GNSS</td><td {VS}>{gnss}</td></tr>')
        if lua_sha1:
            date_cp2 = lua_date_short(lua_dt) if lua_dt else ''
            VS2 = ('style="font-size:.8rem;font-family:Consolas,monospace;'
                   'padding:2px 12px 2px 4px"')
            hr.append(
                f'<tr><td {KS}>Lua commit</td>'
                f'<td {VS2} colspan="5">{lua_sha1}</td>'
                f'<td {KS}>data</td><td {VS}>{date_cp2}</td></tr>'
            )
        dut_copy_html_js = json.dumps(
            '<table style="border-collapse:separate;border-spacing:4px 3px">'
            '<tbody>' + ''.join(hr) + '</tbody></table>',
            ensure_ascii=False
        )
        dut_info_html = (
            '<div class="box">'
            '<div class="box-hdr">'
            '<h2>Identificação do DUT</h2>'
            '<button class="btn-copy" onclick="copyDUT(this)">📋 Copiar</button>'
            '</div>'
            '<table class="dut-tbl"><tbody>'
            + ''.join(rows) +
            '</tbody></table></div>'
        )
    else:
        dut_info_html    = ''
        dut_copy_text_js = '""'
        dut_copy_html_js = '""'

    times = [l['login_time'] for l in loops if l['login_time']]
    date_range = (f"{min(times).strftime('%d/%m/%Y %H:%M')} &rarr; "
                  f"{max(times).strftime('%H:%M')}") if times else '-'

    boot_card_cls = 'boot-fail' if n_boot_fail > 0 else 'boot-none' if ref_ok == 0 else 'boot-ok'

    chart = []
    for l in loops:
        chart.append(dict(
            label  = l['login_time'].strftime('%H:%M') if l['login_time'] else '?',
            temps  = {k: l['sensors'].get(k) for k in sensor_keys},
            status = loop_status(l),
            errors = l['errors'],
        ))

    boot_data = [dict(
        loop       = i + 1,
        ok         = l.get('boot_ok', 0),
        status     = l.get('boot_status', 'unknown'),
        unexpected = l.get('boot_unexpected', []),
    ) for i, l in enumerate(loops)]

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

    # Timeline rows
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

        if i in lua_transitions:
            new_commit = l.get('lua_commit', '?')[:8]
            new_date   = lua_date_short(l.get('lua_date', '')) if l.get('lua_date') else ''
            lua_tag = (f'<span class="tag bk-warn">Lua atualizado: {new_commit}'
                       + (f' ({new_date})' if new_date else '') + f'</span>')
        else:
            lua_tag = ''

        # BCM143 duration tag
        dur143 = l.get('bcm143_duration_s')
        fail143 = l.get('bcm143_fail', 0) or 0
        if dur143:
            tag_cls = 'bk-fail' if fail143 > 0 else 'tag'
            b143_tag = f'<span class="tag {tag_cls}">T143: {dur143}s</span>'
        else:
            b143_tag = ''

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
            f'<div class="tags">{tags_html}{boot_tag}{lua_tag}{b143_tag}</div>'
            + (f'<div class="errs">{errs_html}</div>' if errs_html else '') +
            f'</div></div>'
        )

    # Summary table rows
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

        bst    = l.get('boot_status', 'unknown')
        b_ok_v = l.get('boot_ok', 0)
        if bst == 'unknown' or b_ok_v == 0:
            boot_cell = '<td class="boot-unknown">-</td>'
        elif bst == 'fail':
            boot_cell = f'<td class="boot-fail">{b_ok_v}</td>'
        else:
            boot_cell = f'<td class="boot-ok">{b_ok_v}</td>'

        errs = ', '.join(l['errors']) if l['errors'] else '-'

        if i in lua_transitions:
            lua_pill = f'<span class="pill warn">Lua {l.get("lua_commit","?")[:8]}</span> '
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

    # BCM143 JSON for chart
    bcm143_json = json.dumps([{
        'loop': i+1,
        'dur':  l.get('bcm143_duration_s'),
        'pass': l.get('bcm143_pass', 0) or 0,
        'fail': l.get('bcm143_fail', 0) or 0,
    } for i, l in enumerate(loops)])

    # AVS JSON for chart
    all_avs_sensors = sorted({sid for l in loops for sid in l['avs']},
                              key=lambda x: int(x) if x.isdigit() else 999)
    avs_labels = [f'L{i+1}' for i in range(len(loops))]
    avs_values = [[l['avs'].get(sid) for l in loops] for sid in all_avs_sensors]
    avs_json   = json.dumps({'labels': avs_labels, 'sensors': all_avs_sensors, 'values': avs_values},
                             ensure_ascii=False)
    avs_colors_json = json.dumps(AVS_COLORS[:len(all_avs_sensors)], ensure_ascii=False)

    html = HTML.format(
        product           = product,
        filename          = Path(filepath).name,
        date_range        = date_range,
        n                 = len(loops),
        n_pass            = n_pass,
        n_warn            = n_warn,
        n_fail            = n_fail,
        device            = device,
        extra_info        = extra_info,
        boot_card_cls     = boot_card_cls,
        n_boot_fail       = n_boot_fail,
        dut_info_html     = dut_info_html,
        dut_copy_text_js  = dut_copy_text_js,
        dut_copy_html_js  = dut_copy_html_js,
        boot_anomaly_html = boot_anomaly_html,
        tl_rows           = '\n'.join(tl),
        sensor_headers    = sensor_hdrs,
        tb_rows           = '\n'.join(tb),
        chart_json        = json.dumps(chart,      ensure_ascii=False),
        series_json       = json.dumps(sensor_keys, ensure_ascii=False),
        colors_json       = json.dumps(colors_used, ensure_ascii=False),
        boot_json         = json.dumps(boot_data,  ensure_ascii=False),
        ref_ok            = ref_ok,
        bcm143_json       = bcm143_json,
        avs_json          = avs_json,
        avs_colors_json   = avs_colors_json,
        bug_section_html  = build_bug_section_html(loops),
        test_matrix_html  = build_test_matrix_html(loops),
        dpll_table_html   = build_dpll_table_html(loops),
        bcm143_section_html = build_bcm143_section_html(loops),
        avs_section_html  = build_avs_section_html(loops),
    )

    out = Path.cwd() / (Path(filepath).stem + '_report.html')
    out.write_text(html, encoding='utf-8')
    return out


# ── Entry point ────────────────────────────────────────────────────────────────

TERATERM_DIR = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')

def resolve_log_path(arg):
    ext_swap = {'.txt': '.log', '.log': '.txt'}
    p = Path(arg)
    alt = p.with_suffix(ext_swap.get(p.suffix.lower(), ''))
    # Prefer TERATERM_DIR (authoritative source) so local copies are always refreshed
    candidates = [TERATERM_DIR / p.name, p]
    if alt != p:
        candidates += [TERATERM_DIR / alt.name, alt]
    for c in candidates:
        if c.exists():
            return c
    return p


def main():
    if len(sys.argv) < 2:
        print('Uso: analyze_loop_test <arquivo.log>')
        print(f'     (busca automatica em {TERATERM_DIR} se nao encontrar o caminho)')
        sys.exit(1)

    fp = resolve_log_path(sys.argv[1])
    if not fp.exists():
        print(f'Arquivo nao encontrado: {fp}')
        sys.exit(1)

    # Copy log to cwd so report and log end up in the same place
    local = Path.cwd() / fp.name
    if fp.resolve() != local.resolve():
        import shutil
        shutil.copy2(fp, local)
        print(f'Log copiado para: {local}')
        fp = local

    print(f'Analisando: {fp}')

    loops = parse_log(fp)
    print(f'Loops encontrados: {len(loops)}')

    sensor_keys = normalize_sensors(loops)
    print(f'Sensores detectados: {", ".join(sensor_keys) or "(nenhum)"}')

    ref_ok = compute_boot_stats(loops)
    if ref_ok > 0:
        print(f'Boot de referencia: {ref_ok} servicos [ OK ]')

    sn      = next((l['serial_number'] for l in loops if l.get('serial_number')), None)
    mac     = next((l['mac_address']   for l in loops if l.get('mac_address')),   None)
    lua_cmt = next((l['lua_commit']    for l in loops if l.get('lua_commit')),    None)
    lua_date= next((l['lua_date']      for l in loops if l.get('lua_date')),      None)
    if sn:
        print(f'Serial Number: {sn}  MAC: {mac}')
    if lua_cmt:
        print(f'Lua commit: {lua_cmt}  ({lua_date_short(lua_date) if lua_date else "?"})')

    # Summary of new parsed data
    loops_with_tests = [l for l in loops if l['test_results']]
    if loops_with_tests:
        all_tests = build_test_matrix(loops)
        print(f'Testes detectados: {", ".join(all_tests)}')

    loops_with_dpll = [l for l in loops if l['dpll_refs']]
    if loops_with_dpll:
        print(f'DPLL refs detectadas: {", ".join(sorted(loops_with_dpll[0]["dpll_refs"]))}')

    loops_with_143 = [l for l in loops if l.get('bcm143_pass') is not None]
    if loops_with_143:
        durs = [l['bcm143_duration_s'] for l in loops_with_143 if l['bcm143_duration_s']]
        total_fail = sum(l['bcm143_fail'] for l in loops_with_143)
        dur_str = f'{min(durs)}–{max(durs)}s' if durs else '?'
        print(f'BCM Test 143: {len(loops_with_143)} loops | dur {dur_str} | '
              f'fail_total={total_fail}')
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
        d143  = l.get('bcm143_duration_s')
        t143  = f'  T143={d143}s' if d143 else ''
        print(f'  Loop {i+1:2d} | {t0} | {tst_labels[st]} | {boot_str} | {dur}{t143} | {temps}')
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
