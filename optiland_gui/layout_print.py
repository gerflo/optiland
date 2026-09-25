"""Element numbers for the printed 2D layout.

The printed layout marks every visible element with a circled number and
lists the numbers with the element names in a legend under the plot. An
element is a surface group of the Lens Data Editor (a catalog lens, an
assembly), an ungrouped lens, or a standalone surface: object, image,
mirror, stop, aperture or mask.
"""

from __future__ import annotations

from dataclasses import dataclass

import matplotlib
import numpy as np
from matplotlib.font_manager import FontProperties

import optiland.backend as be
from optiland.visualization.system.lens import Lens2D
from optiland.visualization.system.surface import Surface2D
from optiland.visualization.system.system import mask_zone

# The numbers are as large as the axis tick labels, but never smaller than
# this; the printed plot is scaled down with the page.
CALLOUT_MIN_FONT_PT = 8.0
# Circle padding around the number, in multiples of the font size.
CALLOUT_PAD = 0.3
# Gaps in points: tallest element to the lowest circles, between
# neighbouring circles, and circle top to the axes top.
CALLOUT_GAP_PT = 4.0
CALLOUT_SPACING_PT = 2.0
CALLOUT_TOP_PAD_PT = 2.0
CALLOUT_LINE_WIDTH_PT = 0.6
CALLOUT_LEADER_COLOR = "0.35"
CALLOUT_ZORDER = 10
_PROJECTION = "YZ"
# The dash of a Lens Data Editor row span, between word joiners so that
# line wrapping never splits the span.
ROW_SPAN_DASH = "\u2060\u2013\u2060"


@dataclass
class LayoutElement:
    """One element of the drawn layout.

    Attributes:
        surfaces: Its surfaces of the drawn optic, in optical order.
        points: Every drawn ``(z, y)`` point of it, in data coordinates.
        kind: ``"group"``, ``"lens"`` or ``"surface"``.
    """

    surfaces: list
    points: np.ndarray
    kind: str


@dataclass(frozen=True)
class Callout:
    """A circled element number and the point its leader line ends at.

    Attributes:
        number: The element number.
        x: Circle centre along z, in data coordinates.
        y: Circle centre height, as a fraction of the axes height.
        target: Leader line end ``(z, y)`` in data coordinates: the top of
            the element's visible part.
        fontsize: Size of the number in points.
    """

    number: int
    x: float
    y: float
    target: tuple[float, float]
    fontsize: float


@dataclass
class _Placement:
    """A callout while its row is worked out; lengths in points."""

    number: int
    element: LayoutElement
    x: float
    target: tuple[float, float]
    x_pt: float
    top_pt: float
    diameter: float
    row: int = 0


def _artist_points(artist) -> np.ndarray:
    """The ``(z, y)`` vertices of a drawn polygon or line."""
    if hasattr(artist, "get_xy"):
        points = np.asarray(artist.get_xy(), dtype=float)
    elif hasattr(artist, "get_xdata"):
        points = np.column_stack(
            [
                np.asarray(artist.get_xdata(), dtype=float),
                np.asarray(artist.get_ydata(), dtype=float),
            ]
        )
    else:
        return np.empty((0, 2))
    return points.reshape(-1, 2)


def collect_layout_elements(layout_artists: dict, optic) -> list[LayoutElement]:
    """Group the drawn artists of a 2D layout into elements, in optical order.

    Surfaces of one Lens Data Editor group form one element, and so do the
    ungrouped surfaces of one drawn lens. Every other drawn surface is an
    element of its own, with its line and aperture markers.

    Args:
        layout_artists: Every drawn artist mapped to what it shows, as
            ``OpticalSystem.plot`` returns it: the component for lenses and
            standalone surfaces, the surface for aperture and mask markers.
        optic: The drawn optic.

    Returns:
        The elements, ordered by their first surface.
    """
    position = {id(surface): i for i, surface in enumerate(optic.surfaces.surfaces)}
    lens_of: dict[int, Lens2D] = {}
    for component in layout_artists.values():
        if isinstance(component, Lens2D):
            for member in component.surfaces:
                lens_of.setdefault(id(member.surf), component)

    def key_of(surface) -> tuple[str, object]:
        group = getattr(surface, "group_id", None)
        if group:
            return ("group", str(group))
        lens = lens_of.get(id(surface))
        if lens is not None:
            return ("lens", id(lens))
        return ("surface", id(surface))

    surfaces_of: dict[tuple[str, object], list] = {}
    points_of: dict[tuple[str, object], list[np.ndarray]] = {}

    def add(surface, points: np.ndarray) -> None:
        if id(surface) not in position:
            return
        key = key_of(surface)
        members = surfaces_of.setdefault(key, [])
        if all(member is not surface for member in members):
            members.append(surface)
        points_of.setdefault(key, []).append(points)

    profiled: set[int] = set()
    for artist, component in layout_artists.items():
        if isinstance(component, Lens2D):
            # Glass between two surfaces belongs to the element of the first.
            pair = getattr(component, "polygon_surfaces", {}).get(artist)
            owner = pair[0] if pair else component.surfaces[0].surf
            add(owner, _artist_points(artist))
            if id(component) in profiled:
                continue
            profiled.add(id(component))
            # Each surface profile, so an element whose surfaces own no
            # polygon (a cemented partner) still has points.
            sags = component._compute_sag(projection=_PROJECTION)
            for member, (_, y, z) in zip(component.surfaces, sags, strict=False):
                zy = np.column_stack(
                    [
                        np.asarray(be.to_numpy(z), dtype=float).ravel(),
                        np.asarray(be.to_numpy(y), dtype=float).ravel(),
                    ]
                )
                add(member.surf, zy)
        elif isinstance(component, Surface2D):
            add(component.surf, _artist_points(artist))
        else:
            add(component, _artist_points(artist))

    elements = []
    for key, members in surfaces_of.items():
        members.sort(key=lambda surface: position[id(surface)])
        elements.append(LayoutElement(members, np.concatenate(points_of[key]), key[0]))
    elements.sort(key=lambda element: position[id(element.surfaces[0])])
    return elements


def element_label(element: LayoutElement, optic) -> str:
    """The name of an element: its group name or comment, else what it is."""
    if element.kind == "group":
        name = str(getattr(element.surfaces[0], "group_name", None) or "").strip()
        if name:
            return name
    for surface in element.surfaces:
        comment = str(getattr(surface, "comment", None) or "").strip()
        if comment:
            return comment
    return _generic_name(element, optic)


def _generic_name(element: LayoutElement, optic) -> str:
    if element.kind == "group":
        return "Element"
    if element.kind == "lens":
        return "Lens"
    surface = element.surfaces[0]
    drawn = optic.surfaces.surfaces
    if surface is drawn[0]:
        return "Object"
    if surface is drawn[-1]:
        return "Image"
    if getattr(surface, "is_stop", False):
        return "Aperture stop"
    model = getattr(surface, "interaction_model", None)
    if getattr(model, "is_reflective", False):
        return "Mirror"
    aperture = getattr(surface, "aperture", None)
    if mask_zone(aperture) is not None:
        return "Mask"
    if aperture is not None:
        return "Aperture"
    return "Surface"


def legend_label(element: LayoutElement, optic, rows: list[int]) -> str:
    """The legend text of an element: its name and Lens Data Editor rows.

    The row span is joined with word joiners (U+2060) around its dash, so a
    wrapped legend line never splits it.

    Args:
        element: The element.
        optic: The drawn optic.
        rows: The element's rows in the Lens Data Editor, ascending.
    """
    label = element_label(element, optic)
    if not rows:
        return label
    first, last = rows[0], rows[-1]
    span = f"S{first}" if first == last else f"S{first}{ROW_SPAN_DASH}S{last}"
    return f"{label} ({span})"


def _visible_points(points: np.ndarray, xlim, ylim) -> np.ndarray:
    x0, x1 = sorted(xlim)
    y0, y1 = sorted(ylim)
    points = points[np.isfinite(points).all(axis=1)]
    inside = (
        (points[:, 0] >= x0)
        & (points[:, 0] <= x1)
        & (points[:, 1] >= y0)
        & (points[:, 1] <= y1)
    )
    return points[inside]


def callout_font_size(ax) -> float:
    """Size of the element numbers: that of the tick labels, at least the minimum."""
    labels = ax.get_xticklabels()
    size = (
        labels[0].get_fontsize()
        if labels
        else FontProperties(size=matplotlib.rcParams["xtick.labelsize"]).get_size()
    )
    return max(float(size), CALLOUT_MIN_FONT_PT)


def _assign_rows(placements: list[_Placement]) -> int:
    """Put each circle in the lowest row where it clears its left neighbour.

    Returns:
        The number of rows used.
    """
    row_ends: list[float] = []
    for placement in sorted(placements, key=lambda item: item.x_pt):
        half = 0.5 * placement.diameter
        left = placement.x_pt - half
        for row, end in enumerate(row_ends):
            if left >= end + CALLOUT_SPACING_PT:
                row_ends[row] = placement.x_pt + half
                placement.row = row
                break
        else:
            row_ends.append(placement.x_pt + half)
            placement.row = len(row_ends) - 1
    return len(row_ends)


def place_callouts(
    ax, elements: list[LayoutElement]
) -> list[tuple[LayoutElement, Callout]]:
    """Number the elements visible in *ax* and place their circles.

    The numbers run in optical order over the visible elements. Each circle
    is centred over its element, in one row just above the tallest visible
    element; a circle that would overlap its left neighbour goes up a row.
    Rows that would leave the axes are moved down into it, so the circles
    stay within the plot at any zoom.

    Args:
        ax: The layout axes, drawn at least once.
        elements: The elements, in optical order.

    Returns:
        Each visible element with its callout.
    """
    figure = ax.figure
    box = ax.bbox
    if box.width <= 0 or box.height <= 0:
        return []
    to_pt = 72.0 / figure.dpi
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    visible = []
    for element in elements:
        points = _visible_points(element.points, xlim, ylim)
        if len(points):
            visible.append((element, points))
    if not visible:
        return []

    fontsize = callout_font_size(ax)
    renderer = figure.canvas.get_renderer()
    font = FontProperties(size=fontsize)
    _, line_px, _ = renderer.get_text_width_height_descent("lp", font, ismath=False)
    pad_pt = CALLOUT_PAD * fontsize

    placements = []
    for number, (element, points) in enumerate(visible, start=1):
        text_px, _, _ = renderer.get_text_width_height_descent(
            str(number), font, ismath=False
        )
        top = points[np.argmax(points[:, 1])]
        centre = 0.5 * (float(points[:, 0].min()) + float(points[:, 0].max()))
        x_px = ax.transData.transform((centre, top[1]))[0]
        top_px = ax.transData.transform(top)[1]
        placements.append(
            _Placement(
                number=number,
                element=element,
                x=centre,
                target=(float(top[0]), float(top[1])),
                x_pt=(x_px - box.x0) * to_pt,
                top_pt=(top_px - box.y0) * to_pt,
                diameter=max(text_px, line_px) * to_pt + 2.0 * pad_pt,
            )
        )
    rows = _assign_rows(placements)

    radius = 0.5 * max(placement.diameter for placement in placements)
    pitch = 2.0 * radius + CALLOUT_SPACING_PT
    height_pt = box.height * to_pt
    base = max(placement.top_pt for placement in placements)
    base += CALLOUT_GAP_PT + radius
    highest = base + (rows - 1) * pitch
    base -= max(0.0, highest + radius + CALLOUT_TOP_PAD_PT - height_pt)

    return [
        (
            placement.element,
            Callout(
                number=placement.number,
                x=placement.x,
                y=(base + placement.row * pitch) / height_pt,
                target=placement.target,
                fontsize=fontsize,
            ),
        )
        for placement in placements
    ]


def draw_callouts(ax, callouts: list[Callout]) -> list:
    """Draw circled numbers with leader lines to their elements.

    Returns:
        The added artists, for the caller to remove again.
    """
    artists = []
    for callout in callouts:
        artists.append(
            ax.annotate(
                str(callout.number),
                xy=callout.target,
                xycoords="data",
                xytext=(callout.x, callout.y),
                textcoords=("data", "axes fraction"),
                ha="center",
                va="center",
                fontsize=callout.fontsize,
                color="black",
                bbox={
                    "boxstyle": f"circle,pad={CALLOUT_PAD}",
                    "facecolor": "white",
                    "edgecolor": "black",
                    "linewidth": CALLOUT_LINE_WIDTH_PT,
                },
                arrowprops={
                    "arrowstyle": "-",
                    "color": CALLOUT_LEADER_COLOR,
                    "linewidth": CALLOUT_LINE_WIDTH_PT,
                    "shrinkA": 0.0,
                    "shrinkB": 0.0,
                },
                annotation_clip=False,
                zorder=CALLOUT_ZORDER,
            )
        )
    return artists
