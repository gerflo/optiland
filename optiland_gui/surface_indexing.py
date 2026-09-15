"""Map Lens Data Editor surface numbers onto the optic that is computed.

Disabled editor rows stay in the live optic but are left out of the effective
optic that the layouts draw and the analyses trace, so every surface after a
disabled row has a lower index there.
"""

from __future__ import annotations


def effective_surface_index(
    surface_index: int, disabled: set[int], surface_count: int
) -> int | None:
    """Map a Lens Data Editor row onto the effective optic, which omits disabled rows.

    ``surface_count`` is the row count of the editor. Returns ``None`` when
    the row itself is disabled and therefore not part of the effective optic.
    """
    removed = {index for index in disabled if 0 < index < surface_count - 1}
    if surface_index in removed:
        return None
    return surface_index - sum(1 for index in removed if index < surface_index)


def editor_surface_index(
    drawn_index: int, disabled: set[int], surface_count: int
) -> int | None:
    """Map a surface of the effective optic back onto its Lens Data Editor row.

    The inverse of :func:`effective_surface_index`: the effective optic omits
    the disabled rows, so its *drawn_index*-th surface is the *drawn_index*-th
    row that is not disabled. Returns ``None`` when the effective optic has no
    such surface.
    """
    removed = {index for index in disabled if 0 < index < surface_count - 1}
    kept = [index for index in range(surface_count) if index not in removed]
    if 0 <= drawn_index < len(kept):
        return kept[drawn_index]
    return None


def disabled_surface_indices(connector) -> set[int]:  # noqa: ANN001
    """Disabled editor rows, or none when the connector keeps no such state."""
    getter = getattr(connector, "get_disabled_surface_indices", None)
    if not callable(getter):
        return set()
    try:
        return {int(index) for index in getter()}
    except TypeError:
        return set()
