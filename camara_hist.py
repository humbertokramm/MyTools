"""
Histórico da câmara climática (CSZ Z-32 Plus, controlador EZT-570i).

O monitor no PC da câmara (http://172.22.239.100/camara) grava uma leitura por
minuto e mantém 31 dias. Este módulo busca as leituras de um período e acha a
mais próxima de um instante — usado pelos relatórios de loop/reboot para pôr a
PV/SP da câmara ao lado dos sensores da placa.

    from camara_hist import carregar, mais_proxima
    leituras = carregar(t_ini, t_fim)          # datetimes locais
    l = mais_proxima(leituras, t)              # None se não houver perto
    l.pv, l.sp, l.perfil
"""

import csv
import io
from bisect import bisect_left
from collections import namedtuple
from urllib.request import urlopen

URL = 'http://172.22.239.100/api/camara.csv'
TOLERANCIA = 150      # s: distância máxima aceita entre o instante e a leitura

Leitura = namedtuple('Leitura', 'epoch pv sp perfil')


def carregar(inicio, fim, timeout=15):
    """Leituras entre dois datetimes locais (com folga de TOLERANCIA nas pontas).

    Devolve (leituras, erro): lista vazia + mensagem quando o monitor não responde."""
    de = int(inicio.timestamp()) - TOLERANCIA
    ate = int(fim.timestamp()) + TOLERANCIA
    try:
        with urlopen(f'{URL}?de={de}&ate={ate}', timeout=timeout) as r:
            texto = r.read().decode('utf-8')
    except Exception as e:
        return [], str(e)
    leituras = []
    for row in csv.DictReader(io.StringIO(texto)):
        try:
            leituras.append(Leitura(int(row['epoch']), float(row['temp_pv']),
                                    float(row['temp_sp']) if row['temp_sp'] else None,
                                    row['perfil']))
        except (KeyError, ValueError):
            continue
    return leituras, ''


def mais_proxima(leituras, instante):
    """Leitura mais próxima de um datetime local, ou None se a mais perto estiver
    a mais de TOLERANCIA segundos (câmara sem histórico naquele momento)."""
    if not leituras or instante is None:
        return None
    t = instante.timestamp()
    i = bisect_left([l.epoch for l in leituras], t)
    j = min((k for k in (i - 1, i) if 0 <= k < len(leituras)),
            key=lambda k: abs(leituras[k].epoch - t))
    return leituras[j] if abs(leituras[j].epoch - t) <= TOLERANCIA else None


def perfis(leituras):
    """Nomes de perfil que aparecem no período, na ordem em que apareceram."""
    vistos = []
    for l in leituras:
        if l.perfil and l.perfil not in vistos:
            vistos.append(l.perfil)
    return vistos
