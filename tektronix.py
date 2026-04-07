import numpy as np
from datetime import datetime
from fractions import Fraction
import time

"""
1. Medições de Tensão (Amplitude)

AMPlitude: Diferença entre o topo (High) e a base (Low).
HIGH: Valor do "topo" da forma de onda (estatístico).
LOW: Valor da "base" da forma de onda (estatístico).
MAXimum: O maior valor de tensão encontrado (pico absoluto).
MINImum: O menor valor de tensão encontrado.
PK2pk: Diferença entre o valor máximo e o mínimo (Pico-a-pico).
MEAN: Média aritmética de todos os pontos.
RMS: Valor eficaz da forma de onda.
POSOver: Overshoot positivo (em porcentagem).
NEGOver: Overshoot negativo (em porcentagem).

2. Medições de Tempo e Frequência

FREQuency: Frequência do sinal (em Hz).
PERIod: Período do sinal (em segundos).
RISe: Tempo de subida (do limiar inferior ao superior).
FALL: Tempo de descida (do limiar superior ao inferior).
PWIth: Largura do pulso positivo (Positive Width).
NWIth: Largura do pulso negativo (Negative Width).
PDUTy: Ciclo de trabalho positivo (Positive Duty Cycle %).
NDUTy: Ciclo de trabalho negativo (Negative Duty Cycle %).
DELay: Atraso entre dois canais (exige configurar SOURCE1 e SOURCE2).
PHAse: Diferença de fase entre dois sinais (em graus).
"""
MEAS_MAP_TEKTRONIX = {

    # Voltage
    "Vmax": "MAXimum",
    "Vmin": "MINImum",
    "Vpp": "PK2pk",
    "Vtop": "HIGH",
    "Vbase": "LOW",
    "Vavg": "MEAN",
    "Vrms": "RMS",

    # Time
    "Frequency": "FREQuency",
    "Period": "PERIod",
    "RiseTime": "RISe",
    "FallTime": "FALL",

    # Width
    "PosWidth": "PWIth",
    "NegWidth": "NWIth",
    "DutyCycle": "PDUTy",
    "DutyCycle": "NDUTy",

    # Signal quality
    "Overshoot": "POSOver",
    "Preshoot": "NEGOver",

    # Dual channel
    "Delay": "DELay",
    "Phase": "PHAse",
}

class TektronixScope:

    def __init__(self, inst):

        self.inst = inst


    # ---------------------------------------------------------
    # WAVEFORM
    # ---------------------------------------------------------
    def capture_waveform(self, channel):

        self.inst.write(f"DATA:SOURCE {channel}")
        self.inst.write("DATA:WIDTH 1")
        self.inst.write("DATA:ENC RPB")

        self.inst.write("DATA:START 1")
        self.inst.write("DATA:STOP {10000}")

        ymult = float(self.inst.query("WFMPRE:YMULT?"))
        yzero = float(self.inst.query("WFMPRE:YZERO?"))
        yoff  = float(self.inst.query("WFMPRE:YOFF?"))
        xincr = float(self.inst.query("WFMPRE:XINCR?"))
        xzero = float(self.inst.query("WFMPRE:XZERO?"))
        
        record_length = int(self.inst.query("WFMPRE:NR_PT?"))
        chset = self.get_channel_settings(channel)

        raw = self.inst.query_binary_values("CURVE?", datatype='B', container=np.array)

        voltage = (raw - yoff) * ymult + yzero
        time = np.arange(len(voltage)) * xincr + xzero


        metadata = {
            "Instrumento": self.inst.query("*IDN?").strip(),
            "Canal": channel,
            "Sample Rate (calculado)": 1 / xincr,
            "Record Length": len(raw),
            "Data da captura": datetime.now().isoformat()
        }
        return time, voltage, metadata|chset

    # ---------------------------------------------------------
    def parse_probe_attenuation(self, value):
        try:
            parts = value.split(";")
            attenuation = 1/float(parts[2])
            ratio = Fraction(attenuation).limit_denominator()
            if ratio.denominator == 1:
                return str(ratio.numerator)
            return f"{ratio.numerator}/{ratio.denominator}"
        except:
            return value

    # ---------------------------------------------------------
    def get_channel_settings(self, channel):

        coupling = self.inst.query(f"{channel}:COUPling?").strip()
        probe = self.inst.query(f"{channel}:PROBe?").strip()
        scale = self.inst.query(f"{channel}:SCAle?").strip()
        invert = self.inst.query(f"{channel}:INVert?").strip()
        bw = self.inst.query(f"{channel}:BANDwidth?").strip()

        return {
            "coupling": coupling,
            "probe_attenuation": self.parse_probe_attenuation(probe)+'x',
            "vertical_scale": f"{scale} V/div",
            "inverted": "ON" if invert == "1" else "OFF",
            "BW": bw
        }

    # ---------------------------------------------------------
    def capture_screen(self):

        self.inst.write("HARDCopy:FORMat PNG")
        self.inst.write("HARDCopy STARt")

        data = self.inst.read_raw()

        if data[0:1] == b'#':
            header_len = int(data[1:2])
            data_len = int(data[2:2+header_len])
            return data[2+header_len:2+header_len+data_len]

        return data

    # ---------------------------------------------------------
    def set_channel_settings(self, channel, info):
        delay = 0.2
        ch = channel.replace("CH", "")
        now = datetime.now()
        data_formatada = now.strftime("%Y-%m-%d")
        hora_formatada = now.strftime("%H:%M:%S")


        self.inst.write(f':DATE "{data_formatada}"')
        time.sleep(delay)
        self.inst.write(f':TIME "{hora_formatada}"')
        time.sleep(delay)


        if not info:
            return

        if "label" in info:
            value = info["label"]
            self.inst.write(f':CH{ch}:LAB "{value}"')
            time.sleep(delay)
            self.inst.write(f':CH{ch}:LAB:STATE ON')
            time.sleep(delay)

        if 'cursor' in info:
            self.inst.write(":CURSOR:STATE ON")
            time.sleep(delay)
            self.inst.write(":CURSOR:MODE MANUAL")
            time.sleep(delay)
            self.inst.write(f":CURSOR:SOUR CH{ch}")
            time.sleep(delay)

        if 'meas' in info:
            #for i in range(1, 5):
            #    self.inst.write(f'MEASU:MEAS{i}:STATE OFF')

            for i, v in enumerate(info['meas'], start=1):
                if i < 5:
                    if v == "OFF":
                        self.inst.write(f'MEASU:MEAS{i}:STATE OFF')
                        time.sleep(delay)
                    elif v != "":
                        self.inst.write(f'MEASU:MEAS{i}:STATE ON')
                        time.sleep(delay)
                        self.inst.write(f":MEASU:MEAS{i}:SOURCE1 CH{ch}")
                        time.sleep(delay)
                        self.inst.write(f":MEASU:MEAS{i}:TYPE {v}")
                        time.sleep(delay)

        if "text" in info:
            value = info["text"]
            self.inst.write(f':MESSAGE:SHOW "{value}"')
            time.sleep(delay)
                
    def map_measure(self, meas):
        if meas in MEAS_MAP_TEKTRONIX:
            return MEAS_MAP_TEKTRONIX[meas]
        else: return meas