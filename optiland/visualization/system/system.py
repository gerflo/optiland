"""System Visualization Module

This module contains the OpticalSystem class for visualizing optical systems.

Kramer Harrison, 2024
"""

from __future__ import annotations

import optiland.backend as be
from optiland.physical_apertures.radial import RadialAperture
from optiland.visualization.system.lens import Lens2D, Lens3D
from optiland.visualization.system.mirror import Mirror3D
from optiland.visualization.system.surface import Surface2D, Surface3D
from optiland.visualization.system.utils import transform, transform_3d


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

    def plot(
        self,
        ax,
        theme=None,
        projection="YZ",
        show_apertures=True,
        show_stop_apertures=True,
        show_non_stop_apertures=True,
        hide_internal_surfaces=False,
    ):
        """Plots the components of the optical system on the given
        axis (or renderer for 3D plotting).
        """
        self._identify_components(hide_internal_surfaces=hide_internal_surfaces)
        artists = {}
        for component in self.components:
            component_artists = component.plot(ax, theme=theme, projection=projection)
            if component_artists:
                artists.update(component_artists)
        if show_apertures:
            if self.projection == "2d":
                aperture_artists = self._plot_apertures(
                    ax, theme=theme, projection=projection
                )
                artists.update(aperture_artists)
            else:
                self._plot_apertures_3d(
                    ax,
                    theme=theme,
                    show_stop=show_stop_apertures,
                    show_non_stop=show_non_stop_apertures,
                )
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
            # Get the surface extent
            extent = self.rays.r_extent[k]

            # Object surface
            if k == 0:
                if not surf.is_infinite:
                    self._add_component("surface", surf, extent)

            # Image surface or paraxial surface
            elif k == num_surf - 1 or surf.surface_type == "paraxial":
                self._add_component("surface", surf, extent)

            # Surface is a mirror
            elif surf.interaction_model.is_reflective:
                if lens_surfaces:  # Second surface mirror (lens + mirror)
                    surface = self._get_lens_surface(surf, extent)
                    lens_surfaces.append(surface)
                    surfaces_to_add = (
                        [lens_surfaces[0], lens_surfaces[-1]]
                        if hide_internal_surfaces and len(lens_surfaces) > 2
                        else lens_surfaces
                    )
                    self._add_component("lens", surfaces_to_add)
                    lens_surfaces = []
                else:
                    self._add_component("mirror", surf, extent)

            # Front surface of a lens
            elif n[k] > 1:
                surface = self._get_lens_surface(surf, extent)
                lens_surfaces.append(surface)

            # Back surface of a lens
            elif n[k] == 1 and n[k - 1] > 1 and lens_surfaces:
                surface = self._get_lens_surface(surf, extent)
                lens_surfaces.append(surface)
                surfaces_to_add = (
                    [lens_surfaces[0], lens_surfaces[-1]]
                    if hide_internal_surfaces and len(lens_surfaces) > 2
                    else lens_surfaces
                )
                self._add_component("lens", surfaces_to_add)
                lens_surfaces = []

            # Standalone phase surface
            elif surf.interaction_model.interaction_type == "phase":
                self._add_component("surface", surf, extent)

        # add final lens, if any
        if lens_surfaces:
            surfaces_to_add = (
                [lens_surfaces[0], lens_surfaces[-1]]
                if hide_internal_surfaces and len(lens_surfaces) > 2
                else lens_surfaces
            )
            self._add_component("lens", surfaces_to_add)

    def _add_component(self, component_name, *args):
        """Adds a component to the list of components."""
        if component_name in self.component_registry:
            component_class = self.component_registry[component_name][self.projection]
        else:
            raise ValueError(f"Component {component_name} not found in registry.")

        self.components.append(component_class(*args))

    def _get_lens_surface(self, surface, *args):
        """Gets the lens surface based on the projection type."""
        surface_class = self.component_registry["surface"][self.projection]
        return surface_class(surface, *args)

    def _aperture_radius(self, idx, surface):
        """Return the semi-aperture radius for *surface* at *idx*, or None."""
        if surface.aperture is not None:
            x_min, x_max, y_min, y_max = surface.aperture.extent
            return float(max(abs(x_min), abs(x_max), abs(y_min), abs(y_max)))
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

    def _plot_apertures(self, ax, theme=None, projection="YZ"):
        if projection == "XY":
            return {}
        if projection not in ("XZ", "YZ"):
            raise ValueError("Invalid projection type. Must be 'XY', 'XZ', or 'YZ'.")

        stop_color = "#9B30FF"      # purple: visible on both dark and light
        aperture_color = "#7700CC"  # darker purple for non-stop apertures

        artists = {}
        for idx, surface in enumerate(self.optic.surfaces):
            # Skip surfaces without any aperture indicator (unless it is the stop)
            if surface.aperture is None and not surface.is_stop:
                continue

            # Determine aperture extent
            if surface.aperture is not None:
                x_min, x_max, y_min, y_max = surface.aperture.extent
            elif surface.semi_aperture is not None:
                r = surface.semi_aperture
                x_min, x_max, y_min, y_max = -r, r, -r, r
            elif (
                surface.is_stop
                and self.optic.aperture is not None
                and self.optic.aperture.ap_type == "float_by_stop_size"
            ):
                r = 0.5 * self.optic.aperture.value
                x_min, x_max, y_min, y_max = -r, r, -r, r
            elif surface.is_stop and self.rays is not None:
                r = be.to_numpy(self.rays.r_extent[idx]).item()
                if r <= 0:
                    continue
                x_min, x_max, y_min, y_max = -r, r, -r, r
            else:
                continue

            # Define local coordinates based on projection
            x_local = be.array([x_min, x_max])
            y_local = be.array([y_min, y_max])
            z_local = be.array([0.0, 0.0])
            x_global, y_global, z_global = transform(
                x_local, y_local, z_local, surface, is_global=False
            )
            x_global = be.to_numpy(x_global)
            y_global = be.to_numpy(y_global)
            z_global = be.to_numpy(z_global)

            facecolor = stop_color if surface.is_stop else aperture_color

            # Draw line for aperture edge
            axis_vals = x_global if projection == "XZ" else y_global
            (line,) = ax.plot(
                z_global,
                axis_vals,
                color=facecolor,
                linewidth=1.5,
            )
            artists[line] = surface

            # Add arrows to indicate aperture extent
            eps = 1e-6
            arrowprops = {
                "arrowstyle": "-|>",
                "facecolor": facecolor,
                "edgecolor": facecolor,
                "linewidth": 0,
                "mutation_scale": 8,
            }
            axis_vals = x_global if projection == "XZ" else y_global
            for z_val, axis_val, sign in (
                (z_global[1], axis_vals[1], 1),  # top
                (z_global[0], axis_vals[0], -1),  # bottom
            ):
                ax.annotate(
                    "",
                    xy=(z_val, axis_val),
                    xytext=(z_val, axis_val + sign * eps),
                    arrowprops=arrowprops,
                )

            # For ring apertures (r_min > 0): draw the inner blocking edge too
            if isinstance(surface.aperture, RadialAperture) and surface.aperture.r_min > 0:
                r_in = float(surface.aperture.r_min)
                xi_local = be.array([-r_in, r_in])
                yi_local = be.array([-r_in, r_in])
                zi_local = be.array([0.0, 0.0])
                xi_g, yi_g, zi_g = transform(
                    xi_local, yi_local, zi_local, surface, is_global=False
                )
                xi_g = be.to_numpy(xi_g)
                yi_g = be.to_numpy(yi_g)
                zi_g = be.to_numpy(zi_g)
                axis_vals_i = xi_g if projection == "XZ" else yi_g
                (line_i,) = ax.plot(
                    zi_g, axis_vals_i, color=facecolor, linewidth=1.5
                )
                artists[line_i] = surface
                for z_val, axis_val, sign in (
                    (zi_g[1], axis_vals_i[1], -1),  # top inner → arrow points inward
                    (zi_g[0], axis_vals_i[0], 1),   # bottom inner → arrow points inward
                ):
                    ax.annotate(
                        "",
                        xy=(z_val, axis_val),
                        xytext=(z_val, axis_val + sign * eps),
                        arrowprops=arrowprops,
                    )

        return artists

    def _plot_apertures_3d(
        self, renderer, theme=None, show_stop=True, show_non_stop=True
    ):
        """Add translucent aperture disk actors to the 3D renderer."""
        import vtk

        stop_color = (0.61, 0.19, 1.0)
        if theme:
            from matplotlib.colors import to_rgb

            stop_hex = theme.parameters.get("aperture.stop_color", "#9B30FF")
            stop_color = to_rgb(stop_hex)

        # Non-stop apertures are 20% lighter than stop color
        aperture_color = tuple(min(1.0, c + 0.20 * (1.0 - c)) for c in stop_color)

        for idx, surface in enumerate(self.optic.surfaces):
            if surface.aperture is None and not surface.is_stop:
                continue
            if surface.is_stop and not show_stop:
                continue
            if not surface.is_stop and not show_non_stop:
                continue

            r_outer_edge = self._aperture_radius(idx, surface)
            if r_outer_edge is None or r_outer_edge <= 0:
                continue

            color = stop_color if surface.is_stop else aperture_color

            def _add_disk(r_in, r_out):
                disk = vtk.vtkDiskSource()
                disk.SetInnerRadius(r_in)
                disk.SetOuterRadius(r_out)
                disk.SetRadialResolution(1)
                disk.SetCircumferentialResolution(64)
                disk.Update()
                mapper = vtk.vtkPolyDataMapper()
                mapper.SetInputConnection(disk.GetOutputPort())
                actor = vtk.vtkActor()
                actor.SetMapper(mapper)
                actor = transform_3d(actor, surface)
                prop = actor.GetProperty()
                prop.SetColor(*color)
                prop.SetOpacity(0.65)
                prop.SetAmbient(0.6)
                prop.SetDiffuse(0.4)
                prop.SetSpecular(0.2)
                prop.SetSpecularPower(20.0)
                renderer.AddActor(actor)

            # Outer blocking ring (beyond clear aperture)
            _add_disk(r_outer_edge, r_outer_edge * 1.5)

            # For ring apertures (r_min > 0): add inner central obstruction disk
            if isinstance(surface.aperture, RadialAperture) and surface.aperture.r_min > 0:
                r_inner_edge = float(surface.aperture.r_min)
                _add_disk(0.0, r_inner_edge)
