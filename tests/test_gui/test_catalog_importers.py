from __future__ import annotations

import math
import shutil
import warnings
from pathlib import Path
from struct import Struct

from optiland_gui.catalogs.importers import EdmundCatalogImporter

from optiland_gui.catalogs.importers import ThorlabsCatalogImporter


def _zemax_file(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "zemax_files" / name


def _read_zemax_text(path: Path) -> str:
    data = path.read_bytes()
    for encoding in ("utf-16", "utf-8", "iso-8859-1"):
        try:
            return data.decode(encoding)
        except UnicodeError:
            continue
    raise AssertionError(f"Could not decode test Zemax file: {path}")


def _workspace_tmp_dir() -> Path:
    path = Path("tests") / "_tmp_catalog_importers" / "zmf_case"
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _encode_zmf_payload(data: bytes, a_value: float, b_value: float) -> bytes:
    iv = math.cos(6 * a_value + 3 * b_value)
    iv = math.cos(655 * (math.pi / 180) * iv) + iv
    encoded = bytearray(len(data))
    for position, byte in enumerate(data):
        source = 13.2 * (iv + math.sin(17 * (position + 3))) * (position + 1)
        key = int(f"{source:.8e}"[4:7]) & 0xFF
        encoded[position] = byte ^ key
    return bytes(encoded)


def _build_test_zmf(entry_name: str, zmx_bytes: bytes, a_value: float = 75.0, b_value: float = 12.7) -> bytes:
    header = Struct("<100s24xIdd")
    name_bytes = entry_name.encode("latin1")
    entry_header = header.pack(name_bytes.ljust(100, b"\0"), len(zmx_bytes), a_value, b_value)
    return b"\xE9\x03\x00\x00" + entry_header + _encode_zmf_payload(zmx_bytes, a_value, b_value)


def _build_test_zmf_with_entries(entries: list[tuple[str, bytes]]) -> bytes:
    header = Struct("<100s24xIdd")
    payload = bytearray(b"\xE9\x03\x00\x00")
    for idx, (entry_name, zmx_bytes) in enumerate(entries):
        a_value = 75.0 + idx
        b_value = 12.7 + idx
        name_bytes = entry_name.encode("latin1")
        entry_header = header.pack(
            name_bytes.ljust(100, b"\0"),
            len(zmx_bytes),
            a_value,
            b_value,
        )
        payload.extend(entry_header)
        payload.extend(_encode_zmf_payload(zmx_bytes, a_value, b_value))
    return bytes(payload)


def test_import_thorlabs_toroidal_zemax_file() -> None:
    importer = ThorlabsCatalogImporter()

    records = importer.import_file(str(_zemax_file("thorlabs_lj1598l1.zmx")))

    assert len(records) == 1
    record = records[0]
    assert record.manufacturer == "Thorlabs"
    assert record.part_number == "LJ1598L1"
    assert record.product_name.startswith("LJ1598L1")
    assert record.category == "cylindrical"
    assert record.material_summary == "N-BK7"
    assert len(record.surfaces) == 2
    assert record.surfaces[0].surface_type == "toroidal"
    assert "radius_x" in record.surfaces[0].extra_data
    assert record.source.source_type == "zemax"


def test_import_thorlabs_even_asphere_zemax_file() -> None:
    importer = ThorlabsCatalogImporter()

    records = importer.import_file(str(_zemax_file("lens_thorlabs_iso_8859_1.zmx")))

    assert len(records) == 1
    record = records[0]
    assert record.part_number == "AL1815-C"
    assert record.category == "asphere"
    assert record.efl_mm == 15.0
    assert record.diameter_mm == 18.0
    assert record.coating == "1050-1620 nm"
    assert record.surfaces[0].surface_type == "even_asphere"
    assert record.surfaces[0].extra_data["coefficients"]


def test_import_edmund_zmf_catalog_file() -> None:
    importer = EdmundCatalogImporter()
    zmx_bytes = _zemax_file("lens1.zmx").read_bytes()
    zmf_bytes = _build_test_zmf("08068", zmx_bytes)
    temp_dir = _workspace_tmp_dir()
    zmf_path = temp_dir / "edmund_catalog.zmf"
    try:
        zmf_path.write_bytes(zmf_bytes)

        records = importer.import_file(str(zmf_path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert len(records) == 1
    record = records[0]
    assert record.manufacturer == "Edmund"
    assert record.part_number == "08068"
    assert record.product_name == "08068"
    assert record.source.source_type == "zmf"
    assert record.source.source_path == str(zmf_path)
    assert record.source.version_hint == "08068"


def test_import_edmund_zmf_uses_note_metadata_for_display_fields() -> None:
    importer = EdmundCatalogImporter()
    base_text = _read_zemax_text(_zemax_file("lens1.zmx"))
    zmx_text = (
        "NAME 08068\r\n"
        "NOTE 0 25.4mm Dia. x 250mm FL, Uncoated, UV Double-Convex Lens\r\n"
        f"{base_text}"
    )
    zmf_bytes = _build_test_zmf("08068", zmx_text.encode("utf-8"))
    temp_dir = _workspace_tmp_dir()
    zmf_path = temp_dir / "edmund_catalog.zmf"
    try:
        zmf_path.write_bytes(zmf_bytes)

        records = importer.import_file(str(zmf_path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert len(records) == 1
    record = records[0]
    assert record.part_number == "08068"
    assert record.product_name == "25.4mm Dia. x 250mm FL, Uncoated, UV Double-Convex Lens"
    assert record.efl_mm == 250.0
    assert record.diameter_mm == 25.4
    assert record.coating == "Uncoated"
    assert record.category == "bi-convex"


def test_import_edmund_zmf_skips_unreadable_entries() -> None:
    importer = EdmundCatalogImporter()
    valid_zmx = _zemax_file("lens1.zmx").read_bytes()
    invalid_payload = b"this is not a zemax file"
    zmf_bytes = _build_test_zmf_with_entries(
        [
            ("08068", valid_zmx),
            ("BROKEN", invalid_payload),
        ]
    )
    temp_dir = _workspace_tmp_dir()
    zmf_path = temp_dir / "edmund_mixed_catalog.zmf"
    try:
        zmf_path.write_bytes(zmf_bytes)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            records = importer.import_file(str(zmf_path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    assert len(records) == 1
    assert records[0].part_number == "08068"
