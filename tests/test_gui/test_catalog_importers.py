from __future__ import annotations

from pathlib import Path

from optiland_gui.catalogs.importers import ThorlabsCatalogImporter


def _zemax_file(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "zemax_files" / name


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
