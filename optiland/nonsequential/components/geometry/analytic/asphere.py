"""Even asphere geometry for Non-Sequential Raytracing.

The surface is the rotationally symmetric even asphere

    z(r) = c r^2 / (1 + sqrt(1 - (1 + K) c^2 r^2)) + sum_i C_i r^(2 (i + 1))

with ``r^2 = x^2 + y^2``, vertex curvature ``c = 1 / radius`` and conic
constant ``K``. ``coefficients[0]`` multiplies ``r^2``, ``coefficients[1]``
multiplies ``r^4`` and so on -- the same convention as
:class:`optiland.geometries.even_asphere.EvenAsphere`, so a sequential
surface converts without an index shift.

Unlike the conic, an asphere has no closed-form ray intersection. The
conic's quadric roots (and the vertex plane) serve as starting points for a
fixed number of Newton iterations on the sag residual, evaluated with
backend operations so the geometry stays differentiable under Torch.

All operations in LOCAL coordinates.

Kramer Harrison, 2026
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

import optiland.backend as be
from optiland.nonsequential._utils import as_float, as_param
from optiland.nonsequential.components.geometry.analytic.conic import (
    _TINY,
    ConicGeometry,
)
from optiland.nonsequential.components.geometry.base import AABB

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Newton residual [mm] below which an intersection counts as converged.
_RESIDUAL_TOL = 1e-8


class EvenAsphereGeometry(ConicGeometry):
    """Even asphere ``z = conic(r) + sum C_i r^(2(i+1))`` centred on local z.

    Attributes:
        radius: Vertex radius of curvature [mm]. Positive = centre of
            curvature on the +z side.
        conic: Conic constant K of the base conic.
        aperture_radius: Semi-aperture [mm].
        coefficients: Polynomial coefficients ``C_i``; ``coefficients[0]``
            multiplies ``r^2``.
        max_iter: Newton iterations run per starting point.
    """

    def __init__(
        self,
        radius: float,
        conic: float,
        aperture_radius: float,
        coefficients: Sequence[float] = (),
        max_iter: int = 16,
    ) -> None:
        """Initialize EvenAsphereGeometry.

        Args:
            radius: Vertex radius of curvature [mm].
            conic: Conic constant K.
            aperture_radius: Aperture semi-diameter [mm].
            coefficients: Even polynomial coefficients, ``C_i`` for
                ``r^(2(i+1))``.
            max_iter: Newton iterations per starting point.
        """
        super().__init__(radius, conic, aperture_radius)
        self.coefficients = [as_param(c) for c in coefficients]
        self.max_iter = int(max_iter)

    # -- sag and normal --------------------------------------------------

    def _poly(self, r2):
        """Polynomial part ``sum C_i r2^(i+1)``."""
        z = be.zeros_like(r2)
        for i, ci in enumerate(self.coefficients):
            z = z + ci * r2 ** (i + 1)
        return z

    def _dpoly_dr2(self, r2):
        """Derivative of the polynomial part with respect to ``r2``."""
        d = be.zeros_like(r2)
        for i, ci in enumerate(self.coefficients):
            d = d + (i + 1) * ci * r2**i
        return d

    def _sag(self, x, y):
        """Asphere sag z(x, y): conic sag plus the even polynomial."""
        return super()._sag(x, y) + self._poly(x**2 + y**2)

    def _normal_local(self, x, y):
        """Unnormalized outward normal ``(-dz/dx, -dz/dy, 1)``."""
        n_conic = super()._normal_local(x, y)
        dp = self._dpoly_dr2(x**2 + y**2)
        gx = n_conic[:, 0] - 2.0 * x * dp
        gy = n_conic[:, 1] - 2.0 * y * dp
        return be.stack([gx, gy, be.ones_like(x)], axis=1)

    # -- intersection ------------------------------------------------------

    def _conic_roots(self, origins, directions):
        """Both quadric roots of the base conic (or the plane for c = 0)."""
        ox, oy, oz = origins[:, 0], origins[:, 1], origins[:, 2]
        dx, dy, dz = directions[:, 0], directions[:, 1], directions[:, 2]
        c = self._curvature()
        kp = 1.0 + self.conic

        a = c * (dx**2 + dy**2 + kp * dz**2)
        b = 2.0 * (c * (ox * dx + oy * dy + kp * oz * dz) - dz)
        c_0 = c * (ox**2 + oy**2 + kp * oz**2) - 2.0 * oz

        disc = b**2 - 4.0 * a * c_0
        disc_ok = disc >= 0.0
        sqrt_disc = be.where(
            disc_ok, be.maximum(disc, 1e-12) ** 0.5, be.zeros_like(disc)
        )
        sign_b = be.where(b >= 0.0, 1.0, -1.0)
        q = -0.5 * (b + sign_b * sqrt_disc)
        a_ok = be.abs(a) > _TINY
        q_ok = be.abs(q) > _TINY
        t1 = q / be.where(a_ok, a, be.ones_like(a))
        t2 = c_0 / be.where(q_ok, q, be.ones_like(q))
        ok1 = disc_ok & a_ok
        ok2 = disc_ok & q_ok
        return [(t1, ok1), (t2, ok2)]

    def _refine(self, t0, origins, directions):
        """Newton-refine a starting distance on the sag residual."""
        ox, oy, oz = origins[:, 0], origins[:, 1], origins[:, 2]
        dx, dy, dz = directions[:, 0], directions[:, 1], directions[:, 2]
        t = t0
        for _ in range(self.max_iter):
            px = ox + t * dx
            py = oy + t * dy
            pz = oz + t * dz
            residual = pz - self._sag(px, py)
            n_raw = self._normal_local(px, py)
            slope = dz + n_raw[:, 0] * dx + n_raw[:, 1] * dy
            slope_ok = be.abs(slope) > _TINY
            step = residual / be.where(slope_ok, slope, be.ones_like(slope))
            t = be.where(slope_ok, t - step, t)
        px = ox + t * dx
        py = oy + t * dy
        pz = oz + t * dz
        residual = pz - self._sag(px, py)
        return t, px, py, pz, residual

    def _candidate_valid(self, t, px, py, pz, residual, start_ok, eps):
        r2 = px**2 + py**2
        in_aperture = r2 <= self.aperture_radius**2
        c = self._curvature()
        in_domain = (1.0 - (1.0 + self.conic) * c**2 * r2) >= 0.0
        converged = be.abs(residual) < _RESIDUAL_TOL
        return (
            start_ok & be.isfinite(t) & (t > eps) & in_aperture & in_domain & converged
        )

    def ray_intersect(self, origins, directions):
        """Intersect rays with the asphere by Newton refinement.

        Starting points are both roots of the base conic's quadric and the
        vertex-plane crossing; each is refined for ``max_iter`` Newton steps
        and the nearest converged root inside the aperture wins.

        Args:
            origins: Ray origins in local frame, shape (N, 3) [mm].
            directions: Ray directions in local frame, shape (N, 3).

        Returns:
            (t, normals, hit_mask, n_geom). n_geom points toward local +z
            (the ``material_back`` side by contract; see
            :meth:`ComponentGeometry.ray_intersect`).
        """
        oz = origins[:, 2]
        dz = directions[:, 2]
        eps = 1e-9

        starts = self._conic_roots(origins, directions)
        plane_ok = be.abs(dz) > _TINY
        t_plane = -oz / be.where(plane_ok, dz, be.ones_like(dz))
        starts.append((t_plane, plane_ok))

        t_best = be.ones_like(oz) * be.inf
        px_best = be.zeros_like(oz)
        py_best = be.zeros_like(oz)
        hit_mask = be.zeros_like(oz) > 1.0  # all False, backend-native bool
        for t0, start_ok in starts:
            t0_safe = be.where(start_ok & be.isfinite(t0), t0, be.zeros_like(t0))
            t, px, py, pz, residual = self._refine(t0_safe, origins, directions)
            valid = self._candidate_valid(t, px, py, pz, residual, start_ok, eps)
            better = valid & (t < t_best)
            t_best = be.where(better, t, t_best)
            px_best = be.where(better, px, px_best)
            py_best = be.where(better, py, py_best)
            hit_mask = hit_mask | better

        n_raw = self._normal_local(px_best, py_best)
        n_len = (n_raw * n_raw).sum(axis=1, keepdims=True) ** 0.5
        n_geom = n_raw / (n_len + 1e-30)
        dot = (directions * n_geom).sum(axis=1, keepdims=True)
        normals = be.where(dot > 0, -n_geom, n_geom)
        t_out = be.where(hit_mask, t_best, be.ones_like(t_best) * be.inf)
        return t_out, normals, hit_mask, n_geom

    # -- bounds --------------------------------------------------------------

    def sag_float(self, r: float) -> float:
        """Sag at radial position ``r`` [mm] from detached floats."""
        return float(sag_array(self, np.array([float(r)]))[0])

    def bounding_box(self, transform: tuple[np.ndarray, np.ndarray]) -> AABB:
        """Return the AABB in global coordinates from a sampled sag profile.

        Args:
            transform: (translation, rotation_matrix).

        Returns:
            AABB in global frame.
        """
        t_vec = np.array(transform[0], dtype=float)
        rot = np.array(transform[1], dtype=float)
        r = as_float(self.aperture_radius)
        z = sag_array(self, np.linspace(0.0, r, 65))
        z_min = min(0.0, float(np.nanmin(z)))
        z_max = max(0.0, float(np.nanmax(z)))
        corners_local = np.array(
            [
                [-r, -r, z_min],
                [-r, r, z_min],
                [r, -r, z_min],
                [r, r, z_min],
                [-r, -r, z_max],
                [-r, r, z_max],
                [r, -r, z_max],
                [r, r, z_max],
            ],
            dtype=float,
        )
        corners_global = corners_local @ rot.T + t_vec
        return AABB(corners_global.min(axis=0), corners_global.max(axis=0))


def sag_array(geometry: EvenAsphereGeometry, r: np.ndarray) -> np.ndarray:
    """Detached NumPy sag profile of an even asphere.

    Args:
        geometry: The asphere.
        r: Radial positions [mm], shape (N,).

    Returns:
        Sag values [mm], shape (N,); NaN beyond the conic's domain.
    """
    radius = as_float(geometry.radius)
    conic = as_float(geometry.conic)
    r = np.asarray(r, dtype=float)
    r2 = r * r
    if radius == 0.0 or not np.isfinite(radius):
        z = np.zeros_like(r2)
    else:
        c = 1.0 / radius
        under_root = 1.0 - (1.0 + conic) * c * c * r2
        with np.errstate(invalid="ignore"):
            z = c * r2 / (1.0 + np.sqrt(under_root))
    for i, ci in enumerate(geometry.coefficients):
        z = z + as_float(ci) * r2 ** (i + 1)
    return z
