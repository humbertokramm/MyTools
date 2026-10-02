limites = {
    "74LV165":{
        "all":{
            'ViL': [-0.5 , 0.99],
            'ViH': [2.31 , 3.6],
        }
    },
    "74LVC595":{
        "all":{
            'ViL': [-0.5 , 0.99],
            'ViH': [2.31 , 3.8],
        }
    },
    "74LV125":{
        "all":{
            'ViL': [-0.5 , 0.8],
            'ViH': [2.0 , 3.8],
        }
    },
    "FPGA":{
        "all":{
            'ViL': [-0.5 , 0.8],
            'ViH': [1.7 , 3.6],
        }
    },
    "SFP":{
        "input":{
            'ViL': [-0.3 , 0.8],
            'ViH': [2.0 , 3.3+0.3],
        },
        "I2C":{
            'ViL': [-0.3 , 0.99],
            'ViH': [2.31 , 3.3+0.3],
        }
    },
    "QSFP":{
        "input":{
            'ViL': [-0.3 , 0.8],
            'ViH': [2.0 , 3.3+0.3],
        },
        "I2C":{
            'ViL': [-0.3 , 0.99],
            'ViH': [2.31 , 3.3+0.3],
        }
    },
    "MAX3232":{
        "all":{
            'ViL': [0 , 0.8],
            'ViH': [2.0 , 5.5],
            "maxLimits": [-0.3,6],
        }
    },
    "MAX3232-5V":{
        "all":{
            'ViL': [0 , 0.8],
            'ViH': [2.4 , 5.5],
            "maxLimits": [-0.3,6],
        }
    },
    "SoM":{
        "all":{
            'ViL': [-0.3 , 0.825],
            'ViH': [2.06 , 3.6],
        }
    },
    "FAN":{
        "all":{
            'ViL': [0 , 0.6],
            'ViH': [2.8 , 5.5],
        }
    },
    "LM75":{
        "I2C":{
            'ViL': [-0.3 ,3.3*0.3],
            'ViH': [3.3*0.7, 3.3+0.3],
        }
    },
    "LM89":{
        "I2C":{
            'ViL': [-0.5 ,0.8],
            'ViH': [2.1, 3.3+0.3],
            'Vhys': 400e-3,
        }
    },
    "E2P (280.2402.00)":{
        "I2C":{
            'ViL': [-0.45 ,3.3*0.3],
            'ViH': [3.3*0.7, 3.3+1],
            'tSP': 100e-9,
        }
    },
    "E2P (280.2401.00)":{
        "I2C":{
            'ViL': [-0.5 ,3.3*0.3],
            'ViH': [3.3*0.7, 3.3+0.5],
            'tSP': 50e-9,
        }
    },
    "ISL68127":{
        "all":{
            'ViL': [-0.3 ,0.8],
            'ViH': [1.55, 3.3+0.3],
            'Vhys': 2e-3,
        }
    },
    "Si5340":{
        "all":{
            'ViL': [-0.5 ,3.3*0.3],
            'ViH': [3.3*0.7, 3.3+0.5],
            'tSP': 100e-9,
        }
    },
    "Si53154":{
        "all":{
            'ViL': [-0.3 ,1],
            'ViH': [2.2, 3.3+0.3],
        }
    },
    # DC Electrical Characteristics: VIH/VIL mudam de criterio conforme o
    # Vcc -- percentual ate 1.95V, constante a partir de 2.3V. As tres
    # primeiras linhas do datasheet (1.1-1.3, 1.4-1.6, 1.65-1.95) usam a
    # mesma regra e foram unidas numa faixa so.
    # A linha de Vcc 0.9V do datasheet traz apenas valor tipico, sem Min/Max
    # garantidos, entao nao entra aqui: tipico nao e limite.
    "NC7WV07":{
        "all":{
            "byVcc":[
                ((1.10, 1.95), {'ViL': [-0.5, lambda v: 0.35*v],
                                'ViH': [lambda v: 0.65*v, lambda v: v+0.5]}),
                ((2.30, 2.70), {'ViL': [-0.5, 0.7],
                                'ViH': [1.6, lambda v: v+0.5]}),
                ((2.70, 3.60), {'ViL': [-0.5, 0.8],
                                'ViH': [2.0, lambda v: v+0.5]}),
            ]
        }
    },
    "Marvell":{
        "input-3V3":{
            'ViL': [-0.3 , 0.8],
            'ViH': [2.0 , 3.3+0.3],
        },
        "input-1V8":{
            'ViL': [-0.3 , 1.8*0.35],
            'ViH': [1.8*0.65 , 1.8+0.3],
        },
        "I2C":{
            'ViL': [-0.5 ,3.3*0.3],
            'ViH': [3.3*0.7, 3.3+0.5],
        }
    },
    "AP2553":{
        "all":{
            'ViL': [-0.3 ,0.8],
            'ViH': [2, 6.5],
        }
    },
}
def getPower(nominal, pct=1, maxLimits=None):
    """Limites de uma fonte: tensao nominal +- tolerancia percentual.

    Analise diferente da de nivel logico -- aqui a faixa sombreada no grafico
    e a regiao aceitavel, e o que sai dela e falha.

    Args:
        nominal (float): tensao nominal do trilho, ex ``12.0``.
        pct: tolerancia em PORCENTO (nao fracao: ``1`` = 1%). Numero para
            simetrica, TUPLA para assimetrica, LISTA para varias faixas
            concentricas.
        maxLimits (seq): limites absolutos opcionais, em volts.

    Returns:
        dict: pronto para ``CsvScope.Limits``.

    Exemplo:
        CS.Limits = getPower(12.0, 1)          # 12V +-1%  -> 11.88 a 12.12
        CS.Limits = getPower(3.3, (-3, 5))     # 3.3V -3%/+5%, uma faixa
        CS.Limits = getPower(12.0, [1, 5])     # duas faixas: +-1% e +-5%

    Note:
        Tupla e lista significam coisas diferentes: ``(-3, 5)`` e UMA faixa
        de -3% a +5%; ``[3, 5]`` sao DUAS faixas, +-3% e +-5%.
        O ``threshold`` devolvido usa a primeira faixa, tomada como a
        especificacao principal.
    """
    from csvscope import faixas_pct
    lo_pct, hi_pct = faixas_pct(pct)[0]
    values = {
        "powerLimits": {"nominal": nominal, "pct": pct},
        "threshold": {
            "lower": nominal * (1 + lo_pct / 100.0),
            "upper": nominal * (1 + hi_pct / 100.0),
        },
    }
    if maxLimits is not None:
        values["maxLimits"] = {"low": maxLimits[0], "high": maxLimits[1]}
    return values


def _parse_vcc(vcc):
    """Aceita 3.3 ou a notacao usada nas chaves: '3V3', '1V8', '5V'."""
    if isinstance(vcc, str):
        return float(vcc.upper().replace('V', '.').rstrip('.'))
    return float(vcc)


def _resolve(x, vcc):
    """Valor fixo, ou regra em funcao do Vcc.

    Permite escrever a regra do datasheet no lugar do numero ja calculado:
        'ViH': [lambda v: 0.65*v, ...]
    Assim o limite acompanha o Vcc informado, em vez de ficar congelado numa
    tensao so -- e a regra fica visivel no arquivo.
    """
    return x(vcc) if callable(x) else x


def _faixa_vcc(side, type, entry, vcc):
    """Escolhe a faixa de Vcc de um componente que usa 'byVcc'.

    Falha se o Vcc nao cair em nenhuma faixa. E de proposito: chutar a faixa
    mais proxima daria um limite silenciosamente errado, e esse valor decide
    aprovacao/reprovacao de ensaio.
    """
    for (vmin, vmax), vals in entry['byVcc']:
        if vmin <= vcc <= vmax:
            return vals
    faixas = ', '.join(f'{a}-{b}V' for (a, b), _ in entry['byVcc'])
    raise ValueError(f'{side} [{type}]: Vcc {vcc}V fora das faixas do '
                     f'datasheet ({faixas})')


def getLimit(side,vcc="3V3",type="input"):
    """Limites de um componente, resolvidos para o Vcc informado.

    Args:
        side (str): componente, ex ``'NC7WV07'``.
        vcc  (float or str): tensao de alimentacao -- ``3.3`` ou ``'3V3'``.
        type (str): contexto/interface, ex ``'input'``, ``'I2C'``. Ignorado
            quando o componente tem um unico criterio (chave ``'all'``).
    """
    if side not in limites:
        raise KeyError(f'componente desconhecido em limites: {side}')
    comp = limites[side]
    if "all" in comp: type = "all"
    if type not in comp:
        raise KeyError(f'{side}: contexto "{type}" inexistente '
                       f'(disponiveis: {", ".join(comp)})')

    v = _parse_vcc(vcc)
    entry = comp[type]
    if "byVcc" in entry:
        entry = _faixa_vcc(side, type, entry, v)

    ViL = [_resolve(x, v) for x in entry['ViL']]
    ViH = [_resolve(x, v) for x in entry['ViH']]

    values = {
        "side": side,
        "vcc": v,
        "logicLimits":{
            "low_min": ViL[0],
            "low_max": ViL[1],
            "high_min": ViH[0],
            "high_max": ViH[1],
            },
        "threshold":{
            "lower": ViL[1],
            "upper": ViH[0],
        }
    }
    if "maxLimits" in entry:
        values["maxLimits"]={
            "low":  _resolve(entry["maxLimits"][0], v),
            "high": _resolve(entry["maxLimits"][1], v),
        }
    else:
        values["maxLimits"]={
            "low":  ViL[0],
            "high": ViH[1],
        }
    return values