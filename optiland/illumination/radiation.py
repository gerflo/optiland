"""Angular emission pattern of a light source.

A :class:`RadiationPattern` is the radiant intensity ``I(theta)`` of an
emitter as a function of the polar angle ``theta`` from its normal,
rotationally symmetric about that normal. The flux in the ring between
``theta`` and ``theta + d theta`` is proportional to
``I(theta) sin(theta) d theta``; ray generators draw polar angles from that
density (:meth:`RadiationPattern.sample_cos_theta`).

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Literal

import numpy as np

PatternKind = Literal["lambertian", "half_angle", "table"]

#: The pattern forms, in the order the GUI offers them.
PATTERN_KINDS: tuple[str, ...] = ("lambertian", "half_angle", "table")

#: Polar-angle samples a tabulated pattern is integrated and inverted on.
_TABLE_GRID = 4097


@dataclass(frozen=True)
class RadiationPattern:
    """Rotationally symmetric radiant intensity ``I(theta)`` of an emitter.

    Three forms cover what LED datasheets give:

    - ``"lambertian"``: ``I = cos(theta)``; the default when nothing is
      known about the emitter.
    - ``"half_angle"``: ``I = cos(theta)**m``, with ``m`` chosen so that
      ``I`` falls to one half at ``half_angle_deg`` (datasheets quote the
      "viewing angle", twice that angle). 60 deg is Lambertian (``m = 1``).
    - ``"table"``: ``I`` read off a datasheet curve at ``angles_deg``,
      linearly interpolated, constant below the first angle and zero
      beyond the last.

    Attributes:
        kind: One of the forms above.
        half_angle_deg: Half-intensity angle of a ``"half_angle"`` pattern
            [deg], in (0, 90).
        angles_deg: Polar angles of a ``"table"`` pattern [deg], strictly
            increasing within [0, 90].
        intensities: Relative intensities at ``angles_deg``; non-negative,
            any scale.
    """

    kind: PatternKind = "lambertian"
    half_angle_deg: float | None = None
    angles_deg: tuple[float, ...] = ()
    intensities: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "angles_deg", tuple(map(float, self.angles_deg)))
        object.__setattr__(self, "intensities", tuple(map(float, self.intensities)))
        if self.kind not in PATTERN_KINDS:
            raise ValueError(
                f"Unknown radiation pattern {self.kind!r}; expected one of "
                f"{', '.join(PATTERN_KINDS)}."
            )
        if self.kind == "half_angle":
            if self.half_angle_deg is None or not 0.0 < self.half_angle_deg < 90.0:
                raise ValueError(
                    "A half-angle pattern needs a half-intensity angle between "
                    f"0 and 90 deg, got {self.half_angle_deg!r}."
                )
            object.__setattr__(self, "half_angle_deg", float(self.half_angle_deg))
        if self.kind == "table":
            self._validate_table()

    def _validate_table(self) -> None:
        angles = np.asarray(self.angles_deg)
        values = np.asarray(self.intensities)
        if angles.size < 2 or angles.size != values.size:
            raise ValueError(
                "A tabulated pattern needs at least two angles and one "
                f"intensity per angle, got {angles.size} angles and "
                f"{values.size} intensities."
            )
        if np.any(np.diff(angles) <= 0.0) or angles[0] < 0.0 or angles[-1] > 90.0:
            raise ValueError(
                "The angles of a tabulated pattern must increase strictly "
                "within 0..90 deg."
            )
        if np.any(values < 0.0):
            raise ValueError("The intensities of a tabulated pattern must be >= 0.")
        if not _table_cdf(self.angles_deg, self.intensities, 90.0)[1][-1] > 0.0:
            raise ValueError("The tabulated pattern emits no flux.")

    @property
    def cos_power(self) -> float:
        """Exponent ``m`` of ``I = cos(theta)**m`` (not for tables)."""
        if self.kind == "lambertian":
            return 1.0
        if self.kind == "half_angle":
            return math.log(0.5) / math.log(math.cos(math.radians(self.half_angle_deg)))
        raise ValueError("A tabulated pattern has no cosine power.")

    def intensity(self, theta_deg: float | np.ndarray) -> np.ndarray:
        """Relative intensity at ``theta_deg``, 1 at its maximum."""
        theta = np.asarray(theta_deg, dtype=np.float64)
        if self.kind == "table":
            values = np.asarray(self.intensities)
            curve = np.interp(theta, self.angles_deg, values, left=values[0], right=0.0)
            return curve / values.max()
        cos_t = np.clip(np.cos(np.radians(theta)), 0.0, None)
        return cos_t**self.cos_power

    def flux_fraction(self, half_angle_deg: float) -> float:
        """Share of the emitted flux inside a cone about the normal.

        Args:
            half_angle_deg: Cone half angle [deg]; 90 or more is everything.

        Returns:
            The fraction in [0, 1].
        """
        cone = min(float(half_angle_deg), 90.0)
        if self.kind == "table":
            _, cdf_cone = _table_cdf(self.angles_deg, self.intensities, cone)
            _, cdf_all = _table_cdf(self.angles_deg, self.intensities, 90.0)
            return float(cdf_cone[-1] / cdf_all[-1])
        mu_min = max(math.cos(math.radians(cone)), 0.0)
        return 1.0 - mu_min ** (self.cos_power + 1.0)

    def sample_cos_theta(self, u: np.ndarray, half_angle_deg: float) -> np.ndarray:
        """Polar-angle cosines distributed as this pattern inside a cone.

        Inverse-CDF sampling: equal steps in ``u`` are equal shares of the
        flux inside the cone, from the cone edge (``u = 0``) to the axis
        (``u -> 1``). A table that holds ``cos(theta)`` therefore gives the
        same directions as the Lambertian form for the same ``u``.

        Args:
            u: Uniform numbers in [0, 1).
            half_angle_deg: Cone half angle [deg]; 90 or more is the whole
                hemisphere.

        Returns:
            ``cos(theta)`` per sample.
        """
        u = np.asarray(u, dtype=np.float64)
        cone = min(float(half_angle_deg), 90.0)
        if self.kind == "table":
            theta, cdf = _table_cdf(self.angles_deg, self.intensities, cone)
            return np.cos(np.interp((1.0 - u) * cdf[-1], cdf, theta))
        # Density of mu = cos(theta) is proportional to mu**m on [mu_min, 1].
        exponent = self.cos_power + 1.0
        low = max(math.cos(math.radians(cone)), 0.0) ** exponent
        return (low + u * (1.0 - low)) ** (1.0 / exponent)

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation."""
        data: dict[str, Any] = {"kind": self.kind}
        if self.kind == "half_angle":
            data["half_angle_deg"] = self.half_angle_deg
        if self.kind == "table":
            data["angles_deg"] = list(self.angles_deg)
            data["intensities"] = list(self.intensities)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RadiationPattern:
        """Inverse of :meth:`to_dict`."""
        return cls(
            kind=data.get("kind", "lambertian"),
            half_angle_deg=data.get("half_angle_deg"),
            angles_deg=tuple(data.get("angles_deg", ())),
            intensities=tuple(data.get("intensities", ())),
        )


@lru_cache(maxsize=64)
def _table_cdf(
    angles_deg: tuple[float, ...], intensities: tuple[float, ...], cone_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Polar-angle grid [rad] and cumulative flux of a tabulated pattern.

    The flux density is ``I(theta) sin(theta)``; the grid runs from the axis
    to the cone edge or the last tabulated angle, whichever is smaller.
    """
    values = np.asarray(intensities, dtype=np.float64)
    theta_max = math.radians(min(cone_deg, angles_deg[-1]))
    theta = np.linspace(0.0, theta_max, _TABLE_GRID)
    curve = np.interp(np.degrees(theta), angles_deg, values, left=values[0], right=0.0)
    density = curve * np.sin(theta)
    steps = 0.5 * np.diff(theta) * (density[:-1] + density[1:])
    cdf = np.concatenate(([0.0], np.cumsum(steps)))
    theta.setflags(write=False)
    cdf.setflags(write=False)
    return theta, cdf
