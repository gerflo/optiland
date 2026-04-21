"""Tests for Excelitas / LINOS catalog import helpers."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from optiland_gui.catalogs.importers.excelitas_linos import (
    EXCELITAS_DISCOVERY_PAGE_URLS,
    extract_excelitas_document_urls,
    extract_excelitas_family_urls,
    extract_excelitas_zemax_urls,
)
from optiland_gui.services.catalog_service import CatalogService

from .test_catalog_service_online import _FakeResponse, _FakeSession


def _build_zip(entries: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return data.getvalue()


def _workspace_tmp_dir() -> Path:
    path = Path("tests") / "_tmp_excelitas_catalog_service" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def _sample_zmx_bytes() -> bytes:
    return (Path(__file__).resolve().parents[1] / "zemax_files" / "lens1.zmx").read_bytes()


def test_extract_excelitas_zemax_urls_returns_absolute_document_links() -> None:
    html = """
    <html><body>
      <a href="/files/family.zip">ZEMAX-Files</a>
    </body></html>
    """

    urls = extract_excelitas_zemax_urls(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/demo.html",
    )

    assert urls == ["https://linosoptics.excelitas.com/files/family.zip"]


def test_extract_excelitas_document_urls_reads_docs_tab_links() -> None:
    html = """
    <html><body>
      <div id="tab_docs">
        <ol>
          <li><a href="/out/Graphics/en/00134630_0.pdf" target="_blank" class="pdf">Datasheet</a></li>
          <li><a href="/out/Graphics/en/demo.step" target="_blank">STEP</a></li>
        </ol>
      </div>
    </body></html>
    """

    urls = extract_excelitas_document_urls(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/demo.html",
    )

    assert urls == [
        "https://linosoptics.excelitas.com/out/Graphics/en/00134630_0.pdf",
        "https://linosoptics.excelitas.com/out/Graphics/en/demo.step",
    ]


def test_excelitas_discovery_pages_cover_multiple_official_catalog_roots() -> None:
    assert any("Singlets/Plano-Convex-Lenses/" in url for url in EXCELITAS_DISCOVERY_PAGE_URLS)
    assert any("Singlets/Aspheric-Condenser-Lenses/" in url for url in EXCELITAS_DISCOVERY_PAGE_URLS)
    assert any("LINOS-Achromats-Lens-Systems/Achromats-positive/" in url for url in EXCELITAS_DISCOVERY_PAGE_URLS)
    assert any("LINOS-Laseroptics-Lenses/" in url for url in EXCELITAS_DISCOVERY_PAGE_URLS)


def test_extract_excelitas_family_urls_filters_for_official_family_pages() -> None:
    html = """
    <html><body>
      <a href="/en/Precision-Optics/Singlets/Plano-Convex-Lenses/Plano-convex-lenses-mounted.html">
        Plano-convex lenses, mounted
      </a>
      <a href="/en/Precision-Optics/Optics-Software/Winlens-Basic/Free-software-Winlens-Basic.html">
        WinLens
      </a>
      <a href="/files/family.zip">ZEMAX-Files</a>
    </body></html>
    """

    urls = extract_excelitas_family_urls(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/",
    )

    assert urls == [
        (
            "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
            "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
        )
    ]


def test_import_html_page_parses_variant_table_rows_and_coating_options() -> None:
    html = """
    <html><body>
      <h1>Plano-convex lenses, mounted</h1>
      <table class="variant_list">
        <tr class="odd">
          <td class="bestnr" width="100px"><a id="G052101000" href="#popup_G052101000">G052101000</a></td>
          <td>Plano-convex lens; N-LaSF9; D=3; F=2.5; mounted</td>
          <td>
            <select name="aid" class="aid">
              <option value="G052101000">Uncoated&nbsp;&ndash;&nbsp;€&nbsp;80,00</option>
              <option value="G052101322">ARB2-VIS&nbsp;&ndash;&nbsp;€&nbsp;94,00</option>
            </select>
          </td>
        </tr>
      </table>
    </body></html>
    """
    from optiland_gui.catalogs.importers.excelitas_linos import ExcelitasCatalogImporter

    records = ExcelitasCatalogImporter().import_html_page(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Plano-Convex-Lenses/demo.html",
    )

    assert len(records) == 2
    assert records[0].part_number == "G052101000"
    assert records[0].coating == "Uncoated"
    assert records[0].diameter_mm == 3.0
    assert records[0].efl_mm == 2.5
    assert records[1].part_number == "G052101322"
    assert records[1].coating == "ARB2-VIS"


def test_import_html_page_merges_coating_from_excelitas_spec_table() -> None:
    html = """
    <html><body>
      <h1>Achromats VIS, Positive; Dia. 3 mm to 31.5 mm, Mounted</h1>
      <table>
        <tr>
          <th>Part No.</th>
          <th>Optic Size (mm)</th>
          <th>Focal Length (mm)</th>
          <th>Coating</th>
        </tr>
        <tr>
          <td><a href="/products/g063213000">G063213000</a></td>
          <td>25.4</td>
          <td>80</td>
          <td>ARB2</td>
        </tr>
      </table>
      <a href="/products/g063213000">G063213000</a> Achr. VIS; D=25.4; F=80; mounted
    </body></html>
    """
    from optiland_gui.catalogs.importers.excelitas_linos import ExcelitasCatalogImporter

    records = ExcelitasCatalogImporter().import_html_page(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/LINOS-Achromats-Lens-Systems/Achromats-positive/demo.html",
    )

    assert len(records) == 1
    assert records[0].part_number == "G063213000"
    assert records[0].coating == "ARB2"


def test_import_html_page_can_infer_material_from_page_title_context() -> None:
    html = """
    <html><body>
      <h1>Plano-concave lenses, mounted (N-BK7)</h1>
      <a href="/products/g314332000">G314332000</a> Plano-concave lens; D=12.5; F=25 mounted
    </body></html>
    """
    from optiland_gui.catalogs.importers.excelitas_linos import ExcelitasCatalogImporter

    records = ExcelitasCatalogImporter().import_html_page(
        html,
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Plano-Concave-Lenses/Plano-concave-lenses-mounted-N-BK7.html",
    )

    assert len(records) == 1
    assert records[0].part_number == "G314332000"
    assert records[0].material_summary == "N-BK7"


def test_download_excelitas_catalog_merges_shop_metadata_with_zmx(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = _sample_zmx_bytes()
    family_url = "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/demo.html"
    html = """
    <html>
      <body>
        <h1>Plano-convex lenses, unmounted</h1>
        <a href="/products/g314419000">G314419000</a> Plano-convex lens; Fused silica; D=6; F=10 Uncoated
        <a href="/files/family.zip">ZEMAX-Files</a>
      </body>
    </html>
    """
    session = _FakeSession(
        [
            _FakeResponse(text=html, url=family_url),
            _FakeResponse(content=_build_zip({"G314419000.zmx": zmx_bytes})),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog([family_url])

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G314419000"
        assert summaries[0]["category"] == "plano-convex"
        assert summaries[0]["diameter_mm"] == 6.0
        assert summaries[0]["efl_mm"] == 10.0
        assert summaries[0]["material_summary"] == "Fused silica"
        assert summaries[0]["coating"] == "Uncoated"
        assert "linked Zemax files" in result.message
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_supports_metadata_only_pages(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    family_url = "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/demo.html"
    html = """
    <html>
      <body>
        <h1>Aspheric Condenser Lenses</h1>
        <a href="/products/g317703000">G317703000</a> Asph. condenser lens; Crown glass; D=18; F=15 Uncoated
      </body>
    </html>
    """
    session = _FakeSession([_FakeResponse(text=html, url=family_url)])
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog([family_url])

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G317703000"
        assert summaries[0]["category"] == "asphere"
        assert summaries[0]["diameter_mm"] == 18.0
        assert summaries[0]["efl_mm"] == 15.0
        assert summaries[0]["material_summary"] == "Crown glass"
        assert summaries[0]["coating"] == "Uncoated"
        assert "metadata-only records" in result.message
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_discovers_family_pages_before_fallback(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(
        "optiland_gui.services.catalog_service.EXCELITAS_DISCOVERY_PAGE_URLS",
        ["https://linosoptics.excelitas.com/en/Precision-Optics/"],
    )
    landing_html = """
    <html><body>
      <a href="/en/Precision-Optics/Singlets/Plano-Convex-Lenses/Plano-convex-lenses-mounted.html">
        Plano-convex lenses, mounted
      </a>
    </body></html>
    """
    family_url = (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
    )
    family_html = """
    <html>
      <body>
        <h1>Plano-convex lenses, mounted</h1>
        <a href="/products/g340001000">G340001000</a> Plano-convex lens; Fused silica; D=8; F=16 Uncoated
      </body>
    </html>
    """
    session = _FakeSession(
        [
            _FakeResponse(text=landing_html, url="https://linosoptics.excelitas.com/en/Precision-Optics/"),
            _FakeResponse(text=family_html, url=family_url),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog()

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G340001000"
        assert summaries[0]["diameter_mm"] == 8.0
        assert summaries[0]["efl_mm"] == 16.0
        assert "metadata-only records" in result.message
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_traverses_category_pages_to_find_family_pages(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(
        "optiland_gui.services.catalog_service.EXCELITAS_DISCOVERY_PAGE_URLS",
        ["https://linosoptics.excelitas.com/en/Precision-Optics/"],
    )
    landing_html = """
    <html><body>
      <a href="/en/Precision-Optics/Singlets/Plano-Convex-Lenses.html">
        Plano-Convex Lenses
      </a>
    </body></html>
    """
    category_url = "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/Plano-Convex-Lenses.html"
    category_html = """
    <html><body>
      <a href="/en/Precision-Optics/Singlets/Plano-Convex-Lenses/Plano-convex-lenses-mounted.html">
        Plano-convex lenses, mounted
      </a>
    </body></html>
    """
    family_url = (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
    )
    family_html = """
    <html>
      <body>
        <h1>Plano-convex lenses, mounted</h1>
        <a href="/products/g340001111">G340001111</a> Plano-convex lens; Fused silica; D=12; F=24 Uncoated
      </body>
    </html>
    """
    session = _FakeSession(
        [
            _FakeResponse(text=landing_html, url="https://linosoptics.excelitas.com/en/Precision-Optics/"),
            _FakeResponse(text=category_html, url=category_url),
            _FakeResponse(text=family_html, url=family_url),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog()

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G340001111"
        assert summaries[0]["diameter_mm"] == 12.0
        assert summaries[0]["efl_mm"] == 24.0
        assert result.source_url == family_url
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_falls_back_to_default_family_urls(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(
        "optiland_gui.services.catalog_service.EXCELITAS_DISCOVERY_PAGE_URLS",
        ["https://linosoptics.excelitas.com/en/Precision-Optics/"],
    )
    fallback_family_url = (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Concave-Lenses/Plano-concave-lenses-unmounted-N-BK7.html"
    )
    monkeypatch.setattr(
        "optiland_gui.services.catalog_service.EXCELITAS_DEFAULT_FAMILY_URLS",
        [fallback_family_url],
    )
    session = _FakeSession(
        [
            _FakeResponse(text="<html><body>No family links here</body></html>", url="https://linosoptics.excelitas.com/en/Precision-Optics/"),
            _FakeResponse(
                text="""
                <html><body>
                  <h1>Plano-concave lenses, unmounted</h1>
                  <a href="/products/g350002000">G350002000</a>
                  Plano-concave lens; Crown glass; D=10; F=25 Uncoated
                </body></html>
                """,
                url=fallback_family_url,
            ),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog()

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G350002000"
        assert result.source_url == fallback_family_url
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_reuses_cached_family_urls(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    cached_family_url = (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
    )
    family_html = """
    <html>
      <body>
        <h1>Plano-convex lenses, mounted</h1>
        <a href="/products/g340009999">G340009999</a> Plano-convex lens; Fused silica; D=14; F=28 Uncoated
      </body>
    </html>
    """
    session = _FakeSession([_FakeResponse(text=family_html, url=cached_family_url)])
    service = CatalogService(MagicMock(), session=session)
    service._storage.save_cache_payload(
        "excelitas_family_urls",
        {
            "manufacturer": "Excelitas LINOS",
            "urls": [cached_family_url],
        },
    )

    try:
        result = service.download_excelitas_catalog()

        assert result.imported_count == 1
        summaries = service.search({"manufacturer": "Excelitas LINOS"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "G340009999"
        assert session.calls == [cached_family_url]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_excelitas_catalog_saves_document_manifest(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    family_url = (
        "https://linosoptics.excelitas.com/en/Precision-Optics/Singlets/"
        "Plano-Convex-Lenses/Plano-convex-lenses-mounted.html"
    )
    family_html = """
    <html>
      <body>
        <h1>Plano-convex lenses, mounted</h1>
        <div id="tab_docs">
          <ol>
            <li><a href="/out/Graphics/en/00134630_0.pdf">Datasheet</a></li>
          </ol>
        </div>
        <table class="variant_list">
          <tr class="odd">
            <td class="bestnr"><a id="G052101000" href="#popup_G052101000">G052101000</a></td>
            <td>Plano-convex lens; N-LaSF9; D=3; F=2.5; mounted</td>
            <td><select name="aid"><option value="G052101000">Uncoated – € 80,00</option></select></td>
          </tr>
        </table>
      </body>
    </html>
    """
    session = _FakeSession([_FakeResponse(text=family_html, url=family_url)])
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_excelitas_catalog([family_url])
        manifest = service._storage.load_cache_payload("excelitas_document_urls")

        assert result.imported_count == 1
        assert "official document link" in result.message
        assert manifest["documents"][family_url] == [
            "https://linosoptics.excelitas.com/out/Graphics/en/00134630_0.pdf"
        ]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)
