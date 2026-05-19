"""
ITU-T G.703 Section 15 — 2048 kHz synchronization interface (T12).

Pulse mask per Figure 15-1.
"""

from __future__ import annotations

import numpy as np
from .base import PulseMask


class G703Clock2048kHz(PulseMask):
    """Pulse mask for the 2048 kHz synchronization interface (T12).

    Implements ITU-T G.703 Section 15 — "2048 kHz synchronization interface
    (T12)", Figure 15-1.  Use mode ``"T12"`` when calling
    ``CsvScope.plot_mask()``.

    The mask is referenced to the **falling zero crossing** of each positive
    half-cycle (the point where the signal transitions from +V toward −V).
    Pass every falling zero crossing as a center to ``validate``.

    No sign-folding is performed — the two forbidden-zone polygons already
    encode the full bipolar waveform shape: the positive half-cycle occupies
    the left half of the window (t < 0) and the beginning of the negative
    half-cycle occupies the right half (t > 0).

    Standard parameters (Table 15-1)
    ----------------------------------
    ================  ===========  ================
    Parameter         Coaxial      Symmetrical pair
                      (75 Ω)       (120 Ω)
    ================  ===========  ================
    V  (peak max)     1.50 V       1.90 V
    V1 (peak min)     0.75 V       1.00 V
    ================  ===========  ================

    Period override
    ---------------
    ``T`` is a class variable defaulting to 1 / 2048 kHz ≈ 488 ns::

        G703Clock2048kHz.T = 490e-9          # global
        mask = G703Clock2048kHz(T=490e-9)    # instance only

    Forbidden zone geometry (Figure 15-1)
    --------------------------------------
    Coordinates are normalised: time relative to the **falling zero crossing**
    (0 = falling ZC of the positive half-cycle), voltage as a fraction of
    V_peak (Vnom).

    Key timing parameters::

        tol = T / 30  ≈ 16.3 ns   — transition window half-width
        hT  = T / 2   ≈ 244.1 ns  — half period
        qT  = T / 4   ≈ 122.1 ns  — quarter period
        hw  = hT + qT             — analysis half-window (3T/4 ≈ 366.2 ns)

    Voltage ratio::

        v1 = V1 / V_peak           (coaxial: 0.75 / 1.50 = 0.50)

    Zone 0 — above Mascara_Out (upper corridor boundary):
        Polygon whose floor is the Mascara_Out polyline.  Any sample above
        this boundary (overshoot, premature rise, late fall) is forbidden.

    Zone 1 — below Mascara_In (lower corridor boundary):
        Polygon whose ceiling is the Mascara_In polyline.  Any sample below
        this boundary (insufficient amplitude, premature fall, late rise) is
        forbidden.

    Args:
        interface (str): ``'coaxial'`` (default, 75 Ω) or ``'symmetrical'``
            (120 Ω).
        T (float, optional): Period override in seconds.
    """

    # ------------------------------------------------------------------ #
    # Class-level constants (ITU-T G.703 defaults)                        #
    # ------------------------------------------------------------------ #

    T = 1 / 2048e3   # ≈ 488.28 ns

    PARAMS = {
        'coaxial':     {'V': 1.50, 'V1': 0.75},
        'symmetrical': {'V': 1.90, 'V1': 1.00},
    }

    # Ceiling / floor in normalised coords (must exceed 1.0)
    _V_BOUND = 1.60

    # ------------------------------------------------------------------ #
    # Constructor                                                          #
    # ------------------------------------------------------------------ #

    def __init__(self, interface: str = 'coaxial', T: float = None):
        p = self.PARAMS[interface]
        self.V_peak    = p['V']
        self.V1        = p['V1']
        self.Vnom      = self.V_peak   # base class uses Vnom for normalisation
        self.interface = interface

        if T is not None:
            self.T = T

        self._v1_frac = self.V1 / self.V_peak   # e.g. 0.75 / 1.50 = 0.50
        self._zones   = self._build_zones()

    # ------------------------------------------------------------------ #
    # Forbidden zones                                                      #
    # ------------------------------------------------------------------ #

    def _build_zones(self) -> list:
        vb   = self._V_BOUND
        v1   = self._v1_frac          # normalised V1
        T    = self.T
        hT   = T / 2                  # half period
        qT   = T / 4                  # quarter period
        tol  = T / 30                 # transition window half-width
        hw   = hT + qT# + tol          # analysis half-window

        # ------------------------------------------------------------------
        # Zone 0 — above Mascara_Out  (upper forbidden corridor boundary)
        #
        # The Mascara_Out polyline defines the maximum allowed voltage at
        # each time relative to the falling zero crossing (t = 0).
        # The forbidden zone is everything strictly above this boundary.
        #
        # Polygon:  Mascara_Out boundary (left → right) as the FLOOR,
        #           plus ceiling at +vb to close the polygon.
        #
        # Normalised boundary points (from ITU reference):
        #   (-hw,     -v1 )  — mid-negative half-cycle (left edge of window)
        #   (-hT-tol,  0  )  — upper limit rises to 0 at rising-edge start
        #   (-hT-tol, +1.0)  — immediately allows full +Vmax after ZC timing
        #   (+tol,    +1.0)  — flat positive half-cycle top (no overshoot)
        #   (+tol,     0  )  — falling-edge start: upper limit drops to 0
        #   (+qT,     -v1 )  — mid-negative: must be below −V1
        #   (+hT-tol,  0  )  — upper limit rises to 0 at next rising-edge start
        #   (+hT-tol, +1.0)  — next positive half-cycle begins
        #   (+hw,     +1.0)  — right edge of window
        # ------------------------------------------------------------------
        above_out = np.array([
            (-hw,      -v1  ),
            (-hT-tol,   0.0 ),
            (-hT-tol,  +1.0 ),
            (+tol,     +1.0 ),
            (+tol,      0.0 ),
            (+qT,      -v1  ),
            (+hT-tol,   0.0 ),
            (+hT-tol,  +1.0 ),
            (+hw,      +1.0 ),
            (+hw,      +vb  ),   # ceiling — close polygon
            (-hw,      +vb  ),
        ])

        # ------------------------------------------------------------------
        # Zone 1 — below Mascara_In  (lower forbidden corridor boundary)
        #
        # The Mascara_In polyline defines the minimum required voltage.
        # The forbidden zone is everything strictly below this boundary.
        #
        # Polygon:  floor at -vb (left → right), then Mascara_In boundary
        #           traversed right → left as the CEILING to close.
        #
        # Normalised boundary points (from ITU reference):
        #   (-hw,     -1.0)  — left edge: must be at −Vmax (negative flat)
        #   (-hT+tol, -1.0)  — end of negative flat on the left side
        #   (-hT+tol,  0  )  — rising ZC passes through 0
        #   (-qT,     +v1 )  — positive flat region: must be above +V1
        #   (-tol,     0  )  — falling ZC approaches 0
        #   (-tol,    -1.0)  — immediately must drop to −Vmax after falling ZC
        #   (+hT+tol, -1.0)  — end of negative flat on the right side
        #   (+hT+tol,  0  )  — next rising ZC passes through 0
        #   (+hw,     +v1 )  — right edge: positive rising towards +V1
        # ------------------------------------------------------------------
        below_in = np.array([
            (-hw,      -vb  ),   # floor — left edge
            (+hw,      -vb  ),   # floor — right edge
            (+hw,      +v1  ),   # Mascara_In right endpoint (traverse backwards)
            (+hT+tol,   0.0 ),
            (+hT+tol,  -1.0 ),
            (-tol,     -1.0 ),
            (-tol,      0.0 ),
            (-qT,      +v1  ),
            (-hT+tol,   0.0 ),
            (-hT+tol,  -1.0 ),
            (-hw,      -1.0 ),   # Mascara_In left endpoint
        ])

        return [above_out, below_in]

    @property
    def forbidden_zones(self) -> list:
        return self._zones

    # ------------------------------------------------------------------ #
    # Window size                                                          #
    # ------------------------------------------------------------------ #

    @property
    def _half_window(self) -> float:
        """3T/4 — covers exactly one half-period on each side of the falling ZC.

        hw = T/2 + T/4: the left half covers the full positive half-cycle
        (T/2) and the right half covers the full negative half-cycle (T/2),
        but the window is kept symmetric at 3T/4 so it aligns cleanly with
        other fixed-period signals.
        """
        T = self.T
        return T / 2 + T / 4
