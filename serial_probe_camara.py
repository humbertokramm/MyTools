#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sondagem da porta serial da camara CSZ Z-32 Plus (controlador Synergy).
Roda no PC Linux ligado por cabo RS-232 (null-modem) ao controlador.

Testa dois protocolos em varias combinacoes de baud/paridade:
  1) ASCII nativo do Synergy   -> comando "? C1" (le canal 1 / temperatura)
  2) Modbus RTU                -> le holding register 40103 (PV, em Kelvin x10)

Uso:
    python3 serial_probe_camara.py /dev/ttyUSB0

Requisito: pyserial  (pip install pyserial)
"""
import sys, time

try:
    import serial  # pyserial
except ImportError:
    sys.exit("Falta pyserial. Instale com: pip install pyserial")

PORT = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"

def crc16(data):
    crc = 0xFFFF
    for b in bytearray(data):
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc

def open_port(baud, parity):
    return serial.Serial(PORT, baudrate=baud, bytesize=8,
                         parity=parity, stopbits=1, timeout=1.5)

def try_ascii(baud, parity):
    tag = "ASCII '? C1' @ %d/%s" % (baud, parity)
    try:
        s = open_port(baud, parity)
        s.reset_input_buffer()
        s.write(b"? C1\r\n")
        time.sleep(0.4)
        resp = s.read(256)
        s.close()
        if resp:
            print("  [OK ] %-24s -> %r" % (tag, resp))
            return True
        print("  [   ] %-24s -> (sem resposta)" % tag)
    except Exception as e:
        print("  [ERR] %-24s -> %s" % (tag, e))
    return False

def try_modbus(baud, parity, unit=1, reg=40103):
    tag = "Modbus reg%d @ %d/%s" % (reg, baud, parity)
    addr = reg - 40001
    frame = bytes(bytearray([unit, 3, (addr >> 8) & 0xFF, addr & 0xFF, 0, 1]))
    frame += bytes(bytearray([crc16(frame) & 0xFF, (crc16(frame) >> 8) & 0xFF]))
    try:
        s = open_port(baud, parity)
        s.reset_input_buffer()
        s.write(frame)
        time.sleep(0.4)
        resp = s.read(256)
        s.close()
        if resp and len(resp) >= 5 and resp[1] == 3:
            raw = (resp[3] << 8) | resp[4]
            c = raw / 10.0 - 273.15
            print("  [OK ] %-24s -> raw=%d  =>  %.2f C" % (tag, raw, c))
            return True
        elif resp:
            print("  [OK?] %-24s -> %r (resposta inesperada)" % (tag, resp))
            return True
        print("  [   ] %-24s -> (sem resposta)" % tag)
    except Exception as e:
        print("  [ERR] %-24s -> %s" % (tag, e))
    return False

def main():
    print("Sondando porta %s ...\n" % PORT)
    P = serial.PARITY_NONE
    E = serial.PARITY_EVEN

    print("== Protocolo ASCII (RS-232 nativo Synergy) ==")
    for baud in (19200, 9600):
        try_ascii(baud, P)

    print("\n== Protocolo Modbus RTU ==")
    for baud in (9600, 19200):
        for par in (E, P):
            try_modbus(baud, par)

    print("\nPronto. Linha marcada [OK] indica o protocolo/velocidade que funciona.")
    print("Com isso eu finalizo o logger definitivo.")

if __name__ == "__main__":
    main()
