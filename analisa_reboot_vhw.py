"""Analisador do log do teste [DM4780][VHW] Reboots (DmOS) — ciclosDMOS.ttl.

Le o log unico do Tera Term (timestamp por linha) e produz um relatorio por
ciclo com deteccao e detalhamento de falhas.

Verificacao principal: os frames enviados pelo testset (MTS-5800) devem
passar por TODAS as portas do DUT e retornar ao testset.
  - portas 100G: contadores In/Out == TX do testset (x1)
  - portas 400G: contadores In/Out == 4x TX do testset (o trafego passa
    4 vezes por elas)
  - perda quantificada em percentual (testset e por porta)

Tambem verifica: boot/login/link up (tempos), alarmes esperados x
inesperados, logs critical/warning, erros/descartes por porta e
temperaturas do show environment (quando presente no log).

Uso:
  python analisa_reboot_vhw.py <arquivo.log> [--csv saida.csv]
                               [--html rel.html] [--nao-abrir]

Sempre gera o relatorio HTML ao lado do log (<log>.html, ou o caminho de
--html) e o abre no navegador padrao ao final (suprimir com --nao-abrir).

Codigo de saida: 0 = todos os ciclos OK, 1 = houve falha, 2 = erro de uso.
"""
import argparse
import csv
import os
import re
import sys
from datetime import datetime, timedelta

# Multiplicador de frames esperado por tipo de interface (default 1)
MULTIPLICADOR = {
    "four-hundred-g-ethernet": 4,
}

# Alarmes aceitos neste teste (nome -> justificativa)
ALARMES_ESPERADOS = {
    "PSU_POWER_INPUT_FAILURE": "PSU sem alimentacao (PSU2 desconectada / corte do estagiario)",
    "TCV_NOT_SUPPORTED_APPSEL": "modulo de loop nao suporta o appsel configurado",
    "TEMP_HIGH": "temperatura alta durante ciclagem termica (conferir o sensor no detalhe)",
    "TEMP_LOW": "temperatura baixa no extremo frio da camara (conferir o sensor no detalhe)",
}

# Porta ligada ao testset: o In dela conta o que o testset enviou e o Out o que
# retornou, entao In > Out nela reflete a perda total do anel, nao causa local.
PORTA_ENTRADA = "hundred-gigabit-ethernet 1/1/1"

RE_LINHA = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.(\d{3})\]\s?(.*)$")
RE_CICLO_INI = re.compile(r"===== CICLO (\d+) de (\d+) - iniciando em")
RE_CICLO_FIM = re.compile(r"===== CICLO (\d+) (CONCLUIDO OK|COM FALHA[^=]*?) em .* total: (\d+) ok / (\d+) executados")
RE_TESTSET = re.compile(r"--- testset: (\S+) ---")
RE_TX = re.compile(r"Transmitted Frames\s*:\s*(\d+)")
RE_RX = re.compile(r"Received Frames\s*:\s*(\d+)")
RE_SIGNAL = re.compile(r"Signal present\s*:\s*(\S+)")
RE_PCS = re.compile(r"PCS sync\s*:\s*(\S+)")
RE_SHOW_LINK = re.compile(r"show interface (\S+ \S+) link")
RE_SHOW_STATS = re.compile(r"show interface (\S+ \S+) statistics")
RE_CONTADOR = re.compile(r"^\s*(In|Out) (Octets|Unicast Pkts|Broadcast Pkts|Multicast Pkts|Discards|Errors|Unknown Protos)\s*:\s*(\d+)")
RE_ALARME = re.compile(
    r"^(\d{4}-\d{2}-\d{2} [\d:]+ \S+)\s+(CRITICAL|MAJOR|MINOR|WARNING)\s+(\S+)\s+(Active|Cleared)\s+(\S+)\s*(.*)$")
RE_FIM_LOG = re.compile(r"\*\* End of log \*\* \((\d+) records?\)")
RE_SENSOR = re.compile(r"^\s*(\S+)\s*\|\s*(.+?)\s*\|\s*([\d.]+)\s*\|.*\|\s*(\w+)\s*$")


def ts(data_str, ms):
    return datetime.strptime(f"{data_str}.{ms}", "%Y-%m-%d %H:%M:%S.%f")


def novo_ciclo(n, inicio, total):
    return {
        "n": n, "inicio": inicio, "total": total,
        "metodo": None,          # 'hw' (estagiario) ou 'sw' (reboot via CLI)
        "t_liga": None, "t_login": None, "t_linkup": None,
        "boot_s": None, "linkup_s": None,
        "tx": None, "rx": None, "signal": None, "pcs": None,
        "portas": {},            # iface -> {contador: valor}
        "link_down": {},         # iface -> qtd de respostas 'link Down'
        "alarmes": [],           # (severidade, fonte, status, nome)
        "criticos": None, "warnings": None,
        "crit_registros": [],    # linhas dos registros de severity critical
        "envs": [],              # snapshots do show environment: [[(nome, temp, status), ...], ...]
                                 # (a macro tira um apos o link up - frio - e outro no fim do ciclo)
        "erros_macro": [],       # linhas '!!!'
        "marcador": None,        # texto do CONCLUIDO/FALHA
        "completo": False,
    }


def analisar(caminho):
    ciclos = []
    c = None
    secao = None            # 'stats' | 'alarm' | 'critical' | 'warning' | 'env'
    iface_stats = None
    iface_link = None

    with open(caminho, encoding="utf-8", errors="replace") as f:
        for linha_crua in f:
            m = RE_LINHA.match(linha_crua.rstrip("\r\n"))
            if not m:
                continue
            quando = ts(m.group(1), m.group(2))
            txt = m.group(3)
            # remove eco de prompt no inicio ("DM4780# ...")
            txt_semprompt = re.sub(r"^DM4\d\d0# ?", "", txt)

            mi = RE_CICLO_INI.search(txt_semprompt)
            if mi:
                if c is not None:
                    ciclos.append(c)
                c = novo_ciclo(int(mi.group(1)), quando, int(mi.group(2)))
                secao = None
                continue
            if c is None:
                continue

            mf = RE_CICLO_FIM.search(txt_semprompt)
            if mf:
                c["marcador"] = mf.group(2).strip()
                c["completo"] = True
                secao = None
                continue

            if "--- Desligando equipamento ---" in txt_semprompt:
                c["metodo"] = "hw"
                continue
            if "--- Ligando equipamento ---" in txt_semprompt:
                c["t_liga"] = quando
                continue
            if "--- Rebootando equipamento ---" in txt_semprompt:
                c["t_liga"] = quando
                c["metodo"] = "sw"
                continue
            if re.search(r"DM4\d\d0 login:", txt):
                if c["t_login"] is None:
                    c["t_login"] = quando
                    if c["t_liga"] is not None:
                        c["boot_s"] = (quando - c["t_liga"]).total_seconds()
                continue
            if "--- Todas as portas com link Up ---" in txt_semprompt:
                c["t_linkup"] = quando
                if c["t_login"] is not None:
                    c["linkup_s"] = (quando - c["t_login"]).total_seconds()
                continue
            if txt_semprompt.startswith("!!!"):
                c["erros_macro"].append(txt_semprompt)
                continue

            # ----- poll de link -----
            ml = RE_SHOW_LINK.search(txt_semprompt)
            if ml:
                iface_link = ml.group(1)
                continue
            if txt_semprompt.strip() == "link Down" and iface_link:
                c["link_down"][iface_link] = c["link_down"].get(iface_link, 0) + 1
                continue

            # ----- testset -----
            if RE_TESTSET.search(txt_semprompt):
                secao = None
                continue
            mt = RE_TX.search(txt_semprompt)
            if mt:
                c["tx"] = int(mt.group(1))
                continue
            mr = RE_RX.search(txt_semprompt)
            if mr:
                c["rx"] = int(mr.group(1))
                continue
            ms_ = RE_SIGNAL.search(txt_semprompt)
            if ms_:
                c["signal"] = ms_.group(1)
                continue
            mp = RE_PCS.search(txt_semprompt)
            if mp:
                c["pcs"] = mp.group(1)
                continue

            # ----- inicio de secoes -----
            mstats = RE_SHOW_STATS.search(txt_semprompt)
            if mstats:
                secao = "stats"
                iface_stats = mstats.group(1)
                c["portas"].setdefault(iface_stats, {})
                continue
            if txt_semprompt.startswith("show alarm"):
                secao = "alarm"
                continue
            if txt_semprompt.startswith("show log severity critical"):
                secao = "critical"
                continue
            if txt_semprompt.startswith("show log severity warning"):
                secao = "warning"
                continue
            if txt_semprompt.startswith("show environment"):
                secao = "env"
                c["envs"].append([])
                continue
            if txt_semprompt.startswith("clear log"):
                secao = None
                continue

            # ----- conteudo das secoes -----
            if secao == "stats" and iface_stats:
                mc = RE_CONTADOR.match(txt_semprompt)
                if mc:
                    chave = f"{mc.group(1)} {mc.group(2)}"
                    c["portas"][iface_stats][chave] = int(mc.group(3))
                continue
            if secao == "alarm":
                ma = RE_ALARME.match(txt_semprompt)
                if ma:
                    c["alarmes"].append((ma.group(2), ma.group(3), ma.group(4), ma.group(5)))
                continue
            if secao in ("critical", "warning"):
                me = RE_FIM_LOG.search(txt_semprompt)
                if me:
                    c["criticos" if secao == "critical" else "warnings"] = int(me.group(1))
                    secao = None
                elif secao == "critical" and re.match(r"^\d{4}-\d{2}-\d{2} \d", txt_semprompt):
                    c["crit_registros"].append(txt_semprompt)
                continue
            if secao == "env":
                msen = RE_SENSOR.match(txt_semprompt)
                if msen and msen.group(1) != "Chassis/Slot/Id" and c["envs"]:
                    c["envs"][-1].append((msen.group(2), float(msen.group(3)), msen.group(4)))
                continue

    if c is not None:
        ciclos.append(c)
    return ciclos


def multiplicador(iface):
    tipo = iface.split(" ")[0]
    return MULTIPLICADOR.get(tipo, 1)


def frames_porta(cont, direcao):
    return sum(cont.get(f"{direcao} {k}", 0)
               for k in ("Unicast Pkts", "Broadcast Pkts", "Multicast Pkts"))


def avaliar(c):
    """Retorna (ok, lista de falhas descritas, perda_testset_pct)."""
    falhas = []
    perda_pct = None

    if not c["completo"]:
        # ciclo em andamento (ou teste interrompido): nao avalia o resto
        return (False, ["ciclo incompleto no log (teste interrompido ou em andamento)"], None)

    for e in c["erros_macro"]:
        falhas.append(f"macro: {e}")

    if c["marcador"] and "CONCLUIDO OK" not in c["marcador"]:
        falhas.append(f"marcador da macro: {c['marcador']}")

    # testset
    if c["tx"] is None or c["rx"] is None:
        falhas.append("sem resultados do testset (tunel SSH caido? ver secao 'testset: results')")
    else:
        if c["tx"] == 0:
            falhas.append("testset transmitiu 0 frames (trafego nao ligou?)")
        else:
            perdidos = c["tx"] - c["rx"]
            perda_pct = 100.0 * perdidos / c["tx"]
            if perdidos != 0:
                flr = perdidos / c["tx"]
                falhas.append(
                    f"perda no testset: TX={c['tx']:,} RX={c['rx']:,} "
                    f"perdidos={perdidos:+,} (FLR={flr:.1e}; alvo IEEE 802.3: "
                    f"BER 1e-12 NRZ / 1e-13 PAM4 pos-FEC)")
        if c["signal"] not in (None, "1"):
            falhas.append(f"testset sem sinal (Signal present={c['signal']})")
        if c["pcs"] not in (None, "1"):
            falhas.append(f"testset sem PCS sync (={c['pcs']})")

    # portas: frames esperados = TX * multiplicador.
    # A ligacao e em serie (testset entra na porta 1, passa por todas e volta),
    # entao uma perda numa porta reduz a contagem de todas as portas a jusante.
    # CAUSA RAIZ = porta assimetrica: Out > In significa que ela transmitiu para
    # o modulo/loop e o pacote nao retornou (perda no modulo); In > Out significa
    # descarte interno no DUT. Portas com In == Out abaixo do esperado sao apenas
    # consequencia da perda a montante.
    if c["tx"]:
        assimetricas = []
        consequencia = []
        for iface, cont in sorted(c["portas"].items()):
            in_f = frames_porta(cont, "In")
            out_f = frames_porta(cont, "Out")
            esperado = c["tx"] * multiplicador(iface)
            if in_f != out_f:
                assimetricas.append((iface, in_f, out_f))
            elif in_f != esperado:
                dif = esperado - in_f
                pct = 100.0 * dif / esperado if esperado else 0.0
                consequencia.append(f"{iface} (faltam {dif:,}; {pct:.6f}%)")
        outras = [a for a in assimetricas if a[0] != PORTA_ENTRADA]
        for iface, in_f, out_f in assimetricas:
            if iface == PORTA_ENTRADA and outras:
                falhas.append(
                    f"{iface} (porta de entrada): In-Out = {in_f - out_f:+,} - "
                    "reflete a perda total do anel (causa esta a jusante)")
            elif out_f > in_f:
                falhas.append(
                    f"CAUSA RAIZ - {iface}: {out_f - in_f:,} pacote(s) perdido(s) no "
                    f"modulo/loop desta porta (Out={out_f:,} > In={in_f:,})")
            else:
                falhas.append(
                    f"CAUSA RAIZ - {iface}: {in_f - out_f:,} pacote(s) descartado(s) "
                    f"internamente pelo DUT (In={in_f:,} > Out={out_f:,})")
        if consequencia:
            falhas.append(
                f"{len(consequencia)} porta(s) com contagem abaixo do esperado, "
                "consistentes (In == Out) - consequencia da perda a montante: "
                + ", ".join(consequencia))
    for iface, cont in sorted(c["portas"].items()):
        for chave in ("In Errors", "Out Errors", "In Discards", "Out Discards"):
            v = cont.get(chave, 0)
            if v:
                falhas.append(f"{iface}: {chave} = {v:,}")

    # alarmes inesperados (apenas Active). Os da lista ALARMES_ESPERADOS nao
    # reprovam - aparecem na secao "alarmes ativos observados" para o
    # projetista avaliar (ex.: PSU_POWER_INPUT_FAILURE = PSU desenergizada).
    for sev, fonte, status, nome in c["alarmes"]:
        if status == "Active" and nome not in ALARMES_ESPERADOS:
            falhas.append(f"alarme inesperado: {sev} {nome} em {fonte}")

    # logs critical: TEMP_LOW/TEMP_HIGH sao esperados na ciclagem termica;
    # qualquer outro registro critical reprova o ciclo
    if c["criticos"]:
        nao_temp = [l for l in c["crit_registros"]
                    if "%TEMP-" not in l and "TEMP_" not in l]
        if nao_temp:
            falhas.append(f"{len(nao_temp)} registro(s) critical nao relacionados a temperatura:")
            falhas.extend(f"    {l}" for l in nao_temp[:5])
        elif not c["crit_registros"]:
            # contagem > 0 mas nenhum registro capturado: reporta por seguranca
            falhas.append(f"{c['criticos']} registro(s) de log severity critical")

    # sensores fora do normal (TCVs em LOW/HIGH sao esperados na ciclagem;
    # CPU, fabric e PSU fora do normal reprovam) - avalia todos os snapshots
    fora = {}
    for snap in c["envs"]:
        for nome, temp, status in snap:
            if status != "NORMAL" and not nome.startswith("TCV"):
                fora.setdefault((nome, status), temp)
    for (nome, status), temp in sorted(fora.items()):
        falhas.append(f"sensor {nome}: {temp} C status={status}")

    return (not falhas, falhas, perda_pct)


def pendencia(ciclos):
    """Ciclos pendentes e estimativa de conclusao pelo tempo medio por ciclo."""
    ultimo = ciclos[-1]
    total = ultimo["total"]
    pendentes = total - ultimo["n"] + (0 if ultimo["completo"] else 1)
    media_s = eta = restante_s = None
    if pendentes > 0 and len(ciclos) >= 2:
        media_s = (ciclos[-1]["inicio"] - ciclos[0]["inicio"]).total_seconds() / (len(ciclos) - 1)
        restante_s = pendentes * media_s
        if not ultimo["completo"]:
            decorrido = (datetime.now() - ultimo["inicio"]).total_seconds()
            restante_s -= min(max(decorrido, 0), media_s)
        eta = datetime.now() + timedelta(seconds=restante_s)
    return {"total": total, "pendentes": pendentes, "media_s": media_s,
            "eta": eta, "restante_s": restante_s}


def relatorio(caminho, ciclos, csv_path=None, html_path=None):
    print(f"Arquivo : {caminho}")
    if not ciclos:
        print("Nenhum ciclo encontrado no log.")
        return 1
    print(f"Periodo : {ciclos[0]['inicio']}  ->  {ciclos[-1]['inicio']}")
    print()

    aval = [(c, *avaliar(c)) for c in ciclos]
    completos = [x for x in aval if x[0]["completo"]]
    ok = [x for x in aval if x[1]]

    cab = (f"{'ciclo':>5} {'inicio':<19} {'boot(s)':>8} {'link(s)':>8} "
           f"{'TX testset':>14} {'FLR':>9} {'downs':>5} {'crit':>4} "
           f"{'cpu C':>6} {'tcv C':>6} {'status':<10}")
    print(cab)
    print("-" * len(cab))
    linhas_csv = []
    for c, c_ok, falhas, perda in aval:
        boot = f"{c['boot_s']:.0f}" if c["boot_s"] is not None else "-"
        linkup = f"{c['linkup_s']:.0f}" if c["linkup_s"] is not None else "-"
        tx = f"{c['tx']:,}" if c["tx"] is not None else "-"
        if perda is None:
            perda_s = "-"
        elif perda == 0:
            perda_s = "0"
        else:
            perda_s = f"{perda / 100:.1e}"
        downs = sum(c["link_down"].values())
        crit = c["criticos"] if c["criticos"] is not None else "-"
        if not c["completo"]:
            status = "INCOMPLETO"
        elif c_ok:
            status = "OK"
        else:
            status = "FALHA"
        sens_fim = c["envs"][-1] if c["envs"] else []
        temp_cpu = next((t for n, t, _ in sens_fim if n == "CPU Core"), None)
        temp_fabric = next((t for n, t, _ in sens_fim if n == "Switch Fabric Core"), None)
        temp_max_tcv = max((t for n, t, _ in sens_fim if n.startswith("TCV")), default=None)
        temp_psu = max((t for n, t, _ in sens_fim if n.startswith("PSU")), default=None)
        temp_min_tcv = min((t for snap in c["envs"] for n, t, _ in snap
                            if n.startswith("TCV")), default=None)
        cpu_s = f"{temp_cpu:.1f}" if temp_cpu is not None else "-"
        tcv_s = f"{temp_max_tcv:.1f}" if temp_max_tcv is not None else "-"
        print(f"{c['n']:>5} {c['inicio']:%Y-%m-%d %H:%M:%S} {boot:>8} {linkup:>8} "
              f"{tx:>14} {perda_s:>9} {downs:>5} {crit!s:>4} "
              f"{cpu_s:>6} {tcv_s:>6} {status:<10}")
        linhas_csv.append({
            "ciclo": c["n"], "inicio": c["inicio"], "boot_s": c["boot_s"],
            "linkup_s": c["linkup_s"], "tx": c["tx"], "rx": c["rx"],
            "perda_pct": perda, "polls_down": downs, "criticos": c["criticos"],
            "warnings": c["warnings"], "temp_cpu": temp_cpu,
            "temp_fabric": temp_fabric, "temp_max_tcv": temp_max_tcv,
            "temp_psu": temp_psu, "temp_min_tcv": temp_min_tcv, "status": status,
            "falhas": "; ".join(falhas),
        })

    ok_completos = [x for x in completos if x[1]]
    print()
    print(f"RESUMO: {len(completos)} ciclos completos, {len(ok_completos)} OK, "
          f"{len(completos) - len(ok_completos)} com falha"
          + (f" (+{len(aval) - len(completos)} incompleto)" if len(aval) != len(completos) else ""))

    # ----- ciclos pendentes e estimativa de conclusao -----
    pend = pendencia(ciclos)
    if pend["pendentes"] <= 0:
        print(f"PENDENTES: nenhum - teste concluido ({pend['total']} ciclos).")
    elif pend["eta"] is not None:
        h, resto = divmod(int(pend["restante_s"]), 3600)
        mnt = resto // 60
        print(f"PENDENTES: {pend['pendentes']} de {pend['total']} ciclos | "
              f"tempo medio por ciclo: {pend['media_s'] / 60:.1f} min")
        print(f"CONCLUSAO ESTIMADA: {pend['eta']:%Y-%m-%d %H:%M} (~{h}h{mnt:02d}min restantes)")
    else:
        print(f"PENDENTES: {pend['pendentes']} de {pend['total']} ciclos "
              f"(sem ciclos suficientes para estimar o tempo medio)")

    # detalhe das falhas (apenas ciclos completos; incompleto ja aparece na tabela)
    com_falha = [(c, falhas) for c, c_ok, falhas, _ in aval if c["completo"] and not c_ok]
    if com_falha:
        print()
        print("=" * 70)
        print("DETALHE DAS FALHAS")
        print("=" * 70)
        for c, falhas in com_falha:
            print(f"\nCiclo {c['n']} ({c['inicio']:%Y-%m-%d %H:%M:%S}):")
            for fdesc in falhas:
                print(f"  - {fdesc}")
            if c["link_down"]:
                piores = sorted(c["link_down"].items(), key=lambda kv: -kv[1])
                print("  Portas que demoraram a dar link (polls em Down):")
                for iface, n in piores:
                    print(f"      {iface}: {n}x")

    # alarmes observados
    vistos = {}
    for c, *_ in aval:
        for sev, fonte, status, nome in c["alarmes"]:
            if status == "Active":
                vistos.setdefault(nome, set()).add(fonte)
    if vistos:
        print()
        print("ALARMES ATIVOS OBSERVADOS:")
        for nome, fontes in sorted(vistos.items()):
            just = ALARMES_ESPERADOS.get(nome)
            tag = f"esperado ({just})" if just else "*** INESPERADO ***"
            print(f"  {nome} [{', '.join(sorted(fontes))}] -> {tag}")

    if csv_path:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(linhas_csv[0].keys()), delimiter=";")
            w.writeheader()
            w.writerows(linhas_csv)
        print(f"\nCSV por ciclo salvo em: {csv_path}")

    if html_path:
        gerar_html(html_path, caminho, linhas_csv, com_falha, vistos, pend,
                   len(completos), len(ok_completos))
        print(f"Relatorio HTML salvo em: {html_path}")

    return 1 if com_falha else 0


# ============================================================================
# Relatorio HTML (autocontido, com graficos SVG; suporta tema claro/escuro)
# ============================================================================

def _svg_linhas(series, unidade, w=880, h=250):
    """Grafico de linhas: series = [(nome, [(ciclo, valor), ...]), ...]."""
    series = [(nome, [(x, y) for x, y in pts if y is not None]) for nome, pts in series]
    series = [s for s in series if s[1]]
    pontos = [(x, y) for _, pts in series for x, y in pts]
    if not pontos:
        return "<p class='muted'>sem dados no log</p>"
    xs = sorted({x for x, _ in pontos})
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(y for _, y in pontos), max(y for _, y in pontos)
    folga = (ymax - ymin) * 0.15 or 1.0
    ymin, ymax = ymin - folga, ymax + folga
    ml, mr, mt, mb = 44, 110, 12, 28

    def fx(x):
        return ml + (x - xmin) / (xmax - xmin or 1) * (w - ml - mr)

    def fy(y):
        return mt + (ymax - y) / (ymax - ymin) * (h - mt - mb)

    p = []
    for i in range(5):
        yv = ymin + (ymax - ymin) * i / 4
        yy = fy(yv)
        p.append(f'<line x1="{ml}" y1="{yy:.1f}" x2="{w - mr}" y2="{yy:.1f}" class="grid"/>')
        p.append(f'<text x="{ml - 6}" y="{yy + 4:.1f}" class="tick" text-anchor="end">{yv:.0f}</text>')
    p.append(f'<line x1="{ml}" y1="{fy(ymin):.1f}" x2="{w - mr}" y2="{fy(ymin):.1f}" class="axis"/>')
    passo = max(1, len(xs) // 10)
    for x in xs[::passo]:
        p.append(f'<text x="{fx(x):.1f}" y="{h - 8}" class="tick" text-anchor="middle">{x}</text>')
    p.append(f'<text x="{ml}" y="{mt}" class="tick">{unidade}</text>')

    for si, (nome, pts) in enumerate(series, 1):
        linha = " ".join(f"{fx(x):.1f},{fy(y):.1f}" for x, y in pts)
        p.append(f'<polyline points="{linha}" class="line s{si}"/>')
        for x, y in pts:
            p.append(f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="3" class="dot s{si}"/>')
            p.append(f'<circle cx="{fx(x):.1f}" cy="{fy(y):.1f}" r="9" fill="transparent">'
                     f'<title>ciclo {x}: {y:g} {unidade} ({nome})</title></circle>')
        ux, uy = pts[-1]
        p.append(f'<text x="{fx(ux) + 8:.1f}" y="{fy(uy) + 4:.1f}" class="lbl">{nome}</text>')

    legenda = "".join(
        f'<span class="leg"><span class="chip s{si}"></span>{nome}</span>'
        for si, (nome, _) in enumerate(series, 1))
    return (f'<div class="legenda">{legenda}</div>'
            f'<svg viewBox="0 0 {w} {h}" role="img">{"".join(p)}</svg>')


_CSS = """
:root { --page:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s4:#008300; --s5:#4a3aa7;
  --good:#006300; --crit:#d03b3b; }
@media (prefers-color-scheme: dark) {
  :root { --page:#0d0d0d; --surface:#1a1a19; --ink:#ffffff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#008300; --s5:#9085e9;
    --good:#0ca30c; --crit:#d03b3b; }
}
* { box-sizing:border-box; }
body { margin:0; padding:24px; background:var(--page); color:var(--ink);
  font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif; }
h1 { font-size:20px; margin:0 0 4px; }
h2 { font-size:15px; margin:28px 0 8px; }
.meta, .muted { color:var(--muted); font-size:12px; }
.tiles { display:flex; flex-wrap:wrap; gap:12px; margin:16px 0; }
.tile { background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:10px 16px; min-width:130px; }
.tile .v { font-size:22px; font-weight:600; }
.tile .k { color:var(--ink2); font-size:12px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:8px;
  padding:12px; overflow-x:auto; }
svg { width:100%; height:auto; display:block; }
.grid { stroke:var(--grid); stroke-width:1; }
.axis { stroke:var(--axis); stroke-width:1; }
.tick { fill:var(--muted); font-size:11px; }
.lbl  { fill:var(--ink2); font-size:11px; }
.line { fill:none; stroke-width:2; }
.line.s1{stroke:var(--s1)} .line.s2{stroke:var(--s2)}
.line.s3{stroke:var(--s3)} .line.s4{stroke:var(--s4)} .line.s5{stroke:var(--s5)}
.dot.s1{fill:var(--s1)} .dot.s2{fill:var(--s2)}
.dot.s3{fill:var(--s3)} .dot.s4{fill:var(--s4)} .dot.s5{fill:var(--s5)}
.legenda { display:flex; gap:16px; margin:0 0 8px; font-size:12px; color:var(--ink2); }
.chip { display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:5px; }
.chip.s1{background:var(--s1)} .chip.s2{background:var(--s2)}
.chip.s3{background:var(--s3)} .chip.s4{background:var(--s4)} .chip.s5{background:var(--s5)}
table { border-collapse:collapse; width:100%; font-variant-numeric:tabular-nums; }
th, td { padding:5px 10px; text-align:right; border-bottom:1px solid var(--grid); }
th { color:var(--ink2); font-weight:600; font-size:12px; }
td:first-child, th:first-child { text-align:left; }
.st-ok { color:var(--good); font-weight:600; }
.st-falha { color:var(--crit); font-weight:600; }
ul { margin:6px 0; }
"""


def gerar_html(html_path, caminho_log, linhas, com_falha, alarmes_vistos, pend,
               n_completos, n_ok):
    temp = _svg_linhas(
        [("CPU", [(r["ciclo"], r["temp_cpu"]) for r in linhas]),
         ("Switch Fabric", [(r["ciclo"], r["temp_fabric"]) for r in linhas]),
         ("TCV max", [(r["ciclo"], r["temp_max_tcv"]) for r in linhas]),
         ("PSU max", [(r["ciclo"], r["temp_psu"]) for r in linhas]),
         ("TCV min (inicio)", [(r["ciclo"], r.get("temp_min_tcv")) for r in linhas])],
        "°C")
    tempos = _svg_linhas(
        [("Boot", [(r["ciclo"], r["boot_s"]) for r in linhas]),
         ("Link up", [(r["ciclo"], r["linkup_s"]) for r in linhas])],
        "s")

    tiles = [
        (f"{n_ok} / {n_completos}", "ciclos OK / completos"),
        (str(len(com_falha)), "ciclos com falha"),
    ]
    perdas = [r["perda_pct"] for r in linhas if r["perda_pct"] is not None]
    if perdas:
        pior = max(perdas)
        pior_s = "0" if pior == 0 else f"{pior / 100:.1e}"
        tiles.append((pior_s, "FLR maxima (testset)"))
    if pend["media_s"]:
        tiles.append((f"{pend['media_s'] / 60:.1f} min", "tempo medio por ciclo"))
    if pend["pendentes"] > 0:
        tiles.append((str(pend["pendentes"]), f"ciclos pendentes de {pend['total']}"))
        if pend["eta"]:
            tiles.append((f"{pend['eta']:%d/%m %H:%M}", "conclusao estimada"))
    else:
        tiles.append(("concluido", f"{pend['total']} ciclos"))
    tiles_html = "".join(f'<div class="tile"><div class="v">{v}</div>'
                         f'<div class="k">{k}</div></div>' for v, k in tiles)

    def fmt(v, casas=0):
        if v is None:
            return "-"
        return f"{v:,.{casas}f}"

    linhas_tab = []
    for r in linhas:
        cls = "st-ok" if r["status"] == "OK" else ("st-falha" if r["status"] == "FALHA" else "muted")
        if r["perda_pct"] is None:
            flr_s = "-"
        elif r["perda_pct"] == 0:
            flr_s = "0"
        else:
            flr_s = f"{r['perda_pct'] / 100:.1e}"
        linhas_tab.append(
            f"<tr><td>{r['ciclo']}</td><td>{r['inicio']:%d/%m %H:%M:%S}</td>"
            f"<td>{fmt(r['boot_s'])}</td><td>{fmt(r['linkup_s'])}</td>"
            f"<td>{fmt(r['tx'])}</td><td>{fmt(r['rx'])}</td>"
            f"<td>{flr_s}</td><td>{fmt(r['temp_cpu'], 1)}</td>"
            f"<td>{fmt(r['temp_max_tcv'], 1)}</td><td>{r['polls_down']}</td>"
            f"<td class='{cls}'>{r['status']}</td></tr>")
    tabela = ("<table><tr><th>ciclo</th><th>inicio</th><th>boot (s)</th>"
              "<th>link (s)</th><th>TX testset</th><th>RX testset</th>"
              "<th>FLR</th><th>CPU C</th><th>TCV max C</th>"
              "<th>polls down</th><th>status</th></tr>"
              + "".join(linhas_tab) + "</table>")

    falhas_html = ""
    if com_falha:
        blocos = []
        for c, falhas in com_falha:
            itens = "".join(f"<li>{f}</li>" for f in falhas)
            blocos.append(f"<h3>Ciclo {c['n']} ({c['inicio']:%d/%m %H:%M:%S})</h3><ul>{itens}</ul>")
        falhas_html = "<h2>Detalhe das falhas</h2><div class='card'>" + "".join(blocos) + "</div>"

    alarmes_html = ""
    if alarmes_vistos:
        itens = []
        for nome, fontes in sorted(alarmes_vistos.items()):
            just = ALARMES_ESPERADOS.get(nome)
            tag = f"esperado — {just}" if just else "<b>INESPERADO</b>"
            itens.append(f"<li><b>{nome}</b> [{', '.join(sorted(fontes))}] — {tag}</li>")
        alarmes_html = "<h2>Alarmes ativos observados</h2><div class='card'><ul>" \
                       + "".join(itens) + "</ul></div>"

    doc = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VHW Reboots - {linhas[0]['inicio']:%d/%m/%Y}</title>
<style>{_CSS}</style></head><body>
<h1>[DM4780][VHW] Reboots (DmOS) — relatorio do teste</h1>
<div class="meta">{caminho_log} &middot; gerado em {datetime.now():%Y-%m-%d %H:%M}</div>
<div class="tiles">{tiles_html}</div>
<h2>Temperaturas por ciclo</h2><div class="card">{temp}</div>
<h2>Tempo de boot e link up por ciclo</h2><div class="card">{tempos}</div>
<h2>Resumo por ciclo</h2><div class="card">{tabela}</div>
{falhas_html}
{alarmes_html}
</body></html>"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(doc)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("log", help="arquivo de log do ciclosDMOS.ttl")
    ap.add_argument("--csv", default=None, help="salvar resumo por ciclo em CSV")
    ap.add_argument("--html", default=None,
                    help="caminho do relatorio HTML (default: <log>.html)")
    ap.add_argument("--nao-abrir", action="store_true",
                    help="nao abrir o HTML no navegador ao final")
    args = ap.parse_args()

    html_path = args.html or (os.path.splitext(args.log)[0] + ".html")

    try:
        ciclos = analisar(args.log)
    except OSError as e:
        sys.exit(f"ERRO abrindo o log: {e}")
    rc = relatorio(args.log, ciclos, args.csv, html_path)
    if not args.nao_abrir and os.path.exists(html_path):
        try:
            os.startfile(html_path)          # Windows: abre no navegador padrao
        except (AttributeError, OSError):
            import webbrowser
            webbrowser.open(f"file:///{os.path.abspath(html_path)}")
    sys.exit(rc)


if __name__ == "__main__":
    main()
