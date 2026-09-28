"""A ring of LEDs as the light source of an illumination path.

Fundus cameras and ring lights illuminate through a ring of identical LEDs
in the object plane of their illumination relay. :class:`LEDRing` describes
such a ring once -- the LED type (:class:`LEDType`: chip size, radiation
pattern, spectrum, flux) and the arrangement -- and both models of the
illumination path are derived from it:

- the sequential path gets object-height fields across the emitting zone
  and wavelengths representing the LED spectrum (:func:`apply_led_ring`);
- the non-sequential fold builds its emitter from it: one rectangular chip
  per LED, or the ring smeared into a homogeneous annulus.

The chips lie in the object plane and emit about its normal. Each chip's
height runs radially, its width tangentially.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import numpy as np

from optiland.illumination._quadrature import equal_share_nodes
from optiland.illumination.radiation import RadiationPattern
from optiland.illumination.spectrum import LEDSpectrum

if TYPE_CHECKING:
    from optiland.optic import Optic

EmitterModel = Literal["discrete", "annulus"]
FluxUnit = Literal["W", "lm"]

#: The emitter models, in the order the GUI offers them.
EMITTER_MODELS: tuple[str, ...] = ("discrete", "annulus")

#: Type key of an LED ring in a serialized optic's ``"light_source"``.
LED_RING_TYPE = "led_ring"

#: Decimals (mm) the generated field heights are rounded to: 0.1 um.
_FIELD_DECIMALS = 4

#: Radial samples of the emitting-area density the field points come from.
#: The density of a chip rises like a square root at its inner edge; this
#: many samples keep the field points within 1e-7 mm of their exact place.
_RADIAL_SAMPLES = 20001


@dataclass(frozen=True)
class LEDType:
    """What a datasheet says about one LED.

    Attributes:
        name: Free label, e.g. the part number.
        chip_width: Width of the emitting area [mm]; tangential on a ring.
        chip_height: Height of the emitting area [mm]; radial on a ring.
        radiation: Angular emission; Lambertian unless known better.
        spectrum: Spectral power; the central wavelength if nothing more is
            known.
        flux: Flux of one LED in ``flux_unit``; ``None`` if unknown (the
            non-sequential trace then uses its normalised flux).
        flux_unit: ``"W"`` (radiant) or ``"lm"`` (luminous).
    """

    name: str = ""
    chip_width: float = 1.0
    chip_height: float = 1.0
    radiation: RadiationPattern = field(default_factory=RadiationPattern)
    spectrum: LEDSpectrum = field(default_factory=LEDSpectrum)
    flux: float | None = None
    flux_unit: FluxUnit = "W"

    def __post_init__(self) -> None:
        if not (self.chip_width > 0.0 and self.chip_height > 0.0):
            raise ValueError(
                "The emitting area of an LED needs a positive width and height, "
                f"got {self.chip_width!r} x {self.chip_height!r} mm."
            )
        if self.flux is not None and not self.flux > 0.0:
            raise ValueError(f"The LED flux must be positive, got {self.flux!r}.")
        if self.flux_unit not in ("W", "lm"):
            raise ValueError(f"Unknown flux unit {self.flux_unit!r}; use W or lm.")

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation."""
        return {
            "name": self.name,
            "chip_width": self.chip_width,
            "chip_height": self.chip_height,
            "radiation": self.radiation.to_dict(),
            "spectrum": self.spectrum.to_dict(),
            "flux": self.flux,
            "flux_unit": self.flux_unit,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LEDType:
        """Inverse of :meth:`to_dict`."""
        return cls(
            name=data.get("name", ""),
            chip_width=data.get("chip_width", 1.0),
            chip_height=data.get("chip_height", 1.0),
            radiation=RadiationPattern.from_dict(data.get("radiation") or {}),
            spectrum=LEDSpectrum.from_dict(data.get("spectrum") or {}),
            flux=data.get("flux"),
            flux_unit=data.get("flux_unit", "W"),
        )


@dataclass(frozen=True)
class LEDRing:
    """Identical LEDs evenly spaced on a circle in the object plane.

    Attributes:
        led: The LED type.
        count: Number of LEDs.
        pitch_diameter: Diameter of the circle through the chip centres [mm].
        first_angle_deg: Azimuth of the first LED from the object's local
            x axis [deg].
        emitter_model: How the non-sequential trace models the ring:
            ``"discrete"`` (one chip per LED) or ``"annulus"`` (the ring
            smeared into a homogeneous annulus, e.g. behind a diffuser).
        field_count: Number of field points across the emitting zone.
        field_edges: Also add the inner and outer edge of the zone as
            fields of weight 0 (for layouts and ray fans).
        wavelength_count: Number of wavelengths representing the spectrum
            (a single central wavelength always gives one).
    """

    led: LEDType
    count: int
    pitch_diameter: float
    first_angle_deg: float = 0.0
    emitter_model: EmitterModel = "discrete"
    field_count: int = 5
    field_edges: bool = True
    wavelength_count: int = 5

    def __post_init__(self) -> None:
        if int(self.count) != self.count or self.count < 1:
            raise ValueError(f"An LED ring needs at least one LED, got {self.count!r}.")
        object.__setattr__(self, "count", int(self.count))
        if self.emitter_model not in EMITTER_MODELS:
            raise ValueError(
                f"Unknown emitter model {self.emitter_model!r}; expected one of "
                f"{', '.join(EMITTER_MODELS)}."
            )
        if self.field_count < 1 or self.wavelength_count < 1:
            raise ValueError("The field and wavelength counts must be at least 1.")
        if not self.inner_radius > 0.0:
            raise ValueError(
                f"The chips reach the axis: pitch diameter {self.pitch_diameter:g} "
                f"mm is not larger than the chip height {self.led.chip_height:g} "
                "mm. A ring needs its chips off the axis."
            )
        if (
            self.count > 1
            and math.atan2(0.5 * self.led.chip_width, self.inner_radius)
            > math.pi / self.count + 1e-12
        ):
            raise ValueError(
                f"{self.count} chips of {self.led.chip_width:g} mm width overlap "
                f"on a pitch diameter of {self.pitch_diameter:g} mm."
            )

    @property
    def pitch_radius(self) -> float:
        """Radius of the circle through the chip centres [mm]."""
        return 0.5 * self.pitch_diameter

    @property
    def inner_radius(self) -> float:
        """Smallest radius that emits [mm]."""
        return self.pitch_radius - 0.5 * self.led.chip_height

    @property
    def outer_radius(self) -> float:
        """Largest radius that emits [mm]: the outer chip corners, or the
        outer edge of the annulus."""
        outer_edge = self.pitch_radius + 0.5 * self.led.chip_height
        if self.emitter_model == "annulus":
            return outer_edge
        return math.hypot(outer_edge, 0.5 * self.led.chip_width)

    def led_azimuths_deg(self) -> list[float]:
        """Azimuth of every chip centre [deg]."""
        step = 360.0 / self.count
        return [self.first_angle_deg + step * k for k in range(self.count)]

    def emitting_length(self, r: np.ndarray) -> np.ndarray:
        """Length of the circle of radius ``r`` that lies on emitting area.

        Its integral over ``r`` is the emitting area, so it is the radial
        density of the emitting area.

        Args:
            r: Radii [mm].

        Returns:
            Arc length on emitting area [mm], per radius.
        """
        r = np.asarray(r, dtype=np.float64)
        if self.emitter_model == "annulus":
            inside = (r >= self.inner_radius) & (r <= self.outer_radius)
            return np.where(inside, 2.0 * math.pi * r, 0.0)
        half_h = 0.5 * self.led.chip_height
        half_w = 0.5 * self.led.chip_width
        safe_r = np.maximum(r, 1e-300)
        # A chip centred at (R, 0): the circle is on the chip for
        # a1 <= |phi| <= min(a2, a3) (radial and tangential edges).
        a1 = np.arccos(np.clip((self.pitch_radius + half_h) / safe_r, -1.0, 1.0))
        a2 = np.arccos(np.clip((self.pitch_radius - half_h) / safe_r, -1.0, 1.0))
        a3 = np.arcsin(np.clip(half_w / safe_r, 0.0, 1.0))
        arc = np.maximum(np.minimum(a2, a3) - a1, 0.0)
        return self.count * 2.0 * r * arc

    def field_points(self) -> list[tuple[float, float]]:
        """Object heights and weights of the fields that sample the ring.

        ``field_count`` points cut the emitting zone into radial bands of
        equal emitting area; each sits at its band's area centroid and has
        weight 1. With ``field_edges`` the inner and outer edge of the zone
        follow as weight-0 fields. Heights are rounded to 0.1 um: readable
        in a field table, and tools that round field heights themselves
        then never see a normalized field coordinate above 1.

        Returns:
            ``(y, weight)`` pairs, increasing in ``y``.
        """
        r = np.linspace(self.inner_radius, self.outer_radius, _RADIAL_SAMPLES)
        nodes = equal_share_nodes(r, self.emitting_length(r), self.field_count)
        points = [(round(float(y), _FIELD_DECIMALS), 1.0) for y in nodes]
        if self.field_edges:
            points = [
                (round(self.inner_radius, _FIELD_DECIMALS), 0.0),
                *points,
                (round(self.outer_radius, _FIELD_DECIMALS), 0.0),
            ]
        return points

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation, tagged with its source type."""
        return {
            "type": LED_RING_TYPE,
            "led": self.led.to_dict(),
            "count": self.count,
            "pitch_diameter": self.pitch_diameter,
            "first_angle_deg": self.first_angle_deg,
            "emitter_model": self.emitter_model,
            "field_count": self.field_count,
            "field_edges": self.field_edges,
            "wavelength_count": self.wavelength_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LEDRing:
        """Inverse of :meth:`to_dict`."""
        return cls(
            led=LEDType.from_dict(data.get("led") or {}),
            count=data["count"],
            pitch_diameter=data["pitch_diameter"],
            first_angle_deg=data.get("first_angle_deg", 0.0),
            emitter_model=data.get("emitter_model", "discrete"),
            field_count=data.get("field_count", 5),
            field_edges=data.get("field_edges", True),
            wavelength_count=data.get("wavelength_count", 5),
        )


def light_source_from_dict(data: dict[str, Any] | None) -> LEDRing | None:
    """Rebuild a serialized light source (``None`` stays ``None``).

    Raises:
        ValueError: If the source type is unknown.
    """
    if not data:
        return None
    kind = data.get("type")
    if kind == LED_RING_TYPE:
        return LEDRing.from_dict(data)
    raise ValueError(f"Unknown light source type {kind!r}; expected {LED_RING_TYPE!r}.")


def apply_led_ring(
    optic: Optic,
    ring: LEDRing | None,
    *,
    fields: bool = True,
    wavelengths: bool = True,
) -> None:
    """Make ``ring`` the light source of ``optic`` and derive its settings.

    The fields become object heights across the emitting zone
    (:meth:`LEDRing.field_points`) and the wavelengths represent the LED
    spectrum (:meth:`LEDSpectrum.representative_wavelengths`). ``None``
    removes the light source and leaves fields and wavelengths as they are.

    Args:
        optic: The illumination optic; its object must be finite.
        ring: The LED ring, or ``None``.
        fields: Replace the fields.
        wavelengths: Replace the wavelengths.

    Raises:
        ValueError: If the object is at infinity.
    """
    if ring is None:
        optic.light_source = None
        return
    obj = optic.object_surface
    if obj is None or obj.is_infinite:
        raise ValueError(
            "An LED ring sits in the object plane; this optic's object is at "
            "infinity. Give the object a finite distance first."
        )
    optic.light_source = ring
    if fields:
        optic.fields.fields = []
        optic.fields.set_type("object_height")
        for y, weight in ring.field_points():
            optic.fields.add(y=y, weight=weight)
    if wavelengths:
        values, primary = ring.led.spectrum.representative_wavelengths(
            ring.wavelength_count
        )
        optic.wavelengths.wavelengths = []
        for k, value in enumerate(values):
            optic.wavelengths.add(value=value, is_primary=k == primary)
