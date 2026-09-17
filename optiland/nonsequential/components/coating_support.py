"""Shared coating/reflectance resolution for NSQ components.

RefractiveComponent (an ``optiland.coatings`` coating on a transmissive
interface) and ReflectiveComponent (a required reflectance on a mirror) both
need to validate that a coating is unpolarized and turn it into a per-ray
array. Centralized here so the two components agree on what is accepted.

Kramer Harrison, 2026
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import optiland.backend as be
from optiland.nonsequential._utils import as_float, as_param

if TYPE_CHECKING:
    from collections.abc import Callable

    from optiland.coatings import BaseCoating

# Slack on the ``R + T <= 1`` passivity check, so a coating built as
# ``SimpleCoating(transmittance=1 - R, reflectance=R)`` never trips it on
# rounding alone.
_PASSIVITY_TOLERANCE = 1e-9


def reject_polarized_coating(coating: object, *, surface_name: str) -> None:
    """Raise if ``coating`` is a Jones-matrix (polarized) coating.

    NSQ rays carry no polarization state, so a polarized coating cannot be
    evaluated correctly. Rather than silently falling back to some scalar
    average of its Jones matrix, refuse it outright.

    Args:
        coating: The candidate coating, or None / a plain float / a callable.
        surface_name: Name of the surface the coating is attached to, for
            the error message.

    Raises:
        NotImplementedError: If ``coating`` is a
            ``optiland.coatings.BaseCoatingPolarized`` instance.
    """
    from optiland.coatings import BaseCoatingPolarized  # noqa: PLC0415

    if isinstance(coating, BaseCoatingPolarized):
        raise NotImplementedError(
            f"Surface {surface_name!r} was given a polarized coating "
            f"({type(coating).__name__}); NSQ rays carry no polarization "
            "state, so Jones-matrix coatings cannot be evaluated. Use an "
            "unpolarized coating such as optiland.coatings.SimpleCoating, "
            "a constant reflectance, or a callable(wavelength_um) -> "
            "reflectance instead."
        )


def validate_passive_coating(coating: object, *, surface_name: str) -> None:
    """Raise if a constant-R/T coating is not a passive, finite one.

    A ``SimpleCoating``-style coating is a passive optical element: its
    reflectance and transmittance must be finite, non-negative, and sum to
    at most 1 (``R + T < 1`` is an absorbing coating, ``R + T == 1`` a
    lossless one). Anything else would create or destroy flux at the
    interface and break every energy-balance diagnostic downstream.
    Coatings without a scalar ``reflectance``/``transmittance`` pair (a
    callable, a polarized coating that :func:`reject_polarized_coating`
    handles) are left alone.

    Args:
        coating: The candidate coating, or ``None``.
        surface_name: Name of the surface the coating is attached to, for
            the error message.

    Raises:
        ValueError: If ``R`` or ``T`` is not finite, is negative, or
            ``R + T`` exceeds 1.
    """
    if coating is None:
        return
    reflectance = getattr(coating, "reflectance", None)
    transmittance = getattr(coating, "transmittance", None)
    if reflectance is None or transmittance is None:
        return
    if callable(reflectance) or callable(transmittance):
        return
    r_value = as_float(reflectance)
    t_value = as_float(transmittance)
    label = f"Surface {surface_name!r}" if surface_name else "Surface"
    if not (math.isfinite(r_value) and math.isfinite(t_value)):
        raise ValueError(
            f"{label}: coating reflectance/transmittance must be finite, got "
            f"R={r_value!r}, T={t_value!r}."
        )
    if r_value < 0.0 or t_value < 0.0:
        raise ValueError(
            f"{label}: coating reflectance and transmittance must be "
            f"non-negative, got R={r_value!r}, T={t_value!r}."
        )
    if r_value + t_value > 1.0 + _PASSIVITY_TOLERANCE:
        raise ValueError(
            f"{label}: a passive coating needs R + T <= 1, got "
            f"R={r_value!r}, T={t_value!r} (sum {r_value + t_value!r})."
        )


def validate_reflectance(reflectance: object, *, surface_name: str) -> None:
    """Raise if a constant mirror reflectance lies outside ``[0, 1]``.

    Callables are evaluated per ray at trace time and cannot be checked
    here; coatings are checked through :func:`validate_passive_coating`.

    Args:
        reflectance: A constant, a callable, or a coating.
        surface_name: Name of the surface, for the error message.

    Raises:
        ValueError: If a constant reflectance is not finite or not in
            ``[0, 1]``.
    """
    if reflectance is None or callable(reflectance):
        return
    if hasattr(reflectance, "transmittance"):
        validate_passive_coating(reflectance, surface_name=surface_name)
        return
    value = as_float(reflectance)
    label = f"Surface {surface_name!r}" if surface_name else "Surface"
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError(
            f"{label}: mirror reflectance must be a finite value in [0, 1], "
            f"got {value!r}."
        )


def coating_coefficient(value: object) -> object:
    """Return a coating coefficient ready to multiply a per-ray array.

    A ``torch.Tensor`` (possibly with ``requires_grad=True``) is passed
    through untouched so ``d(flux)/dR`` reaches it under the Torch backend;
    anything else becomes a plain float. Used by
    ``RefractiveComponent.interact`` for ``coating.reflectance`` and
    ``coating.transmittance``.

    Args:
        value: The coating's scalar coefficient.

    Returns:
        The tensor unchanged, or ``float(value)``.
    """
    return as_param(value)


def resolve_reflectance(
    reflectance: float | Callable[[be.ndarray], be.ndarray] | BaseCoating,
    wavelength: be.ndarray,
) -> be.ndarray:
    """Turn a mirror's ``reflectance`` spec into a per-ray array.

    Args:
        reflectance: A constant, a ``callable(wavelength_um) -> reflectance``,
            or an unpolarized ``optiland.coatings.BaseCoating`` (read via its
            ``.reflectance`` attribute, e.g. ``SimpleCoating``).
        wavelength: Per-ray wavelength [µm], shape (N,); used only to build
            the broadcast shape for a constant/coating reflectance.

    Returns:
        Per-ray reflectance, shape (N,).
    """
    from optiland.coatings import BaseCoating  # noqa: PLC0415

    if isinstance(reflectance, BaseCoating):
        return be.ones_like(wavelength) * coating_coefficient(reflectance.reflectance)
    if callable(reflectance):
        return be.ones_like(wavelength) * be.array(reflectance(wavelength))
    return be.ones_like(wavelength) * coating_coefficient(reflectance)
