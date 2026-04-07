import numpy as np
from datetime import datetime
from fractions import Fraction
from pprint import pprint


MEAS_MAP_TEKTRONIX = {

    # Voltage
    "Vmax": "MAXIMUM",
    "Vmin": "MINIMUM",
    "Vpp": "PK2PK",
    "Vtop": "TOP",
    "Vbase": "BASE",
    "Vavg": "MEAN",
    "Vrms": "RMS",

    # Time
    "Frequency": "FREQUENCY",
    "Period": "PERIOD",
    "RiseTime": "RISETIME",
    "FallTime": "FALLTIME",

    # Width
    "PosWidth": "PWIDTH",
    "NegWidth": "NWIDTH",
    "DutyCycle": "DUTY",

    # Signal quality
    "Overshoot": "POVERSHOOT",
    "Preshoot": "NOVERSHOOT",

    # Dual channel
    "Delay": "DELAY",
    "Phase": "PHASE",
}

class TektronixScope:

    def __init__(self, inst):

        self.inst = inst


    def capture_waveform(self, channel):

        self.inst.write(f"DATA:SOURCE {channel}")
        self.inst.write("DATA:WIDTH 1")
        self.inst.write("DATA:ENC RPB")
        
        self.inst.write("DATA:START 1")
        self.inst.write(f"DATA:STOP {10000}")

        ymult = float(self.inst.query("WFMPRE:YMULT?"))
        yzero = float(self.inst.query("WFMPRE:YZERO?"))
        yoff  = float(self.inst.query("WFMPRE:YOFF?"))
        xincr = float(self.inst.query("WFMPRE:XINCR?"))
        xzero = float(self.inst.query("WFMPRE:XZERO?"))
        
        record_length = int(self.inst.query("WFMPRE:NR_PT?"))
        chset = self.get_channel_settings(channel)

        # Calcula sample rate corretamente
        #sample_rate = 1.0 / xincr
        #sample_rate = EM.getEngSTR(sample_rate)
        
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
    
    def capture_screen(self):

        self.inst.write("HARDCopy:FORMat PNG")
        self.inst.write("HARDCopy STARt")

        data = self.inst.read_raw()

        if data[0:1] == b'#':
            header_len = int(data[1:2])
            data_len = int(data[2:2+header_len])
            image = data[2+header_len:2+header_len+data_len]
        else:
            image = data
        return image
    
    def set_channel_settings(self, channel,info):
        if info:
            if "label" in info:
                self.inst.write(f'CH{channel}:LABel "{info['label']}"')
                self.inst.write(f'CH{channel}:LABel:VISible ON')