#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Converte um profile .txt da camara climatica CSZ Z-32 Plus (Synergy Controller)
para o JSON de setpoint aceito pelo thermal_plot2.py.

Formato de cada linha real de step (colunas separadas por virgula):
  0: horas do STEP TIME
  1: minutos do STEP TIME * 256
  2: bitmask dos eventos do step (CHAMBER=1, HUMIDITY=2, ----=4, DRY AIR PURGE=8, ...)
  3-7: nao identificadas (humidity/product SP e reservados?)
  8: Jump Step (proximo step; para o step final, target do loop)
  9: Jump Count (repeticoes do loop; 0 = sem loop)
  10: Temperature SP (C)
  11-14: nao identificadas

A 1a linha do arquivo e cabecalho (nao e step). Steps reais tem bitmask (col 2) != 0;
o arquivo tem slots nao usados no final (padding) com bitmask == 0 - a leitura para
ao encontrar o primeiro desses.

Uso:
    python camara_profile_to_json.py -i perfil.txt --start "22/07/2026 18:39" -o sp.json
"""
import argparse
import json
import os
from datetime import datetime, timedelta

SP_FMT = "%d/%m/%Y %H:%M"


def parse_steps(path):
    with open(path, encoding="utf-8") as f:
        lines = [l.strip() for l in f if l.strip()]
    rows = [line.split(",") for line in lines[1:]]  # pula o cabecalho
    steps = []
    for r in rows:
        if int(r[2]) == 0:
            break  # inicio da area de padding (steps nao usados)
        hrs = int(r[0])
        minutes = int(r[1]) / 256.0
        duration_min = hrs * 60 + minutes
        sp = float(r[10])
        jump_step = int(r[8])
        jump_count = int(r[9])
        steps.append({"duration_min": duration_min, "sp": sp,
                       "jump_step": jump_step, "jump_count": jump_count})
    return steps


def steps_to_points(steps, start_dt):
    """Converte a lista de steps num setpoint {timestamp: valor}.

    O cursor "oficial" avanca SOMENTE pela duracao real dos steps (duracao>0):
    isso fixa os horarios de plato/rampa sem nenhum acumulo/drift. Um step com
    duracao 0 e uma transicao rapida (rate-limited) que nao consome tempo no
    cursor oficial; para representa-la como quase-vertical, reafirmamos o valor
    ANTERIOR 1 minuto antes do instante atual e ja registramos o valor NOVO
    exatamente no instante atual (mesma convencao usada manualmente antes:
    "19:08 valor antigo, 19:09 valor novo"). Steps com duracao>0 e valor
    diferente do anterior viram RAMPA (reta entre o ponto anterior e o novo,
    desenhada pelo proprio grafico); com o mesmo valor, apenas estendem o plato."""
    cursor = start_dt
    points = {}
    prev_sp = None
    for i, step in enumerate(steps):
        if step["duration_min"] > 0:
            cursor = cursor + timedelta(minutes=step["duration_min"])
        elif i > 0:
            points[(cursor - timedelta(minutes=1)).strftime(SP_FMT)] = prev_sp
        points[cursor.strftime(SP_FMT)] = step["sp"]
        prev_sp = step["sp"]
    return points


def main():
    ap = argparse.ArgumentParser(description="Profile .txt da camara -> JSON de setpoint")
    ap.add_argument("-i", "--input", required=True, help="Arquivo .txt do profile")
    ap.add_argument("--start", required=True, help="Data/hora de inicio 'dd/mm/aaaa HH:MM'")
    ap.add_argument("-o", "--output", required=True, help="Arquivo JSON de saida")
    ap.add_argument("--loops", type=int, default=1,
                    help="Quantas vezes expandir o loop final (Jump Count). Default: 1 (sem repetir)")
    args = ap.parse_args()

    steps = parse_steps(args.input)
    start_dt = datetime.strptime(args.start, SP_FMT)

    last = steps[-1]
    body = steps[:-1] if last["jump_count"] > 0 else steps
    all_steps = body * max(1, args.loops)
    if last["jump_count"] == 0:
        pass  # last ja incluido em 'steps' sem loop

    points = steps_to_points(all_steps if last["jump_count"] > 0 else steps, start_dt)

    out_abs = os.path.abspath(args.output)
    out_dir = os.path.dirname(out_abs)
    if out_dir and not os.path.isdir(out_dir):
        print("AVISO: a pasta de destino nao existia e foi criada:", out_dir)
        print("       (confira se e esse mesmo o lugar; caminhos relativos dependem de onde")
        print("        voce rodou o comando -", os.getcwd(), ")")
        os.makedirs(out_dir, exist_ok=True)

    with open(out_abs, "w", encoding="utf-8") as f:
        json.dump(points, f, ensure_ascii=False, indent=2)
    print("Steps lidos:", len(steps), "| loop final: jump_step={} jump_count={}".format(
        last["jump_step"], last["jump_count"]))
    print("JSON escrito em", out_abs, "com", len(points), "pontos")


if __name__ == "__main__":
    main()
