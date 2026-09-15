"""Analysis Base Module

This module contains the abstract base class for all analysis
classes in the Optiland package.

Kramer Harrison, 2025
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING

from matplotlib.axes import Axes

from optiland.utils import resolve_wavelengths

if TYPE_CHECKING:
    from matplotlib.transforms import Bbox

    from optiland.optic import Optic


class EqualAspectAxes(Axes):
    """Axes that show x and y at the same scale and fill their layout box.

    Pass it as ``axes_class`` when creating the subplot. The equal scale is
    kept by widening one of the view limits (``adjustable="datalim"``) rather
    than by shrinking the axes, so the plot uses all the space the figure
    layout gives it, also after the toolbar zoomed or panned.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_aspect("equal", adjustable="datalim")

    def apply_aspect(self, position: Bbox | None = None) -> None:
        """Widen the view limits to equal scale, including limits a zoom fixed.

        Matplotlib logs "Ignoring fixed x limits to fulfill fixed data aspect"
        before widening limits that are not autoscaled, which every zoom
        rectangle leaves behind. Widening them is intended here, so the limits
        count as autoscaled while the aspect is applied.
        """
        # Pending autoscaling must not run on limits the user fixed.
        self._unstale_viewLim()
        autoscale = self.get_autoscalex_on(), self.get_autoscaley_on()
        self.set_autoscalex_on(True)
        self.set_autoscaley_on(True)
        try:
            super().apply_aspect(position)
        finally:
            self.set_autoscalex_on(autoscale[0])
            self.set_autoscaley_on(autoscale[1])


def surface_label(optic: Optic, surface_index: int) -> str:
    """Name a surface of *optic* for plot titles.

    Args:
        optic: The optic that holds the surface.
        surface_index: Index into ``optic.surfaces``; negative values count
            from the end, so ``-1`` is the image surface.

    Returns:
        ``"Surface <n>: <comment>"`` with the resolved, non-negative surface
        number, or ``"Surface <n>"`` when the surface has no comment.

    Raises:
        IndexError: If *surface_index* does not name a surface of *optic*.
    """
    count = optic.surfaces.num_surfaces
    if not -count <= surface_index < count:
        raise IndexError(
            f"Surface index {surface_index} is out of range for {count} surfaces."
        )
    index = surface_index % count
    comment = str(getattr(optic.surfaces[index], "comment", "") or "").strip()
    return f"Surface {index}: {comment}" if comment else f"Surface {index}"


class BaseAnalysis(abc.ABC):
    """Base class for all analysis routines.

    Args:
        optic (Optic): The optic object to analyze.
        wavelengths (str or list, optional): The wavelengths to analyze.
            Can be 'all', 'primary', or a list of wavelength values.
            Defaults to 'all'.

    Attributes:
        optic (Optic): The optic object being analyzed.
        wavelengths (list): The list of wavelengths (in µm) being analyzed.
        data: The generated analysis data. This is populated by the
              `_generate_data` method implemented by subclasses.
    """

    def __init__(self, optic: Optic, wavelengths: str | list = "all"):
        self.optic = optic
        self.wavelengths = resolve_wavelengths(optic, wavelengths)
        self.data = self._generate_data()

    @abc.abstractmethod
    def _generate_data(self):
        """Abstract method to generate analysis-specific data.

        This method must be implemented by subclasses. It should perform
        the necessary calculations and return the data to be stored in
        `self.data`.
        """
        pass

    @abc.abstractmethod
    def view(self, figsize=None, *, show: bool = True, **kwargs):
        """Visualize the analysis data.

        Args:
            figsize (tuple, optional): Figure size passed to matplotlib.
            show (bool): If True (default), calls plt.show(). Set to False
                for headless use (e.g. saving to file, CI environments).
            **kwargs: Additional keyword arguments for customization.

        Returns:
            The matplotlib Figure object (or a tuple starting with the Figure).
        """
        pass
