"""
SSH-transparent scope driver.

Connects to a remote Linux host via SSH (paramiko), executes a self-contained
Python capture script on the remote interpreter, and returns the data locally.

Resource format (used in scope.py):
    "SSH::user@host"                          # auto-detect VISA resource
    "SSH::user@host::USB::0x0699::..."        # explicit VISA resource
    "SSH::user@host:2222"                     # custom SSH port
    "SSH::user@host:2222::USB::..."           # port + explicit VISA resource

Authentication:
    paramiko uses the system SSH agent and ~/.ssh/id_* keys automatically.
    Pass password='...' to SshScope.__init__ for password authentication.

Requirements on the remote Linux host:
    python3, pyvisa, numpy
"""
from __future__ import annotations

import base64
import json

import numpy as np


# ──────────────────────────────────────────────────────────────────────────────
# Remote script templates (executed on the Linux host via paramiko stdin)
#
# Variables injected at the top by _build_script():
#   _resource  — VISA resource string or 'auto'
#   _channel   — e.g. 'CH1'
#   _info      — dict with cursor/label/meas settings (screen script only)
# ──────────────────────────────────────────────────────────────────────────────

_WAVEFORM_TEMPLATE = r'''
import json, sys
import pyvisa
import numpy as np
from datetime import datetime

rm = pyvisa.ResourceManager(_backend)

def _open_inst(rm, resource, timeout=30000):
    """Open resource, falling back to auto-detect if not found."""
    if resource != 'auto':
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout
            return inst
        except Exception:
            pass  # serial number not found — try auto-detect
    resources = rm.list_resources()
    candidates = [r for r in resources if r.startswith('USB') or r.startswith('GPIB')]
    if not candidates:
        print(json.dumps({'error': 'no instrument found', 'resources': list(resources)}))
        sys.exit(1)
    inst = rm.open_resource(candidates[0])
    inst.timeout = timeout
    return inst

inst = _open_inst(rm, _resource)
inst.timeout = 30000
idn = inst.query('*IDN?').strip()

try:
    # ── Tektronix ─────────────────────────────────────────────────────────────
    if 'TEKTRONIX' in idn.upper():
        inst.write(f'DATA:SOURCE {_channel}')
        inst.write('DATA:WIDTH 1')
        inst.write('DATA:ENC RPB')
        inst.write('DATA:RESOLUTION REDUCED')
        inst.write('DATA:START 1')
        inst.write('DATA:STOP 10000')

        ymult = float(inst.query('WFMPRE:YMULT?'))
        yzero = float(inst.query('WFMPRE:YZERO?'))
        yoff  = float(inst.query('WFMPRE:YOFF?'))
        xincr = float(inst.query('WFMPRE:XINCR?'))
        xzero = float(inst.query('WFMPRE:XZERO?'))

        coupling = inst.query(f'{_channel}:COUPling?').strip()
        scale    = inst.query(f'{_channel}:SCAle?').strip()
        bw       = inst.query(f'{_channel}:BANDwidth?').strip()
        probe    = inst.query(f'{_channel}:PROBe?').strip()

        raw     = inst.query_binary_values('CURVE?', datatype='B', container=list)
        raw     = np.array(raw, dtype=float)
        voltage = (raw - yoff) * ymult + yzero
        t_arr   = np.arange(len(voltage)) * xincr + xzero

        result = {
            'time'    : t_arr.tolist(),
            'voltage' : voltage.tolist(),
            'metadata': {
                'Instrumento'           : idn,
                'Canal'                 : _channel,
                'Sample Rate (calculado)': 1 / xincr,
                'Record Length'         : len(raw),
                'Data da captura'       : datetime.now().isoformat(),
                'coupling'              : coupling,
                'vertical_scale'        : f'{scale} V/div',
                'BW'                    : bw,
            },
        }

    # ── Keysight / Agilent ────────────────────────────────────────────────────
    elif 'KEYSIGHT' in idn.upper() or 'AGILENT' in idn.upper():
        ch = _channel.replace('CH', 'CHAN')   # CH1 → CHAN1
        inst.write(f':WAV:SOUR {ch}')
        inst.write(':WAV:FORM BYTE')
        inst.write(':WAV:UNS ON')
        inst.write(':WAV:POIN:MODE MAX')

        pre   = inst.query(':WAV:PRE?').split(',')
        xincr = float(pre[4])
        xorig = float(pre[5])
        xref  = float(pre[6])
        yincr = float(pre[7])
        yorig = float(pre[8])
        yref  = float(pre[9])

        raw     = inst.query_binary_values(':WAV:DATA?', datatype='B', container=list)
        raw     = np.array(raw, dtype=float)
        voltage = (raw - yref - yorig) * yincr
        t_arr   = (np.arange(len(raw)) - xref) * xincr + xorig

        result = {
            'time'    : t_arr.tolist(),
            'voltage' : voltage.tolist(),
            'metadata': {
                'Instrumento'           : idn,
                'Canal'                 : _channel,
                'Sample Rate (calculado)': 1 / xincr if xincr else None,
                'Record Length'         : len(raw),
                'Data da captura'       : datetime.now().isoformat(),
            },
        }

    else:
        print(json.dumps({'error': f'unsupported instrument: {idn}'}))
        sys.exit(1)

    result['resource'] = _resource
    print(json.dumps(result))
finally:
    inst.close()
    rm.close()
'''

_SCREEN_TEMPLATE = r'''
import json, sys, base64, time
import pyvisa
from datetime import datetime

rm = pyvisa.ResourceManager(_backend)

def _open_inst(rm, resource, timeout=30000):
    if resource != 'auto':
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout
            return inst
        except Exception:
            pass
    resources = rm.list_resources()
    candidates = [r for r in resources if r.startswith('USB') or r.startswith('GPIB')]
    if not candidates:
        print(json.dumps({'error': 'no instrument found'}))
        sys.exit(1)
    inst = rm.open_resource(candidates[0])
    inst.timeout = timeout
    return inst

inst = _open_inst(rm, _resource)
inst.timeout = 30000
idn = inst.query('*IDN?').strip()
delay = 0.2

try:
    # ── Tektronix ─────────────────────────────────────────────────────────────
    if 'TEKTRONIX' in idn.upper():
        ch = _channel.replace('CH', '')
        now = datetime.now()
        inst.write(f':DATE "{now.strftime("%Y-%m-%d")}"')
        time.sleep(delay)
        inst.write(f':TIME "{now.strftime("%H:%M:%S")}"')
        time.sleep(delay)

        if _info and 'label' in _info:
            inst.write(f':CH{ch}:LAB "{_info["label"]}"')
            time.sleep(delay)
            inst.write(f':CH{ch}:LAB:STATE ON')
            time.sleep(delay)

        if _info and 'cursor' in _info:
            cursor = {k.lower(): v for k, v in _info['cursor'].items()}
            has_y  = 'y1' in cursor or 'y2' in cursor
            has_x  = 'x1' in cursor or 'x2' in cursor
            inst.write(':CURSOR:STATE ON')
            if has_y and not has_x:
                inst.write(':CURSOR:FUNCTION HBARS')
                inst.write(':CURSOR:HBARS:UNITS BASE')
                inst.write(f':CURSOR:HBARS:SOURCE1 CH{ch}')
                if 'y1' in cursor: inst.write(f':CURSOR:HBARS:POSITION1 {cursor["y1"]}')
                if 'y2' in cursor: inst.write(f':CURSOR:HBARS:POSITION2 {cursor["y2"]}')
            elif has_x and not has_y:
                inst.write(':CURSOR:FUNCTION VBARS')
                inst.write(':CURSOR:VBARS:UNITS SECONDS')
                inst.write(f':CURSOR:VBARS:SOURCE1 CH{ch}')
                if 'x1' in cursor: inst.write(f':CURSOR:VBARS:POSITION1 {cursor["x1"]}')
                if 'x2' in cursor: inst.write(f':CURSOR:VBARS:POSITION2 {cursor["x2"]}')
            else:
                inst.write(':CURSOR:FUNCTION SCREEN')
                inst.write(':CURSOR:HBARS:UNITS BASE')
                inst.write(f':CURSOR:HBARS:SOURCE1 CH{ch}')
                if 'y1' in cursor: inst.write(f':CURSOR:HBARS:POSITION1 {cursor["y1"]}')
                if 'y2' in cursor: inst.write(f':CURSOR:HBARS:POSITION2 {cursor["y2"]}')
                inst.write(':CURSOR:VBARS:UNITS SECONDS')
                if 'x1' in cursor: inst.write(f':CURSOR:VBARS:POSITION1 {cursor["x1"]}')
                if 'x2' in cursor: inst.write(f':CURSOR:VBARS:POSITION2 {cursor["x2"]}')

        if _info and 'meas' in _info:
            for i, v in enumerate(_info['meas'], start=1):
                if i > 4:
                    break
                if v is None:
                    inst.write(f'MEASU:MEAS{i}:STATE OFF')
                elif v:
                    _MEAS_MAP = {
                        'Vmax': 'MAXimum', 'Vmin': 'MINImum', 'Vpp': 'PK2pk',
                        'Vamp': 'AMPlitude', 'Vtop': 'HIGH', 'Vbase': 'LOW',
                        'Vavg': 'MEAN', 'Vrms': 'RMS', 'Frequency': 'FREQuency',
                        'Period': 'PERIod', 'RiseTime': 'RISe', 'FallTime': 'FALL',
                    }
                    mtype = _MEAS_MAP.get(v, v)
                    inst.write(f'MEASU:MEAS{i}:STATE ON')
                    time.sleep(delay)
                    inst.write(f':MEASU:MEAS{i}:SOURCE1 CH{ch}')
                    time.sleep(delay)
                    inst.write(f':MEASU:MEAS{i}:TYPE {mtype}')
                time.sleep(delay)

        inst.write('HARDCopy:FORMat PNG')
        inst.write('HARDCopy STARt')
        raw = inst.read_raw()

        if raw[0:1] == b'#':
            hlen = int(raw[1:2])
            dlen = int(raw[2:2+hlen])
            raw  = raw[2+hlen:2+hlen+dlen]

        print(json.dumps({'png': base64.b64encode(raw).decode()}))

    # ── Keysight / Agilent ──────────────────────────────────────────────────────
    elif 'KEYSIGHT' in idn.upper() or 'AGILENT' in idn.upper():
        ch = _channel.replace('CH', 'CHAN')   # CH1 → CHAN1

        if _info and 'label' in _info:
            inst.write(f':{ch}:LABel "{_info["label"]}"')
            time.sleep(delay)
            inst.write(':DISPlay:LABel ON')
            time.sleep(delay)

        if _info and 'meas' in _info:
            _MEAS_MAP = {
                'Vmax': 'VMAX', 'Vmin': 'VMIN', 'Vpp': 'VPP',
                'Vamp': 'VAMPlitude', 'Vtop': 'VTOP', 'Vbase': 'VBASe',
                'Vavg': 'VAVerage', 'Vrms': 'VRMS', 'Frequency': 'FREQuency',
                'Period': 'PERiod', 'RiseTime': 'RISetime', 'FallTime': 'FALLtime',
            }
            for v in _info['meas']:
                if v:
                    mtype = _MEAS_MAP.get(v, v)
                    inst.write(f':MEASure:{mtype} {ch}')
                    time.sleep(delay)

        # InfiniiVision: :DISPlay:DATA? <format>,<palette>
        raw = inst.query_binary_values(':DISPlay:DATA? PNG,COLor',
                                       datatype='B', container=bytes)
        print(json.dumps({'png': base64.b64encode(raw).decode()}))

    else:
        print(json.dumps({'error': f'screenshot not implemented for: {idn}'}))
        sys.exit(1)

finally:
    inst.close()
    rm.close()
'''

_MONITOR_TEMPLATE = r'''
import json, sys, time
import pyvisa


rm = pyvisa.ResourceManager(_backend)

def _open_inst(rm, resource, timeout=5000):
    if resource != 'auto':
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout
            return inst
        except Exception:
            pass
    resources = rm.list_resources()
    candidates = [r for r in resources if r.startswith('USB') or r.startswith('GPIB')]
    if not candidates:
        print(json.dumps({'error': 'no instrument found'}))
        sys.exit(1)
    inst = rm.open_resource(candidates[0])
    inst.timeout = timeout
    return inst

inst = _open_inst(rm, _resource)
idn  = inst.query('*IDN?').strip().upper()

elapsed_total = 0.0
done          = False

def _arm(inst, idn):
    if 'TEKTRONIX' in idn:
        inst.write('ACQuire:STOPAfter SEQuence')
        inst.write('ACQuire:STATE RUN')
    elif 'KEYSIGHT' in idn or 'AGILENT' in idn:
        inst.write(':SINGle')

def _is_done(inst, idn):
    if 'TEKTRONIX' in idn:
        return inst.query('ACQuire:STATE?').strip() == '0'
    elif 'KEYSIGHT' in idn or 'AGILENT' in idn:
        return int(inst.query(':OPERegister:CONDition?').strip()) & 8 == 0
    return False

try:
    _arm(inst, idn)
    while elapsed_total < _max_wait:
        elapsed = 0.0
        while elapsed < _retry_timeout:
            time.sleep(_interval)
            elapsed += _interval
            if _is_done(inst, idn):
                done = True
                break
        if done:
            break
        elapsed_total += elapsed
        _arm(inst, idn)  # re-arm for next attempt
finally:
    inst.close()
    rm.close()

print(json.dumps({'triggered': done, 'elapsed': round(elapsed_total, 2)}))
'''

_WAIT_TEMPLATE = r'''
import json, sys, time
import pyvisa

rm = pyvisa.ResourceManager(_backend)

def _open_inst(rm, resource, timeout=5000):
    if resource != 'auto':
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout
            return inst
        except Exception:
            pass
    resources = rm.list_resources()
    candidates = [r for r in resources if r.startswith('USB') or r.startswith('GPIB')]
    if not candidates:
        print(json.dumps({'error': 'no instrument found'}))
        sys.exit(1)
    inst = rm.open_resource(candidates[0])
    inst.timeout = timeout
    return inst

inst = _open_inst(rm, _resource)
inst.timeout = 5000
idn = inst.query('*IDN?').strip().upper()

elapsed = 0.0
done    = False

try:
    while elapsed < _timeout:
        time.sleep(_interval)
        elapsed += _interval
        if 'TEKTRONIX' in idn:
            if inst.query('ACQuire:STATE?').strip() == '0':
                done = True
                break
        elif 'KEYSIGHT' in idn or 'AGILENT' in idn:
            cond = int(inst.query(':OPERegister:CONDition?').strip())
            if cond & 8 == 0:
                done = True
                break
finally:
    inst.close()
    rm.close()

print(json.dumps({'triggered': done, 'elapsed': round(elapsed, 2)}))
'''

_SCPI_TEMPLATE = r'''
import json, sys
import pyvisa

rm = pyvisa.ResourceManager(_backend)

def _open_inst(rm, resource, timeout=10000):
    if resource != 'auto':
        try:
            inst = rm.open_resource(resource)
            inst.timeout = timeout
            return inst
        except Exception:
            pass
    resources = rm.list_resources()
    candidates = [r for r in resources if r.startswith('USB') or r.startswith('GPIB')]
    if not candidates:
        print(json.dumps({'error': 'no instrument found'}))
        sys.exit(1)
    inst = rm.open_resource(candidates[0])
    inst.timeout = timeout
    return inst

inst = _open_inst(rm, _resource)
inst.timeout = 10000
idn = inst.query('*IDN?').strip().upper()

try:
    commands = []
    for brand, cmds in _commands.items():
        if brand.upper() in idn:
            commands = cmds
            break

    for cmd in commands:
        inst.write(cmd)
finally:
    inst.close()
    rm.close()

print(json.dumps({'ok': True}))
'''


# ──────────────────────────────────────────────────────────────────────────────
# Driver class
# ──────────────────────────────────────────────────────────────────────────────

class SshScope:
    """Oscilloscope driver that tunnels pyvisa commands over SSH.

    Sends self-contained Python scripts to the remote host via paramiko,
    executes them with the remote ``python3`` interpreter, and retrieves
    waveform data (JSON) or screenshots (base64-encoded PNG in JSON).

    Args:
        host     (str): Remote hostname or IP address.
        user     (str): SSH username.
        visa_resource (str): VISA resource on the remote host, or ``'auto'``
            to detect the first USB/GPIB instrument automatically.
        port     (int): SSH port. Default ``22``.
        password (str, optional): SSH password. Leave ``None`` to use key
            authentication (system SSH agent / ``~/.ssh/id_*``).
        debug    (bool): Print SSH stderr output. Default ``False``.
        visa_backend (str): pyvisa backend used on the remote host.
            ``'@py'`` (default) uses pyvisa-py — talks USBTMC directly via
            pyusb, no NI-VISA / nipalk.ko needed. Use ``''`` to let the
            remote pyvisa pick its default (e.g. NI-VISA).
    """

    def __init__(
        self,
        host:          str,
        user:          str,
        visa_resource: str  = 'auto',
        port:          int  = 22,
        password:      str  = None,
        debug:         bool = False,
        visa_backend:  str  = '@py',
    ):
        try:
            import paramiko
        except ImportError:
            raise ImportError(
                "paramiko is required for SSH connections.\n"
                "Install it with:  pip install paramiko"
            )

        self.host          = host
        self.user          = user
        self.visa_resource = visa_resource
        self.visa_backend  = visa_backend
        self.debug         = debug

        # Pending display settings (set by set_channel_settings, consumed by capture_screen)
        self._pending_channel = None
        self._pending_info    = None

        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # Try key authentication first; fall back to password prompt if it fails.
        try:
            self._ssh.connect(host, port=port, username=user,
                              password=password, look_for_keys=True, allow_agent=True)
        except paramiko.AuthenticationException:
            import getpass
            password = getpass.getpass(f"SSH password for {user}@{host}: ")
            self._ssh.connect(host, port=port, username=user,
                              password=password, look_for_keys=False, allow_agent=False)

        # Keep the SSH session alive during long waits (e.g. monitor_single).
        # Sends a keepalive packet every 60 s to prevent idle timeout.
        self._ssh.get_transport().set_keepalive(60)

        print(f"SSH connection established: {user}@{host}:{port}")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _build_script(self, template: str, **kwargs) -> str:
        """Prepend variable assignments to a template script.

        Each keyword argument becomes a Python assignment at the top of the
        generated script, using ``repr()`` for safe serialisation::

            _backend  = '@py'
            _resource = 'USB::0x0699::...'
            _channel  = 'CH1'

        The VISA backend (``_backend``) is injected automatically from
        ``self.visa_backend`` so every remote script uses the same backend.
        """
        kwargs.setdefault('backend', self.visa_backend)
        lines = [f'_{k} = {v!r}' for k, v in kwargs.items()]
        return '\n'.join(lines) + '\n' + template

    def _run_script(self, script: str) -> dict:
        """Send *script* to the remote ``python3`` via stdin and parse JSON stdout.

        Args:
            script (str): Complete Python source code to execute remotely.

        Returns:
            dict: Parsed JSON response from the remote script.

        Raises:
            RuntimeError: If the remote script writes to stderr or the output
                cannot be parsed as JSON.
        """
        stdin, stdout, stderr = self._ssh.exec_command('python3')
        stdin.write(script.encode())
        stdin.channel.shutdown_write()

        try:
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
        except KeyboardInterrupt:
            # Ctrl+C: close the channel so the remote script gets stdin EOF
            # and exits cleanly (releasing the USB device).
            stdout.channel.close()
            raise

        if self.debug and err:
            print(f"[SSH remote stderr]\n{err}")

        if not out:
            raise RuntimeError(
                f"Remote script produced no output.\nstderr: {err}"
            )
        try:
            result = json.loads(out)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"Remote script output is not valid JSON: {exc}\n"
                f"stdout: {out[:200]}"
            ) from exc

        if 'error' in result:
            raise RuntimeError(f"Remote script error: {result['error']}")

        return result

    # ── Public interface ──────────────────────────────────────────────────────

    def capture_waveform(self, channel: str):
        """Capture a waveform from *channel* via SSH.

        Executes the waveform capture script on the remote host and returns
        time/voltage arrays built from the JSON response.

        Args:
            channel (str): Channel name, e.g. ``'CH1'``.

        Returns:
            tuple: ``(time_array, voltage_array, metadata)``

                - *time_array*   – :class:`numpy.ndarray` of time values (s).
                - *voltage_array*– :class:`numpy.ndarray` of voltages (V).
                - *metadata*     – dict with instrument info.
        """
        script = self._build_script(
            _WAVEFORM_TEMPLATE,
            resource = self.visa_resource,
            channel  = channel,
        )
        result = self._run_script(script)

        time_arr    = np.array(result['time'])
        voltage_arr = np.array(result['voltage'])
        metadata    = result.get('metadata', {})

        return time_arr, voltage_arr, metadata

    def set_channel_settings(self, channel: str, info):
        """Store display settings to be applied before the next screenshot.

        Unlike the local driver (which configures the instrument immediately),
        SSH defers configuration to :meth:`capture_screen` so that setup and
        screenshot happen in a single remote session.

        Args:
            channel (str): Channel name, e.g. ``'CH1'``.
            info    (dict or bool): Cursor/label/measurement settings, or
                ``False`` / ``None`` to skip configuration.
        """
        self._pending_channel = channel
        self._pending_info    = info if info else None

    def capture_screen(self) -> bytes | None:
        """Capture a screenshot via SSH.

        Applies any pending display settings (from :meth:`set_channel_settings`)
        and captures a PNG screenshot, all in a single remote Python session.

        Returns:
            bytes: PNG image data, or ``None`` if the instrument does not
                support screenshots over this interface.
        """
        channel = self._pending_channel or 'CH1'
        info    = self._pending_info

        script = self._build_script(
            _SCREEN_TEMPLATE,
            resource = self.visa_resource,
            channel  = channel,
            info     = info,
        )
        try:
            result = self._run_script(script)
        except RuntimeError as exc:
            if self.debug:
                print(f"capture_screen: {exc}")
            return None

        png_b64 = result.get('png')
        if png_b64 is None:
            return None

        return base64.b64decode(png_b64)

    def monitor_single(self, max_wait=3600, retry_timeout=30, interval=0.5):
        """Wait for a single acquisition keeping one USB connection open.

        Runs a single remote script that arms the oscilloscope, polls for
        the trigger, re-arms on timeout, and only closes the USB connection
        when the trigger fires (or *max_wait* expires). This avoids the
        repeated USB reset that happens when :meth:`wait_single` is called
        in a loop.

        Args:
            max_wait      (float): Total seconds to wait. Default 3600 (1 h).
            retry_timeout (float): Seconds per attempt before re-arming.
                Default 30.
            interval      (float): Polling interval in seconds. Default 0.5.

        Returns:
            bool: ``True`` if triggered, ``False`` if *max_wait* expired.
        """
        script = self._build_script(
            _MONITOR_TEMPLATE,
            resource      = self.visa_resource,
            max_wait      = max_wait,
            retry_timeout = retry_timeout,
            interval      = interval,
        )
        result = self._run_script(script)
        return result.get('triggered', False)

    def wait_single(self, timeout=30, interval=0.5):
        """Block until a single acquisition completes on the remote scope.

        Runs a polling loop remotely (single SSH round-trip) to avoid
        per-tick SSH overhead.

        Args:
            timeout  (float): Maximum seconds to wait. Default 30.
            interval (float): Polling interval in seconds. Default 0.5.

        Returns:
            bool: ``True`` if acquisition completed, ``False`` if timed out.
        """
        script = self._build_script(
            _WAIT_TEMPLATE,
            resource = self.visa_resource,
            timeout  = timeout,
            interval = interval,
        )
        result = self._run_script(script)
        return result.get('triggered', False)

    def single(self):
        """Arm the remote oscilloscope for a single triggered acquisition."""
        script = self._build_script(
            _SCPI_TEMPLATE,
            resource = self.visa_resource,
            commands = {
                'TEKTRONIX': ['ACQuire:STOPAfter SEQuence', 'ACQuire:STATE RUN'],
                'KEYSIGHT':  [':SINGle'],
                'AGILENT':   [':SINGle'],
            },
        )
        self._run_script(script)

    def stop(self):
        """Stop the current acquisition on the remote oscilloscope."""
        script = self._build_script(
            _SCPI_TEMPLATE,
            resource = self.visa_resource,
            commands = {
                'TEKTRONIX': ['ACQuire:STATE STOP'],
                'KEYSIGHT':  [':STOP'],
                'AGILENT':   [':STOP'],
            },
        )
        self._run_script(script)

    def close(self):
        """Close the SSH connection."""
        self._ssh.close()

    # ── Resource string parser (class method, used by scope.py) ───────────────

    @classmethod
    def from_resource_string(cls, resource: str, debug: bool = False) -> 'SshScope':
        """Construct a :class:`SshScope` from a resource string.

        Format::

            SSH::user@host
            SSH::user@host:port
            SSH::user@host::VISA_RESOURCE
            SSH::user@host:port::VISA_RESOURCE

        Args:
            resource (str): Resource string starting with ``"SSH::"``.
            debug    (bool): Enable debug output.

        Returns:
            SshScope: Connected driver instance.
        """
        # Strip leading 'SSH::' prefix
        body = resource[5:]   # everything after 'SSH::'

        # Split at most once on '::' to separate host part from VISA resource
        parts = body.split('::', 1)
        host_part     = parts[0]                           # user@host[:port]
        visa_resource = parts[1] if len(parts) > 1 else 'auto'

        # Parse user@host:port
        user, host = (host_part.split('@', 1)
                      if '@' in host_part else ('root', host_part))
        port = 22
        if ':' in host:
            host, port_str = host.rsplit(':', 1)
            port = int(port_str)

        return cls(
            host          = host,
            user          = user,
            visa_resource = visa_resource,
            port          = port,
            debug         = debug,
        )
