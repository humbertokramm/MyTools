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
}
def getLimit(side,vcc="3V3",type="input"):
    if "all" in limites[side]: type = "all"
    values = {
        "side": side,
        "logicLimits":{
            "low_min": limites[side][type]['ViL'][0],
            "low_max": limites[side][type]['ViL'][1],
            "high_min": limites[side][type]['ViH'][0],
            "high_max": limites[side][type]['ViH'][1],
            },
        "threshold":{
            "lower":limites[side][type]['ViL'][1],
            "upper":limites[side][type]['ViH'][0],
        }
    }
    if "maxLimits" in limites[side][type]:
        values["maxLimits"]={
            "low": limites[side][type]["maxLimits"][0],
            "high":limites[side][type]["maxLimits"][1],
        }
    else:
        values["maxLimits"]={
            "low": limites[side][type]['ViL'][0],
            "high":limites[side][type]['ViH'][1],
        }
    return values