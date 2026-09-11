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


def _doublet_zmx_text(
    name: str,
    comment: str,
    *,
    fixed_semi_diameter: bool = True,
    clear_aperture_radius: float | None = None,
) -> str:
    """Return a synthetic cemented-doublet prescription in Zemax text form."""
    flag = "1" if fixed_semi_diameter else "0"
    clap = (
        [f"  CLAP 0 {clear_aperture_radius} 0"]
        if clear_aperture_radius is not None
        else []
    )
    lens_surface = lambda curv, disz, glas: [  # noqa: E731
        "  TYPE STANDARD",
        f"  CURV {curv}",
        f"  DISZ {disz}",
        *( [f"  GLAS {glas}"] if glas else [] ),
        f'  DIAM 12.7 {flag} 0 0 1 ""',
        "  FLAP 0 12.7 0",
        *clap,
    ]
    lines = [
        "VERS 230607",
        "MODE SEQ",
        f"NAME {name}",
        "NOTE 0 FOR INFORMATION ONLY, NOT FOR MANUFACTURING.",
        "UNIT MM X W X CM MR CPMM",
        "ENPD 22.86",
        "GCAT SCHOTT",
        "WAVM 1 0.4861 1",
        "WAVM 2 0.5876 1",
        "WAVM 3 0.6563 1",
        "PWAV 2",
        "FTYP 0 0 1 3 0 0 0",
        "XFLN 0",
        "YFLN 0",
        "FWGN 1",
        "SURF 0",
        "  TYPE STANDARD",
        "  CURV 0.0",
        "  DISZ INFINITY",
        '  DIAM 0 0 0 0 1 ""',
        "SURF 1",
        f"  COMM {comment}",
        "  STOP",
        *lens_surface("0.03", "8", "N-BAF10"),
        "SURF 2",
        *lens_surface("-0.045", "2.5", "SF10"),
        "SURF 3",
        *lens_surface("-0.0035", "45", None),
        "SURF 4",
        "  TYPE STANDARD",
        "  CURV 0.0",
        "  DISZ 0",
        '  DIAM 0 0 0 0 1 ""',
    ]
    return "\r\n".join(lines) + "\r\n"


def _import_zmx_text(importer, text: str, filename: str):  # noqa: ANN001
    temp_dir = _workspace_tmp_dir()
    path = temp_dir / filename
    try:
        path.write_text(text, encoding="utf-8")
        records = importer.import_file(str(path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    assert len(records) == 1
    return records[0]


def _import_zmf_entry(importer, entry_name: str, text: str):  # noqa: ANN001
    temp_dir = _workspace_tmp_dir()
    zmf_path = temp_dir / "catalog.zmf"
    try:
        zmf_path.write_bytes(_build_test_zmf(entry_name, text.encode("utf-8")))
        records = importer.import_file(str(zmf_path))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    assert len(records) == 1
    return records[0]


def test_import_uses_fixed_zemax_semi_diameters_when_surfaces_have_no_aperture() -> None:
    """Thorlabs prescriptions carry the physical size only in DIAM/FLAP lines."""
    text = _doublet_zmx_text(
        "AC254-050-A AC254-050-A POSITIVE VISIBLE ACHROMATS: Infinite 50",
        "AC254-050-A",
    )

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "AC254-050-A.zmx")

    assert record.part_number == "AC254-050-A"
    assert [surface.semi_diameter for surface in record.surfaces] == [12.7, 12.7, 12.7]
    assert record.diameter_mm == 25.4


def test_import_computes_paraxial_efl_when_title_has_no_focal_length() -> None:
    from optiland.fileio import load_zemax_text

    text = _doublet_zmx_text(
        "AC254-050-A AC254-050-A POSITIVE VISIBLE ACHROMATS: Infinite 50",
        "AC254-050-A",
    )
    expected = round(float(load_zemax_text(text).paraxial.f2()), 2)

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "AC254-050-A.zmx")

    assert record.efl_mm == expected
    assert 30.0 < record.efl_mm < 60.0


def test_import_keeps_automatic_zemax_semi_diameters_unset() -> None:
    """Automatic DIAM values are ray footprints, not the physical lens edge."""
    text = _doublet_zmx_text("Synthetic doublet", "AC254-050-A", fixed_semi_diameter=False)

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "AC254-050-A.zmx")

    assert [surface.semi_diameter for surface in record.surfaces] == [None, None, None]
    assert record.diameter_mm is None


def test_import_prefers_clear_aperture_over_fixed_semi_diameter() -> None:
    text = _doublet_zmx_text("Synthetic doublet", "AC254-050-A", clear_aperture_radius=11.43)

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "AC254-050-A.zmx")

    assert [surface.semi_diameter for surface in record.surfaces] == [11.43, 11.43, 11.43]
    assert record.diameter_mm == 22.86


def test_import_thorlabs_asphere_file_keeps_auto_back_surface_unset() -> None:
    records = ThorlabsCatalogImporter().import_file(
        str(_zemax_file("lens_thorlabs_iso_8859_1.zmx"))
    )

    record = records[0]
    assert record.surfaces[0].semi_diameter == 9.0
    assert record.surfaces[1].semi_diameter is None
    assert record.diameter_mm == 18.0


def test_import_zmf_entry_name_beats_glass_name_in_title() -> None:
    text = _doublet_zmx_text(
        "Ø=7.20mm, f=6.24mm, NA=0.40 H-LAK54 Asphere, -B Coated",
        "Surface 1",
    )

    record = _import_zmf_entry(ThorlabsCatalogImporter(), "A110-B", text)

    assert record.part_number == "A110-B"
    assert record.catalog_id == "thorlabs:a110-b"
    assert record.efl_mm == 6.24
    assert record.diameter_mm == 7.2


def test_import_zmx_surface_comment_beats_glass_name_in_title() -> None:
    text = _doublet_zmx_text(
        "Ø=7.20mm, f=6.24mm, NA=0.40 H-LAK54 Asphere, -B Coated",
        "A110-B",
    )

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "download.zmx")

    assert record.part_number == "A110-B"


def test_import_reads_negative_focal_length_from_title() -> None:
    text = _doublet_zmx_text("N-SF11 Bi-Concave Lens, Ø6 mm, f = -6.0 mm", "LD2746")

    record = _import_zmx_text(ThorlabsCatalogImporter(), text, "LD2746.zmx")

    assert record.part_number == "LD2746"
    assert record.efl_mm == -6.0
    assert record.diameter_mm == 6.0
