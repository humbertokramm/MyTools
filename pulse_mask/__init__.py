"""
pulse_mask — ITU-T G.703 pulse mask validation.

Classes
-------
G703Data2048kbits
    2048 kbit/s data interface mask (Figure 11-1).
G703Clock2048kHz
    2048 kHz synchronization clock mask (Figure 15-1).
CustomMask
    User-defined mask with free polygon geometry.

Usage
-----
>>> from pulse_mask import G703Data2048kbits
>>> mask = G703Data2048kbits(interface='coaxial')
>>> result = mask.validate(time, voltage, centers=[122e-9, 610e-9])
>>> print(result)
>>> mask.plot(ax, t_center=122e-9)
"""

from .base        import PulseMask, MaskResult, Violation
from .g703_data   import G703Data2048kbits
from .g703_clock  import G703Clock2048kHz
from .custom      import CustomMask

__all__ = [
    'PulseMask',
    'MaskResult',
    'Violation',
    'G703Data2048kbits',
    'G703Clock2048kHz',
    'CustomMask',
]
