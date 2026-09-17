"""2D and 3D renderers for NSQ sources.

Sources have no geometry of their own, so they are drawn as a marker at the
source origin plus an arrow along the emission axis (the source's local
``+z``). A collimated source additionally shows its aperture as a bar
across the beam; a point/extended source shows the edges of its emission
cone.

Kramer Harrison, 2026
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from optiland.nonsequential.visualization.renderers.lens import _projection_indices

if TYPE_CHECKING:
    from matplotlib.axes import Axes

_SOURCE_COLOR = (0.95, 0.6, 0.1)


def _arrow_length(scene) -> float:
    """A visible arrow length: 6 % of the scene's bounding diagonal."""
    from optiland.nonsequential._utils import estimate_bounding_scale  # noqa: PLC0415

    return max(1.0, 0.06 * estimate_bounding_scale(scene))


def _source_segments(source, length: float) -> list[np.ndarray]:
    """Line segments (global frame) that depict *source*."""
    from optiland.nonsequential.components.base import _get_transform  # noqa: PLC0415
    from optiland.nonsequential.sources.collimated import (  # noqa: PLC0415
        CollimatedSource,
    )

    translation, rot = _get_transform(source.cs)
    origin = np.asarray(translation, dtype=float)
    axis = rot @ np.array([0.0, 0.0, 1.0])
    segments = [np.stack([origin, origin + length * axis])]

    if isinstance(source, CollimatedSource):
        r = float(source.aperture_radius)
        for local_axis in (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])):
            across = rot @ local_axis
            segments.append(np.stack([origin - r * across, origin + r * across]))
            for sign in (-1.0, 1.0):
                start = origin + sign * r * across
                segments.append(np.stack([start, start + length * axis]))
    else:
        half_angle = np.radians(float(getattr(source, "half_angle_deg", 0.0)))
        half_angle = min(half_angle, np.radians(89.0))
        for local_axis in (np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])):
            across = rot @ local_axis
            for sign in (-1.0, 1.0):
                edge = np.cos(half_angle) * axis + sign * np.sin(half_angle) * across
                segments.append(np.stack([origin, origin + length * edge]))
    return segments


class SourceRenderer2D:
    """Renders a source as a marker with an emission arrow in 2D."""

    def render(
        self,
        source,
        ax: Axes,
        scene=None,
        theme=None,
        projection: str = "YZ",
    ) -> None:
        """Draw *source* onto *ax*.

        Args:
            source: A ``BaseNSQSource``.
            ax: Matplotlib axes.
            scene: The scene, used to size the arrow.
            theme: Optional theme.
            projection: Projection plane.
        """
        h_idx, v_idx = _projection_indices(projection)
        length = _arrow_length(scene) if scene is not None else 2.0
        color = _SOURCE_COLOR
        for seg in _source_segments(source, length):
            ax.plot(
                seg[:, h_idx],
                seg[:, v_idx],
                color=color,
                linewidth=1.2,
                zorder=5,
            )
        origin, tip = _source_segments(source, length)[0]
        ax.annotate(
            "",
            xy=(tip[h_idx], tip[v_idx]),
            xytext=(origin[h_idx], origin[v_idx]),
            arrowprops={"arrowstyle": "->", "color": color, "lw": 1.4},
            zorder=6,
        )
        ax.plot(
            [origin[h_idx]],
            [origin[v_idx]],
            marker="o",
            color=color,
            markersize=5,
            zorder=6,
            label=getattr(source, "name", None) or None,
        )


class SourceRenderer3D:
    """Renders a source as line actors in VTK."""

    def render(self, source, renderer, scene=None, theme=None) -> None:
        """Add VTK line actors for *source* to *renderer*.

        Args:
            source: A ``BaseNSQSource``.
            renderer: VTK renderer.
            scene: The scene, used to size the arrow.
            theme: Optional theme.
        """
        try:
            import vtk  # type: ignore[import]  # noqa: PLC0415
        except ImportError:
            return

        length = _arrow_length(scene) if scene is not None else 2.0
        points = vtk.vtkPoints()
        lines = vtk.vtkCellArray()
        for seg in _source_segments(source, length):
            i0 = points.InsertNextPoint(*seg[0])
            i1 = points.InsertNextPoint(*seg[1])
            line = vtk.vtkLine()
            line.GetPointIds().SetId(0, i0)
            line.GetPointIds().SetId(1, i1)
            lines.InsertNextCell(line)
        poly = vtk.vtkPolyData()
        poly.SetPoints(points)
        poly.SetLines(lines)
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(poly)
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*_SOURCE_COLOR)
        actor.GetProperty().SetLineWidth(2.0)
        renderer.AddActor(actor)
