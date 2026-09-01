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
    "Vamp": "AMPlitude",
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
    "PosDutyCycle": "PDUTy",
    "NegDutyCycle": "NDUTy",

    # Signal quality
    "Overshoot": "POSOver",
    "Preshoot": "NEGOver",

    # Dual channel
    "Delay": "DELay",
    "Phase": "PHAse",
}

class TektronixScope:

    def __init__(self, inst,debug=False):
        self.inst = inst
        self.debug = debug

    # ---------------------------------------------------------
    # WAVEFORM
    # ---------------------------------------------------------
    def capture_waveform(self, channel):

        self._write(f"DATA:SOURCE {channel}")
        self._write("DATA:WIDTH 1")
        self._write("DATA:ENC RPB")

        # ESSENCIAL
        self._write("DATA:RESOLUTION REDUCED")

        self._write("DATA:START 1")
        self._write("DATA:STOP 10000")  # opcional (display típico)

        ymult = float(self.inst.query("WFMPRE:YMULT?"))
        yzero = float(self.inst.query("WFMPRE:YZERO?"))
        yoff  = float(self.inst.query("WFMPRE:YOFF?"))
        xincr = float(self.inst.query("WFMPRE:XINCR?"))
        xzero = float(self.inst.query("WFMPRE:XZERO?"))

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

        return time, voltage, metadata | chset

    # ---------------------------------------------------------
    def _parse_probe_attenuation(self, value):
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
            "probe_attenuation": self._parse_probe_attenuation(probe)+'x',
            "vertical_scale": f"{scale} V/div",
            "inverted": "ON" if invert == "1" else "OFF",
            "BW": bw
        }

    # ---------------------------------------------------------
    def capture_screen(self):

        self._write("HARDCopy:FORMat PNG")
        self.inst.write("HARDCopy STARt")  # produz dados — não pode usar _write em modo debug

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


        self._write(f':DATE "{data_formatada}"')
        time.sleep(delay)
        self._write(f':TIME "{hora_formatada}"')
        time.sleep(delay)


        if not info:
            return

        if "label" in info:
            value = info["label"]
            self._write(f':CH{ch}:LAB "{value}"')
            time.sleep(delay)
            self._write(f':CH{ch}:LAB:STATE ON')
            time.sleep(delay)

        if 'cursor' in info:
            cursor = {k.lower(): v for k, v in info['cursor'].items()} if isinstance(info['cursor'], dict) else {}
            has_y = 'y1' in cursor or 'y2' in cursor
            has_x = 'x1' in cursor or 'x2' in cursor
            show  = cursor.get('show', 'y')   # 'y' = HBARS, 'x' = VBARS (padrão: y)
            self._write(":CURSOR:STATE ON")
            if has_y and not has_x:
                self._write(":CURSOR:FUNCTION HBARS")
                self._write(":CURSOR:HBARS:UNITS BASE")
                self._write(f":CURSOR:HBARS:SOURCE1 CH{ch}")
                if 'y1' in cursor: self._write(f":CURSOR:HBARS:POSITION1 {cursor['y1']}")
                if 'y2' in cursor: self._write(f":CURSOR:HBARS:POSITION2 {cursor['y2']}")
            elif has_x and not has_y:
                self._write(":CURSOR:FUNCTION VBARS")
                self._write(":CURSOR:VBARS:UNITS SECONDS")
                self._write(f":CURSOR:VBARS:SOURCE1 CH{ch}")
                if 'x1' in cursor: self._write(f":CURSOR:VBARS:POSITION1 {cursor['x1']}")
                if 'x2' in cursor: self._write(f":CURSOR:VBARS:POSITION2 {cursor['x2']}")
            elif has_x and has_y:
                # Modo SCREEN: HBARS = Y, VBARS = X (setar VBARS por último —
                # setar HBARS em SCREEN recalcula VBARS para cruzamento da onda)
                self._write(":CURSOR:FUNCTION SCREEN")
                self._write(":CURSOR:HBARS:UNITS BASE")
                self._write(f":CURSOR:HBARS:SOURCE1 CH{ch}")
                if 'y1' in cursor: self._write(f":CURSOR:HBARS:POSITION1 {cursor['y1']}")
                if 'y2' in cursor: self._write(f":CURSOR:HBARS:POSITION2 {cursor['y2']}")
                self._write(":CURSOR:VBARS:UNITS SECONDS")
                if 'x1' in cursor: self._write(f":CURSOR:VBARS:POSITION1 {cursor['x1']}")
                if 'x2' in cursor: self._write(f":CURSOR:VBARS:POSITION2 {cursor['x2']}")

        if 'meas' in info:
            #for i in range(1, 5):
            #    self._write(f'MEASU:MEAS{i}:STATE OFF')

            for i, v in enumerate(info['meas'], start=1):
                value = self._map_measure(v)
                if i < 5:
                    if v == None:
                        self._write(f'MEASU:MEAS{i}:STATE OFF')
                        time.sleep(delay)
                    elif v != "":
                        self._write(f'MEASU:MEAS{i}:STATE ON')
                        time.sleep(delay)
                        self._write(f":MEASU:MEAS{i}:SOURCE1 CH{ch}")
                        time.sleep(delay)
                        self._write(f":MEASU:MEAS{i}:TYPE {value}")
                        time.sleep(delay)

        if "text" in info:
            value = info["text"]
            self._write(f':MESSAGE:SHOW "{value}"')
            time.sleep(delay)
                
    # ---------------------------------------------------------
    def set_timebase(self, scale=None, position=None, reference=None):
        """Configure the horizontal timebase.

        Args:
            scale     (float): seconds per division.
            position  (float): deslocamento em segundos entre o trigger e o
                ponto de referencia.
            reference (str): ``'left'``, ``'center'`` ou ``'right'``.

        Note:
            O Tektronix expressa a posicao horizontal em PERCENTUAL do
            registro antes do trigger, nao em segundos. A conversao usa a
            largura da tela (10 divisoes x scale) e assume a mesma convencao
            de sinal do Keysight. Se ``scale`` nao for informado, o valor
            atual e consultado no instrumento.
        """
        if scale is not None:
            self._write(f'HORizontal:SCAle {scale:.9g}')

        pct = None
        if reference is not None:
            pct = {'left': 10.0, 'center': 50.0,
                   'centre': 50.0, 'right': 90.0}.get(str(reference).lower())

        if position is not None:
            sc = scale if scale is not None else float(
                self.inst.query('HORizontal:SCAle?').strip())
            base = pct if pct is not None else 50.0
            pct = base - 100.0 * position / (10.0 * sc)
            pct = max(0.0, min(100.0, pct))

        if pct is not None:
            self._write(f'HORizontal:POSition {pct:.4f}')

    def set_trigger(self, channel='CH1', level=0.0, slope='rise', mode='NORMal'):
        """Configure the edge trigger.

        Args:
            channel (str): trigger source, e.g. ``'CH1'``.
            level   (float): trigger level in volts.
            slope   (str): ``'rise'`` or ``'fall'`` (also accepts
                ``'positive'``/``'negative'`` and ``'+'``/``'-'``).
            mode    (str): ``'NORMal'`` waits for a real edge; ``'AUTO'``
                free-runs when none arrives. Use NORMal before :meth:`single`.
        """
        fall = str(slope).lower() in ('fall', 'falling', 'neg', 'negative', '-')
        self._write('TRIGger:A:TYPe EDGE')
        self._write(f'TRIGger:A:EDGE:SOUrce {channel}')
        self._write(f'TRIGger:A:EDGE:SLOpe {"FALL" if fall else "RISe"}')
        self._write(f'TRIGger:A:LEVel {level:.6f}')
        self._write(f'TRIGger:A:MODe {mode}')

    def single(self):
        """Arm the oscilloscope for a single triggered acquisition."""
        self._write('ACQuire:STOPAfter SEQuence')
        self._write('ACQuire:STATE RUN')

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

        Args:
            timeout  (float): Maximum seconds to wait. Default 30.
            interval (float): Polling interval in seconds. Default 0.5.

        Returns:
            bool: ``True`` if acquisition completed, ``False`` if timed out.
        """
        elapsed = 0
        while elapsed < timeout:
            time.sleep(interval)
            elapsed += interval
            if self.inst.query('ACQuire:STATE?').strip() == '0':
                return True
        return False

    def stop(self):
        """Stop the current acquisition."""
        self._write('ACQuire:STATE STOP')

    # ---------------------------------------------------------
    def _write(self, txt):
        if self.debug:
            self.inst.write('*CLS')
            self.inst.write(txt)
            err = self.inst.query('EVMSG?').strip()
            print(f"{txt}  =>  {err}")
        else:
            self.inst.write(txt)
        
    def _map_measure(self, meas):
        if meas in MEAS_MAP_TEKTRONIX:
            return MEAS_MAP_TEKTRONIX[meas]
        else: return meas