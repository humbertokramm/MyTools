#!/usr/bin/env python3
"""
BCM Test 143 failure comparator.

Usage:
    python bcm143_compare.py <teraterm.log>
    python bcm143_compare.py <teraterm.log> --task
    python bcm143_compare.py <teraterm.log> --task 5
    python bcm143_compare.py <teraterm.log> --en
    python bcm143_compare.py <teraterm.log> --task --en
"""

import re
import sys
import difflib
from pathlib import Path
from datetime import datetime

LOG_DIR = Path(r'C:\Users\humberto.kramm\AppData\Local\teraterm5')

TS_RE          = re.compile(r'^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\]')
TS_STRIP_RE    = re.compile(r'^\[[^\]]{10,30}\]\s*')
BCM_START_RE   = re.compile(r'Running Broadcom Internal Test Run')
BCM_END_RE     = re.compile(r'\binit all\b')
RESULT_RE      = re.compile(r'\[(OK|ERROR)\]\s+Testing_BCM_Test_Run\s*:\s*(OK|ERROR)', re.IGNORECASE)
LOOP_MARKER_RE = re.compile(r'=== LOOP TEST ===\s*(\d+)')


# ── Localisation strings ───────────────────────────────────────────────────────

L = {}   # populated in main() based on --en flag

PT = {
    'title':            'BCM Test 143 — Análise de Falhas',
    'executions':       'Execuções',
    'no_result':        'Sem resultado',
    'exec_table':       'Tabela de execuções',
    'col_loop':         'Loop Lua',
    'col_start':        'Início',
    'col_end':          'Fim',
    'col_dur':          'Duração',
    'col_lines':        'Linhas',
    'col_status':       'Status',
    'ref_window':       'Janela de referência (PASS)',
    'ref_exec':         'execução',
    'see_full':         'Ver conteúdo completo',
    'lines':            'linhas',
    'fail_analysis':    'Análise de falhas',
    'occurrences':      'ocorrências',
    'fail_label':       'FALHA',
    'see_diff':         'Ver diff unificado vs referência PASS',
    'see_content':      'Ver conteúdo completo desta falha',
    'identical':        'Conteúdo idêntico ao PASS de referência.',
    'lines_only_fail':  'Linhas presentes nesta FALHA mas ausentes no PASS de referência',
    'lines_only_ref':   'Linhas presentes no PASS de referência mas ausentes nesta FALHA',
    'identical_warn':   'Conteúdo de linhas idêntico ao PASS — diferença pode estar apenas na ordem ou em valores numéricos.',
    # task fragment
    'task_title':       'BG-2323 — BCM Test 143: Análise de Falhas',
    'log_label':        'Log',
    'period_label':     'Período',
    'ref_label':        'Referência PASS',
    'summary':          'Resumo',
    'total_exec':       'Execuções totais',
    'fail_rate':        'Taxa de falha',
    'typ_dur':          'Duração típica (PASS)',
    'fail_dur':         'Duração nas falhas',
    'occurrences_h':    'Ocorrências',
    'col_datetime':     'Data/Hora início',
    'col_vs':           'vs. PASS típico',
    'col_uniq_fail':    'Linhas únicas (fail)',
    'col_absent_fail':  'Linhas ausentes (fail)',
    'common_all':       'Linhas presentes em TODAS as {n} falhas (ausentes no PASS)',
    'no_common':        'Nenhuma linha presente em 100% das falhas. Ver tabela abaixo para linhas recorrentes.',
    'recurring':        'Linhas recorrentes (presentes em >1 falha)',
    'col_occ':          'Ocorrências',
    'col_line':         'Linha',
    'detail_h':         'Detalhe por falha',
    'fail_word':        'Falha',
    'unique_here':      'Linhas únicas nesta falha',
    'absent_vs':        'Linhas ausentes vs PASS',
    'identical_note':   'Conteúdo idêntico ao PASS — diferença apenas em valores numéricos ou ordem.',
    # console
    'usage':            'Uso: bcm143_compare.py <teraterm.log> [--task] [--en] [ref_exec_number]',
    'not_found':        'Arquivo não encontrado',
    'analysing':        'Analisando',
    'extracting':       'Extraindo janelas BCM Test 143...',
    'total':            'Total',
    'no_pass':          'Nenhuma execução PASS encontrada — impossível comparar.',
    'no_fail':          'Nenhuma falha encontrada.',
    'bad_ref':          'não é PASS — usando 1ª PASS disponível.',
    'ref_info':         'Referência PASS: execução',
    'fail_summary':     'Sumário por falha:',
    'uniq_lines':       'linhas únicas',
    'absent_lines':     'linhas ausentes',
    'yodiz_out':        'Fragmento Yodiz',
    'report_out':       'Relatório',
}

EN = {
    'title':            'BCM Test 143 — Failure Analysis',
    'executions':       'Executions',
    'no_result':        'No result',
    'exec_table':       'Execution table',
    'col_loop':         'Lua Loop',
    'col_start':        'Start',
    'col_end':          'End',
    'col_dur':          'Duration',
    'col_lines':        'Lines',
    'col_status':       'Status',
    'ref_window':       'Reference window (PASS)',
    'ref_exec':         'execution',
    'see_full':         'Show full content',
    'lines':            'lines',
    'fail_analysis':    'Failure analysis',
    'occurrences':      'occurrences',
    'fail_label':       'FAILURE',
    'see_diff':         'Show unified diff vs PASS reference',
    'see_content':      'Show full content of this failure',
    'identical':        'Content identical to reference PASS.',
    'lines_only_fail':  'Lines present in this FAILURE but absent in reference PASS',
    'lines_only_ref':   'Lines present in reference PASS but absent in this FAILURE',
    'identical_warn':   'Line content identical to PASS — difference may be only in order or numeric values.',
    # task fragment
    'task_title':       'BG-2323 — BCM Test 143: Failure Analysis',
    'log_label':        'Log',
    'period_label':     'Period',
    'ref_label':        'PASS reference',
    'summary':          'Summary',
    'total_exec':       'Total executions',
    'fail_rate':        'Failure rate',
    'typ_dur':          'Typical duration (PASS)',
    'fail_dur':         'Duration at failure',
    'occurrences_h':    'Occurrences',
    'col_datetime':     'Start date/time',
    'col_vs':           'vs. typical PASS',
    'col_uniq_fail':    'Unique lines (fail)',
    'col_absent_fail':  'Absent lines (fail)',
    'common_all':       'Lines present in ALL {n} failures (absent in PASS)',
    'no_common':        'No line present in 100% of failures. See recurring table below.',
    'recurring':        'Recurring lines (present in >1 failure)',
    'col_occ':          'Occurrences',
    'col_line':         'Line',
    'detail_h':         'Per-failure detail',
    'fail_word':        'Failure',
    'unique_here':      'Lines unique to this failure',
    'absent_vs':        'Lines absent vs PASS',
    'identical_note':   'Content identical to PASS — difference only in numeric values or order.',
    # console
    'usage':            'Usage: bcm143_compare.py <teraterm.log> [--task] [--en] [ref_exec_number]',
    'not_found':        'File not found',
    'analysing':        'Analysing',
    'extracting':       'Extracting BCM Test 143 windows...',
    'total':            'Total',
    'no_pass':          'No PASS execution found — cannot compare.',
    'no_fail':          'No failures found.',
    'bad_ref':          'is not PASS — using first available PASS.',
    'ref_info':         'PASS reference: execution',
    'fail_summary':     'Failure summary:',
    'uniq_lines':       'unique lines',
    'absent_lines':     'absent lines',
    'yodiz_out':        'Yodiz fragment',
    'report_out':       'Report',
}


def t(key, **kwargs):
    s = L.get(key, key)
    return s.format(**kwargs) if kwargs else s


# ── Parse log into BCM execution windows ──────────────────────────────────────

def parse_ts(line):
    m = TS_RE.match(line)
    return datetime.strptime(m.group(1), '%Y-%m-%d %H:%M:%S.%f') if m else None


def strip_ts(line):
    return TS_STRIP_RE.sub('', line.strip())


def resolve(arg):
    # Prefer LOG_DIR (authoritative source) so local copies are always refreshed
    p = Path(arg)
    q = LOG_DIR / p.name
    if q.exists():
        return q
    if p.exists():
        return p
    return p


def parse_windows(filepath):
    with open(filepath, 'r', encoding='utf-8', errors='replace') as fh:
        all_lines = fh.readlines()

    windows       = []
    current_window = None
    current_loop   = None
    pending        = []

    for i, raw in enumerate(all_lines):
        lineno = i + 1
        line   = raw.rstrip('\n')

        m = LOOP_MARKER_RE.search(line)
        if m:
            current_loop = int(m.group(1))

        if BCM_START_RE.search(line) and current_window is None:
            current_window = {
                'start_line':  lineno,
                'end_line':    None,
                'result_line': None,
                'status':      'unknown',
                'loop_num':    current_loop,
                'start_ts':    parse_ts(line),
                'end_ts':      None,
                'duration_s':  None,
                'raw_lines':   [raw],
            }
            continue

        if current_window is not None:
            current_window['raw_lines'].append(raw)
            if BCM_END_RE.search(line) and current_window['end_line'] is None:
                current_window['end_line'] = lineno
                current_window['end_ts']   = parse_ts(line)
                if current_window['start_ts'] and current_window['end_ts']:
                    current_window['duration_s'] = round(
                        (current_window['end_ts'] - current_window['start_ts']).total_seconds(), 1
                    )
                pending.append(current_window)
                current_window = None
            continue

        m = RESULT_RE.search(line)
        if m and pending:
            w = pending[-1]
            if w['status'] == 'unknown':
                w['status']      = 'pass' if m.group(1).upper() == 'OK' else 'fail'
                w['result_line'] = lineno
                windows.append(pending.pop())

    for w in pending:
        windows.append(w)

    for w in windows:
        w['lines'] = [strip_ts(r) for r in w['raw_lines']]

    return windows


# ── Comparison helpers ─────────────────────────────────────────────────────────

def _esc(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def diff_windows(ref_lines, fail_lines, ref_label='PASS', fail_label='FAIL'):
    diff = list(difflib.unified_diff(
        ref_lines, fail_lines,
        fromfile=ref_label, tofile=fail_label,
        lineterm='', n=3
    ))
    if not diff:
        return f'<p style="color:#2e7d32;font-size:.82rem">{t("identical")}</p>'

    parts = ['<pre style="font-size:.72rem;line-height:1.5;white-space:pre-wrap;word-break:break-all">']
    for d in diff:
        if d.startswith('+++') or d.startswith('---') or d.startswith('@@'):
            parts.append(f'<span style="color:#666">{_esc(d)}</span>\n')
        elif d.startswith('+'):
            parts.append(f'<span style="background:#e8f5e9;color:#1b5e20">{_esc(d)}</span>\n')
        elif d.startswith('-'):
            parts.append(f'<span style="background:#ffebee;color:#b71c1c">{_esc(d)}</span>\n')
        else:
            parts.append(f'<span style="color:#aaa">{_esc(d)}</span>\n')
    parts.append('</pre>')
    return ''.join(parts)


def lines_to_pre(lines, status):
    color   = '#b71c1c' if status == 'fail' else '#1b5e20'
    bg      = '#fff8f8' if status == 'fail' else '#f8fff8'
    content = _esc('\n'.join(lines))
    return (f'<pre style="font-size:.72rem;line-height:1.5;white-space:pre-wrap;'
            f'word-break:break-all;background:{bg};color:{color};padding:10px;'
            f'border-radius:4px;max-height:500px;overflow-y:auto">{content}</pre>')


def extract_anomalies(ref_lines, fail_lines):
    ref_set  = set(l.strip() for l in ref_lines  if l.strip())
    fail_set = set(l.strip() for l in fail_lines if l.strip())
    return ([l for l in fail_set - ref_set if l],
            [l for l in ref_set  - fail_set if l])


# ── Full HTML report ───────────────────────────────────────────────────────────

HTML_HEADER = """\
<!DOCTYPE html>
<html lang="{lang}">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',Arial,sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:14px}}
.wrap{{max-width:1280px;margin:0 auto;padding:24px}}
h1{{font-size:1.3rem;margin-bottom:4px}}
.sub{{font-size:.82rem;color:#666;margin-bottom:20px}}
.box{{background:#fff;border-radius:8px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.09);margin-bottom:20px}}
.box h2{{font-size:.95rem;margin-bottom:14px;color:#333;border-bottom:1px solid #eee;padding-bottom:8px}}
.box h3{{font-size:.88rem;margin-bottom:10px;color:#555}}
table{{width:100%;border-collapse:collapse;font-size:.8rem}}
th{{text-align:left;padding:8px 10px;background:#f5f5f5;border-bottom:2px solid #ddd;white-space:nowrap}}
td{{padding:7px 10px;border-bottom:1px solid #eee;vertical-align:top}}
tr:hover td{{background:#fafafa}}
.pass{{color:#2e7d32;font-weight:700}}
.fail{{color:#c62828;font-weight:700}}
.unknown{{color:#9e9e9e}}
.pill{{display:inline-block;padding:1px 8px;border-radius:10px;font-size:.71rem;font-weight:600}}
.pill.pass{{background:#e8f5e9;color:#2e7d32}}
.pill.fail{{background:#ffebee;color:#c62828}}
.pill.unknown{{background:#f5f5f5;color:#9e9e9e}}
.anomaly-box{{background:#fff3e0;border-left:3px solid #e65100;padding:10px 14px;
             border-radius:0 4px 4px 0;margin-bottom:12px;font-size:.78rem}}
.anomaly-box h4{{color:#e65100;font-size:.8rem;margin-bottom:6px}}
.anomaly-box li{{margin-left:16px;margin-bottom:2px;font-family:monospace;font-size:.75rem}}
.anomaly-ok{{background:#e8f5e9;border-left:3px solid #2e7d32}}
.anomaly-ok h4{{color:#2e7d32}}
.cols2{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
details summary{{cursor:pointer;font-size:.82rem;color:#1565c0;padding:4px 0;user-select:none}}
details[open] summary{{margin-bottom:8px}}
.badge-fail{{background:#ffebee;color:#c62828;border:1px solid #ffcdd2;
            border-radius:4px;padding:2px 8px;font-size:.72rem;font-weight:700;display:inline}}
</style>
</head>
<body>
<div class="wrap">
"""

HTML_FOOTER = """
</div>
</body>
</html>
"""


def build_report(windows, filepath, ref_window, lang='pt'):
    n_total = len(windows)
    n_pass  = sum(1 for w in windows if w['status'] == 'pass')
    n_fail  = sum(1 for w in windows if w['status'] == 'fail')
    n_unk   = sum(1 for w in windows if w['status'] == 'unknown')

    fail_windows = [w for w in windows if w['status'] == 'fail']

    title = t('title')
    parts = [HTML_HEADER.format(lang='en' if lang == 'en' else 'pt-BR', title=title)]
    parts.append(f'<h1>{title}</h1>')
    parts.append(f'<div class="sub">{Path(filepath).name}</div>')

    parts.append(
        '<div style="display:flex;gap:12px;margin-bottom:20px;flex-wrap:wrap">'
        f'<div class="box" style="flex:1;min-width:100px"><div style="font-size:1.8rem;font-weight:700">{n_total}</div>'
        f'<div style="font-size:.73rem;color:#888">{t("executions")}</div></div>'
        f'<div class="box" style="flex:1;min-width:100px"><div style="font-size:1.8rem;font-weight:700;color:#2e7d32">{n_pass}</div>'
        f'<div style="font-size:.73rem;color:#888">PASS</div></div>'
        f'<div class="box" style="flex:1;min-width:100px"><div style="font-size:1.8rem;font-weight:700;color:#c62828">{n_fail}</div>'
        f'<div style="font-size:.73rem;color:#888">FAIL</div></div>'
        f'<div class="box" style="flex:1;min-width:100px"><div style="font-size:1.8rem;font-weight:700;color:#9e9e9e">{n_unk}</div>'
        f'<div style="font-size:.73rem;color:#888">{t("no_result")}</div></div>'
        '</div>'
    )

    parts.append(f'<div class="box"><h2>{t("exec_table")}</h2>'
                 '<div style="overflow-x:auto"><table>'
                 f'<thead><tr><th>#</th><th>{t("col_loop")}</th><th>{t("col_start")}</th><th>{t("col_end")}</th>'
                 f'<th>{t("col_dur")}</th><th>{t("col_lines")}</th><th>{t("col_status")}</th></tr></thead><tbody>')
    for i, w in enumerate(windows):
        st     = w['status']
        t0     = w['start_ts'].strftime('%d/%m %H:%M:%S') if w['start_ts'] else '-'
        t1     = w['end_ts'].strftime('%H:%M:%S')         if w['end_ts']   else '-'
        dur    = f'{w["duration_s"]:.0f}s'                if w['duration_s'] else '-'
        loop   = str(w['loop_num']) if w['loop_num'] is not None else '-'
        lrange = f'{w["start_line"]}–{w["end_line"] or "?"}'
        ref_marker = ' ★' if w is ref_window else ''
        status_label = 'PASS' if st == 'pass' else 'FAIL' if st == 'fail' else '?'
        parts.append(
            f'<tr>'
            f'<td>{i+1}{ref_marker}</td>'
            f'<td>{loop}</td>'
            f'<td>{t0}</td><td>{t1}</td><td>{dur}</td>'
            f'<td style="font-family:monospace;font-size:.73rem">{lrange}</td>'
            f'<td><span class="pill {st}">{status_label}</span></td>'
            f'</tr>'
        )
    parts.append('</tbody></table></div></div>')

    ref_t = ref_window['start_ts'].strftime('%H:%M:%S') if ref_window['start_ts'] else '?'
    ref_n = windows.index(ref_window) + 1
    parts.append(
        f'<div class="box"><h2>{t("ref_window")} — {t("ref_exec")} #{ref_n} @ {ref_t}</h2>'
        f'<details><summary>{t("see_full")} ({len(ref_window["lines"])} {t("lines")})</summary>'
        + lines_to_pre(ref_window['lines'], 'pass') +
        '</details></div>'
    )

    parts.append(f'<div class="box"><h2>{t("fail_analysis")} ({n_fail} {t("occurrences")})</h2>')

    for fi, fw in enumerate(fail_windows):
        exec_idx = windows.index(fw) + 1
        t0  = fw['start_ts'].strftime('%d/%m/%Y %H:%M:%S') if fw['start_ts'] else '-'
        dur = f'{fw["duration_s"]:.0f}s' if fw['duration_s'] else '-'
        loop = fw['loop_num'] if fw['loop_num'] is not None else '-'

        only_fail, only_ref = extract_anomalies(ref_window['lines'], fw['lines'])

        parts.append(
            f'<details open>'
            f'<summary><span class="badge-fail">{t("fail_label")} #{fi+1}</span>'
            f' &nbsp; {t("ref_exec").capitalize()} #{exec_idx} &nbsp; {t("col_loop")} {loop} &nbsp; {t0} &nbsp; {dur}</summary>'
        )

        if only_fail:
            items = ''.join(f'<li>{_esc(l)}</li>' for l in sorted(only_fail)[:30])
            parts.append(
                '<div class="anomaly-box">'
                f'<h4>{t("lines_only_fail")} ({len(only_fail)}):</h4>'
                f'<ul>{items}</ul></div>'
            )
        if only_ref:
            items = ''.join(f'<li>{_esc(l)}</li>' for l in sorted(only_ref)[:30])
            parts.append(
                '<div class="anomaly-box anomaly-ok">'
                f'<h4>{t("lines_only_ref")} ({len(only_ref)}):</h4>'
                f'<ul>{items}</ul></div>'
            )
        if not only_fail and not only_ref:
            parts.append(
                f'<p style="color:#e65100;font-size:.82rem;margin-bottom:10px">{t("identical_warn")}</p>'
            )

        parts.append(f'<details><summary>{t("see_diff")}</summary>')
        parts.append(diff_windows(ref_window['lines'], fw['lines'],
                                  ref_label=f'PASS ref ({t("ref_exec")} #{windows.index(ref_window)+1})',
                                  fail_label=f'{t("fail_label")} #{fi+1} ({t("ref_exec")} #{exec_idx})'))
        parts.append('</details>')

        parts.append(f'<details><summary>{t("see_content")} ({len(fw["lines"])} {t("lines")})</summary>')
        parts.append(lines_to_pre(fw['lines'], 'fail'))
        parts.append('</details></details><hr style="border:none;border-top:1px solid #eee;margin:16px 0">')

    parts.append('</div>')
    parts.append(HTML_FOOTER)

    suffix = '_bcm143_compare_en.html' if lang == 'en' else '_bcm143_compare.html'
    out = Path(filepath).with_name(Path(filepath).stem + suffix)
    out.write_text(''.join(parts), encoding='utf-8')
    return out


# ── Yodiz / task HTML fragment ────────────────────────────────────────────────

_S = {
    'h2':   'font-size:1.05rem;font-weight:700;margin:18px 0 6px 0;color:#1a1a2e',
    'h3':   'font-size:.92rem;font-weight:700;margin:14px 0 5px 0;color:#333',
    'p':    'font-size:.85rem;margin:4px 0 8px 0;line-height:1.5',
    'th':   'text-align:left;padding:5px 10px;background:#f0f0f0;border:1px solid #ddd;font-size:.82rem;white-space:nowrap',
    'td':   'padding:5px 10px;border:1px solid #ddd;font-size:.82rem;vertical-align:top',
    'td_c': 'padding:5px 10px;border:1px solid #ddd;font-size:.82rem;text-align:center',
    'pre':  ('font-family:Consolas,monospace;font-size:.75rem;background:#f8f8f8;'
             'padding:8px 12px;border-left:3px solid #ccc;margin:6px 0;'
             'white-space:pre-wrap;word-break:break-all'),
    'pre_f':('font-family:Consolas,monospace;font-size:.75rem;background:#fff8f8;'
             'padding:8px 12px;border-left:3px solid #c62828;margin:6px 0;'
             'white-space:pre-wrap;word-break:break-all'),
    'pass': 'color:#2e7d32;font-weight:700',
    'fail': 'color:#c62828;font-weight:700',
    'note': 'font-size:.78rem;color:#e65100;background:#fff3e0;padding:6px 10px;border-radius:4px;margin:6px 0',
    'hr':   'border:none;border-top:1px solid #ddd;margin:14px 0',
    'tbl':  'width:100%;border-collapse:collapse;margin:8px 0',
}

def _th(s):  return f'<th style="{_S["th"]}">{s}</th>'
def _td(s):  return f'<td style="{_S["td"]}">{_esc(str(s))}</td>'
def _tdc(s): return f'<td style="{_S["td_c"]}">{_esc(str(s))}</td>'
def _tdf(s, ok):
    c  = '#2e7d32' if ok else '#c62828'
    bg = '#e8f5e9' if ok else '#ffebee'
    return f'<td style="{_S["td_c"]};color:{c};background:{bg};font-weight:700">{_esc(str(s))}</td>'


def build_task_report(windows, filepath, ref_window, fail_windows, lang='pt'):
    n_total = len(windows)
    n_pass  = sum(1 for w in windows if w['status'] == 'pass')
    n_fail  = len(fail_windows)

    pass_durs = [w['duration_s'] for w in windows if w['status'] == 'pass' and w['duration_s']]
    fail_durs = [w['duration_s'] for w in fail_windows if w['duration_s']]
    avg_pass  = round(sum(pass_durs) / len(pass_durs), 1) if pass_durs else None
    min_fail  = min(fail_durs) if fail_durs else None
    max_fail  = max(fail_durs) if fail_durs else None

    logname  = Path(filepath).name
    ref_exec = windows.index(ref_window) + 1

    p = []

    p.append(f'<h2 style="{_S["h2"]}">{t("task_title")}</h2>')
    p.append(f'<p style="{_S["p"]}"><b>{t("log_label")}:</b> {_esc(logname)} &nbsp;|&nbsp; '
             f'<b>{t("period_label")}:</b> {_fmt_period(windows)} &nbsp;|&nbsp; '
             f'<b>{t("ref_label")}:</b> #{ref_exec} ({ref_window["duration_s"]:.0f}s)</p>')

    p.append(f'<h3 style="{_S["h3"]}">{t("summary")}</h3>')
    p.append(f'<table style="{_S["tbl"]}">'
             f'<tr>{_th(t("total_exec"))}{_th("PASS")}{_th("FAIL")}'
             f'{_th(t("fail_rate"))}{_th(t("typ_dur"))}{_th(t("fail_dur"))}</tr>'
             f'<tr>{_td(n_total)}'
             f'{_tdf(n_pass, True)}'
             f'{_tdf(n_fail, n_fail == 0)}'
             f'{_tdc(f"{n_fail/n_total*100:.2f}%")}'
             f'{_tdc(f"{avg_pass:.0f}s" if avg_pass else "-")}'
             f'{_tdc(f"{min_fail:.0f}–{max_fail:.0f}s" if min_fail else "-")}'
             f'</tr></table>')

    p.append(f'<h3 style="{_S["h3"]}">{t("occurrences_h")} ({n_fail})</h3>')
    p.append(f'<table style="{_S["tbl"]}">'
             f'<tr>{_th("#")}{_th(t("col_loop"))}{_th(t("col_datetime"))}'
             f'{_th(t("col_dur"))}{_th(t("col_vs"))}'
             f'{_th(t("col_uniq_fail"))}{_th(t("col_absent_fail"))}</tr>')

    all_anomalies = []
    for fi, fw in enumerate(fail_windows):
        only_fail, only_ref = extract_anomalies(ref_window['lines'], fw['lines'])
        all_anomalies.append((only_fail, only_ref))
        t0  = fw['start_ts'].strftime('%d/%m/%Y %H:%M:%S') if fw['start_ts'] else '-'
        dur = f'{fw["duration_s"]:.0f}s' if fw['duration_s'] else '-'
        delta = ''
        if fw['duration_s'] and avg_pass:
            delta = f'{fw["duration_s"] - avg_pass:+.0f}s'
        p.append(
            f'<tr>{_tdc(fi+1)}{_td(fw["loop_num"] or "-")}{_td(t0)}'
            f'{_tdc(dur)}{_tdc(delta)}'
            f'{_tdc(len(only_fail))}{_tdc(len(only_ref))}</tr>'
        )
    p.append('</table>')

    fail_line_counts = {}
    for only_fail, _ in all_anomalies:
        for l in only_fail:
            fail_line_counts[l] = fail_line_counts.get(l, 0) + 1

    common_to_all = [(l, c) for l, c in fail_line_counts.items() if c == n_fail]
    common_most   = sorted(
        [(l, c) for l, c in fail_line_counts.items() if 1 < c < n_fail],
        key=lambda x: -x[1]
    )

    p.append(f'<h3 style="{_S["h3"]}">{t("common_all", n=n_fail)}</h3>')
    if common_to_all:
        items = '\n'.join(l for l, _ in sorted(common_to_all))
        p.append(f'<pre style="{_S["pre_f"]}">{_esc(items)}</pre>')
    else:
        p.append(f'<p style="{_S["note"]}">{t("no_common")}</p>')

    if common_most:
        p.append(f'<h3 style="{_S["h3"]}">{t("recurring")}</h3>')
        p.append(f'<table style="{_S["tbl"]}">'
                 f'<tr>{_th(t("col_occ"))}{_th(t("col_line"))}</tr>')
        for l, c in common_most[:20]:
            p.append(f'<tr>{_tdc(f"{c}/{n_fail}")}{_td(l)}</tr>')
        p.append('</table>')

    p.append(f'<h3 style="{_S["h3"]}">{t("detail_h")}</h3>')
    for fi, (fw, (only_fail, only_ref)) in enumerate(zip(fail_windows, all_anomalies)):
        t0  = fw['start_ts'].strftime('%d/%m/%Y %H:%M:%S') if fw['start_ts'] else '-'
        dur = f'{fw["duration_s"]:.0f}s' if fw['duration_s'] else '-'
        p.append(f'<p style="{_S["p"]}"><b>{t("fail_word")} #{fi+1}</b> — {t("col_loop")} {fw["loop_num"] or "?"} '
                 f'| {t0} | {dur}</p>')

        if only_fail:
            items = '\n'.join(sorted(only_fail)[:25])
            p.append(f'<p style="{_S["p"]};margin-bottom:2px"><i>{t("unique_here")} ({len(only_fail)}):</i></p>')
            p.append(f'<pre style="{_S["pre_f"]}">{_esc(items)}</pre>')
        if only_ref:
            items = '\n'.join(sorted(only_ref)[:25])
            p.append(f'<p style="{_S["p"]};margin-bottom:2px"><i>{t("absent_vs")} ({len(only_ref)}):</i></p>')
            p.append(f'<pre style="{_S["pre"]}">{_esc(items)}</pre>')
        if not only_fail and not only_ref:
            p.append(f'<p style="{_S["note"]}">{t("identical_note")}</p>')
        p.append(f'<hr style="{_S["hr"]}">')

    suffix = '_bcm143_task_en.html' if lang == 'en' else '_bcm143_task.html'
    out = Path(filepath).with_name(Path(filepath).stem + suffix)
    out.write_text(''.join(p), encoding='utf-8')
    return out


def _fmt_period(windows):
    ts_list = [w['start_ts'] for w in windows if w['start_ts']]
    if not ts_list:
        return '-'
    t0 = min(ts_list).strftime('%d/%m/%Y %H:%M')
    t1 = max(ts_list).strftime('%d/%m/%Y %H:%M')
    return f'{t0} → {t1}'


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    global L

    args = sys.argv[1:]

    if not args:
        print('Usage: bcm143_compare.py <teraterm.log> [--task] [--en] [ref_exec_number]')
        sys.exit(1)

    task_mode = '--task' in args
    lang      = 'en' if '--en' in args else 'pt'
    args = [a for a in args if a not in ('--task', '--en')]

    L = EN if lang == 'en' else PT

    fp = resolve(args[0])
    if not fp.exists():
        print(f'{t("not_found")}: {fp}')
        sys.exit(1)

    # Copy log to cwd so report and log end up in the same place
    local = Path.cwd() / fp.name
    if fp.resolve() != local.resolve():
        import shutil
        shutil.copy2(fp, local)
        print(f'Log copiado para: {local}' if lang == 'pt' else f'Log copied to: {local}')
        fp = local

    ref_idx_arg = int(args[1]) if len(args) > 1 else None

    print(f'{t("analysing")}: {fp}')
    print(t('extracting'))

    windows = parse_windows(fp)

    n_pass = sum(1 for w in windows if w['status'] == 'pass')
    n_fail = sum(1 for w in windows if w['status'] == 'fail')
    n_unk  = sum(1 for w in windows if w['status'] == 'unknown')
    print(f'{t("total")}: {len(windows)} | {n_pass} PASS | {n_fail} FAIL | {n_unk} {t("no_result").lower()}')

    pass_windows = [w for w in windows if w['status'] == 'pass']
    fail_windows = [w for w in windows if w['status'] == 'fail']

    if not pass_windows:
        print(t('no_pass'))
        sys.exit(1)
    if not fail_windows:
        print(t('no_fail'))
        sys.exit(0)

    if ref_idx_arg:
        idx = ref_idx_arg - 1
        if 0 <= idx < len(windows) and windows[idx]['status'] == 'pass':
            ref_window = windows[idx]
        else:
            print(f'{t("ref_exec").capitalize()} {ref_idx_arg} {t("bad_ref")}')
            ref_window = pass_windows[0]
    else:
        durs = sorted([w for w in pass_windows if w['duration_s']], key=lambda w: w['duration_s'])
        ref_window = durs[len(durs) // 2] if durs else pass_windows[0]

    ref_exec = windows.index(ref_window) + 1
    ref_ts   = ref_window['start_ts'].strftime('%H:%M:%S') if ref_window['start_ts'] else '?'
    ref_dur  = f' ({ref_window["duration_s"]:.0f}s)' if ref_window['duration_s'] else ''
    print(f'{t("ref_info")} #{ref_exec} @ {ref_ts}{ref_dur}')

    print()
    print(t('fail_summary'))
    for fi, fw in enumerate(fail_windows):
        exec_idx = windows.index(fw) + 1
        t0 = fw['start_ts'].strftime('%d/%m %H:%M:%S') if fw['start_ts'] else '-'
        dur = f'{fw["duration_s"]:.0f}s' if fw['duration_s'] else '-'
        only_fail, only_ref = extract_anomalies(ref_window['lines'], fw['lines'])
        print(f'  FAIL #{fi+1:2d} | #{exec_idx:4d} | {t("col_loop")} {fw["loop_num"] or "-":>5} | {t0} | {dur}'
              f' | +{len(only_fail)} {t("uniq_lines")}  -{len(only_ref)} {t("absent_lines")}')

    import os

    if task_mode:
        out = build_task_report(windows, fp, ref_window, fail_windows, lang=lang)
        print(f'\n{t("yodiz_out")}: {out}')
        os.startfile(out)
    else:
        out = build_report(windows, fp, ref_window, lang=lang)
        print(f'\n{t("report_out")}: {out}')
        os.startfile(out)


if __name__ == '__main__':
    main()
