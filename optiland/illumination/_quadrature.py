"""Representative nodes of a one-dimensional density.

The LED ring turns two densities into a handful of sequential samples: the
emitting area over the radius (field points) and the spectral power over
the wavelength (system wavelengths). Both use the same rule, so it lives
here once.

Kramer Harrison, 2026
"""

from __future__ import annotations

import numpy as np


def equal_share_nodes(x: np.ndarray, density: np.ndarray, count: int) -> np.ndarray:
    """Centroids of ``count`` consecutive intervals of equal integral.

    The interval ``[x[0], x[-1]]`` is cut into ``count`` pieces that each
    hold the same share of the integral of ``density``; each node is the
    density-weighted centroid of its piece. Equal shares mean equal
    weights, so every node stands for the same part of the whole.

    Args:
        x: Increasing sample positions.
        density: Non-negative density at ``x``, linear between samples.
        count: Number of nodes (at least 1).

    Returns:
        The ``count`` nodes, increasing.

    Raises:
        ValueError: If ``count`` is below 1 or the density integrates to
            zero.
    """
    if count < 1:
        raise ValueError(f"count must be at least 1, got {count}.")
    x = np.asarray(x, dtype=np.float64)
    density = np.asarray(density, dtype=np.float64)
    dx = np.diff(x)
    # Cumulative integral and first moment; the moment of each linear
    # segment is exact for a density that is linear on it.
    mass = np.concatenate(([0.0], np.cumsum(0.5 * dx * (density[:-1] + density[1:]))))
    seg_moment = (
        dx
        / 6.0
        * (density[:-1] * (2.0 * x[:-1] + x[1:]) + density[1:] * (x[:-1] + 2.0 * x[1:]))
    )
    moment = np.concatenate(([0.0], np.cumsum(seg_moment)))
    total = mass[-1]
    if not total > 0.0:
        raise ValueError("The density integrates to zero; it has no nodes.")
    shares = np.linspace(0.0, total, count + 1)
    edge_moment = np.interp(shares, mass, moment)
    return np.diff(edge_moment) / np.diff(shares)
