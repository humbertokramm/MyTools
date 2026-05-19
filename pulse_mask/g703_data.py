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

    # Timing half-widths — derived from Figure 11-1 (Tnom = 244 ns)
    #   (Tnom + 25) / 2  → Mascara_Out transition point  (134.5 ns)
    #   (Tnom - 25) / 2  → Mascara_In  transition point  (109.5 ns)
    #   (Tnom - 50) / 2  → Mascara_In  slope point        (97.0 ns)
    _W_MID_OUT = (244e-9 + 25e-9) / 2   # 134.5 ns
    _W_MID_IN  = (244e-9 - 25e-9) / 2   # 109.5 ns
    _W_TOP     = (244e-9 - 50e-9) / 2   #  97.0 ns

    # Voltage fractions (normalised by Vnom) — from Excel reference data
    # Mascara_Out: transition at 0.50, overshoot limit 1.20 (edge) / 1.10 (center)
    # Mascara_In:  transition at 0.50, flat min 0.90 (center), slope 0.80 (±w_top)
    #              space tolerance ±0.10 at window edges, ±0.20 at transition edge
    _V_TRANS   = 0.50   # voltage at transition boundary (both masks)
    _V_OS_EDGE = 1.20   # overshoot limit near the transition timing (Mascara_Out)
    _V_OS_CTR  = 1.10   # overshoot limit at center (Mascara_Out)
    _V_FLAT    = 0.90   # minimum flat-top at center (Mascara_In)
    _V_SLOPE   = 0.80   # minimum at ±_W_TOP (Mascara_In)

    # Polygon ceiling/floor (normalised, must exceed 1.0 in absolute value)
    _V_BOUND   = 1.60

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
        vb    = self._V_BOUND
        T     = self.T
        Tnom  = self.Tnom
        w_out = T / 2              # 244 ns — window half-width = half-period
        w_mo  = self._W_MID_OUT    # 134.5 ns — Mascara_Out transition timing
        w_mi  = self._W_MID_IN     # 109.5 ns — Mascara_In  transition timing
        w_top = self._W_TOP        #  97.0 ns — Mascara_In  slope timing

        # Normalized voltage levels (from Excel reference, same ratio for all interfaces)
        v_sp  = self.Vspace_tol / self.Vnom   # 0.10 — space tolerance
        v_tr  = self._V_TRANS                  # 0.50 — transition boundary
        v_ose = self._V_OS_EDGE                # 1.20 — overshoot limit at edge timing
        v_osc = self._V_OS_CTR                 # 1.10 — overshoot limit at center
        v_top = self._V_FLAT                   # 0.90 — minimum flat top at center
        v_sl  = self._V_SLOPE                  # 0.80 — minimum at ±w_top

        # ------------------------------------------------------------------
        # Zone 0 — above Mascara_Out  (overshoot + pulse too wide)
        #
        # Mascara_Out boundary (left → right), then ceiling closes polygon:
        #   (±w_out, v_sp)          — window edges at space-tolerance level
        #   (±w_mo,  v_tr)          — transition lower corner
        #   (±w_mo,  v_ose)         — vertical step up to overshoot limit
        #   (0,      v_osc)         — slight dip at center
        # ------------------------------------------------------------------
        above_out = np.array([
            (-w_out,  v_sp ),
            (-w_mo,   v_tr ),
            (-w_mo,   v_ose),   # vertical step up
            (   0.0,  v_osc),
            (+w_mo,   v_ose),
            (+w_mo,   v_tr ),   # vertical step down
            (+w_out,  v_sp ),
            (+w_out,  +vb  ),   # ceiling — close polygon
            (-w_out,  +vb  ),
        ])

        # ------------------------------------------------------------------
        # Zone 1 — below Mascara_In  (amplitude too low + pulse too narrow)
        #
        # Floor at -vb, then Mascara_In boundary traversed right → left:
        #   (±w_out, -v_sp)         — window edges at −space-tolerance
        #   (±w_mi,  -2*v_sp)       — transition lower corner (most negative)
        #   (±w_mi,  v_tr)          — vertical step up to transition level
        #   (±w_top, v_sl)          — slope region (80 % min)
        #   (0,      v_top)         — center minimum (90 % min)
        # ------------------------------------------------------------------
        below_in = np.array([
            (-w_out,  -vb      ),   # floor left
            (+w_out,  -vb      ),   # floor right
            (+w_out,  -v_sp    ),   # Mascara_In right endpoint
            (+w_mi,   -2*v_sp  ),   # Mascara_In: traversed right→left
            (+w_mi,   v_tr     ),   # vertical step up
            (+w_top,  v_sl     ),
            (   0.0,  v_top    ),
            (-w_top,  v_sl     ),
            (-w_mi,   v_tr     ),
            (-w_mi,   -2*v_sp  ),   # vertical step down
            (-w_out,  -v_sp    ),   # Mascara_In left endpoint
        ])

        return [above_out, below_in]

    @property
    def forbidden_zones(self) -> list:
        return self._zones

    # ------------------------------------------------------------------ #
    # Validate (polarity-agnostic override)                               #
    # ------------------------------------------------------------------ #

    def validate(self, time, voltage, centers):
        """Validate each pulse using polarity-aware forbidden zones.

        Positive pulses are tested against the standard (positive) zones.
        Negative pulses are tested against the same zones with the voltage
        axis negated — equivalent to the "Mascara Negativa" from the standard,
        which is the exact mirror of the positive mask.

        Violations are recorded at the **original** signal voltage so they
        overlay correctly on the unmodified waveform.

        Args:
            time    (np.ndarray): Full-signal time array (s).
            voltage (np.ndarray): Full-signal voltage array (V).
            centers (list[float]): Pulse center timestamps (s).

        Returns:
            MaskResult: Aggregated pass/fail with individual violations.
        """
        from matplotlib.path import Path as MplPath
        from .base import MaskResult, Violation

        zones     = self.forbidden_zones
        pos_paths = [MplPath(np.vstack([z, z[0]])) for z in zones]
        # Negative zones: same time coords, y negated
        neg_zones = [np.column_stack([z[:, 0], -z[:, 1]]) for z in zones]
        neg_paths = [MplPath(np.vstack([z, z[0]])) for z in neg_zones]

        half           = self._half_window
        all_violations = []
        failed_pulses  = set()

        for pulse_idx, c in enumerate(centers):
            idx = (time >= c - half) & (time <= c + half)
            t_w = time[idx]
            v_w = voltage[idx]

            if len(t_w) == 0:
                continue

            # Determine polarity from the dominant peak in the window
            peak  = v_w[np.argmax(np.abs(v_w))]
            paths = pos_paths if peak >= 0 else neg_paths

            # Normalise into mask coordinate space
            t_n = t_w - c
            v_n = v_w / self.Vnom      # original voltage, NOT folded
            points = np.column_stack([t_n, v_n])

            for zone_idx, path in enumerate(paths):
                hits = path.contains_points(points)
                for i in np.where(hits)[0]:
                    all_violations.append(Violation(
                        pulse_index = pulse_idx,
                        time        = float(t_w[i]),
                        voltage     = float(v_w[i]),   # original coordinate
                        zone        = zone_idx,
                    ))
                    failed_pulses.add(pulse_idx)

        n = len(centers)
        return MaskResult(
            passed          = len(all_violations) == 0,
            violation_count = len(all_violations),
            pass_rate       = (n - len(failed_pulses)) / n if n else 1.0,
            pulse_count     = n,
            violations      = all_violations,
        )
