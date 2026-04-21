"""Tests for WinLens SPD import and record linking."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock

from optiland_gui.catalogs.importers.winlens_spd import (
    load_winlens_alias_groups,
    load_winlens_catalog_record,
    load_winlens_dat_records,
    load_winlens_table_records,
)
from optiland_gui.services.catalog_service import CatalogService


def _workspace_tmp_dir() -> Path:
    path = Path("tests") / "_tmp_winlens_catalog_service" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sample_winlens_v4_spd() -> str:
    return """\"-- Version 4.0 file --\",\"02-17-1998\"
\"Asphere demo\",\"\",1
#FALSE#
0,#FALSE#,#FALSE#,#FALSE#,0
1,1,0,0,587.6,486.1,656.3,486.1,656.3
\"1\",\"   \",\"Nom\",\"lens\",\"0,0.5\",-1,\"\",\"\",\"\",\"\",\"air\",\" \",\"\",\"\",0,\"NonSH\",\"\",0
\" LENS 1\"
\"   Surf  1\",\"sphere\",0,25,#TRUE#,\"\",\"\",0,587.6,9,0,\"\"
\"   Space 1\",4,\"\",\"N-BK7\",\"Schott\",\"\",\"\",\"\",\"\",\"\"
\"   Surf  2\",\"sphere\",0,-25,#TRUE#,\"\",\"\",0,587.6,9,0,\"\"
\"   Space 2\",10,\"\",\"AIR\",\" \",\"\",\"\",\"\",\"\",\"\"
\" LENS 1 End\"
\"Defocus\",.05,0,\"\"
\"Zoom\",1,\" \",0
\"ObjMedia\",\"air\",\"\",\" \",\"ImgMedia\",\"air\",\"\",\" \"
\"ParameterTypes\",0,0,1,0,0
\"Waveband\",587.6,486.1,656.3,486.1,656.3
\"efl\",15.0
\"ObjDist\",-500000000,\"   ImagDist\",64.6
\"ObjNa\",0.01,\"   ImagNa\",0.02,\"Stop Rad\",9
\"317703.SPD\"
"""


def test_load_winlens_catalog_record_parses_v4_metadata() -> None:
    tmp_path = _workspace_tmp_dir()
    try:
        spd_path = tmp_path / "317703.SPD"
        spd_path.write_text(_sample_winlens_v4_spd(), encoding="utf-8")

        record = load_winlens_catalog_record(str(spd_path), "WinLens Library 2002")

        assert record.part_number == "317703"
        assert record.product_name == "Asphere demo"
        assert record.efl_mm == 15.0
        assert record.diameter_mm == 18.0
        assert record.material_summary == "N-BK7"
        assert len(record.surfaces) == 2
        assert record.surfaces[0].material == "N-BK7"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_builds_links_to_existing_catalog_records(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    spd_root = tmp_path / "WinLens Library 2002" / "LINOS_STANDARD_SYSTEMS" / "Aspheres"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "317703.SPD").write_text(_sample_winlens_v4_spd(), encoding="utf-8")

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317703000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317703000",
                    "product_name": "Asph. condenser lens; Crown glass; D=18; F=15 Uncoated",
                    "category": "asphere",
                    "efl_mm": 15.0,
                    "diameter_mm": 18.0,
                    "material_summary": "Crown glass",
                    "coating": "Uncoated",
                }
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        imported = service.import_catalog_file("Excelitas", str(excelitas_json))
        result = service.import_winlens_library(str(tmp_path / "WinLens Library 2002"))
        links = service.get_record_links("winlens library 2002:317703")

        assert imported == 1
        assert result.imported_count >= 1
        assert result.linked_count == 1
        assert links[0]["catalog_id"] == "excelitas linos:g317703000"
        assert links[0]["match_type"] == "confirmed"
        assert "numeric part number overlap" in links[0]["reasons"]
        assert "matching efl" in links[0]["reasons"]
        assert "matching diameter" in links[0]["reasons"]
        assert "WinLens strong family match" in links[0]["reasons"]
        assert service.get_record("winlens library 2002:317703").availability_status is None
        summaries = service.search({"match_type_text": "confirmed"})
        assert any(item["catalog_id"] == "winlens library 2002:317703" for item in summaries)
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_load_winlens_alias_groups_extracts_qioptiq_cross_reference() -> None:
    tmp_path = _workspace_tmp_dir()
    try:
        basic_dir = tmp_path / "WinLens Library 2002" / "WinLens3DBasic"
        basic_dir.mkdir(parents=True, exist_ok=True)
        alias_file = basic_dir / "sh_l2.dat"
        alias_file.write_bytes(
            (
                b"322384000322307000063213000                  Achromat 80/25.4   "
                b"ECO-Vers.-322             Achromat         \r\n"
                b"322384000322307322                           Achromat  f = 80/25.4 mm\r\n"
                b"@N-BK7     N-SF5\r\n"
            )
        )

        groups = load_winlens_alias_groups(tmp_path / "WinLens Library 2002")

        matched = [
            group
            for group in groups
            if "322307322" in group.part_numbers and "063213000" in group.part_numbers
        ]
        assert matched
        assert "322307" in matched[0].family_numbers
        assert matched[0].materials == ["N-BK7", "N-SF5"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_prefers_alias_map_over_heuristic_overlap(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Achromats"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "322307.SPD").write_text(_sample_winlens_v4_spd().replace("317703.SPD", "322307.SPD"), encoding="utf-8")

    basic_dir = root / "WinLens3DBasic"
    basic_dir.mkdir(parents=True, exist_ok=True)
    (basic_dir / "sh_l2.dat").write_bytes(
        (
            b"322384000322307000063213000                  Achromat 80/25.4   "
            b"ECO-Vers.-322             Achromat         \r\n"
            b"322384000322307322                           Achromat  f = 80/25.4 mm\r\n"
            b"@N-BK7     N-SF5\r\n"
        )
    )

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g063213000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G063213000",
                    "product_name": "Achr. VIS ARB2; D=25.4; F=80; mounted",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                    "coating": "ARB2",
                },
                {
                    "catalog_id": "excelitas linos:g322307322",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "322307322",
                    "product_name": "Legacy alias for the same achromat family",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                },
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        result = service.import_winlens_library(str(root))
        links = service.get_record_links("winlens library 2002:322307")

        assert result.imported_count >= 1
        assert result.linked_count >= 1
        link_ids = [link["catalog_id"] for link in links[:2]]
        assert "excelitas linos:g063213000" in link_ids
        assert "excelitas linos:g322307322" in link_ids
        assert all(
            any(reason.startswith("WinLens alias") for reason in link["reasons"])
            for link in links[:2]
        )
        assert any(link["match_type"] == "confirmed" for link in links[:2])
        assert service.get_record("winlens library 2002:322307").availability_status is None
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_propagates_confirmed_family_across_coating_variants(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Achromats"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "322307.SPD").write_text(
        _sample_winlens_v4_spd().replace('"Asphere demo"', '"Achromat demo"').replace('"efl",15.0', '"efl",80.0').replace('"Stop Rad",9', '"Stop Rad",12.7').replace("317703.SPD", "322307.SPD"),
        encoding="utf-8",
    )
    basic_dir = root / "WinLens3DBasic"
    basic_dir.mkdir(parents=True, exist_ok=True)
    (basic_dir / "sh_l2.dat").write_bytes(
        (
            b"322384000322307000063213000                  Achromat 80/25.4   "
            b"ECO-Vers.-322             Achromat         \r\n"
            b"322384000322307322                           Achromat  f = 80/25.4 mm\r\n"
            b"@N-BK7     N-SF5\r\n"
        )
    )
    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g063213000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G063213000",
                    "product_name": "Achr. VIS Uncoated; D=25.4; F=80; mounted",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                    "coating": "Uncoated",
                },
                {
                    "catalog_id": "excelitas linos:g063213322",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G063213322",
                    "product_name": "Achr. VIS ARB2; D=25.4; F=80; mounted",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                    "coating": "ARB2",
                },
                {
                    "catalog_id": "excelitas linos:g063213329",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G063213329",
                    "product_name": "Achr. VIS ARB5; D=25.4; F=80; mounted",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                    "coating": "ARB5",
                },
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(root))
        links = service.get_record_links("winlens library 2002:322307")

        propagated = {
            link["catalog_id"]: link
            for link in links
            if link["catalog_id"] in {
                "excelitas linos:g063213000",
                "excelitas linos:g063213322",
                "excelitas linos:g063213329",
            }
        }

        assert set(propagated) == {
            "excelitas linos:g063213000",
            "excelitas linos:g063213322",
            "excelitas linos:g063213329",
        }
        assert all(link["match_type"] == "confirmed" for link in propagated.values())
        assert all(
            "WinLens coating-blind family propagation" in link["reasons"]
            for link in propagated.values()
        )
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_marks_alias_only_records_as_legacy(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Achromats"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "322307.SPD").write_text(
        _sample_winlens_v4_spd().replace("317703.SPD", "322307.SPD"),
        encoding="utf-8",
    )
    basic_dir = root / "WinLens3DBasic"
    basic_dir.mkdir(parents=True, exist_ok=True)
    (basic_dir / "sh_l2.dat").write_bytes(
        (
            b"322384000322307000063213000                  Achromat 80/25.4   "
            b"ECO-Vers.-322             Achromat         \r\n"
            b"322384000322307322                           Achromat  f = 80/25.4 mm\r\n"
            b"@N-BK7     N-SF5\r\n"
        )
    )

    service = CatalogService(MagicMock())

    try:
        result = service.import_winlens_library(str(root))
        record = service.get_record("winlens library 2002:322307")

        assert result.imported_count >= 1
        assert result.linked_count == 0
        assert record is not None
        assert record.availability_status == "legacy"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_promotes_strong_family_match_without_alias(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Aspheres"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "317708.SPD").write_text(
        _sample_winlens_v4_spd()
        .replace('"Asphere demo"', '"Aspherical condenser lens f = 40"')
        .replace('"efl",15.0', '"efl",40.0')
        .replace('"Stop Rad",9', '"Stop Rad",25.0')
        .replace("317703.SPD", "317708.SPD"),
        encoding="utf-8",
    )

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317708000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317708000",
                    "product_name": "Asph. condenser lens; D=50; F=40",
                    "category": "condenser",
                    "efl_mm": 40.0,
                    "diameter_mm": 50.0,
                },
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(root))
        links = service.get_record_links("winlens library 2002:317708")

        assert links[0]["catalog_id"] == "excelitas linos:g317708000"
        assert links[0]["match_type"] == "confirmed"
        assert "WinLens strong family match" in links[0]["reasons"]
        assert service.get_record("winlens library 2002:317708").availability_status is None
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_get_winlens_review_candidates_returns_only_high_confidence_candidates(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    spd_root = tmp_path / "WinLens Library 2002" / "LINOS_STANDARD_SYSTEMS" / "Aspheres"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "317703.SPD").write_text(_sample_winlens_v4_spd(), encoding="utf-8")

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317703000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317703000",
                    "product_name": "Asph. condenser lens; Crown glass; D=18; F=15 Uncoated",
                    "category": "asphere",
                    "efl_mm": 15.0,
                    "diameter_mm": 18.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())
    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(tmp_path / "WinLens Library 2002"))
        rows = service.get_winlens_review_candidates(76)

        assert rows == []
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_confirm_winlens_links_persists_manual_selection(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    spd_root = tmp_path / "WinLens Library 2002" / "LINOS_STANDARD_SYSTEMS" / "Aspheres"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "317703.SPD").write_text(_sample_winlens_v4_spd(), encoding="utf-8")

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317703000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317703000",
                    "product_name": "Asph. condenser lens; Crown glass; D=18; F=15 Uncoated",
                    "category": "asphere",
                    "efl_mm": 15.0,
                    "diameter_mm": 18.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())
    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(tmp_path / "WinLens Library 2002"))
        count = service.confirm_winlens_links(
            [
                {
                    "winlens_catalog_id": "winlens library 2002:317703",
                    "target_catalog_id": "excelitas linos:g317703000",
                }
            ]
        )
        payload = service._storage.load_cache_payload("winlens_confirmed_links")

        assert count == 1
        assert payload["links"]["winlens library 2002:317703"]["match_type"] == "confirmed"
        assert "Manual review apply" in payload["links"]["winlens library 2002:317703"]["reasons"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_delete_records_removes_marked_catalog_entries(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    excelitas_json = tmp_path / "records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317703000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317703000",
                    "product_name": "Asph. condenser lens; D=18; F=15",
                },
                {
                    "catalog_id": "excelitas linos:g317704000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317704000",
                    "product_name": "Asph. condenser lens; D=18; F=20",
                },
            ]
        ),
        encoding="utf-8",
    )
    service = CatalogService(MagicMock())
    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        removed = service.delete_records(["excelitas linos:g317703000"])

        assert removed == 1
        assert service.get_record("excelitas linos:g317703000") is None
        assert service.get_record("excelitas linos:g317704000") is not None
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_get_winlens_review_candidates_include_family_and_preview(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Aspheres"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "317703.SPD").write_text(_sample_winlens_v4_spd(), encoding="utf-8")

    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g317703000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317703000",
                    "product_name": "Asph. condenser lens; Crown glass; D=17; F=15",
                    "category": "asphere",
                    "efl_mm": 15.0,
                    "diameter_mm": 17.0,
                }
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())
    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(root))
        service._storage.save_cache_payload(
            "winlens_record_links",
            {
                "manufacturer": "WinLens Library 2002",
                "links": {
                    "winlens library 2002:317703": [
                        {
                            "catalog_id": "excelitas linos:g317703000",
                            "manufacturer": "Excelitas LINOS",
                            "part_number": "G317703000",
                            "product_name": "Asph. condenser lens; Crown glass; D=17; F=15",
                            "score": 80,
                            "match_type": "candidate",
                            "confidence_percent": 80,
                            "reasons": ["numeric part number overlap", "matching efl"],
                        }
                    ]
                },
            },
        )
        rows = service.get_winlens_review_candidates(76)

        assert rows
        assert rows[0]["family_key"] == "317703"
        assert "Confirm family 317703 -> G317703000" == rows[0]["preview"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_load_winlens_dat_records_imports_historical_lens_families() -> None:
    tmp_path = _workspace_tmp_dir()
    try:
        lens_path = tmp_path / "sh_l2.dat"
        lens_path.write_bytes(
            (
                b"322210000063128000                  Achromat  f = 80/18 mm                       \r\n"
                b"?N-BK7     N-F2      \r\n"
                b"033101000Hyperchromatic Doublet  f = 50/18 mm         \r\n"
                b"`@N-SF57    AIR       N-BK10    \r\n"
            )
        )

        records = load_winlens_dat_records(str(lens_path), "WinLens Library 2002")

        assert [record.part_number for record in records[:2]] == ["322210000", "063128000"]
        assert records[0].category == "achromat"
        assert records[0].efl_mm == 80.0
        assert records[0].diameter_mm == 18.0
        assert records[0].material_summary == "N-BK7, N-F2"
        assert any(record.category == "hyperchromatic doublet" for record in records)
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_persists_confirmed_links(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    root = tmp_path / "WinLens Library 2002"
    spd_root = root / "LINOS_STANDARD_SYSTEMS" / "Achromats"
    spd_root.mkdir(parents=True, exist_ok=True)
    (spd_root / "322307.SPD").write_text(
        _sample_winlens_v4_spd().replace("317703.SPD", "322307.SPD"),
        encoding="utf-8",
    )
    basic_dir = root / "WinLens3DBasic"
    basic_dir.mkdir(parents=True, exist_ok=True)
    (basic_dir / "sh_l2.dat").write_bytes(
        (
            b"322384000322307000063213000                  Achromat 80/25.4   "
            b"ECO-Vers.-322             Achromat         \r\n"
            b"322384000322307322                           Achromat  f = 80/25.4 mm\r\n"
            b"@N-BK7     N-SF5\r\n"
        )
    )
    excelitas_json = tmp_path / "excelitas_records.json"
    excelitas_json.write_text(
        json.dumps(
            [
                {
                    "catalog_id": "excelitas linos:g322307322",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "322307322",
                    "product_name": "Legacy alias for the same achromat family",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                },
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        service.import_catalog_file("Excelitas", str(excelitas_json))
        service.import_winlens_library(str(root))
        payload = service._storage.load_cache_payload("winlens_confirmed_links")
        persisted = payload.get("links", {})

        assert "winlens library 2002:322307" in persisted
        assert persisted["winlens library 2002:322307"]["catalog_id"] == "excelitas linos:g322307322"
        assert persisted["winlens library 2002:322307"]["match_type"] == "confirmed"
        summaries = service.search({"match_type_text": "confirmed"})
        assert any(item["catalog_id"] == "winlens library 2002:322307" for item in summaries)
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_load_winlens_table_records_imports_prisms_and_gratings() -> None:
    tmp_path = _workspace_tmp_dir()
    try:
        prism_path = tmp_path / "prisms.txt"
        prism_path.write_text(
            "\n".join(
                [
                    "note,Part#,Part# mount,PrismType,Depth,LinDim1,LinDim2,LinDim3,AngDim1,AngDim2,Glass1, GlassMaker1,Glass2, GlassMaker2",
                    "refl:90 uncoated,339910000,063901000,enPT_r_90,5,5,,,,,N-BK7,SCHOTT,,",
                ]
            ),
            encoding="utf-8",
        )
        grating_path = tmp_path / "gratings.txt"
        grating_path.write_text(
            "\n".join(
                [
                    "Part No.,Thickness (mm),Edge Length (mm),Grooves (1 / mm),Blaze Wavelength (nm),,,,",
                    "G392100000,6,12.7 x 12.7,300,300,Ruled grating; 300/300/12.7,mirror,ruled,na",
                ]
            ),
            encoding="utf-8",
        )

        prism_records = load_winlens_table_records(str(prism_path), "WinLens Library 2002")
        grating_records = load_winlens_table_records(str(grating_path), "WinLens Library 2002")

        assert [record.part_number for record in prism_records] == ["339910000", "063901000"]
        assert prism_records[0].category == "prism"
        assert prism_records[0].coating == "Uncoated"
        assert prism_records[0].material_summary == "N-BK7"
        assert grating_records[0].part_number == "G392100000"
        assert grating_records[0].category == "grating"
        assert grating_records[0].center_thickness_mm == 6.0
        assert grating_records[0].diameter_mm == 12.7
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_counts_table_records(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    root = tmp_path / "WinLens Library 2002" / "WinLens3DBasic"
    root.mkdir(parents=True, exist_ok=True)
    (root / "prisms.txt").write_text(
        "\n".join(
            [
                "note,Part#,Part# mount,PrismType,Depth,LinDim1,LinDim2,LinDim3,AngDim1,AngDim2,Glass1, GlassMaker1,Glass2, GlassMaker2",
                "refl:90 coated,339952000,,enPT_r_90,10,10,,,,,N-BK7,SCHOTT,,",
            ]
        ),
        encoding="utf-8",
    )
    (root / "gratings.txt").write_text(
        "\n".join(
            [
                "Part No.,Thickness (mm),Edge Length (mm),Grooves (1 / mm),Blaze Wavelength (nm),,,,",
                "G392127000,6,12.7 x 12.7,600,UV,Holographic Grating; 600/UV/12.7,mirror,holo,na",
            ]
        ),
        encoding="utf-8",
    )

    service = CatalogService(MagicMock())

    try:
        result = service.import_winlens_library(str(tmp_path / "WinLens Library 2002"))
        prism = service.get_record("winlens library 2002:339952000")
        grating = service.get_record("winlens library 2002:g392127000")

        assert result.imported_count == 2
        assert prism is not None
        assert prism.category == "prism"
        assert grating is not None
        assert grating.category == "grating"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_load_winlens_dat_records_imports_cylinder_and_grin_families() -> None:
    tmp_path = _workspace_tmp_dir()
    try:
        cylinder_path = tmp_path / "sh_c1.dat"
        cylinder_path.write_bytes(
            (
                b"318334000063426000                  Cylinder  f = 80/31.5 mm  ( contour: see     \r\n"
                b"@N-BK7     \r\n"
            )
        )
        grin_path = tmp_path / "sh_grin.dat"
        grin_path.write_bytes(
            (
                b"fff?fff?fff?fff?X9,AGRIN rod  \r\n"
                b"399743000                           f = 4.45mm: pitch 0.25: na 0.20: wd 0.00mm   \r\n"
                b"6@GRIN slab \r\n"
                b"399781000                           Cyl f = 1.24mm: pitch 0.24: na 0.2: wd 0.10mm\r\n"
            )
        )

        cylinder_records = load_winlens_dat_records(str(cylinder_path), "WinLens Library 2002")
        grin_records = load_winlens_dat_records(str(grin_path), "WinLens Library 2002")

        assert [record.part_number for record in cylinder_records] == ["318334000", "063426000"]
        assert cylinder_records[0].category == "cylindrical"
        assert cylinder_records[0].efl_mm == 80.0
        assert cylinder_records[0].material_summary == "N-BK7"
        assert grin_records[0].part_number == "399743000"
        assert grin_records[0].category == "grin lens"
        assert grin_records[0].material_summary == "GRIN"
        assert grin_records[1].category == "grin cylindrical"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_winlens_library_counts_dat_records(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    root = tmp_path / "WinLens Library 2002" / "WinLens3DBasic"
    root.mkdir(parents=True, exist_ok=True)
    (root / "sh_c1.dat").write_bytes(
        (
            b"318334000063426000                  Cylinder  f = 80/31.5 mm  ( contour: see     \r\n"
            b"@N-BK7     \r\n"
        )
    )
    (root / "sh_grin.dat").write_bytes(
        (
            b"fff?fff?fff?fff?X9,AGRIN rod  \r\n"
            b"399743000                           f = 4.45mm: pitch 0.25: na 0.20: wd 0.00mm   \r\n"
        )
    )

    service = CatalogService(MagicMock())

    try:
        result = service.import_winlens_library(str(tmp_path / "WinLens Library 2002"))
        cylinder = service.get_record("winlens library 2002:318334000")
        grin = service.get_record("winlens library 2002:399743000")

        assert result.imported_count == 3
        assert cylinder is not None
        assert cylinder.category == "cylindrical"
        assert grin is not None
        assert grin.category == "grin lens"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)
