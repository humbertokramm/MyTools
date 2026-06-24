import pyvisa
import os
from time import sleep

from agilent_sa import AgilentSA


class SA:
    """Facade para analisadores de espectro, similar ao Scope para osciloscópios.

    Uso:
        sa = SA('TCPIP0::192.168.0.30::inst0::INSTR')
        sa.load_state(r'D:/State/Setup_EMC.state')
        sa.set_average(100)
        sa.sweep_single()
        freq, amp, meta = sa.capture_trace('Trace1')
        sa.export_csv('Trace1', 'eut_H.csv')
        img = sa.capture_screen()
        open('tela.png', 'wb').write(img)
        sa.close()

    Ou como context manager:
        with SA('TCPIP0::192.168.0.30::inst0::INSTR') as sa:
            ...
    """

    def __init__(self, resource=None, debug=False, overwrite=False):
        self.overwrite = overwrite
        self.inst = None
        self.rm   = None

        if resource is None:
            try:
                import detectScope as DS
                resource = DS.select_visa_resource()
            except ImportError:
                raise ValueError('resource nao informado')

        for attempt in range(3):
            try:
                self.resource = resource
                self.rm   = pyvisa.ResourceManager()
                self.inst = self.rm.open_resource(resource)
                break
            except Exception as e:
                print(f'Tentativa {attempt + 1} falhou: {e}')
                sleep(2)
                if attempt >= 2:
                    raise

        self.inst.timeout = 15000

        idn = self.inst.query('*IDN?').strip()
        print('Instrumento detectado:', idn)

        idn_upper = idn.upper()
        if any(k in idn_upper for k in ('AGILENT', 'N9010', 'N9020', 'N9030', 'HP')):
            self.driver = AgilentSA(self.inst, debug)
        else:
            raise Exception(f'Instrumento nao suportado: {idn}')

    # ------------------------------------------------------------------
    # File overwrite guard (igual ao scope.py)
    # ------------------------------------------------------------------
    def _file_exists(self, path):
        if os.path.exists(path):
            if self.overwrite:
                return False
            nome = os.path.basename(path)
            resp = input(f'"{nome}" ja existe. Sobrescrever? (s/N): ').strip().lower()
            return resp != 's'
        return False

    # ------------------------------------------------------------------
    # Delegate — trace
    # ------------------------------------------------------------------
    def capture_trace(self, trace='Trace1'):
        return self.driver.capture_trace(trace)

    def get_trace_settings(self, trace='Trace1'):
        return self.driver.get_trace_settings(trace)

    def export_csv(self, trace, path):
        path = path if path.endswith('.csv') else path + '.csv'
        if self._file_exists(path):
            return
        self.driver.export_csv(trace, path)

    # ------------------------------------------------------------------
    # Delegate — screen
    # ------------------------------------------------------------------
    def capture_screen(self, filename=None):
        data = self.driver.capture_screen()
        if filename is not None:
            filename = filename if filename.endswith('.png') else filename + '.png'
            if not self._file_exists(filename):
                with open(filename, 'wb') as f:
                    f.write(data)
                print('PNG salvo:', filename)
        return data

    # ------------------------------------------------------------------
    # Delegate — sweep control
    # ------------------------------------------------------------------
    def sweep_single(self, count=None):
        return self.driver.sweep_single(count)

    def wait_sweep(self, timeout=600, interval=1.0):
        return self.driver.wait_sweep(timeout, interval)

    def pause(self):
        self.driver.pause()

    # ------------------------------------------------------------------
    # Delegate — configuration
    # ------------------------------------------------------------------
    def load_state(self, state_path):
        self.driver.load_state(state_path)

    def set_freq_range(self, start_hz, stop_hz):
        self.driver.set_freq_range(start_hz, stop_hz)

    def set_average(self, count, avg_type='Voltage'):
        self.driver.set_average(count, avg_type)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self):
        try:
            self.driver.close()
        except Exception:
            pass
        if self.rm:
            try:
                self.rm.close()
            except Exception:
                pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
