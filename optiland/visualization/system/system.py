"""System Visualization Module

This module contains the OpticalSystem class for visualizing optical systems.

Kramer Harrison, 2024
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import numpy as np

import optiland.backend as be
from optiland.physical_apertures.base import DifferenceAperture
from optiland.physical_apertures.radial import RadialAperture
from optiland.visualization.system.lens import Lens2D, Lens3D
from optiland.visualization.system.mirror import Mirror3D
from optiland.visualization.system.surface import Surface2D, Surface3D
from optiland.visualization.system.utils import transform, transform_3d

if TYPE_CHECKING:
    from optiland.visualization.component_renderer import ComponentRenderer

# Registry for user-defined ComponentRenderer extensions.
# Built-in component types ("lens", "mirror", "surface") are handled via the
# internal component_registry on each OpticalSystem instance.
_CUSTOM_RENDERER_REGISTRY: dict[str, ComponentRenderer] = {}

STOP_COLOR = "#9B30FF"  # purple: visible on both dark and light
APERTURE_COLOR = "#7700CC"  # darker purple for non-stop apertures
MASK_COLOR = "#E8202A"  # red: mask stops, visible on both dark and light

# 2D mask body: a bar this thick (points), sampled at this many points per
# blocked zone so it follows a curved surface instead of cutting its chord.
MASK_LINE_WIDTH = 3.5
_MASK_SAMPLES = 33


def mask_zone(aperture) -> tuple[float, float] | None:
    """The radial zone ``(r_min, r_max)`` a mask stop blocks.

    A mask stop is a clear circle minus a centred disk (``r_min == 0``) or
    ring: ``DifferenceAperture(RadialAperture, RadialAperture)``, as the
    GUI's Circular/Annular Mask and the anti-reflex dots define it.

    Args:
        aperture: A surface's physical aperture, or None.

    Returns:
        The blocked zone in the surface's local frame, or None when the
        aperture is not such a mask (including a decentred blocking disk).
    """
    if not isinstance(aperture, DifferenceAperture):
        return None
    blocked = aperture.b
    if not isinstance(blocked, RadialAperture):
        return None
    if float(getattr(blocked, "offset_x", 0.0)) or float(
        getattr(blocked, "offset_y", 0.0)
    ):
        return None
    r_min = float(be.to_numpy(blocked.r_min))
    r_max = float(be.to_numpy(blocked.r_max))
    if not r_max > r_min:
        return None
    return r_min, r_max


class _CustomRendererAdapter:
    """Adapts a ComponentRenderer to the plot()-based component interface."""

    def __init__(
        self,
        renderer: ComponentRenderer,
        component_data: dict,
        projection: str,
    ) -> None:
        self._renderer = renderer
        self._component_data = component_data
        self._projection = projection

    def plot(self, ax, **kwargs):
        if self._projection == "2d":
            self._renderer.render_2d(ax, self._component_data)
        else:
            self._renderer.render_3d(ax, self._component_data)
        return {}


class OpticalSystem:
    """A class to represent an optical system for visualization. The optical
    system contains surfaces and lenses.

    Args:
        optic (Optic): The optical system to be used for plotting.
        rays (Rays): The rays interacting with the optical system.
        projection (str): The type of projection for visualization.
            Must be '2d' or '3d'.

    Attributes:
        optic (Optic): The optical system to be used for plotting.
        rays (Rays): The rays interacting with the optical system.
        projection (str): The type of projection for visualization.
            Must be '2d' or '3d'.
        components (list): A list to store the components of the optical
            system.
        component_registry (dict): A registry mapping component names to their
            respective classes for 2D and 3D projections.

    Methods:
        plot(ax):
            Identifies and plots the components of the optical system on the
                given axis (or renderer for 3D plotting).

    """

    def __init__(self, optic, rays, projection="2d"):
        self.optic = optic
        self.rays = rays
        self.projection = projection
        self.components = []  # initialize empty list of components

        if self.projection not in ["2d", "3d"]:
            raise ValueError("Invalid projection type. Must be '2d' or '3d'.")

        self.component_registry = {
            "lens": {"2d": Lens2D, "3d": Lens3D},
            "mirror": {"2d": Surface2D, "3d": Mirror3D},
            "surface": {"2d": Surface2D, "3d": Surface3D},
        }

    @classmethod
    def register_component_renderer(
        cls,
        component_type: str,
        renderer: ComponentRenderer,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a renderer for a custom component type.

        The registered renderer is used when ``_identify_components`` adds a
        component of this type. Custom types are checked before the built-in
        registry, so this can also override existing built-in types when
        ``overwrite=True``.

        Args:
            component_type: String key identifying the component type.
            renderer: A ComponentRenderer instance.
            overwrite: Allow replacing an existing registration.

        Raises:
            ValueError: If component_type is already registered and
                overwrite is False.
        """
        if component_type in _CUSTOM_RENDERER_REGISTRY and not overwrite:
            raise ValueError(
                f"Component type '{component_type}' is already registered. "
                "Pass overwrite=True to replace it."
            )
        _CUSTOM_RENDERER_REGISTRY[component_type] = renderer

    def plot(
        self,
        ax,
        theme=None,
        projection="YZ",
        show_apertures=True,
        show_stop_apertures=True,
        show_non_stop_apertures=True,
        hide_internal_surfaces=False,
        show_masks=None,
    ):
        """Plots the components of the optical system on the given
        axis (or renderer for 3D plotting).

        Args:
            show_apertures: Draw the aperture markers of the stop and the
                other surfaces with an aperture.
            show_stop_apertures: 3D only: draw the stop's aperture marker.
            show_non_stop_apertures: 3D only: draw the other surfaces'
                aperture markers.
            hide_internal_surfaces: Draw compound lenses by their outer
                surfaces only.
            show_masks: Draw mask stops (see :func:`mask_zone`) in red, with
                their blocking disk or ring. None follows ``show_apertures``.

        Returns:
            dict: Every drawn artist (2D) or actor (3D) mapped to what it
                shows: the component for lenses and standalone surfaces, the
                surface for aperture and mask markers.
        """
        self._identify_components(hide_internal_surfaces=hide_internal_surfaces)
        artists = {}
        for component in self.components:
            component_artists = component.plot(ax, theme=theme, projection=projection)
            if component_artists:
                artists.update(component_artists)
        if show_masks is None:
            show_masks = show_apertures
        if show_apertures or show_masks:
            if self.projection == "2d":
                aperture_artists = self._plot_apertures(
                    ax,
                    theme=theme,
                    projection=projection,
                    show_apertures=show_apertures,
                    show_masks=show_masks,
                )
            else:
                aperture_artists = self._plot_apertures_3d(
                    ax,
                    theme=theme,
                    show_stop=show_apertures and show_stop_apertures,
                    show_non_stop=show_apertures and show_non_stop_apertures,
                    show_masks=show_masks,
                )
            artists.update(aperture_artists)
        return artists

    def _identify_components(self, hide_internal_surfaces=False):
        """Identifies the components of the optical system and adds them to the
        list of components.
        """
        self.components = []
        n = self.optic.surfaces.n(self.optic.primary_wavelength)  # refractive indices
        num_surf = self.optic.surfaces.num_surfaces

        lens_surfaces = []

        for k, surf in enumerate(self.optic.surfaces):
            extent = self.rays.r_extent[k]

            # Object surface at infinity: nothing to draw
            if k == 0 and surf.is_infinite:
                continue

            # Object, image, or paraxial surface
            if k == 0 or k == num_surf - 1 or surf.surface_type == "paraxial":
                self._add_component("surface", surf, extent)

            # Surface is a mirror
            elif surf.interaction_model.is_reflective:
                lens_surfaces = self._add_mirror_component(
                    surf, extent, lens_surfaces, hide_internal_surfaces
                )

            # Front or back surface of a lens
            elif n[k] > 1 or (n[k] == 1 and n[k - 1] > 1 and lens_surfaces):
                lens_surfaces = self._add_lens_edge_component(
                    surf, extent, n[k], lens_surfaces, hide_internal_surfaces
                )

            # Standalone phase surface
            elif surf.interaction_model.interaction_type == "phase":
                self._add_component("surface", surf, extent)

        # add final lens, if any
        if lens_surfaces:
            self._add_component(
                "lens",
                self._visible_lens_surfaces(lens_surfaces, hide_internal_surfaces),
            )

    @staticmethod
    def _visible_lens_surfaces(lens_surfaces: list, hide_internal: bool) -> list:
        """Reduce a lens to its outer surfaces when internal ones are hidden."""
        if hide_internal and len(lens_surfaces) > 2:
            return [lens_surfaces[0], lens_surfaces[-1]]
        return lens_surfaces

    def _add_mirror_component(
        self, surf, extent, lens_surfaces: list, hide_internal: bool = False
    ) -> list:
        """Add a standalone mirror, or close out a second-surface mirror lens.

        Returns the (possibly reset) `lens_surfaces` accumulator.
        """
        if lens_surfaces:  # Second surface mirror (lens + mirror)
            lens_surfaces.append(self._get_lens_surface(surf, extent))
            self._add_component(
                "lens", self._visible_lens_surfaces(lens_surfaces, hide_internal)
            )
            return []
        self._add_component("mirror", surf, extent)
        return lens_surfaces

    def _add_lens_edge_component(
        self,
        surf,
        extent,
        n_k: float,
        lens_surfaces: list,
        hide_internal: bool = False,
    ) -> list:
        """Append a front or back lens surface; close out the lens on the back one.

        Returns the (possibly reset) `lens_surfaces` accumulator.
        """
        lens_surfaces.append(self._get_lens_surface(surf, extent))
        if n_k == 1:  # back surface: n drops back to 1, closing out the lens
            self._add_component(
                "lens", self._visible_lens_surfaces(lens_surfaces, hide_internal)
            )
            return []
        return lens_surfaces

    def _add_component(self, component_name, *args):
        """Adds a component to the list of components."""
        if component_name in _CUSTOM_RENDERER_REGISTRY:
            renderer = _CUSTOM_RENDERER_REGISTRY[component_name]
            component_data = {"args": args, "projection": self.projection}
            self.components.append(
                _CustomRendererAdapter(renderer, component_data, self.projection)
            )
            return
        if component_name in self.component_registry:
            component_class = self.component_registry[component_name][self.projection]
            self.components.append(component_class(*args))
            return
        raise ValueError(f"Component {component_name} not found in registry.")

    def _get_lens_surface(self, surface, *args):
        """Gets the lens surface based on the projection type."""
        surface_class = self.component_registry["surface"][self.projection]
        return surface_class(surface, *args)

    def _aperture_extent(self, surface, idx: int):
        """The (x_min, x_max, y_min, y_max) box to draw this surface's
        aperture indicator in, or None if there's nothing to draw.
        """
        if surface.aperture is not None:
            return surface.aperture.extent

        r = self._aperture_radius(surface, idx)
        if r is None:
            return None
        return -r, r, -r, r

    def _aperture_radius(self, surface, idx: int) -> float | None:
        """The isotropic radius to draw for a circular aperture indicator
        (semi-aperture, float-by-stop-size, or ray extent at the stop), or
        None if none applies.
        """
        if surface.semi_aperture is not None:
            return float(be.to_numpy(surface.semi_aperture))
        if (
            surface.is_stop
            and self.optic.aperture is not None
            and self.optic.aperture.ap_type == "float_by_stop_size"
        ):
            return float(0.5 * self.optic.aperture.value)
        if surface.is_stop and self.rays is not None:
            r = float(be.to_numpy(self.rays.r_extent[idx]).item())
            return r if r > 0 else None
        return None

    @staticmethod
    def _local_aperture_coords(projection: str, extent: tuple):
        # Only the axis actually shown in this projection is swept between
        # its aperture bounds; the other is held at 0 (its axis-of-symmetry
        # value) rather than paired corner-to-corner, which would otherwise
        # mix in the wrong sag contribution for offset apertures.
        x_min, x_max, y_min, y_max = extent
        if projection == "XZ":
            return be.array([x_min, x_max]), be.array([0.0, 0.0])
        return be.array([0.0, 0.0]), be.array([y_min, y_max])  # YZ

    @staticmethod
    def _aperture_indicator_globals(surface, projection, x_local, y_local):
        """Sag-projected global (z, in-plane) coordinates of an aperture
        indicator's two endpoints.

        The sag is evaluated at each point (instead of assuming z=0) so the
        indicator line follows the true, possibly-tilted surface instead of
        a flat plane through the vertex. Apertures with an unbounded extent
        (e.g. an annular obstruction defined with r_max = inf) have no
        well-defined sag at their outer edge; fall back to the vertex plane
        there rather than evaluating sag() out of its domain.
        """
        finite = be.isfinite(x_local) & be.isfinite(y_local)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            z_local = be.where(finite, surface.geometry.sag(x_local, y_local), 0.0)
        x_global, y_global, z_global = transform(
            x_local, y_local, z_local, surface, is_global=False
        )
        axis_vals = x_global if projection == "XZ" else y_global
        return be.to_numpy(z_global), be.to_numpy(axis_vals)

    @staticmethod
    def _draw_aperture_indicator(
        ax, z_global, axis_vals, facecolor: str, inward: bool = False
    ):
        (line,) = ax.plot(z_global, axis_vals, color=facecolor, linewidth=1.5)

        eps = 1e-6
        arrowprops = {
            "arrowstyle": "-|>",
            "facecolor": facecolor,
            "edgecolor": facecolor,
            "linewidth": 0,
            "mutation_scale": 8,
        }
        direction = -1 if inward else 1  # inward: arrows point toward the axis
        for z_val, axis_val, sign in (
            (z_global[1], axis_vals[1], direction),  # top
            (z_global[0], axis_vals[0], -direction),  # bottom
        ):
            ax.annotate(
                "",
                xy=(z_val, axis_val),
                xytext=(z_val, axis_val + sign * eps),
                arrowprops=arrowprops,
            )
        return line

    @staticmethod
    def _local_zone_coords(projection: str, lo: float, hi: float):
        """Local points sampled from ``lo`` to ``hi`` along the shown axis."""
        t = be.linspace(lo, hi, _MASK_SAMPLES)
        if projection == "XZ":
            return t, be.zeros_like(t)
        return be.zeros_like(t), t  # YZ

    def _draw_mask_body(self, ax, surface, projection: str, zone) -> list:
        """Draw the blocked zone of a mask stop as thick red bars on its surface.

        A centred disk is one bar across the axis; a ring is two bars, one
        on either side of the axis.

        Returns:
            list: The drawn lines.
        """
        r_min, r_max = zone
        segments = (
            [(-r_max, r_max)] if r_min == 0 else [(r_min, r_max), (-r_max, -r_min)]
        )
        lines = []
        for lo, hi in segments:
            x_local, y_local = self._local_zone_coords(projection, lo, hi)
            z_global, axis_vals = self._aperture_indicator_globals(
                surface, projection, x_local, y_local
            )
            (line,) = ax.plot(
                z_global,
                axis_vals,
                color=MASK_COLOR,
                linewidth=MASK_LINE_WIDTH,
                solid_capstyle="butt",
            )
            lines.append(line)
        return lines

    def _plot_apertures(
        self, ax, theme=None, projection="YZ", show_apertures=True, show_masks=True
    ):
        """Draw the aperture markers and mask stops onto a 2D axis.

        The stop is purple, other apertures dark purple. A mask stop is red:
        its clear edge like an aperture marker, its blocking disk or ring as
        a thick bar that follows the surface. A mask on the stop surface keeps
        the stop's purple edge.

        Args:
            show_apertures: Draw the markers of the stop and the apertures
                that are no mask.
            show_masks: Draw the mask stops (clear edge and blocked zone).

        Returns:
            dict: Every drawn line mapped to the surface it marks.
        """
        if projection == "XY":
            return {}
        if projection not in ("XZ", "YZ"):
            raise ValueError("Invalid projection type. Must be 'XY', 'XZ', or 'YZ'.")

        artists = {}
        for idx, surface in enumerate(self.optic.surfaces):
            # Skip surfaces without any aperture indicator (unless it is the stop)
            if surface.aperture is None and not surface.is_stop:
                continue
            zone = mask_zone(surface.aperture)
            if surface.is_stop:
                facecolor, show_edge = STOP_COLOR, show_apertures
            elif zone is not None:
                facecolor, show_edge = MASK_COLOR, show_masks
            else:
                facecolor, show_edge = APERTURE_COLOR, show_apertures

            extent = self._aperture_extent(surface, idx) if show_edge else None
            if extent is not None:
                x_local, y_local = self._local_aperture_coords(projection, extent)
                z_global, axis_vals = self._aperture_indicator_globals(
                    surface, projection, x_local, y_local
                )
                line = self._draw_aperture_indicator(ax, z_global, axis_vals, facecolor)
                artists[line] = surface

                # For ring apertures (r_min > 0): draw the inner blocking edge too
                if (
                    isinstance(surface.aperture, RadialAperture)
                    and surface.aperture.r_min > 0
                ):
                    r_in = float(surface.aperture.r_min)
                    xi_local, yi_local = self._local_aperture_coords(
                        projection, (-r_in, r_in, -r_in, r_in)
                    )
                    zi_global, axis_vals_i = self._aperture_indicator_globals(
                        surface, projection, xi_local, yi_local
                    )
                    line_i = self._draw_aperture_indicator(
                        ax, zi_global, axis_vals_i, facecolor, inward=True
                    )
                    artists[line_i] = surface

            if zone is not None and show_masks:
                for line in self._draw_mask_body(ax, surface, projection, zone):
                    artists[line] = surface

        return artists

    @staticmethod
    def _add_aperture_disk(
        renderer, surface, r_in, r_out, color, *, opacity=0.65, on_surface=False
    ):
        """Add a disk or ring actor in the surface's local frame.

        Args:
            renderer: The VTK renderer.
            surface: The surface whose frame places the disk.
            r_in: Inner radius of the ring (0 for a full disk).
            r_out: Outer radius.
            color: RGB tuple.
            opacity: Actor opacity.
            on_surface: Lay the disk onto the surface's sag instead of its
                vertex plane, and draw it in front of the coincident surface.

        Returns:
            The added actor.
        """
        import vtk

        disk = vtk.vtkDiskSource()
        disk.SetInnerRadius(r_in)
        disk.SetOuterRadius(r_out)
        disk.SetRadialResolution(8 if on_surface else 1)
        disk.SetCircumferentialResolution(64)
        disk.Update()
        mapper = vtk.vtkPolyDataMapper()
        if on_surface:
            poly = disk.GetOutput()
            points = poly.GetPoints()
            xyz = np.array(
                [points.GetPoint(i) for i in range(points.GetNumberOfPoints())]
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                sag = surface.geometry.sag(be.array(xyz[:, 0]), be.array(xyz[:, 1]))
            sag = np.nan_to_num(np.asarray(be.to_numpy(sag), dtype=float))
            for i, (x, y, z) in enumerate(zip(xyz[:, 0], xyz[:, 1], sag, strict=True)):
                points.SetPoint(i, x, y, z)
            points.Modified()
            mapper.SetInputData(poly)
            # The disk lies on a lens surface: pull it in front of that face.
            mapper.SetRelativeCoincidentTopologyPolygonOffsetParameters(-2.0, -2.0)
        else:
            mapper.SetInputConnection(disk.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor = transform_3d(actor, surface)
        prop = actor.GetProperty()
        prop.SetColor(*color)
        prop.SetOpacity(opacity)
        prop.SetAmbient(0.6)
        prop.SetDiffuse(0.4)
        prop.SetSpecular(0.2)
        prop.SetSpecularPower(20.0)
        renderer.AddActor(actor)
        return actor

    def _plot_apertures_3d(
        self, renderer, theme=None, show_stop=True, show_non_stop=True, show_masks=True
    ):
        """Add translucent aperture disk actors to the 3D renderer.

        A mask stop is red: a ring beyond its clear edge and its blocking
        disk or ring laid onto the surface. A mask on the stop surface keeps
        the stop's purple ring.

        Returns:
            dict: Every added actor mapped to the surface whose aperture it
                shows.
        """
        from matplotlib.colors import to_rgb

        actors = {}
        stop_color = to_rgb(STOP_COLOR)
        mask_color = to_rgb(MASK_COLOR)
        if theme:
            stop_color = to_rgb(theme.parameters.get("aperture.stop_color", STOP_COLOR))
            mask_color = to_rgb(theme.parameters.get("aperture.mask_color", MASK_COLOR))

        # Non-stop apertures are 20% lighter than stop color
        aperture_color = tuple(min(1.0, c + 0.20 * (1.0 - c)) for c in stop_color)

        for idx, surface in enumerate(self.optic.surfaces):
            if surface.aperture is None and not surface.is_stop:
                continue
            zone = mask_zone(surface.aperture)
            if surface.is_stop:
                color, show_edge = stop_color, show_stop
            elif zone is not None:
                color, show_edge = mask_color, show_masks
            else:
                color, show_edge = aperture_color, show_non_stop

            extent = self._aperture_extent(surface, idx) if show_edge else None
            r_outer_edge = (
                max(abs(float(v)) for v in extent) if extent is not None else 0.0
            )
            if r_outer_edge > 0:
                # Outer blocking ring (beyond clear aperture)
                actor = self._add_aperture_disk(
                    renderer, surface, r_outer_edge, r_outer_edge * 1.5, color
                )
                actors[actor] = surface

                # For ring apertures (r_min > 0): add inner central obstruction disk
                if (
                    isinstance(surface.aperture, RadialAperture)
                    and surface.aperture.r_min > 0
                ):
                    r_inner_edge = float(surface.aperture.r_min)
                    actor = self._add_aperture_disk(
                        renderer, surface, 0.0, r_inner_edge, color
                    )
                    actors[actor] = surface

            if zone is not None and show_masks:
                actor = self._add_aperture_disk(
                    renderer, surface, *zone, mask_color, opacity=0.9, on_surface=True
                )
                actors[actor] = surface
        return actors
