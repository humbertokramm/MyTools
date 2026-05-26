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

    def __init__(self, inst,debug=False):
        self.inst = inst
        self.debug = debug


    def capture_waveform(self, channel):
        print("lendo: ",channel) 
        ch = self._channel_name(channel)
        
        # Verifica se o canal está ativo
        disp = int(self.inst.query(f":{ch}:DISP?"))
        if disp == 0:
            raise RuntimeError(f"Canal {channel} não está exibido na tela")
        
        self._write(f":WAV:SOUR {ch}")
        self._write(":WAV:FORM BYTE")
        self._write(":WAV:MODE RAW")

        try:
            xinc = float(self.inst.query(":WAV:XINC?"))
        except Exception:
            raise RuntimeError(f"Canal {channel} não possui waveform válido")
        
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

    def _parse_probe_attenuation(self, value):
        try:
            attenuation = float(value)
            ratio = Fraction(attenuation).limit_denominator()
            if ratio.denominator == 1:
                return str(ratio.numerator)
            return f"{ratio.numerator}/{ratio.denominator}"
        except:
            return value

    def get_channel_settings(self, channel):
        res = {}
        channel = self._channel_name(channel)
        if "CH" in channel:
            res['coupling'] = self.inst.query(f":{channel}:COUPling?").strip()
            probe = self.inst.query(f":{channel}:PROBe?").strip()
            res["inverted"] = "ON" if self.inst.query(f":{channel}:INVert?").strip() == "1" else "OFF"
            res["BW"] = "ON" if self.inst.query(f":{channel}:BWLimit?").strip() == "1" else "OFF"
        res['vertical_scale'] = f"{self.inst.query(f":{channel}:SCALe?").strip()} V/div"
        return res
    
    def capture_screen(self):
        self._write(':SAVE:IMAGe:FORMat PNG')
        self._write(':SAVE:IMAGe:FACTors 1')
        self._write(':HARDcopy:INKSaver OFF')
        sleep(4)

        image = self.inst.query_binary_values(
            ':DISPlay:DATA? PNG,COLor',
            datatype='B',
            container=bytes
        )
        self._write(f':DISPlay:ANN:TEXT ""')
        return image

    def _channel_name(self, channel):
        if "MATH" in channel:
            ch = "FUNCtion"
        else:
            ch = "CHANnel"+ channel.replace("CH", "")
        return ch

    def set_channel_settings(self, channel,info):
        now = datetime.now()
        self._write(f":SYSTem:DATE {now.year},{now.month},{now.day}")
        self._write(f":SYSTem:TIME {now.hour},{now.minute},{now.second}")
        
        channel = self._channel_name(channel)
        if info:
            if "label" in info:
                value = info['label']
                self._write(f':{channel}:LABel "{value}"')
                self._write(f':{channel}:LABel:STATe ON')
                self._write(':DISPlay:LABel ON')
            if 'cursor' in info:
                cursor = {k.lower(): v for k, v in info['cursor'].items()} if isinstance(info['cursor'], dict) else {}
                self._write(':MARKer:MODE MANual')
                if 'y1' in cursor: self._write(f':MARKer:Y1P {cursor["y1"]}')
                if 'y2' in cursor: self._write(f':MARKer:Y2P {cursor["y2"]}')
                if 'x1' in cursor: self._write(f':MARKer:X1P {cursor["x1"]}')
                if 'x2' in cursor: self._write(f':MARKer:X2P {cursor["x2"]}')
            if 'meas' in info and len(info['meas']) > 0:
                #if len(info['meas']) > 0: self._write(":MEASure:CLEar")
                for v in info['meas']:
                    v = self._map_measure(v)
                    if v == 'RISetime' or v == 'FALLtime':
                        LOWer = info['threshold']['lower']
                        UPPer = info['threshold']['upper']
                        self._write(f':MEASure:LOWer {LOWer:.6f}')
                        self._write(f':MEASure:UPPer {UPPer:.6f}')
                    
                    if 'FFT' in v:
                        func = re.search(r"\((.*?)\)", v).group(1)
                        self._write(f':FUNCtion1:OPERator FFT')
                        self._write(f':FUNCtion1:SOURce1 {channel}')
                        self._write(f':FUNCtion1:DISPlay ON')
                        self._write(f':MEASure:{func} FUNCtion1')
                    else:
                        self._write(f':MEASure:{v} {channel}')
            if "text" in info:
                txt = self._format_dso_text(info['text'])
                self._write(f':DISPlay:ANN:STATe ON')
                self._write(f':DISPlay:ANN:TEXT "{txt}"')
                self._write(f':DISPlay:ANN:Y 10')
                self._write(f':DISPlay:ANN:X 10')
    
    def _format_dso_text(self, txt):
        pos = txt.find(" - ")
        return txt.replace(' - ',' '*(31-pos))
    
    # ---------------------------------------------------------
    def single(self):
        """Arm the oscilloscope for a single triggered acquisition."""
        self._write(':SINGle')

    def monitor_single(self, max_wait=3600, retry_timeout=30, interval=0.5):
        """Wait for a single acquisition, re-arming on each timeout.

        Args:
            max_wait      (float): Total seconds to wait. Default 3600 (1 h).
            retry_timeout (float): Seconds per attempt before re-arming.
            interval      (float): Polling interval in seconds.

        Returns:
            bool: ``True`` if triggered, ``False`` if *max_wait* expired.
        """
        elapsed_total = 0.0
        while elapsed_total < max_wait:
            self.single()
            if self.wait_single(timeout=retry_timeout, interval=interval):
                return True
            elapsed_total += retry_timeout
        return False

    def wait_single(self, timeout=30, interval=0.5):
        """Block until a single acquisition completes or *timeout* expires.

        Polls ``:OPERegister:CONDition?`` bit 3 (Measuring). When the bit
        clears the acquisition has finished.

        Args:
            timeout  (float): Maximum seconds to wait. Default 30.
            interval (float): Polling interval in seconds. Default 0.5.

        Returns:
            bool: ``True`` if acquisition completed, ``False`` if timed out.
        """
        from time import sleep
        elapsed = 0
        while elapsed < timeout:
            sleep(interval)
            elapsed += interval
            cond = int(self.inst.query(':OPERegister:CONDition?').strip())
            if cond & 8 == 0:
                return True
        return False

    def stop(self):
        """Stop the current acquisition."""
        self._write(':STOP')

    # ---------------------------------------------------------
    def _write(self, txt):
        if self.debug:
            self.inst.write('*CLS')
            self.inst.write(txt)
            err = self.inst.query(':SYST:ERR?').strip()
            print(f"{txt}  =>  {err}")
        else:
            self.inst.write(txt)
    
    def _map_measure(self, meas):
        if meas in MEAS_MAP_KEYSIGHT:
            return MEAS_MAP_KEYSIGHT[meas]
        else: return meas