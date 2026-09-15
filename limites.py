limites = {
    "74LV165":{
        'ViL': [-0.5 , 0.99],
        'ViH': [2.31 , 3.6],
    },
    "74LVC595":{
        'ViL': [-0.5 , 0.99],
        'ViH': [2.31 , 3.8],
    },
    "74LV125":{
        'ViL': [-0.5 , 0.8],
        'ViH': [2.0 , 3.8],
    },
    "FPGA":{
        'ViL': [-0.5 , 0.8],
        'ViH': [1.7 , 3.6],
        "maxLimits": [-0.5,3.6],
    },
    "SFP":{
        'ViL': [-0.3 , 0.8],
        'ViH': [2.0 , 3.3+0.3],
        "maxLimits": [-0.5,3.6],
    },
    "QSFP":{
        'ViL': [-0.3 , 0.8],
        'ViH': [2.0 , 3.3+0.3],
        "maxLimits": [-0.5,3.6],
    },
    "MAX3232":{
        'ViL': [0 , 0.8],
        'ViH': [2.0 , 5.5],
        "maxLimits": [-0.3,6],
    },
    "MAX3232-5V":{
        'ViL': [0 , 0.8],
        'ViH': [2.4 , 5.5],
        "maxLimits": [-0.3,6],
    },
    "SoM":{
        'ViL': [-0.3 , 0.825],
        'ViH': [2.06 , 3.6],
    },
}
def getLimit(side):
    values = {
        "side": side,
        "logicLimits":{
            "low_min": limites[side]['ViL'][0],
            "low_max": limites[side]['ViL'][1],
            "high_min": limites[side]['ViH'][0],
            "high_max": limites[side]['ViH'][1],
            },
        "threshold":{
            "lower":limites[side]['ViL'][1],
            "upper":limites[side]['ViH'][0],
        }
    }
    if "maxLimits" in limites[side]:
        values["maxLimits"]={
            "low": limites[side]["maxLimits"][0],
            "high":limites[side]["maxLimits"][1],
        }
    else:
        values["maxLimits"]={
            "low": limites[side]['ViL'][0],
            "high":limites[side]['ViH'][1],
        }
    'threshold'
    return values