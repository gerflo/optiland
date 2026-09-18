"""2D and 3D renderers for single-surface compound components.

A :class:`~optiland.nonsequential.components.compound.SingleSurfaceCompound`
(what ``NSQScene.add_component`` wraps a raw ``RefractiveComponent`` /
``ReflectiveComponent`` / ``AbsorbingComponent`` in -- a beam-splitter
plate, a fold mirror, a baffle) is drawn from its geometry alone:

- planar geometries as the projected outline of their clear aperture,
  which is a line for a plate seen edge-on and an ellipse for a tilted
  plate seen from the side;
- conic and spherical geometries as their meridional sag profile.

Kramer Harrison, 2026
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from optiland.nonsequential._utils import as_float
from optiland.nonsequential.visualization.renderers.base import (
    ComponentRenderer2D,
    ComponentRenderer3D,
)
from optiland.nonsequential.visualization.renderers.lens import (
    _projection_indices,
    _sag_array,
)

if TYPE_CHECKING:
    from matplotlib.axes import Axes

    from optiland.nonsequential.components.base import BaseComponent
    from optiland.nonsequential.components.compound import CompoundComponent

_N_OUTLINE = 96
_N_PROFILE = 128

# Line colours per interaction, used when no theme colour applies.
_KIND_COLORS = {
    "refractive": (0.35, 0.55, 0.85),
    "reflective": (0.55, 0.55, 0.55),
    "absorbing": (0.2, 0.2, 0.2),
}


def _component_kind(component: BaseComponent) -> str:
    """Return the IR component kind of a live surface (for colouring)."""
    from optiland.nonsequential.ir.lower import _component_kind  # noqa: PLC0415

    try:
        return _component_kind(component)
    except Exception:  # noqa: BLE001 -- colouring only, never fatal
        return "refractive"


def _local_outline(geometry) -> np.ndarray | None:
    """Closed outline of a planar geometry's clear aperture, local frame."""
    from optiland.nonsequential.components.geometry.analytic.annulus import (  # noqa: PLC0415
        AnnularPlaneGeometry,
    )
    from optiland.nonsequential.components.geometry.analytic.plane import (  # noqa: PLC0415
        FinitePlaneGeometry,
        PlaneGeometry,
    )

    if isinstance(geometry, FinitePlaneGeometry):
        if geometry.aperture_radius is not None:
            r = as_float(geometry.aperture_radius)
            phi = np.linspace(0.0, 2.0 * np.pi, _N_OUTLINE + 1)
            return np.stack(
                [r * np.cos(phi), r * np.sin(phi), np.zeros_like(phi)], axis=1
            )
        hw = as_float(geometry.width) / 2.0
        hh = as_float(geometry.height) / 2.0
        return np.array(
            [[-hw, -hh, 0], [hw, -hh, 0], [hw, hh, 0], [-hw, hh, 0], [-hw, -hh, 0]],
            dtype=float,
        )
    if isinstance(geometry, PlaneGeometry):
        # Unbounded: draw a nominal 10 mm square so it is visible at all.
        s = 5.0
        return np.array(
            [[-s, -s, 0], [s, -s, 0], [s, s, 0], [-s, s, 0], [-s, -s, 0]],
            dtype=float,
        )
    if isinstance(geometry, AnnularPlaneGeometry):
        # Outer rim, then the hole outline, joined through a NaN break.
        phi = np.linspace(0.0, 2.0 * np.pi, _N_OUTLINE + 1)
        z = as_float(geometry.z_offset)
        r_out = as_float(geometry.outer_radius)
        a = as_float(geometry.inner_radius)
        b = as_float(geometry.inner_radius_y) if geometry.is_elliptical else a
        outer = np.stack(
            [r_out * np.cos(phi), r_out * np.sin(phi), np.full_like(phi, z)], axis=1
        )
        hole = np.stack(
            [a * np.cos(phi), b * np.sin(phi), np.full_like(phi, z)], axis=1
        )
        gap = np.full((1, 3), np.nan)
        return np.concatenate([outer, gap, hole], axis=0)
    return None


def _local_profile(geometry, axis: int) -> np.ndarray | None:
    """Meridional sag profile of a conic/spherical geometry, local frame.

    Args:
        geometry: A ``ConicGeometry`` or ``SphereGeometry``.
        axis: 0 to sweep local x, 1 to sweep local y.

    Returns:
        ``(N, 3)`` local points, or ``None`` for unsupported geometries.
    """
    from optiland.nonsequential.components.geometry.analytic.asphere import (  # noqa: PLC0415
        EvenAsphereGeometry,
        sag_array,
    )
    from optiland.nonsequential.components.geometry.analytic.conic import (  # noqa: PLC0415
        ConicGeometry,
    )
    from optiland.nonsequential.components.geometry.analytic.sphere import (  # noqa: PLC0415
        SphereGeometry,
    )

    if isinstance(geometry, EvenAsphereGeometry):
        r_ap = as_float(geometry.aperture_radius)
        h = np.linspace(-r_ap, r_ap, _N_PROFILE)
        z = sag_array(geometry, np.abs(h))
    elif isinstance(geometry, ConicGeometry):
        r_ap = as_float(geometry.aperture_radius)
        h = np.linspace(-r_ap, r_ap, _N_PROFILE)
        z = _sag_array(as_float(geometry.radius), as_float(geometry.conic), h)
    elif isinstance(geometry, SphereGeometry):
        radius = as_float(geometry.radius)
        r_ap = (
            as_float(geometry.aperture_radius)
            if geometry.aperture_radius is not None
            else abs(radius)
        )
        r_ap = min(r_ap, abs(radius))
        h = np.linspace(-r_ap, r_ap, _N_PROFILE)
        z = _sag_array(radius, 0.0, h)
    else:
        return None
    pts = np.zeros((h.size, 3))
    pts[:, axis] = h
    pts[:, 2] = z
    return pts


def _color(component: BaseComponent, theme) -> object:
    color = _KIND_COLORS.get(_component_kind(component), (0.5, 0.5, 0.5))
    if theme is not None and _component_kind(component) != "refractive":
        color = theme.parameters.get("axes.edgecolor", color)
    return color


class SurfaceRenderer2D(ComponentRenderer2D):
    """Renders a single-surface compound as an outline or sag profile."""

    def render(
        self,
        component: CompoundComponent,
        ax: Axes,
        theme=None,
        projection: str = "YZ",
    ) -> None:
        """Draw the surface onto *ax*.

        Args:
            component: A ``SingleSurfaceCompound``.
            ax: Matplotlib axes.
            theme: Optional theme.
            projection: Projection plane.
        """
        from optiland.nonsequential.components.base import (  # noqa: PLC0415
            _get_transform,
        )
        from optiland.nonsequential.components.compound import (  # noqa: PLC0415
            SingleSurfaceCompound,
        )

        if not isinstance(component, SingleSurfaceCompound):
            return
        surface = component.component
        translation, rot = _get_transform(surface.cs)
        h_idx, v_idx = _projection_indices(projection)

        pts_local = _local_outline(surface.geometry)
        if pts_local is None:
            axis = 0 if projection.upper() == "XZ" else 1
            pts_local = _local_profile(surface.geometry, axis)
        if pts_local is None:
            return

        pts_global = pts_local @ rot.T + translation
        ax.plot(
            pts_global[:, h_idx],
            pts_global[:, v_idx],
            color=_color(surface, theme),
            linewidth=2.0,
            zorder=3,
            label=component.name,
        )


class SurfaceRenderer3D(ComponentRenderer3D):
    """Renders a single-surface compound as a VTK polygon or revolved cap."""

    def render(
        self,
        component: CompoundComponent,
        renderer,
        theme=None,
    ) -> None:
        """Add a VTK actor for the surface to *renderer*.

        Args:
            component: A ``SingleSurfaceCompound``.
            renderer: VTK renderer.
            theme: Optional theme.
        """
        from optiland.nonsequential.components.base import (  # noqa: PLC0415
            _get_transform,
        )
        from optiland.nonsequential.components.compound import (  # noqa: PLC0415
            SingleSurfaceCompound,
        )

        if not isinstance(component, SingleSurfaceCompound):
            return
        try:
            import vtk  # type: ignore[import]  # noqa: PLC0415
        except ImportError:
            return

        surface = component.component
        translation, rot = _get_transform(surface.cs)
        outline = _local_outline(surface.geometry)

        if outline is not None:
            pts_global = outline[:-1] @ rot.T + translation
            points = vtk.vtkPoints()
            polygon = vtk.vtkPolygon()
            polygon.GetPointIds().SetNumberOfIds(len(pts_global))
            for i, pt in enumerate(pts_global):
                points.InsertNextPoint(*pt)
                polygon.GetPointIds().SetId(i, i)
            cells = vtk.vtkCellArray()
            cells.InsertNextCell(polygon)
            poly = vtk.vtkPolyData()
            poly.SetPoints(points)
            poly.SetPolys(cells)
            mapper = vtk.vtkPolyDataMapper()
            mapper.SetInputData(poly)
            actor = vtk.vtkActor()
            actor.SetMapper(mapper)
        else:
            profile = _local_profile(surface.geometry, 1)
            if profile is None:
                return
            try:
                from optiland.visualization.system.utils import (  # noqa: PLC0415
                    revolve_contour,
                )
            except ImportError:
                return
            half = profile[profile[:, 1] >= 0.0]
            pts_global = half @ rot.T + translation
            actor = revolve_contour(
                pts_global[:, 0], pts_global[:, 1], pts_global[:, 2]
            )

        color = _KIND_COLORS.get(_component_kind(surface), (0.5, 0.5, 0.5))
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(0.6 if _component_kind(surface) == "refractive" else 1.0)
        renderer.AddActor(actor)
