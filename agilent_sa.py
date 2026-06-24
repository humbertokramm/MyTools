import numpy as np
from datetime import datetime
from time import sleep


TRACE_NAMES = {
    'Trace1': 'TRACE1',
    'Trace2': 'TRACE2',
    'Trace3': 'TRACE3',
    'Trace4': 'TRACE4',
    'Trace5': 'TRACE5',
    'Trace6': 'TRACE6',
}


class AgilentSA:

    def __init__(self, inst, debug=False):
        self.inst = inst
        self.debug = debug

    # ------------------------------------------------------------------
    # Trace capture
    # ------------------------------------------------------------------

    def capture_trace(self, trace='Trace1'):
        """Captura trace e retorna (freq_hz, amp_dbuv, metadata).

        freq_hz   : np.ndarray de frequencias em Hz
        amp_dbuv  : np.ndarray de amplitudes em dBuV
        metadata  : dict com parametros da medicao
        """
        tr = self._trace_name(trace)

        settings = self.get_trace_settings(trace)

        raw = self.inst.query(f':TRACe:DATA? {tr}').strip()
        amp = np.array([float(v) for v in raw.split(',')])

        start = float(self.inst.query(':SENSe:FREQuency:STARt?').strip())
        stop  = float(self.inst.query(':SENSe:FREQuency:STOP?').strip())
        freq  = np.linspace(start, stop, len(amp))

        metadata = {
            'Instrumento': self.inst.query('*IDN?').strip(),
            'Trace': trace,
            'Start Frequency': start,
            'Stop Frequency':  stop,
            'Number of Points': len(amp),
            'Data da captura': datetime.now().isoformat(),
        }
        metadata.update(settings)
        return freq, amp, metadata

    def get_trace_settings(self, trace='Trace1'):
        tr = self._trace_name(trace)
        settings = {}
        queries = {
            'RBW':          ':SENSe:BANDwidth:RESolution?',
            'VBW':          ':SENSe:BANDwidth:VIDeo?',
            'Sweep Time':   ':SENSe:SWEep:TIME?',
            'Attenuation':  ':SENSe:POWer:RF:ATTenuation?',
            'Ref Level':    ':DISPlay:WINDow:TRACe:Y:SCALe:RLEVel?',
            'Average Count': ':SENSe:AVERage:COUNt?',
            'Average Type': ':SENSe:AVERage:TYPE?',
            'Trace Type':   f':TRACe{tr[-1]}:TYPE?',
        }
        for key, cmd in queries.items():
            try:
                settings[key] = self.inst.query(cmd).strip()
            except Exception:
                settings[key] = ''
        return settings

    # ------------------------------------------------------------------
    # Screen capture
    # ------------------------------------------------------------------

    def capture_screen(self):
        """Captura screenshot e retorna bytes PNG."""
        tmp = '/User/Temp/_sa_screen.png'
        self._write(f':MMEMory:STORe:SCReen "{tmp}"')
        sleep(1.0)
        data = self.inst.query_binary_values(
            f':MMEMory:DATA? "{tmp}"', datatype='B', container=bytes
        )
        try:
            self._write(f':MMEMory:DELete "{tmp}"')
        except Exception:
            pass
        return data

    # ------------------------------------------------------------------
    # Sweep control
    # ------------------------------------------------------------------

    def sweep_single(self, count=None):
        """Configura varredura unica, dispara e aguarda conclusao.

        Se count for informado, configura o numero de varreduras/averages.
        Retorna True se concluiu, False se timeout.
        """
        if count is not None:
            self.set_average(count)

        self._write(':INITiate:CONTinuous 0')
        self._write(':INITiate:RESTart')
        return self.wait_sweep()

    def wait_sweep(self, timeout=600, interval=1.0):
        """Aguarda conclusao da varredura.

        Polling do bit 3 de :STATus:OPERation:CONDition? (Sweeping).
        Retorna True quando concluido, False se timeout.
        """
        elapsed = 0.0
        while elapsed < timeout:
            sleep(interval)
            elapsed += interval
            cond = int(self.inst.query(':STATus:OPERation:CONDition?').strip())
            if cond & 8 == 0:
                return True
        return False

    def pause(self):
        self._write(':INITiate:PAUSe')

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def load_state(self, state_path):
        self._write(f':MMEMory:LOAD:STATe "{state_path}"')

    def set_freq_range(self, start_hz, stop_hz):
        self._write(f':SENSe:FREQuency:STARt {start_hz:G}')
        self._write(f':SENSe:FREQuency:STOP {stop_hz:G}')

    def set_average(self, count, avg_type='Voltage'):
        self._write(f':SENSe:AVERage:COUNt {count}')
        self._write(f':SENSe:AVERage:TYPE {avg_type}')

    # ------------------------------------------------------------------
    # CSV export (formato nativo N9010A — compativel com radiada_plot.py)
    # ------------------------------------------------------------------

    def export_csv(self, trace, path):
        """Salva trace em CSV no mesmo formato exportado pelo N9010A."""
        freq, amp, meta = self.capture_trace(trace)

        lines = []
        lines.append('Trace')
        lines.append('Swept SA')
        lines.append(f"{meta.get('Instrumento', '').split(',')[1].strip() if ',' in meta.get('Instrumento','') else ''},")
        lines.append(f"Number of Points,{len(amp)}")
        lines.append(f"Start Frequency,{freq[0]:.0f}")
        lines.append(f"Stop Frequency,{freq[-1]:.0f}")
        lines.append(f"RBW,{meta.get('RBW', '')}")
        lines.append(f"VBW,{meta.get('VBW', '')}")
        lines.append(f"Sweep Time,{meta.get('Sweep Time', '')}")
        lines.append(f"Average Count,{meta.get('Average Count', '')}")
        lines.append(f"Average Type,{meta.get('Average Type', '')}")
        lines.append(f"Attenuation,{meta.get('Attenuation', '')}")
        lines.append(f"Ref Level Offset,0")
        lines.append(f"Trace Type,{meta.get('Trace Type', '')}")
        lines.append(f"Trace Name,{trace}")
        lines.append('X Axis Units,Hz')
        lines.append('Y Axis Units,dBuV')
        lines.append('DATA')
        for f, a in zip(freq, amp):
            lines.append(f'{f:.10g},{a:.15g}')

        with open(path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines))

        print(f'CSV salvo: {path}  ({len(amp)} pontos)')

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _trace_name(self, trace):
        return TRACE_NAMES.get(trace, trace.upper())

    def _write(self, cmd):
        if self.debug:
            self.inst.write('*CLS')
            self.inst.write(cmd)
            err = self.inst.query(':SYST:ERR?').strip()
            print(f'{cmd}  =>  {err}')
        else:
            self.inst.write(cmd)

    def close(self):
        try:
            self.inst.close()
        except Exception:
            pass
