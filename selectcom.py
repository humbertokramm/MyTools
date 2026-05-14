import serial
import serial.tools.list_ports
import time

DEFAULT_BAUDRATE = 115200


def list_ports(silent=False, port=None):
    """List available serial ports.

    Args:
        silent (bool, optional): If ``True``, return the port list without
            printing. Defaults to ``False``.
        port (str, optional): If given, mark the matching port as the
            auto-selected choice. Defaults to ``None``.

    Returns:
        list or tuple: Port list when *silent* is ``True``;
            ``(ports, match_index)`` otherwise.
    """
    ports = list(serial.tools.list_ports.comports())
    if silent:
        return ports

    if not ports:
        print("No serial port found.")
        return []

    print("\nAvailable serial ports:\n")
    match = None
    for i, p in enumerate(ports):
        print(f"     {i} -> {p.device}\t{p.description}", end="\t")
        print(f"Brand: {p.manufacturer}")
        if port == p.device:
            match = i

    return ports, match


def open_port(port, baudrate=DEFAULT_BAUDRATE):
    """Open a serial port.

    Args:
        port (str): Port name (e.g. ``'COM3'``).
        baudrate (int, optional): Baud rate. Defaults to
            :data:`DEFAULT_BAUDRATE`.

    Returns:
        serial.Serial or None: Open serial object, or ``None`` on failure.
    """
    try:
        ser = serial.Serial(port, baudrate, timeout=1)
        time.sleep(2)
        return ser
    except serial.SerialException as e:
        msg = str(e)
        if "PermissionError" in msg or "Acesso negado" in msg:
            print(f"\n⚠  Port {port} is in use by another program.")
            print("Close the program using the port and try again.\n")
        else:
            print(f"\n⚠  Could not open {port}")
            print(f"Error: {e}\n")
        return None


def select_and_open_port(baudrate=DEFAULT_BAUDRATE, port=None):
    """Interactively select and open a serial port.

    Args:
        baudrate (int, optional): Baud rate. Defaults to
            :data:`DEFAULT_BAUDRATE`.
        port (str, optional): Pre-selected port name; skips the prompt if
            found. Defaults to ``None``.

    Returns:
        serial.Serial or None: Open serial object, or ``None`` if the user
            cancels or no ports are available.
    """
    while True:
        ports, match = list_ports(port=port)

        if not ports:
            return None

        try:
            choice = match if match is not None else int(input("Select port number: "))
            if 0 <= choice < len(ports):
                device = ports[choice].device
                ser = open_port(device, baudrate)
                if ser:
                    print(f"\n✅ Port {device} opened successfully!\n")
                    return ser
                else:
                    again = input("Try another port? (y/n): ").lower()
                    if again != "y":
                        return None
            else:
                print("Invalid number.\n")
        except ValueError:
            print("Enter a valid number.\n")
