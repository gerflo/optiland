"""Helpers for decoding WinLens ``glassplus`` material records.

The WinLens 2002 files ``stglassplus.dat`` and ``spglassplus.dat`` store a
fixed-layout binary material catalogue. This module focuses on the parts we
can validate locally against Optiland's existing material database:

- record name
- manufacturer / reference
- the optical formula family
- the primary coefficient block

The decoder is intentionally conservative. It currently exposes only the
fields we have validated with regression tests against known glasses.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

_ENTRY_RE = re.compile(
    rb"([A-Z][A-Za-z0-9-]{2,20})\s{8,}[\x00-\x20\xff\xfe]{0,4}(\[[A-Za-z]+\]|[A-Za-z][A-Za-z ]{2,20})\s{8,}"
)
_NAME_BYTES = 30
_REFERENCE_OFFSET = 32
_REFERENCE_BYTES = 30
_COEFFICIENT_OFFSET = 72
_COEFFICIENT_COUNT = 6
_SUPPORTED_FORMULAS = {
    "schott": "formula 2",
    "ohara": "formula 2",
    "hoya": "formula 3",
    "hikari": "formula 3",
    "sumita": "formula 3",
    "corning": "formula 3",
    "pilkington": "formula 3",
    "chengdu": "formula 3",
}


@dataclass(slots=True)
class WinLensGlassplusRecord:
    """Decoded WinLens material record with validated optical data."""

    name: str
    reference: str | None
    formula_type: str
    coefficients: list[float]
    source_path: str
    offset: int

    def coefficient_string(self) -> str:
        """Return coefficients in Optiland YAML formatting."""
        values = [self._format_coefficient(value) for value in self.coefficients]
        if self.formula_type == "formula 2":
            b1, b2, b3, c1, c2, c3 = values
            return f"0 {b1} {c1} {b2} {c2} {b3} {c3}"
        if self.formula_type == "formula 3":
            a0, a1, a2, a3, a4, a5 = values
            return (
                f"{a0} {a1} 2 {a2} -2 {a3} -4 {a4} -6 {a5} -8"
            )
        raise ValueError(f"Unsupported formula type: {self.formula_type}")

    @staticmethod
    def _format_coefficient(value: float) -> str:
        return f"{value:.12g}"


def find_glassplus_record(
    path: str | Path,
    name: str,
    reference: str | None = None,
) -> WinLensGlassplusRecord | None:
    """Return one decoded record from a WinLens ``glassplus`` file."""
    data = Path(path).read_bytes()
    name_bytes = name.encode("latin1")
    reference_key = _normalize_reference(reference)
    search_start = 0
    while True:
        offset = data.find(name_bytes, search_start)
        if offset < 0:
            return None
        record = _decode_record_at(data, offset, str(path))
        if record is None:
            search_start = offset + 1
            continue
        if record.name != name:
            search_start = offset + 1
            continue
        if reference_key is not None and _normalize_reference(record.reference) != reference_key:
            search_start = offset + 1
            continue
        return record


def iter_glassplus_records(path: str | Path) -> list[WinLensGlassplusRecord]:
    """Return every validated record from a WinLens ``glassplus`` file."""
    data = Path(path).read_bytes()
    records: list[WinLensGlassplusRecord] = []
    seen: set[tuple[str, str | None, int]] = set()
    for match in _ENTRY_RE.finditer(data):
        record = _decode_record_at(data, match.start(), str(path))
        if record is None:
            continue
        key = (record.name, record.reference, record.offset)
        if key in seen:
            continue
        seen.add(key)
        records.append(record)
    return records


def _decode_record_at(
    data: bytes,
    offset: int,
    source_path: str,
) -> WinLensGlassplusRecord | None:
    name = _decode_name(data, offset)
    reference = _decode_reference(data, offset)
    reference_key = _normalize_reference(reference)
    formula_type = _SUPPORTED_FORMULAS.get(reference_key or "")
    if not name or not formula_type:
        return None
    coefficients = _decode_coefficients(data, offset)
    return WinLensGlassplusRecord(
        name=name,
        reference=reference,
        formula_type=formula_type,
        coefficients=coefficients,
        source_path=source_path,
        offset=offset,
    )


def _decode_name(data: bytes, offset: int) -> str:
    chunk = data[offset : offset + _NAME_BYTES]
    return chunk.decode("latin1", "ignore").strip().rstrip("\x00")


def _decode_reference(data: bytes, offset: int) -> str | None:
    start = offset + _REFERENCE_OFFSET
    chunk = data[start : start + _REFERENCE_BYTES]
    reference = "".join(
        character
        for character in chunk.decode("latin1", "ignore")
        if character.isalpha() or character in "[] -"
    ).strip()
    if not reference or reference.casefold() == "[generic]":
        return None
    return reference


def _decode_coefficients(data: bytes, offset: int) -> list[float]:
    values: list[float] = []
    base = offset + _COEFFICIENT_OFFSET
    for index in range(_COEFFICIENT_COUNT):
        start = base + (index * 8)
        stop = start + 8
        values.append(struct.unpack("<d", data[start:stop])[0])
    return values


def _normalize_reference(reference: str | None) -> str | None:
    cleaned = str(reference or "").strip()
    if not cleaned:
        return None
    return cleaned.casefold()
