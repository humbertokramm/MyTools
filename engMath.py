import numpy as np
from datetime import datetime

ENG_NOTATION = {
    'Y':  1e24,  'Z':  1e21,  'E':  1e18,  'P':  1e15,  'T':  1e12,  'G':  1e9,
    'M':  1e6,   'k':  1e3,   'h':  1e2,   'da': 1e1,   '':   1e0,   'd':  1e-1,
    'c':  1e-2,  'm':  1e-3,  'u':  1e-6,  'µ':  1e-6,  'n':  1e-9,  'p':  1e-12,
    'f':  1e-15, 'a':  1e-18, 'z':  1e-21, 'y':  1e-24,
}

SYMBOLS = ['V', 'W', 'A', 'Ω', 's', 'Hz', 'RPM']


def format_eng(label, suffix=False):
    """Extract and convert engineering notation from a bracketed label string.

    Args:
        label (str): String containing engineering notation in brackets,
            e.g. ``'Time[ms]'``.
        suffix (bool or str, optional): Return mode:

            - ``False`` – return the numeric factor (e.g. ``1e-3`` for ``'m'``).
            - ``True``  – return notation + symbol string (e.g. ``'mV'``).
            - ``'symbol'`` – return only the unit symbol (e.g. ``'V'``).

            Defaults to ``False``.

    Returns:
        float or str: Depends on *suffix*:

            - ``False``: numeric scale factor.
            - ``True``: notation+symbol string.
            - ``'symbol'``: unit symbol string.
            - If no notation found: ``1`` (suffix=False) or ``''`` (suffix=True).
    """
    i = label.find('[') + 1
    o = label.find(']')
    if i > o:
        return '' if suffix else 1
    label = label[i:o]
    symbol = ''
    for q in SYMBOLS:
        if label.find(q) > -1:
            symbol = q
        label = label.replace(q, '')
    if suffix == 'symbol':
        return symbol
    if suffix is True:
        return label + symbol
    return ENG_NOTATION[label]


def format_eng_str(number, decimals=2, string=True):
    """Convert a number to an engineering-notation string.

    Args:
        number (float or str): Number to convert.
            If already a string, it is returned with a trailing space.
        decimals (int, optional): Decimal places. Defaults to ``2``.
        string (bool, optional): If ``True`` return a formatted string;
            if ``False`` return a dict with ``value``, ``decimals``,
            ``unit`` and ``factor`` keys. Defaults to ``True``.

    Returns:
        str or dict: Formatted string (e.g. ``'1.23 k'``) or breakdown dict.
            Returns ``'0 '`` when *number* is zero.
    """
    if number == 0:
        return '0 '
    if isinstance(number, str):
        return number + ' '
    exponent = int(np.floor(np.log10(abs(number))))
    exponent = (exponent // 3) * 3
    unit = {
        -30: 'q', -27: 'r', -24: 'y', -21: 'z', -18: 'a', -15: 'f',
        -12: 'p',  -9: 'n',  -6: 'µ',  -3: 'm',   0: '',   3: 'k',
          6: 'M',   9: 'G',  12: 'T',  15: 'P',  18: 'E',  21: 'Z',
         24: 'Y',  27: 'R',  30: 'Q',
    }
    if string:
        return "{:.{}f} {}".format(number / 10 ** exponent, decimals, unit.get(exponent, ''))
    return {
        'value':   number / 10 ** exponent,
        'decimals': decimals,
        'unit':    unit.get(exponent, ''),
        'factor':  10 ** exponent,
    }


def format_value(number, series, axis, decimals=2):
    """Format a numeric value with engineering notation and the correct unit.

    Args:
        number (float): Value to format (in normalised units).
        series (dict): Series metadata containing:

            - ``'engNoteX'``: X-axis scale factor.
            - ``'engNoteY'``: Y-axis scale factor.
            - ``'symbolX'``: X-axis unit symbol.
            - ``'symbolY'``: Y-axis unit symbol.

        axis (str): Type of value:

            - ``'x'``   – time / X position.
            - ``'y'``   – amplitude.
            - ``'f'``   – frequency (inverse of time).
            - ``'bps'`` – bits per second.
            - ``'v/t'`` – slew rate (V/µs).

        decimals (int, optional): Decimal places. Defaults to ``2``.

    Returns:
        str: Formatted string with unit, e.g. ``'1.23 ms'``, ``'456.78 V'``.
    """
    if axis == 'x':
        return format_eng_str(number * series['engNoteX'], decimals) + series['symbolX']
    if axis == 'f':
        return format_eng_str(number / series['engNoteX'], decimals) + 'Hz'
    if axis == 'bps':
        return format_eng_str(number / series['engNoteX'], decimals) + 'bps'
    if axis == 'y':
        return format_eng_str(number * series['engNoteY'], decimals) + series['symbolY']
    if axis == 'v/t':
        return format_eng_str(number * series['engNoteX'] * 1e6, decimals) + 'V/µs'
    return 'ERROR: format_value(axis=' + axis + ')'


def auto_scale(array):
    """Return engineering-notation breakdown for the span of *array*.

    Args:
        array (array-like): Numeric array.

    Returns:
        dict: Breakdown dict from :func:`format_eng_str` with
            ``value``, ``decimals``, ``unit`` and ``factor`` keys.
    """
    span = np.max(array) - np.min(array)
    return format_eng_str(span, string=False)


def normalize_data(value):
    """Normalise a date/time value to a formatted string.

    Accepts a :class:`datetime`, a Unix timestamp (int/float) or a
    date string in several formats.

    Args:
        value (datetime | int | float | str): Input value.

    Returns:
        str: Date/time string in ``'DD/MM/YYYY - HH:MM:SS'`` format.

    Raises:
        ValueError: If *value* is a string in an unknown format.
        TypeError: If *value* is of an unsupported type.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value)
    elif isinstance(value, str):
        formats = [
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y - %H:%M:%S.%f",
            "%d/%m/%Y - %H:%M:%S",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Unknown format: {value}")
    else:
        raise TypeError(f"Unsupported type: {type(value)}")

    return dt.strftime("%d/%m/%Y - %H:%M:%S")
