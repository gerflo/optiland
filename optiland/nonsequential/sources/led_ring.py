"""LED ring source for Non-Sequential Raytracing.

Identical rectangular chips evenly spaced on a circle, each a uniform area
emitter with a Lambertian or tabulated angular pattern -- the emitter the
fold builds from an illumination path's
:class:`~optiland.illumination.LEDRing`.

Kramer Harrison, 2026
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from optiland.nonsequential._utils import as_detached_param
from optiland.nonsequential.rng import EventSlot
from optiland.nonsequential.sources.base import BaseNSQSource, Spectrum
from optiland.nonsequential.sources.extended import (
    emission_directions,
    emitted_bundle,
    sample_emission_cos_theta,
)

if TYPE_CHECKING:
    from optiland.coordinate_system import CoordinateSystem
    from optiland.illumination import RadiationPattern
    from optiland.nonsequential.ray_bundle import NSQRayBundle
    from optiland.nonsequential.rng import NSQRng


class LEDRingSource(BaseNSQSource):
    """Identical rectangular chips evenly spaced on a circle.

    The chips lie in the local x-y plane (z = 0) and emit about local +z.
    Chip ``k`` is centred at azimuth ``first_angle_deg + 360 k / count`` on
    the circle of radius ``pitch_radius``, its height radial and its width
    tangential. Every chip carries the same share of ``total_flux``: the
    ray with id ``i`` leaves chip ``i mod count``, so the shares are exact,
    not only on average.

    Attributes:
        cs: Coordinate system (local z = emission axis, origin = ring
            centre).
        spectrum: Wavelength distribution.
        total_flux: Flux of all chips together inside the cone [W].
        count: Number of chips.
        pitch_radius: Radius of the circle through the chip centres [mm].
        chip_width: Tangential chip size [mm].
        chip_height: Radial chip size [mm].
        first_angle_deg: Azimuth of chip 0 from local x [deg].
        half_angle_deg: Half angle of the emission cone [deg]; 90 is the
            hemisphere.
        radiation: Angular emission pattern; ``None`` is Lambertian.
        medium: Medium the source is embedded in.
    """

    def __init__(
        self,
        cs: CoordinateSystem,
        spectrum: Spectrum,
        total_flux: float = 1.0,
        count: int = 1,
        pitch_radius: float = 0.0,
        chip_width: float = 1.0,
        chip_height: float = 1.0,
        first_angle_deg: float = 0.0,
        half_angle_deg: float = 90.0,
        radiation: RadiationPattern | None = None,
        medium=None,
    ) -> None:
        """Initialize LEDRingSource.

        Args:
            cs: Coordinate system.
            spectrum: Wavelength distribution.
            total_flux: Flux of all chips together inside the cone [W].
            count: Number of chips (at least 1).
            pitch_radius: Radius of the circle through the chip centres
                [mm].
            chip_width: Tangential chip size [mm].
            chip_height: Radial chip size [mm].
            first_angle_deg: Azimuth of chip 0 from local x [deg].
            half_angle_deg: Half angle of the emission cone [deg].
            radiation: Angular emission pattern; ``None`` is Lambertian
                (cosine-weighted, restricted to the cone).
            medium: Medium the source is embedded in (default: vacuum).

        Raises:
            ValueError: If ``count`` is below 1, a chip size is not positive
                or ``pitch_radius`` is negative.
        """
        super().__init__(cs, spectrum, total_flux)
        if int(count) != count or count < 1:
            raise ValueError(f"LEDRingSource: count must be >= 1, got {count!r}.")
        if not (chip_width > 0.0 and chip_height > 0.0) or pitch_radius < 0.0:
            raise ValueError(
                "LEDRingSource: the chip sizes must be positive and the pitch "
                f"radius non-negative, got {chip_width!r} x {chip_height!r} mm "
                f"on radius {pitch_radius!r} mm."
            )
        owner = "LEDRingSource"
        self.count = int(count)
        self.pitch_radius = as_detached_param(pitch_radius, "pitch_radius", owner)
        self.chip_width = as_detached_param(chip_width, "chip_width", owner)
        self.chip_height = as_detached_param(chip_height, "chip_height", owner)
        self.first_angle_deg = as_detached_param(
            first_angle_deg, "first_angle_deg", owner
        )
        self.half_angle_deg = as_detached_param(half_angle_deg, "half_angle_deg", owner)
        self.radiation = radiation
        self.medium = medium

    def chip_azimuths(self, ray_id: np.ndarray) -> np.ndarray:
        """Azimuth [rad] of the chip each ray leaves."""
        chip = np.asarray(ray_id, dtype=np.int64) % self.count
        return np.radians(self.first_angle_deg) + 2.0 * np.pi * chip / self.count

    def generate(self, ray_id: np.ndarray, rng: NSQRng) -> NSQRayBundle:
        """Generate rays from the chips in global coordinates.

        Args:
            ray_id: Unique identifiers for the rays to generate, shape (N,).
            rng: Keyed PCG32 RNG.

        Returns:
            NSQRayBundle with all rays alive.
        """
        num_rays = len(ray_id)
        bounce0 = np.zeros(num_rays, dtype=np.int32)

        # Uniform position on the chip, then onto the chip's place.
        u1 = rng.uniform(ray_id, bounce0, EventSlot.SOURCE_U1)
        u2 = rng.uniform(ray_id, bounce0, EventSlot.SOURCE_U2)
        tangential = (u1 - 0.5) * self.chip_width
        radial = self.pitch_radius + (u2 - 0.5) * self.chip_height
        phi = self.chip_azimuths(ray_id)
        cos_p, sin_p = np.cos(phi), np.sin(phi)
        pos_local = np.stack(
            [
                radial * cos_p - tangential * sin_p,
                radial * sin_p + tangential * cos_p,
                np.zeros(num_rays),
            ],
            axis=1,
        )

        u1d = rng.uniform(ray_id, bounce0, EventSlot.SOURCE_U3)
        u2d = rng.uniform(ray_id, bounce0, EventSlot.SOURCE_U4)
        cos_theta = sample_emission_cos_theta(
            u1d, self.half_angle_deg, True, self.radiation
        )
        dirs_local = emission_directions(cos_theta, u2d)
        return emitted_bundle(self, ray_id, rng, pos_local, dirs_local)
