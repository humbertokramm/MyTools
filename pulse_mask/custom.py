"""
User-defined pulse mask with free polygon geometry.
"""

from __future__ import annotations

import numpy as np
from .base import PulseMask


class CustomMask(PulseMask):
    """Pulse mask with user-defined forbidden zone polygons.

    Allows defining any mask geometry without subclassing, using the same
    validation and plotting interface as the standard G.703 masks.

    Coordinate system (same as all PulseMask subclasses)
    -----------------------------------------------------
    Each polygon is an (N, 2) array:
        column 0 — time in **seconds relative to the pulse center** (t = 0)
        column 1 — voltage as a **fraction of Vnom** (1.0 = Vnom)

    Args:
        forbidden_zones (list[np.ndarray]): List of forbidden-zone polygons.
        T    (float): Signal period in seconds.
        Vnom (float): Nominal peak voltage in volts.
        Tnom (float, optional): Nominal pulse width in seconds.
            Used for reference / plotting only.  Defaults to ``T / 2``.

    Example:
        Define a simple rectangular forbidden zone above 120 % V::

            import numpy as np
            from pulse_mask import CustomMask

            overshoot_zone = np.array([
                (-100e-9,  1.20),
                ( 100e-9,  1.20),
                ( 100e-9,  1.60),
                (-100e-9,  1.60),
            ])

            mask = CustomMask(
                forbidden_zones = [overshoot_zone],
                T    = 488e-9,
                Vnom = 2.37,
            )

            result = mask.validate(time, voltage, centers)
    """

    def __init__(
        self,
        forbidden_zones: list,
        T:    float,
        Vnom: float,
        Tnom: float = None,
    ):
        if not forbidden_zones:
            raise ValueError('forbidden_zones must contain at least one polygon.')

        for i, z in enumerate(forbidden_zones):
            z = np.asarray(z, dtype=float)
            if z.ndim != 2 or z.shape[1] != 2:
                raise ValueError(
                    f'forbidden_zones[{i}] must be shape (N, 2), '
                    f'got {np.asarray(z).shape}.'
                )

        self._forbidden_zones = [np.asarray(z, dtype=float) for z in forbidden_zones]
        self.T    = T
        self.Vnom = Vnom
        self.Tnom = Tnom if Tnom is not None else T / 2

    @property
    def forbidden_zones(self) -> list:
        return self._forbidden_zones

    def add_zone(self, polygon: np.ndarray) -> None:
        """Append an additional forbidden zone polygon.

        Args:
            polygon (np.ndarray): Shape (N, 2) array in normalised coordinates.
        """
        polygon = np.asarray(polygon, dtype=float)
        if polygon.ndim != 2 or polygon.shape[1] != 2:
            raise ValueError(f'polygon must be shape (N, 2), got {polygon.shape}.')
        self._forbidden_zones.append(polygon)
