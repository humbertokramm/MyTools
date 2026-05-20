import pyvisa
import csv
import detectScope as DS
import os
import dirHandle as dh
from time import sleep

from tektronix import TektronixScope
from tektronix_net import TektronixNetScope
from keysight import KeysightScope
from scope_ssh import SshScope

class Scope:

    def __init__(self, resource=None, debug=False, overwrite=False):
        self.overwrite = overwrite
        self.inst = None
        self.rm = None

        # -------------------------------------------------
        # SSH connection (oscilloscope on a remote Linux host)
        # resource format: "SSH::user@host[::VISA_RESOURCE]"
        # -------------------------------------------------
        if resource is not None and resource.upper().startswith("SSH::"):
            self.resource = resource
            self.driver   = SshScope.from_resource_string(resource, debug)
            return

        # -------------------------------------------------
        # HTTP connection (TDS3052B or similar)
        # resource format: "HTTP::192.168.1.100"
        # -------------------------------------------------
        if resource is not None and resource.upper().startswith("HTTP::"):
            ip = resource.split("::", 1)[1]
            self.resource = resource
            self.driver = TektronixNetScope(ip, debug)
            print(f"HTTP connection established: {ip}")
            return

        # -------------------------------------------------
        # detect resource automatically (VISA)
        # -------------------------------------------------
        if resource is None:
            resource = DS.select_visa_resource()

            if resource is None or "USB" not in resource:
                print("Invalid instrument!!")
                exit()
            else:
                print(f"resource = {resource}")

        # -------------------------------------------------
        # connect VISA
        # -------------------------------------------------
        for attempt in range(3):
            try:
                self.resource = resource
                self.rm = pyvisa.ResourceManager()
                self.inst = self.rm.open_resource(resource)
                break
            except Exception:
                dh.print_colored(f"Connection attempt {attempt + 1} failed:", 'RED')
                print(f'RESOURCE = "{resource}"')
                sleep(2)
                if attempt > 1:
                    exit()

        self.inst.timeout = 10000

        idn = self.inst.query("*IDN?")
        print("Instrument detected:", idn)

        # -------------------------------------------------
        # select driver
        # -------------------------------------------------

        if "TEKTRONIX" in idn.upper():
            self.driver = TektronixScope(self.inst, debug)

        elif "KEYSIGHT" in idn.upper() or "AGILENT" in idn.upper():
            self.driver = KeysightScope(self.inst, debug)

        else:
            raise Exception("Unsupported instrument")
            
    # ---------------------------------------------------------
    # file overwrite guard
    # ---------------------------------------------------------
    def _file_exists(self, caminho_arquivo):
        if os.path.exists(caminho_arquivo):
            if self.overwrite:
                return False   # Sobrescreve direto sem perguntar
            nome = os.path.basename(caminho_arquivo)
            resposta = input(f'O arquivo "{nome}" já existe. \n\tDeseja sobrescrever? (s/N): ').strip().lower()

            if resposta == 's':
                return False   # Pode sobrescrever
            else:
                return True    # Não sobrescrever
        else:
            return False       # Arquivo não existe, pode continuar normalmente
        
    # ---------------------------------------------------------
    # waveform capture
    # ---------------------------------------------------------
    def capture_waveform(self, channel, filename):
        filename += ".csv"
        if self._file_exists(filename):
            return
        try: 
            time, voltage, metadata = self.driver.capture_waveform(channel)
        except RuntimeError as e:
            dh.print_colored(e,'RED')
            return None, None, None
        
        with open(filename, "w") as f:

            for k, v in metadata.items():
                f.write(f"# {k}: {v}\n")

            f.write("Time,Voltage\n")

            for t, v in zip(time, voltage):
                f.write(f"{t},{v}\n")

        print("CSV saved:", filename)
        
        
    # ---------------------------------------------------------
    # screenshot
    # ---------------------------------------------------------
    def capture_screen(self, filename,ch,info=False):
        
        self.driver.set_channel_settings(ch,info)
        
        filename += "-screen.png"
        if self._file_exists(filename):
            return
        data = self.driver.capture_screen()

        if data is None:
            dh.print_colored("Screenshot not available for this instrument.", 'YELLOW')
            return

        with open(filename, "wb") as f:
            f.write(data)

        print("Screenshot saved:", filename)

    # ---------------------------------------------------------
    # connection
    # ---------------------------------------------------------
    def close(self):
        if self.inst is not None:
            self.inst.close()
        if self.rm is not None:
            self.rm.close()
        if hasattr(self, 'driver') and hasattr(self.driver, 'close'):
            self.driver.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    # ---------------------------------------------------------
    # HIGH LEVEL CAPTURE
    # ---------------------------------------------------------

    @staticmethod
    def main(file, resource=None, channel="CH1", screenshot=True,
             info=False, debug=False, overwrite=False, scope=None):
        """Capture waveform and optional screenshot.

        Args:
            scope (Scope, optional): Existing Scope instance to reuse.
                When provided the connection is NOT closed after capture —
                the caller is responsible for calling scope.close() (or
                using the 'with Scope(...) as scope:' pattern).
                When omitted a new connection is opened and closed
                automatically after each call.
        """
        owned = scope is None
        if owned:
            scope = Scope(resource, debug, overwrite)

        if isinstance(channel, str):
            channel = [channel]

        try:
            for ch in channel:
                scope.capture_waveform(ch, file)

            if screenshot:
                scope.capture_screen(file, channel[0], info)

        finally:
            if owned:
                scope.close()