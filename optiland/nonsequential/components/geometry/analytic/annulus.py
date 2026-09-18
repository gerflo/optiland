"""Annular plane geometry for Non-Sequential Raytracing.

AnnularPlaneGeometry -- a flat ring (annulus) at a fixed axial offset, with
inner and outer radii.  Used as the rim surface of a lens whose front and
back apertures differ.

All operations in LOCAL coordinates.

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np

import optiland.backend as be
from optiland.nonsequential._utils import as_float, as_param
from optiland.nonsequential.components.geometry.base import AABB, AnalyticGeometry


class AnnularPlaneGeometry(AnalyticGeometry):
    """Flat annular ring at ``z = z_offset`` in the local frame.

    The annulus extends from ``inner_radius`` to ``outer_radius`` in the
    radial direction.  Rays that hit the z = z_offset plane inside the
    annular band register a hit; rays outside or on the inner hole do not.

    The hole may be elliptical: ``inner_radius`` is its semi-axis along
    local x and ``inner_radius_y`` (default: the same) along local y. A
    perforated fold mirror tilted by 45 deg about y needs a hole elongated
    along x by ``1 / cos(45 deg)`` to look circular along the optical axis.

    Attributes:
        inner_radius: Inner (hole) semi-axis along local x [mm].
        inner_radius_y: Inner (hole) semi-axis along local y [mm].
        outer_radius: Outer radius of the annulus [mm].
        z_offset: Axial position of the plane in local frame [mm].
    """

    def __init__(
        self,
        inner_radius: float,
        outer_radius: float,
        z_offset: float = 0.0,
        inner_radius_y: float | None = None,
    ) -> None:
        """Initialize AnnularPlaneGeometry.

        Args:
            inner_radius: Inner (hole) radius [mm], or its semi-axis along
                local x when ``inner_radius_y`` is given.
            outer_radius: Outer (rim) radius [mm].
            z_offset: Axial z-position of the plane [mm].
            inner_radius_y: Semi-axis of an elliptical hole along local y
                [mm]. ``None`` keeps the hole circular.
        """
        self.inner_radius = as_param(inner_radius)
        self.outer_radius = as_param(outer_radius)
        self.z_offset = as_param(z_offset)
        self.inner_radius_y = (
            as_param(inner_radius_y) if inner_radius_y is not None else None
        )

    @property
    def is_elliptical(self) -> bool:
        """Whether the hole is an ellipse rather than a circle."""
        return self.inner_radius_y is not None

    def ray_intersect(
        self, origins: np.ndarray, directions: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Intersect rays with the annular plane.

        Uses the standard plane intersection: t = (z_offset - oz) / dz,
        then checks that the hit radius is within [inner_radius, outer_radius].

        Args:
            origins: Ray origins in local frame, shape (N, 3) [mm].
            directions: Ray directions in local frame, shape (N, 3).

        Returns:
            (t, normals, hit_mask, n_geom) all in local frame. n_geom is
            the fixed local +z (the ``material_back`` side by contract; see
            :meth:`ComponentGeometry.ray_intersect`).
        """
        N = origins.shape[0]

        oz = origins[:, 2]
        dz = directions[:, 2]

        eps = 1e-9
        inf_arr = be.ones(N) * be.inf
        # Avoid division by zero for rays parallel to the plane
        t = be.where(
            be.abs(dz) > eps,
            (self.z_offset - oz) / (dz + 1e-30),
            inf_arr,
        )

        # Compute hit position; inf t values naturally fail the r^2 check
        hx = origins[:, 0] + t * directions[:, 0]
        hy = origins[:, 1] + t * directions[:, 1]
        r2 = hx * hx + hy * hy

        if self.inner_radius_y is None:
            outside_hole = r2 >= self.inner_radius**2
        else:
            outside_hole = (
                (hx / self.inner_radius) ** 2 + (hy / self.inner_radius_y) ** 2
            ) >= 1.0
        hit_mask = (t > eps) & outside_hole & (r2 <= self.outer_radius**2)

        t_out = be.where(hit_mask, t, inf_arr)

        n_geom = be.stack([be.zeros(N), be.zeros(N), be.ones(N)], axis=1)
        # Normal is (0, 0, +/-1) -- flip to face incoming ray
        nz_sign = be.where(dz > 0, -1.0, 1.0)
        normals = be.stack([be.zeros(N), be.zeros(N), nz_sign * be.ones(N)], axis=1)

        return t_out, normals, hit_mask, n_geom

    def bounding_box(self, transform: tuple[np.ndarray, np.ndarray]) -> AABB:
        """Return AABB of the annulus in global coordinates.

        Args:
            transform: (translation, rotation_matrix).

        Returns:
            AABB in global frame.
        """
        t_vec = np.array(transform[0], dtype=float)
        R = np.array(transform[1], dtype=float)
        r = as_float(self.outer_radius)
        z = as_float(self.z_offset)

        corners_local = np.array(
            [
                [-r, -r, z],
                [-r, r, z],
                [r, -r, z],
                [r, r, z],
            ],
            dtype=float,
        )
        corners_global = corners_local @ R.T + t_vec
        return AABB(corners_global.min(axis=0), corners_global.max(axis=0))
