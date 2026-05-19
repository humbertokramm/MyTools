"""
Base classes for pulse mask validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.path import Path


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    """A single point that violated a forbidden zone.

    Attributes:
        pulse_index (int): Index into the ``centers`` list (0-based).
        time        (float): Absolute time of the violating sample (s).
        voltage     (float): Absolute voltage of the violating sample (V).
        zone        (int): Index of the forbidden zone that was hit.
    """
    pulse_index: int
    time:        float
    voltage:     float
    zone:        int


@dataclass
class MaskResult:
    """Aggregated result of a mask validation run.

    Attributes:
        passed          (bool): True if zero violations were found.
        violation_count (int): Total number of violating samples.
        pass_rate       (float): Fraction of pulses (0.0-1.0) with no violations.
        pulse_count     (int): Total number of pulses tested.
        violations      (list[Violation]): Individual violation records.
    """
    passed:          bool
    violation_count: int
    pass_rate:       float
    pulse_count:     int
    violations:      List[Violation] = field(default_factory=list)

    def __repr__(self) -> str:
        status = 'PASS' if self.passed else 'FAIL'
        return (
            f'MaskResult({status}  pulses={self.pulse_count}'
            f'  pass_rate={self.pass_rate:.1%}'
            f'  violations={self.violation_count})'
        )


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class PulseMask:
    """Base class for pulse mask validation.

    Subclasses must set:
        T    (float): Signal period in seconds — class variable with the
                      standard default.  Override at class or instance level.
        Vnom (float): Nominal peak voltage in volts — set in ``__init__``.

    Subclasses must implement:
        forbidden_zones (property) → list[np.ndarray]

    Forbidden zone coordinate system
    ---------------------------------
    Each zone is an (N, 2) numpy array where:
        column 0 — time in **seconds relative to the pulse center** (0 = center)
        column 1 — voltage as a **fraction of Vnom** (0.0 = 0 V, 1.0 = Vnom)

    ``validate`` normalises each pulse window into this coordinate system,
    then checks every sample against every zone using matplotlib Path
    (ray-casting inside-polygon test).
    """

    # Subclasses define these as class variables; instances may override.
    T:    float = NotImplemented
    Vnom: float = NotImplemented

    # ------------------------------------------------------------------ #
    # Abstract interface                                                   #
    # ------------------------------------------------------------------ #

    @property
    def forbidden_zones(self) -> List[np.ndarray]:
        """List of forbidden-zone polygons in normalised coordinates.

        Returns:
            list[np.ndarray]: Each array is (N, 2) with columns
                [t_relative_s, V_fraction].

        Raises:
            NotImplementedError: Must be overridden by subclasses.
        """
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # Window size                                                          #
    # ------------------------------------------------------------------ #

    @property
    def _half_window(self) -> float:
        """Half-width of the extraction window around each pulse center (s).

        Default is ``T / 2`` (one full pulse slot, suitable for data masks).
        Subclasses that analyse half-cycles (e.g. clock masks) override this
        to ``T / 4`` so the window exactly matches the half-cycle duration and
        adjacent half-cycles do not bleed into each other.
        """
        return self.T / 2

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    def validate(
        self,
        time:    np.ndarray,
        voltage: np.ndarray,
        centers: List[float],
    ) -> MaskResult:
        """Validate each pulse against the forbidden zones.

        For every center in *centers*, a window of ± :attr:`_half_window` is
        extracted from *time* / *voltage*, normalised, and tested against
        every polygon in :attr:`forbidden_zones`.  A sample that falls inside
        any polygon is recorded as a :class:`Violation`.

        Args:
            time    (np.ndarray): Full-signal time array (s).
            voltage (np.ndarray): Full-signal voltage array (V).
            centers (list[float]): Pulse center timestamps (s).
                Pass one entry per pulse to be validated.

        Returns:
            MaskResult: Aggregated pass/fail with individual violations.
        """
        zones = self.forbidden_zones
        paths = [Path(np.vstack([z, z[0]])) for z in zones]   # close each polygon

        all_violations: List[Violation] = []
        failed_pulses:  set             = set()

        half = self._half_window

        for pulse_idx, c in enumerate(centers):
            idx = (time >= c - half) & (time <= c + half)
            t_w = time[idx]
            v_w = voltage[idx]

            if len(t_w) == 0:
                continue

            # Normalise into mask coordinate space
            t_n = t_w - c            # relative to pulse center
            v_n = v_w / self.Vnom    # fraction of Vnom

            points = np.column_stack([t_n, v_n])

            for zone_idx, path in enumerate(paths):
                hits = path.contains_points(points)
                for i in np.where(hits)[0]:
                    all_violations.append(Violation(
                        pulse_index = pulse_idx,
                        time        = float(t_w[i]),
                        voltage     = float(v_w[i]),
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

    # ------------------------------------------------------------------ #
    # Plotting                                                             #
    # ------------------------------------------------------------------ #

    def plot(
        self,
        ax,
        t_center: float = 0.0,
        t_scale:  float = 1.0,
        v_scale:  float = 1.0,
        color:    str   = 'red',
        alpha:    float = 0.25,
        label:    str   = None,
    ) -> None:
        """Overlay forbidden zones on an existing matplotlib axis.

        Converts zone polygons from physical units (seconds, volts) into the
        display units used by the plot, so the mask aligns with the signal.

        Args:
            ax       : Matplotlib ``Axes`` to draw on.
            t_center (float): Pulse center in **physical seconds**. Default ``0.0``.
            t_scale  (float): Factor that converts seconds → display X unit.
                Pass ``series['engNoteX']`` from a CsvScope read dict to match
                the signal's time axis (e.g. ``1e-3`` when the axis is in ms).
                Default ``1.0`` (no conversion — plot stays in seconds).
            v_scale  (float): Factor that converts volts → display Y unit.
                Pass ``series['engNoteY']`` from a CsvScope read dict.
                Default ``1.0`` (plot stays in volts).
            color    (str): Fill colour for forbidden zones. Default ``'red'``.
            alpha    (float): Transparency (0 = invisible, 1 = opaque).
                Default ``0.25``.
            label    (str, optional): Legend label attached to the first zone
                only (avoids duplicate legend entries). Default ``None``.
        """
        for i, zone in enumerate(self.forbidden_zones):
            # Denormalise to physical units, then convert to display units
            t_disp = (zone[:, 0] + t_center) / t_scale
            v_disp = (zone[:, 1] * self.Vnom)  / v_scale

            ax.fill(
                t_disp, v_disp,
                color = color,
                alpha = alpha,
                label = label if i == 0 else None,
            )
