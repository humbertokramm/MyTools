import pyvisa
import csv
import detectScope as DS
import os

from tektronix import TektronixScope
from keysight import KeysightScope

class Scope:

    def __init__(self, resource=None):
        # -------------------------------------------------
        # detect resource automatically
        # -------------------------------------------------
        if resource is None:

            resource = DS.select_visa_resource()

            if resource is None or "USB" not in resource:
                print("Invalid instrument!!")
                exit()
            else:
                print(f"resource = {resource}")

        self.resource = resource

        # -------------------------------------------------
        # connect VISA
        # -------------------------------------------------

        self.rm = pyvisa.ResourceManager()
        self.inst = self.rm.open_resource(resource)

        self.inst.timeout = 10000

        idn = self.inst.query("*IDN?")
        print("Instrument detected:", idn)

        # -------------------------------------------------
        # select driver
        # -------------------------------------------------

        if "TEKTRONIX" in idn.upper():
            self.driver = TektronixScope(self.inst)

        elif "KEYSIGHT" in idn.upper() or "AGILENT" in idn.upper():
            self.driver = KeysightScope(self.inst)

        else:
            raise Exception("Unsupported instrument")
            
    # ---------------------------------------------------------
    # Verifica se já existe o arquivo
    # ---------------------------------------------------------
    def checkExistentFile(self,caminho_arquivo):
        if os.path.exists(caminho_arquivo):
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
        if self.checkExistentFile(filename):
            return
        time, voltage, metadata = self.driver.capture_waveform(channel)

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
        if self.checkExistentFile(filename):
            return
        data = self.driver.capture_screen()

        with open(filename, "wb") as f:
            f.write(data)

        print("Screenshot saved:", filename)

    # ---------------------------------------------------------
    # connection
    # ---------------------------------------------------------
    def close(self):

        self.inst.close()
        self.rm.close()
    
    # ---------------------------------------------------------
    # HIGH LEVEL CAPTURE
    # ---------------------------------------------------------

    @staticmethod
    def main(file, resource, channel="CH1", screenshot=True,info=False):
        scope = Scope(resource)

        if isinstance(channel, str):
            channel = [channel]

        try:
            for ch in channel:
                scope.capture_waveform(ch, file)

            if screenshot:
                scope.capture_screen(file,ch,info)

        finally:
            scope.close()