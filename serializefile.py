import os
import glob
import time
from selectcom import select_and_open_port
import subprocess
import sys
import dirHandle as dh
from datetime import datetime
import argparse

# ================= CONFIG =================
LOCAL_DIR    = "."
REMOTE_DEST  = "."
DELIMITER    = "__END_OF_LUA_837462__"
LINE_DELAY   = 0.003
BAUDRATE     = 115200
# ==========================================


def sync_datetime(ser):
    """Set the remote device clock to the current system time.

    Args:
        ser (serial.Serial): Open serial connection to the device.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"Setting date/time: {now}")
    ser.write(f'date -s "{now}"\n'.encode())
    time.sleep(0.5)
    ser.write(b'hwclock -w\n')
    time.sleep(0.5)


port = None
if len(sys.argv) == 2:
    port = sys.argv[1].upper()

print("=== SERIAL FILE DEPLOY ===\n")

ser = select_and_open_port(BAUDRATE, port)

if ser is None:
    print("Exiting.")
    exit()

sync_datetime(ser)


def send_line(cmd, delay=0.2):
    """Send a single command line over the serial connection.

    Args:
        cmd (str): Command string (newline appended automatically).
        delay (float, optional): Seconds to wait after sending.
            Defaults to ``0.2``.
    """
    ser.write((cmd + "\n").encode("utf-8"))
    time.sleep(delay)


def wait_for_prompt(timeout=5):
    """Block until a shell prompt character is received.

    Args:
        timeout (float, optional): Maximum wait in seconds. Defaults to ``5``.

    Returns:
        bool: ``True`` if a prompt (``#`` or ``$``) was detected,
            ``False`` if the timeout expired.
    """
    deadline = time.time() + timeout
    buffer = ""
    while time.time() < deadline:
        if ser.in_waiting:
            buffer += ser.read(ser.in_waiting).decode(errors="ignore")
            if "#" in buffer or "$" in buffer:
                return True
        time.sleep(0.1)
    return False


print("Searching for .lua files...\n")

files = glob.glob(os.path.join(LOCAL_DIR, "*.lua"))

if not files:
    print("No .lua files found.")
    ser.close()
    exit()

for path_file in files:
    name = os.path.basename(path_file)
    remote = f"{REMOTE_DEST}/{name}".replace("//", "/")

    print(f"Sending {name}...")

    send_line(f"rm -f {remote}", 0.1)
    send_line(f"cat > {remote} << '{DELIMITER}'", 0.2)

    with open(path_file, "r", encoding="utf-8") as f:
        content = f.read()

    content = content.rstrip("\n") + "\n"

    for line in content.splitlines(True):
        ser.write(line.encode("utf-8"))
        time.sleep(LINE_DELAY)

    send_line(DELIMITER, 0.3)

    if wait_for_prompt():
        print(f"{name} sent successfully.\n")
    else:
        print(f"⚠ Prompt not detected after sending {name}\n")

print("Transfer complete.")
serial_port = ser.port
ser.close()
time.sleep(0.5)

use_putty = "-p" in sys.argv
try:
    if use_putty:
        dh.print_colored("Opening external terminal\n", 'GREEN')
        subprocess.Popen([
            r"C:\Program Files\PuTTY\putty.exe",
            "-serial", serial_port,
            "-sercfg", f"{BAUDRATE},8,n,1,N"
        ])
    else:
        dh.print_colored("Opening serial terminal...\n", 'GREEN')
        print("#")
        subprocess.run([
            "plink", "-serial", serial_port,
            "-sercfg", f"{BAUDRATE},8,n,1,N"
        ])
except (Exception, KeyboardInterrupt):
    dh.print_colored("Terminal closed", 'RED')
