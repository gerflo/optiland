"""CompoundComponent ABC for Non-Sequential Raytracing.

A compound component manages a group of sub-surfaces that together represent
a single optical element (e.g. a lens with front face, back face, and edge).
The tracer never sees compound objects -- it works on the flat list of
BaseComponent surfaces exposed by each compound.

Kramer Harrison, 2026
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from optiland.coordinate_system import CoordinateSystem
    from optiland.nonsequential.components.base import BaseComponent


class CompoundComponent(ABC):
    """Abstract base class for multi-surface optical elements.

    A ``CompoundComponent`` is a logical grouping of one or more
    :class:`~optiland.nonsequential.components.base.BaseComponent` surfaces
    that collectively form a single optical element.  Compound components are
    stored in the :class:`ComponentRegistry`; when the tracer needs a flat
    surface list it calls :attr:`surfaces` on each compound.

    Subclasses must implement :attr:`name`, :attr:`surfaces`, and
    :attr:`coordinate_system`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable identifier for this compound component."""

    @property
    @abstractmethod
    def surfaces(self) -> list[BaseComponent]:
        """Ordered flat list of sub-surfaces for intersection testing."""

    @property
    @abstractmethod
    def coordinate_system(self) -> CoordinateSystem:
        """Primary coordinate system (front vertex for lenses, surface for mirrors)."""


class SingleSurfaceCompound(CompoundComponent):
    """A compound made of exactly one raw surface.

    This is what :meth:`~optiland.nonsequential.scene.NSQScene.add_component`
    wraps a bare ``RefractiveComponent``/``ReflectiveComponent``/
    ``AbsorbingComponent`` in -- a beam-splitter plate, a fold mirror, a
    baffle -- so the registry, the serializer and the viewers can treat it
    like any other compound.

    Args:
        name: Registry name.
        component: The wrapped surface.
    """

    def __init__(self, name: str, component: BaseComponent) -> None:
        self._name = name
        self._component = component

    @property
    def name(self) -> str:
        return self._name

    @property
    def component(self) -> BaseComponent:
        """The wrapped surface."""
        return self._component

    @property
    def surfaces(self) -> list[BaseComponent]:
        return [self._component]

    @property
    def coordinate_system(self) -> CoordinateSystem:
        return self._component.cs

    def __repr__(self) -> str:
        return (
            f"SingleSurfaceCompound(name={self._name!r}, component={self._component!r})"
        )
