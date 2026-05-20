"""Footprint Diagram Analysis

Shows the geometric ray footprint on the image (target) surface.
All fields are overlaid with distinct colours, making it easy to see the
total illuminated area and individual field contributions.

This is particularly useful for illumination systems where PSF / irradiance
analysis is not appropriate: run FootprintDiagram to see where light from
every source point lands on the target plane.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import matplotlib.pyplot as plt
import numpy as _np

import optiland.backend as be

from .base import BaseAnalysis

if TYPE_CHECKING:
    from matplotlib.figure import Figure


class FootprintDiagram(BaseAnalysis):
    """Ray footprint on the image (target) surface.

    Unlike IncoherentIrradiance – which bins power into pixels *per field* –
    FootprintDiagram overlays the raw ray landing positions for **all** fields
    in a single scatter plot per wavelength.  This gives an immediate picture of:

    - The total illuminated area on the target plane.
    - The contribution of each source field separately (one colour per field).
    - Overlap or gaps between field footprints.

    It is especially suited to illumination systems where the aim is to see
    how the beam from an extended source covers the target.

    Args:
        optic: The optical system to analyse.
        num_rays: Number of rays per (field, wavelength) pair.  Default 500.
        fields: Which fields to include.  ``"all"`` uses every field defined on
            the optic; otherwise pass a list of ``(Hx, Hy)`` normalised pairs.
        wavelengths: ``"all"``, ``"primary"``, or a list of wavelength values
            in µm.  Default ``"all"``.
        distribution: Pupil-sampling strategy.  Default ``"hexapolar"``.
        marker_size: Scatter-plot point size (matplotlib *s* parameter).
            Default ``1.0``.
    """

    def __init__(
        self,
        optic,
        num_rays: int = 500,
        *,
        fields="all",
        wavelengths="all",
        distribution: Literal[
            "random", "hexapolar", "grid", "ring", "line_x", "line_y"
        ] = "hexapolar",
        marker_size: float = 1.0,
    ):
        if fields == "all":
            self.fields = optic.fields.get_field_coords()
        else:
            self.fields = list(fields)

        self.num_rays = num_rays
        self.distribution = distribution
        self.marker_size = marker_size
        super().__init__(optic, wavelengths)

    # ------------------------------------------------------------------
    # Data generation
    # ------------------------------------------------------------------

    def _generate_data(self):
        """Trace rays and collect image-plane hit positions.

        Returns:
            list[list[tuple]]: ``data[f][w]`` is ``(x, y, intensity)`` NumPy
            arrays containing only rays that survived to the image surface
            (intensity > 0).
        """
        from optiland.visualization.system.utils import transform

        # Robust ray aiming recurses aggressively when the stop is very close
        # to the source (common in illumination systems), making this analysis
        # prohibitively slow.  Iterative aiming is sufficient for a footprint
        # visualisation — exact pupil sampling doesn't matter here.
        ray_tracer = getattr(self.optic, "ray_tracer", None)
        original_config = None
        if ray_tracer is not None:
            original_config = ray_tracer.ray_aiming_config.copy()
            if original_config.get("mode") == "robust":
                ray_tracer.ray_aiming_config = {
                    **original_config,
                    "mode": "iterative",
                }

        image_surf = self.optic.surfaces[-1]
        data = []
        try:
            for field in self.fields:
                f_block = []
                for wp in self.wavelengths:
                    Hx, Hy = float(field[0]), float(field[1])
                    try:
                        rays = self.optic.trace(
                            Hx, Hy, wp.value, self.num_rays, self.distribution
                        )
                        x_g = be.to_numpy(rays.x)
                        y_g = be.to_numpy(rays.y)
                        z_g = be.to_numpy(rays.z)
                        i_np = be.to_numpy(rays.i)

                        x_loc, y_loc, _ = transform(
                            be.array(x_g), be.array(y_g), be.array(z_g),
                            image_surf, is_global=True,
                        )
                        x_loc = be.to_numpy(x_loc)
                        y_loc = be.to_numpy(y_loc)

                        mask = i_np > 0
                        f_block.append((x_loc[mask], y_loc[mask], i_np[mask]))
                    except Exception as exc:
                        print(
                            f"[FootprintDiagram] Trace failed for field {field}, "
                            f"wavelength {wp.value}: {exc}"
                        )
                        f_block.append((_np.empty(0), _np.empty(0), _np.empty(0)))
                data.append(f_block)
        finally:
            if original_config is not None:
                ray_tracer.ray_aiming_config = original_config
        return data

    # ------------------------------------------------------------------
    # View
    # ------------------------------------------------------------------

    def view(
        self,
        fig_to_plot_on: Figure | None = None,
        figsize: tuple[float, float] = (6.0, 6.0),
    ) -> tuple[Figure, _np.ndarray]:
        """Display the footprint scatter plot.

        One subplot per wavelength; all fields overlaid with distinct colours.

        Args:
            fig_to_plot_on: Existing Figure to draw on (cleared first).
            figsize: (width, height) in inches *per subplot*.

        Returns:
            (fig, axs): The Figure and a 1-D ndarray of Axes objects.
        """
        n_wl = len(self.wavelengths)
        colors = plt.cm.tab10.colors

        if fig_to_plot_on is not None:
            fig = fig_to_plot_on
            fig.clear()
            axs = fig.subplots(1, n_wl, squeeze=False)[0]
        else:
            fig, axs_2d = plt.subplots(
                1, n_wl,
                figsize=(figsize[0] * n_wl, figsize[1]),
                squeeze=False,
            )
            axs = axs_2d[0]

        for w_idx, wp in enumerate(self.wavelengths):
            ax = axs[w_idx]
            any_plotted = False
            for f_idx, f_block in enumerate(self.data):
                x, y, _ = f_block[w_idx]
                if x.size == 0:
                    continue
                color = colors[f_idx % len(colors)]
                Hx, Hy = self.fields[f_idx][0], self.fields[f_idx][1]
                ax.scatter(
                    x, y,
                    s=self.marker_size,
                    color=color,
                    label=f"Field {f_idx} ({Hx:.2f}, {Hy:.2f})",
                    rasterized=True,
                )
                any_plotted = True

            ax.set_xlabel("X (mm)")
            ax.set_ylabel("Y (mm)")
            ax.set_title(f"$\\lambda$ = {wp.value:.3f} µm")
            ax.set_aspect("equal", adjustable="datalim")
            ax.grid(True, linewidth=0.4)
            if any_plotted:
                ax.legend(markerscale=6, fontsize="small")

        fig.suptitle("Footprint Diagram")
        if hasattr(fig, "canvas"):
            fig.canvas.draw_idle()
        return fig, axs
