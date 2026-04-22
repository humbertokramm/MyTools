import numpy as np
from datetime import datetime
from time import sleep
from fractions import Fraction
from pprint import pprint
import re


'''
| Medida             | SCPI        |
| ------------------ | ----------- |
| Vmax               | `VMAX`      |
| Vmin               | `VMIN`      |
| Vpp                | `VPP`       |
| Vtop               | `VTOP`      |
| Vbase              | `VBASE`     |
| Vamp               | `VAMP`      |
| Vavg (full screen) | `VAVerage`  |
| Vrms               | `VRMS`      |
| Overshoot          | `OVERshoot` |
| Preshoot           | `PREShoot`  |

| Medida        | SCPI        |
| ------------- | ----------- |
| Período       | `PERiod`    |
| Frequência    | `FREQuency` |
| Rise Time     | `RISetime`  |
| Fall Time     | `FALLtime`  |
| Pulse Width + | `PWIDth`    |
| Pulse Width - | `NWIDth`    |
| Duty Cycle    | `DUTYcycle` |

| Medida | SCPI    |
| ------ | ------- |
| Delay  | `DELay` |
| Phase  | `PHASe` |


| Medida      | SCPI        |
| ----------- | ----------- |
| Edge Count  | `EDGecount` |
| Burst Width | `BWIDth`    |
| Area        | `AREa`      |


| Medida     | SCPI    |
| ---------- | ------- |
| Cycle RMS  | `CRMS`  |
| Cycle Mean | `CMEAN` |'''


MEAS_MAP_KEYSIGHT = {

    # Voltage
    "Vmax": "VMAX",
    "Vmin": "VMIN",
    "Vpp": "VPP",
    "Vtop": "VTOP",
    "Vbase": "VBASE",
    "Vamp": "VAMP",
    "Vavg": "VAVerage",
    "Vrms": "VRMS",

    # Time
    "Frequency": "FREQuency",
    "Period": "PERiod",
    "RiseTime": "RISetime",
    "FallTime": "FALLtime",

    # Width
    "PosWidth": "PWIDth",
    "NegWidth": "NWIDth",
    "DutyCycle": "DUTYcycle",

    # Signal quality
    "Overshoot": "OVERshoot",
    "Preshoot": "PREShoot",

    # Dual channel
    "Delay": "DELay",
    "Phase": "PHASe",
    
    # Especiais
    'FFT(vpp)': 'FFT(VPP)',
    'FFT(fmax)':'FFT(XMAX)',
}

class KeysightScope:

    def __init__(self, inst):

        self.inst = inst
        self.chinfo = False


    def capture_waveform(self, channel):
        print("lendo: ",channel) 
        ch = channel.replace("CH", "")
        self.inst.write(f":WAV:SOUR CHANnel{ch}")
        self.inst.write(":WAV:FORM BYTE")
        self.inst.write(":WAV:MODE RAW")

        xinc = float(self.inst.query(":WAV:XINC?"))
        xorig = float(self.inst.query(":WAV:XOR?"))

        yinc = float(self.inst.query(":WAV:YINC?"))
        yorig = float(self.inst.query(":WAV:YOR?"))
        yref = float(self.inst.query(":WAV:YREF?"))
        chset = self.get_channel_settings(channel)

        raw = self.inst.query_binary_values(":WAV:DATA?", datatype='B', container=np.array)

        voltage = (raw - yref) * yinc + yorig
        time = np.arange(len(raw)) * xinc + xorig
        metadata = {
            "Instrumento": self.inst.query("*IDN?").strip(),
            "Canal": channel,
            "Sample Rate (calculado)": 1 / xinc,
            "Record Length": len(raw),
            "Data da captura": datetime.now().isoformat()
        }
        return time, voltage, metadata|chset

    def parse_probe_attenuation(self, value):
        try:
            attenuation = float(value)
            ratio = Fraction(attenuation).limit_denominator()
            if ratio.denominator == 1:
                return str(ratio.numerator)
            return f"{ratio.numerator}/{ratio.denominator}"
        except:
            return value

    def get_channel_settings(self, channel):
        ch = channel.replace("CH", "")
        coupling = self.inst.query(f":CHANnel{ch}:COUPling?").strip()
        probe = self.inst.query(f":CHANnel{ch}:PROBe?").strip()
        scale = self.inst.query(f":CHANnel{ch}:SCALe?").strip()
        invert = self.inst.query(f":CHANnel{ch}:INVert?").strip()
        bw = self.inst.query(f":CHANnel{ch}:BWLimit?").strip()
        return {
            "coupling": coupling,
            "probe_attenuation": self.parse_probe_attenuation(probe) + "x",
            "vertical_scale": f"{scale} V/div",
            "inverted": "ON" if invert == "1" else "OFF",
            "BW": "ON" if bw == "1" else "OFF"
        }
    
    def capture_screen(self):
        self.inst.write(':SAVE:IMAGe:FORMat PNG')
        self.inst.write(':SAVE:IMAGe:FACTors 1')
        self.inst.write(':HARDcopy:INKSaver OFF')
        sleep(4)

        image = self.inst.query_binary_values(
            ':DISPlay:DATA? PNG,COLor',
            datatype='B',
            container=bytes
        )
        self.inst.write(f':DISPlay:ANN:TEXT ""')
        return image
    
    def set_channel_settings(self, channel,info):
        ch = channel.replace("CH", "")
        now = datetime.now()
        self.inst.write(f":SYSTem:DATE {now.year},{now.month},{now.day}")
        self.inst.write(f":SYSTem:TIME {now.hour},{now.minute},{now.second}")
        
        if info:
            if "label" in info:
                value = info['label']
                self.inst.write(f':CHANnel{ch}:LABel "{value}"')
                self.inst.write(f':CHANnel{ch}:LABel:STATe ON')
                self.inst.write(':DISPlay:LABel ON')
            if 'cursor' in info:
                self.inst.write(f':CURSor:MODE MANual')
                self.inst.write(f':CURSor:Y1 0')
                self.inst.write(f':CURSor:Y2 3.3')
                self.inst.write(f':DISPlay:GRID FULL')
            if 'meas' in info and len(info['meas']) > 0:
                self.inst.write(":MEASure:CLEar")
                for v in info['meas']:
                    v = self.map_measure(v)
                    if v == 'RISetime' or v == 'FALLtime':
                        self.inst.write(":MEASure:DEFine THResholds,ABSolute")
                        LOWer = info['threshold']['lower']
                        UPPer = info['threshold']['upper']
                        MIDDle = (UPPer-LOWer)/2+LOWer
                        self.inst.write(f":MEASure:THResholds:ABSolute:LOWer {LOWer:.6f}")
                        self.inst.write(f":MEASure:THResholds:ABSolute:MIDDle {MIDDle:.6f}")
                        self.inst.write(f":MEASure:THResholds:ABSolute:UPPer {UPPer:.6f}")
                    
                    if 'FFT' in v:
                        func = re.search(r"\((.*?)\)", v).group(1)
                        self.inst.write(f':FUNCtion1:OPERator FFT')
                        self.inst.write(f':FUNCtion1:SOURce1 CHANnel{ch}')
                        self.inst.write(f':FUNCtion1:DISPlay ON')
                        self.inst.write(f':MEASure:{func} FUNCtion1')
                    else:
                        self.inst.write(f':MEASure:{v} CHANnel{ch}')
            if "text" in info:
                txt = self.text4DSO(info['text'])
                self.inst.write(f':DISPlay:ANN:STATe ON')
                self.inst.write(f':DISPlay:ANN:TEXT "{txt}"')
                self.inst.write(f':DISPlay:ANN:Y 10')
                self.inst.write(f':DISPlay:ANN:X 10')
    
    def text4DSO(self, txt):
        pos = txt.find(" - ")
        return txt.replace(' - ',' '*(31-pos))
    
    def map_measure(self, meas):
        if meas in MEAS_MAP_KEYSIGHT:
            return MEAS_MAP_KEYSIGHT[meas]
        else: return meas