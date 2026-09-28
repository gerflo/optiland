"""Light source of the active path: the LED ring and the LED type library.

Qt-free: the System Properties page (:mod:`optiland_gui.led_ring_editor`)
drives it, and it can run headless.

- :class:`LightSourceService` applies an :class:`~optiland.illumination.
  LEDRing` to the active optic as one undoable edit, with its generated
  fields and wavelengths.
- :class:`LEDLibrary` keeps LED types (chip, radiation pattern, spectrum,
  flux) as JSON files, so a datasheet is entered once.
- :func:`parse_xy_table` and :func:`fold_symmetric_curve` read digitized
  datasheet curves (two columns, CSV or pasted text).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from optiland.illumination import LEDRing, LEDType, apply_led_ring

if TYPE_CHECKING:
    from optiland_gui.optiland_connector import OptilandConnector


class LightSourceService:
    """Reads and sets the light source of the active optic.

    Args:
        connector: The connector owning the active optic and the undo stack.
    """

    def __init__(self, connector: OptilandConnector) -> None:
        self._connector = connector

    def get_light_source(self) -> LEDRing | None:
        """The LED ring of the active optic, or ``None``."""
        optic = self._connector.get_optic()
        return getattr(optic, "light_source", None) if optic is not None else None

    def set_light_source(
        self,
        ring: LEDRing | None,
        *,
        fields: bool = True,
        wavelengths: bool = True,
    ) -> None:
        """Make ``ring`` the light source of the active optic, undoably.

        Args:
            ring: The LED ring; ``None`` removes the light source and keeps
                fields and wavelengths.
            fields: Replace the fields by the ring's field points.
            wavelengths: Replace the wavelengths by the LED spectrum's.

        Raises:
            ValueError: If the object is at infinity (nothing is changed).
        """
        connector = self._connector
        optic = connector.get_optic()
        if optic is None:
            return
        if ring is None and getattr(optic, "light_source", None) is None:
            return
        old_state = connector._capture_optic_state()
        apply_led_ring(optic, ring, fields=fields, wavelengths=wavelengths)
        connector._undo_redo_manager.add_state(old_state)
        connector.set_modified(True)
        connector.opticChanged.emit()


class LEDLibrary:
    """LED types stored as one JSON file each.

    Args:
        root: Directory of the library; created on the first save.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    @property
    def root(self) -> Path:
        """Directory of the library."""
        return self._root

    def names(self) -> list[str]:
        """Names of the stored LED types, sorted case-insensitively."""
        if not self._root.is_dir():
            return []
        names = []
        for path in self._root.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            names.append(str(data.get("name") or path.stem))
        return sorted(names, key=str.casefold)

    def load(self, name: str) -> LEDType:
        """The LED type stored under ``name``.

        Raises:
            KeyError: If there is no such type.
        """
        path = self._path(name)
        if not path.is_file():
            raise KeyError(f"No LED type {name!r} in {self._root}.")
        return LEDType.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save(self, led: LEDType) -> Path:
        """Store ``led`` under its name, replacing a type of that name.

        Raises:
            ValueError: If the LED type has no name.
        """
        if not led.name.strip():
            raise ValueError("An LED type needs a name to be stored.")
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._path(led.name)
        path.write_text(json.dumps(led.to_dict(), indent=2), encoding="utf-8")
        return path

    def delete(self, name: str) -> None:
        """Remove the LED type ``name`` (nothing happens if it is missing)."""
        self._path(name).unlink(missing_ok=True)

    def _path(self, name: str) -> Path:
        stem = re.sub(r"[^\w.-]+", "_", name.strip()).strip("._") or "led"
        return self._root / f"{stem}.json"


_NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"


def parse_xy_table(text: str) -> tuple[list[float], list[float]]:
    """Two numeric columns from CSV or pasted text.

    Columns are separated by ``;``, tab, ``,`` or spaces. With ``;`` or tab
    as separator a decimal comma is accepted (``"12,5;0,98"``). Lines that
    do not start with two numbers (headers, comments) are skipped; further
    columns are ignored.

    Args:
        text: The table text.

    Returns:
        The first and second column.
    """
    xs: list[float] = []
    ys: list[float] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if ";" in line or "\t" in line:
            cells = [c.strip().replace(",", ".") for c in re.split(r"[;\t]", line)]
        else:
            cells = [c for c in re.split(r"[,\s]+", line) if c]
        if len(cells) < 2:
            continue
        if not (re.fullmatch(_NUMBER, cells[0]) and re.fullmatch(_NUMBER, cells[1])):
            continue
        xs.append(float(cells[0]))
        ys.append(float(cells[1]))
    return xs, ys


def fold_symmetric_curve(
    angles: list[float], values: list[float]
) -> tuple[list[float], list[float]]:
    """One half of a radiation curve given over -90..90 deg.

    Datasheets plot the pattern on both sides of the axis. The negative
    half is mirrored and averaged with the positive half at the positive
    half's angles (where both exist); a curve given on one side only is
    returned sorted, mirrored to positive angles.

    Args:
        angles: Polar angles [deg], any order, possibly negative.
        values: Relative intensities at ``angles``.

    Returns:
        Angles in [0, 90], strictly increasing, and their intensities.
    """
    a = np.asarray(angles, dtype=float)
    v = np.asarray(values, dtype=float)
    pos, neg = a >= 0.0, a < 0.0
    if not neg.any() or not (a > 0.0).any():
        half_a, half_v = np.abs(a), v
    else:
        order = np.argsort(-a[neg])
        neg_a, neg_v = -a[neg][order], v[neg][order]
        order = np.argsort(a[pos])
        half_a, half_v = a[pos][order], v[pos][order].copy()
        inside = (half_a >= neg_a[0]) & (half_a <= neg_a[-1])
        mirrored = np.interp(half_a[inside], neg_a, neg_v)
        half_v[inside] = 0.5 * (half_v[inside] + mirrored)
    order = np.argsort(half_a, kind="stable")
    half_a, half_v = half_a[order], half_v[order]
    keep = np.concatenate(([True], np.diff(half_a) > 0.0))
    return half_a[keep].tolist(), half_v[keep].tolist()
