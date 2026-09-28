"""Spectral power distribution of an LED.

An LED is described by what its datasheet gives: often only the central
(peak or dominant) wavelength, sometimes a FWHM as well, and sometimes the
whole spectral curve. :class:`LEDSpectrum` holds any of the three and turns
it into a sampled density for the non-sequential trace and into a few
representative wavelengths for the sequential path.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from optiland.illumination._quadrature import equal_share_nodes

SpectrumKind = Literal["line", "gaussian", "table"]

#: The spectrum forms, in the order the GUI offers them.
SPECTRUM_KINDS: tuple[str, ...] = ("line", "gaussian", "table")

#: Samples of a sampled spectral density.
_DENSITY_SAMPLES = 401

#: A Gaussian spectrum is sampled out to this many FWHM from its centre.
_GAUSSIAN_SPAN_FWHM = 2.0

#: Shortest wavelength a sampled spectrum may reach [um].
_MIN_WAVELENGTH_UM = 0.1


@dataclass(frozen=True)
class LEDSpectrum:
    """Spectral power distribution of an LED, in micrometres.

    - ``"line"``: only the central wavelength is known; the LED is treated
      as monochromatic at ``center_um``.
    - ``"gaussian"``: a Gaussian with centre ``center_um`` and full width at
      half maximum ``fwhm_um``.
    - ``"table"``: relative spectral power ``powers`` at ``wavelengths_um``
      (a digitized datasheet curve), linear between the samples.

    Attributes:
        kind: One of the forms above.
        center_um: Central wavelength [um] (``"line"``, ``"gaussian"``).
        fwhm_um: Full width at half maximum [um] (``"gaussian"``).
        wavelengths_um: Wavelengths of a ``"table"`` [um], strictly
            increasing.
        powers: Relative spectral power at ``wavelengths_um``; non-negative,
            any scale.
    """

    kind: SpectrumKind = "line"
    center_um: float = 0.55
    fwhm_um: float | None = None
    wavelengths_um: tuple[float, ...] = ()
    powers: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "wavelengths_um", tuple(map(float, self.wavelengths_um))
        )
        object.__setattr__(self, "powers", tuple(map(float, self.powers)))
        if self.kind not in SPECTRUM_KINDS:
            raise ValueError(
                f"Unknown LED spectrum {self.kind!r}; expected one of "
                f"{', '.join(SPECTRUM_KINDS)}."
            )
        if self.kind in ("line", "gaussian"):
            if not self.center_um > _MIN_WAVELENGTH_UM:
                raise ValueError(
                    f"The central wavelength must exceed {_MIN_WAVELENGTH_UM} um, "
                    f"got {self.center_um!r}."
                )
            object.__setattr__(self, "center_um", float(self.center_um))
        if self.kind == "gaussian":
            if self.fwhm_um is None or not self.fwhm_um > 0.0:
                raise ValueError(
                    f"A Gaussian spectrum needs a FWHM > 0, got {self.fwhm_um!r}."
                )
            object.__setattr__(self, "fwhm_um", float(self.fwhm_um))
        if self.kind == "table":
            self._validate_table()

    def _validate_table(self) -> None:
        waves = np.asarray(self.wavelengths_um)
        powers = np.asarray(self.powers)
        if waves.size < 2 or waves.size != powers.size:
            raise ValueError(
                "A tabulated spectrum needs at least two wavelengths and one "
                f"power per wavelength, got {waves.size} wavelengths and "
                f"{powers.size} powers."
            )
        if np.any(np.diff(waves) <= 0.0) or waves[0] <= _MIN_WAVELENGTH_UM:
            raise ValueError(
                "The wavelengths of a tabulated spectrum must increase strictly "
                f"and exceed {_MIN_WAVELENGTH_UM} um."
            )
        if np.any(powers < 0.0) or not powers.max() > 0.0:
            raise ValueError(
                "The powers of a tabulated spectrum must be >= 0 and not all zero."
            )

    @property
    def peak_um(self) -> float:
        """Wavelength of maximum spectral power [um]."""
        if self.kind == "table":
            return self.wavelengths_um[int(np.argmax(self.powers))]
        return self.center_um

    def density(self) -> tuple[np.ndarray, np.ndarray]:
        """Sampled spectral density: wavelengths [um] and relative power.

        A ``"line"`` spectrum is a single sample of weight 1. The other forms
        are sampled on a uniform grid, so the powers can serve directly as
        the weights of a discrete wavelength distribution.
        """
        if self.kind == "line":
            return np.array([self.center_um]), np.array([1.0])
        if self.kind == "gaussian":
            span = _GAUSSIAN_SPAN_FWHM * self.fwhm_um
            low = max(self.center_um - span, _MIN_WAVELENGTH_UM)
            waves = np.linspace(low, self.center_um + span, _DENSITY_SAMPLES)
            sigma = self.fwhm_um / (2.0 * math.sqrt(2.0 * math.log(2.0)))
            return waves, np.exp(-0.5 * ((waves - self.center_um) / sigma) ** 2)
        waves = np.linspace(
            self.wavelengths_um[0], self.wavelengths_um[-1], _DENSITY_SAMPLES
        )
        return waves, np.interp(waves, self.wavelengths_um, self.powers)

    def representative_wavelengths(self, count: int) -> tuple[list[float], int]:
        """A few wavelengths that stand for the spectrum in a sequential path.

        The spectrum is cut into ``count`` bands of equal power and each band
        is represented by its power-weighted mean wavelength, so all nodes
        carry the same weight. A ``"line"`` spectrum gives its one
        wavelength whatever ``count`` is.

        Args:
            count: Number of wavelengths (at least 1).

        Returns:
            The wavelengths [um], increasing, and the index of the one
            closest to the peak (the primary wavelength).
        """
        if count < 1:
            raise ValueError(f"count must be at least 1, got {count}.")
        if self.kind == "line":
            return [self.center_um], 0
        waves, power = self.density()
        nodes = equal_share_nodes(waves, power, count)
        primary = int(np.argmin(np.abs(nodes - self.peak_um)))
        return [float(v) for v in nodes], primary

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation."""
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind in ("line", "gaussian"):
            data["center_um"] = self.center_um
        if self.kind == "gaussian":
            data["fwhm_um"] = self.fwhm_um
        if self.kind == "table":
            data["wavelengths_um"] = list(self.wavelengths_um)
            data["powers"] = list(self.powers)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LEDSpectrum:
        """Inverse of :meth:`to_dict`."""
        return cls(
            kind=data.get("kind", "line"),
            center_um=data.get("center_um", 0.55),
            fwhm_um=data.get("fwhm_um"),
            wavelengths_um=tuple(data.get("wavelengths_um", ())),
            powers=tuple(data.get("powers", ())),
        )
