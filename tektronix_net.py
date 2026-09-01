import numpy as np
import pandas as pd
import requests
import time
from datetime import datetime

"""
Driver for Tektronix TDS3052B via HTTP (web interface).

Connection string format used in scope.py:
    resource = "HTTP::192.168.1.100"

The TDS3052B exposes a waveform endpoint at:
    POST http://{ip}/getwfm.isf
    body: command=select:{channel} on\\r\\n & wfmsend=Get

Each channel capture takes approximately 25 seconds.

NOTE: This driver was ported from legacy code and has not been validated
      against a physical instrument. Treat as a starting point.
"""


class TektronixNetScope:
    """Tektronix TDS3052B driver using the built-in HTTP interface.

    Follows the same interface as :class:`TektronixScope` so that
    :class:`Scope` can route to it transparently.

    Args:
        ip (str): IP address of the instrument (e.g. ``'192.168.1.100'``).
        debug (bool, optional): If ``True``, print each request and response.
            Defaults to ``False``.
    """

    def __init__(self, ip, debug=False):
        self.ip = ip
        self.debug = debug
        self._base_url = f"http://{ip}"

    # ---------------------------------------------------------
    # WAVEFORM
    # ---------------------------------------------------------
    def capture_waveform(self, channel):
        """Capture a waveform from *channel* via HTTP POST.

        Args:
            channel (str): Channel name, e.g. ``'CH1'``, ``'CH2'``.

        Returns:
            tuple: ``(time_array, voltage_array, metadata)``

                - *time_array* – :class:`numpy.ndarray` of time values in seconds.
                - *voltage_array* – :class:`numpy.ndarray` of voltage values in volts.
                - *metadata* – dict with instrument info and capture timestamp.

        Note:
            Each call takes approximately 25 seconds — the instrument streams
            the full acquisition buffer over HTTP.
        """
        ch = channel.lower()
        url = f"{self._base_url}/getwfm.isf"

        if self.debug:
            print(f"POST {url}  channel={ch}")

        start = time.time()
        response = requests.post(
            url,
            data={"command": f"select:{ch} on\r\n", "wfmsend": "Get"},
            headers={"Content-Type": "text/plain"},
        )
        elapsed = round(time.time() - start, 2)

        if self.debug:
            print(f"  => {response.status_code}  ({elapsed} s)")

        # Parse response: each line is "time,voltage"
        rows = [
            line.split(",")
            for line in response.text.split("\r\n")
            if "," in line
        ]
        df = pd.DataFrame(rows, columns=["t", "v"])
        df = df.apply(pd.to_numeric, errors="coerce").dropna()

        time_arr    = df["t"].to_numpy()
        voltage_arr = df["v"].to_numpy()

        metadata = {
            "Instrumento": f"TEKTRONIX,TDS3052B,{self.ip}",
            "Canal": channel,
            "Sample Rate (calculado)": (
                1 / (time_arr[1] - time_arr[0]) if len(time_arr) > 1 else None
            ),
            "Record Length": len(time_arr),
            "Data da captura": datetime.now().isoformat(),
            "Tempo de captura (s)": elapsed,
        }

        return time_arr, voltage_arr, metadata

    # ---------------------------------------------------------
    # SCREEN
    # ---------------------------------------------------------
    def capture_screen(self):
        """Capture a screenshot from the instrument.

        Returns:
            bytes: PNG image data, or ``None`` if the endpoint is unavailable.

        Note:
            The TDS3052B HTTP interface may not expose a PNG screenshot
            endpoint on all firmware versions. Returns ``None`` in that case.
        """
        url = f"{self._base_url}/image.png"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                return response.content
        except requests.RequestException as e:
            if self.debug:
                print(f"capture_screen failed: {e}")
        return None

    # ---------------------------------------------------------
    # SETTINGS (stubs — HTTP interface does not expose these)
    # ---------------------------------------------------------
    def set_channel_settings(self, channel, info):
        """No-op: HTTP interface does not support remote configuration.

        Args:
            channel (str): Ignored.
            info (dict): Ignored.
        """
        if self.debug:
            print("set_channel_settings: not supported over HTTP")

    def get_channel_settings(self, channel):
        """Return an empty dict — settings not available via HTTP.

        Args:
            channel (str): Ignored.

        Returns:
            dict: Empty dict.
        """
        return {}

    # ---------------------------------------------------------
    # TRIGGER CONTROL (stubs — HTTP interface does not expose these)
    # ---------------------------------------------------------
    def monitor_single(self, max_wait=3600, retry_timeout=30, interval=0.5):
        """Not supported over HTTP — returns False immediately."""
        if self.debug:
            print("monitor_single: not supported over HTTP")
        return False

    def set_timebase(self, scale=None, position=None, reference=None):
        """No-op: timebase control not supported over HTTP."""
        if self.debug:
            print("set_timebase: not supported over HTTP")

    def set_trigger(self, channel='CH1', level=0.0, slope='rise', mode='NORMal'):
        """No-op: trigger control not supported over HTTP."""
        if self.debug:
            print("set_trigger: not supported over HTTP")

    def single(self):
        """No-op: trigger control not supported over HTTP."""
        if self.debug:
            print("single: not supported over HTTP")

    def wait_single(self, timeout=30, interval=0.5):
        """Not supported over HTTP — returns False immediately."""
        if self.debug:
            print("wait_single: not supported over HTTP")
        return False

    def stop(self):
        """No-op: trigger control not supported over HTTP."""
        if self.debug:
            print("stop: not supported over HTTP")
