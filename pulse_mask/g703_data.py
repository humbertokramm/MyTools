"""
ITU-T G.703 Section 11 — 2048 kbit/s interface (E12), HDB3 pulse mask (Figure 11-1).
"""

from __future__ import annotations

import numpy as np
from .base import PulseMask


class G703Data2048kbits(PulseMask):
    """Pulse mask for the 2048 kbit/s interface (E12), HDB3.

    Implements ITU-T G.703 Section 11 — "Interface at 2048 kbit/s (E12)",
    Figure 11-1.  Code: HDB3 (High Density Bipolar order 3).
    Use mode ``"E12"`` when calling ``CsvScope.plot_mask()``.

    Supports coaxial (75 Ω) and symmetrical pair (120 Ω) configurations.
    The mask applies to every *mark* (pulse) regardless of sign; internally
    ``validate`` folds negative pulses into the positive domain.

    Standard parameters (Table 11-1)
    ----------------------------------
    ================  ===========  ================
    Parameter         Coaxial      Symmetrical pair
                      (75 Ω)       (120 Ω)
    ================  ===========  ================
    Vnom (peak mark)  2.37 V       3.00 V
    Vspace tolerance  0.237 V      0.300 V
    Pulse width       244 ns       244 ns
    ================  ===========  ================

    Period override
    ---------------
    ``T`` is a class variable defaulting to the standard 488 ns.
    Override globally or per-instance::

        G703Data2048kbits.T = 490e-9          # global
        mask = G703Data2048kbits(T=490e-9)    # instance only

    Forbidden zone geometry (Figure 11-1)
    --------------------------------------
    Mask coordinates are normalised: time relative to pulse center (s),
    voltage as a fraction of Vnom.

    The outer boundary is a trapezoid defined by three timing levels
    taken directly from the standard::

        At V = 0 %  : half-width = (244 + 25) / 2 = 134.5 ns  (outer)
        At V = 20 % : half-width = (244 - 25) / 2 = 109.5 ns  (transition mid)
        At V = 80 % : half-width = (244 - 50) / 2 =  97.0 ns  (near top)
        At V = 120%  : half-width =  97.0 ns                   (overshoot limit)

    NOTE: The exact polygon vertices should be validated against a physical
    instrument.  The key timing constants (_W_*) are public so they can be
    tuned without subclassing.

    Args:
        interface (str): ``'coaxial'`` (default, 75 Ω, Vnom = 2.37 V) or
            ``'symmetrical'`` (120 Ω, Vnom = 3.0 V).
        T (float, optional): Period override in seconds.
    """

    # ------------------------------------------------------------------ #
    # Class-level constants (ITU-T G.703 defaults)                        #
    # ------------------------------------------------------------------ #

    T    = 488e-9    # period  = 1 / 2048e3
    Tnom = 244e-9    # nominal pulse width

    PARAMS = {
        'coaxial':     {'Vnom': 2.37, 'Vspace_tol': 0.237},
        'symmetrical': {'Vnom': 3.00, 'Vspace_tol': 0.300},
    }

    # Half-widths at each voltage level — derived from Figure 11-1
    #   (244 + 25) / 2  → outer boundary at baseline
    #   (244 - 25) / 2  → transition mid-point (20 % V)
    #   (244 - 50) / 2  → near-top level (80 % V)
    _W_OUTER_BASE  = (244e-9 + 25e-9) / 2   # 134.5 ns
    _W_MID         = (244e-9 - 25e-9) / 2   # 109.5 ns
    _W_TOP         = (244e-9 - 50e-9) / 2   #  97.0 ns

    # Voltage fractions for the polygon corners
    _V_BASE        = 0.00
    _V_TRANS_LOW   = 0.20   # 20 % V — lower transition boundary
    _V_TRANS_HIGH  = 0.80   # 80 % V — upper transition boundary
    _V_OVERSHOOT   = 1.20   # 120 % V — maximum overshoot allowed

    # Polygon bounds (kept finite for matplotlib Path)
    _T_BOUND = 260e-9   # slightly larger than T/2 = 244 ns
    _V_BOUND = 1.60     # well above _V_OVERSHOOT

    # ------------------------------------------------------------------ #
    # Constructor                                                          #
    # ------------------------------------------------------------------ #

    def __init__(self, interface: str = 'coaxial', T: float = None):
        p = self.PARAMS[interface]
        self.Vnom        = p['Vnom']
        self.Vspace_tol  = p['Vspace_tol']
        self.interface   = interface

        if T is not None:
            self.T = T   # instance-level override

        self._zones = self._build_zones()

    # ------------------------------------------------------------------ #
    # Forbidden zones                                                      #
    # ------------------------------------------------------------------ #

    def _build_zones(self) -> list:
        tb  = self._T_BOUND
        vb  = self._V_BOUND
        w0  = self._W_OUTER_BASE
        wm  = self._W_MID
        wt  = self._W_TOP
        vl  = self._V_TRANS_LOW
        vh  = self._V_TRANS_HIGH
        vos = self._V_OVERSHOOT

        # Zone 0 — Left outer forbidden
        #   Region to the left of the outer trapezoid's rising edge.
        #   The boundary slopes inward from (−w0, 0%) through (−wm, 20%)
        #   to (−wt, 80%), then stays vertical up to the plot ceiling.
        left = np.array([
            (-tb,  self._V_BASE),
            (-w0,  self._V_BASE),
            (-wm,  vl),
            (-wt,  vh),
            (-wt,  vb),
            (-tb,  vb),
        ])

        # Zone 1 — Right outer forbidden (mirror of Zone 0)
        right = left.copy()
        right[:, 0] *= -1

        # Zone 2 — Top center forbidden (overshoot above 120 % V)
        top = np.array([
            (-wt, vos),
            ( wt, vos),
            ( wt, vb),
            (-wt, vb),
        ])

        # Zone 3 — Below baseline (negative voltage for a positive pulse)
        below = np.array([
            (-tb,  0.00),
            ( tb,  0.00),
            ( tb, -0.50),
            (-tb, -0.50),
        ])

        return [left, right, top, below]

    @property
    def forbidden_zones(self) -> list:
        return self._zones

    # ------------------------------------------------------------------ #
    # Validate (polarity-agnostic override)                               #
    # ------------------------------------------------------------------ #

    def validate(self, time, voltage, centers):
        """Validate each pulse, folding negative pulses into positive domain.

        The G.703 specification states the mask applies *irrespective of sign*,
        so negative pulses are sign-inverted before checking.

        Args:
            time    (np.ndarray): Full-signal time array (s).
            voltage (np.ndarray): Full-signal voltage array (V).
            centers (list[float]): Pulse center timestamps (s).

        Returns:
            MaskResult: Aggregated pass/fail with individual violations.
        """
        # For each center, determine polarity from the peak in the window,
        # then fold negative pulses into the positive domain.
        half = self._half_window   # T/2 — one full pulse slot
        v_folded = voltage.copy()

        for c in centers:
            idx = (time >= c - half) & (time <= c + half)
            if not np.any(idx):
                continue
            peak = voltage[idx][np.argmax(np.abs(voltage[idx]))]
            if peak < 0:
                v_folded[idx] = -voltage[idx]

        return super().validate(time, v_folded, centers)
