"""Tests for online stock-lens catalog download helpers."""

from __future__ import annotations

import io
import json
import math
import shutil
import zipfile
from pathlib import Path
from struct import Struct
from uuid import uuid4

import requests
from unittest.mock import MagicMock

from optiland_gui.services.catalog_service import (
    CatalogService,
    EDMUND_FALLBACK_ARCHIVE_URL,
    EDMUND_PRODUCTS_PAGE_URL,
    EDMUND_ZEMAX_PAGE_URL,
    THORLABS_ZEMAX_PAGE_URL,
    extract_edmund_download_url,
    extract_thorlabs_download_url,
)


class _FakeResponse:
    def __init__(
        self,
        text: str = "",
        content: bytes = b"",
        status_code: int = 200,
        url: str = "",
    ) -> None:
        self.text = text
        self.content = content
        self.status_code = status_code
        self.url = url

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(
                f"{self.status_code} error",
                response=self,
            )
        return None


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **kwargs):  # noqa: ANN003
        self.calls.append(url)
        if not self._responses:
            raise AssertionError("No fake response left for request")
        return self._responses.pop(0)


def _build_zip(entries: dict[str, bytes]) -> bytes:
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return data.getvalue()


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
    entry_header = header.pack(
        entry_name.encode("latin1").ljust(100, b"\0"),
        len(zmx_bytes),
        a_value,
        b_value,
    )
    return b"\xE9\x03\x00\x00" + entry_header + _encode_zmf_payload(zmx_bytes, a_value, b_value)


def test_extract_edmund_download_url_prefers_catalog_archive() -> None:
    html = """
    <html>
      <body>
        <a href="/media/abc/other.zip">Other</a>
        <a href="/media/xyz/2019zmf.zip">Download Now</a>
      </body>
    </html>
    """

    url = extract_edmund_download_url(html)

    assert url == "https://www.edmundoptics.com/media/xyz/2019zmf.zip"


def test_extract_thorlabs_download_url_prefers_catalog_file() -> None:
    html = """
    <html>
      <body>
        <a href="/_sd.cfm?fileName=manual.pdf">Manual</a>
        <a href="/_sd.cfm?fileName=Thorlabs_Zemax_Catalog.zip">Download</a>
      </body>
    </html>
    """

    url = extract_thorlabs_download_url(html, THORLABS_ZEMAX_PAGE_URL)

    assert url == "https://www.thorlabs.com/_sd.cfm?fileName=Thorlabs_Zemax_Catalog.zip"


def _workspace_tmp_dir() -> Path:
    path = Path("tests") / "_tmp_catalog_service_online" / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_download_edmund_catalog_downloads_and_imports_supported_zmx(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = (
        Path("tests/zemax_files/lens1.zmx")
        .read_bytes()
    )
    html = '<a href="/media/abc/2019zmf.zip">Download Now</a>'
    session = _FakeSession(
        [
            _FakeResponse(text=html),
            _FakeResponse(content=_build_zip({"lens1.zmx": zmx_bytes})),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_edmund_catalog()

        assert session.calls[0] == EDMUND_ZEMAX_PAGE_URL
        assert result.imported_count == 1
        assert Path(result.archive_path).is_file()
        assert any(path.endswith("lens1.zmx") for path in result.extracted_files)
        assert service.get_manufacturers() == ["Edmund"]
        summaries = service.search({"manufacturer": "Edmund"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_edmund_catalog_falls_back_when_page_is_forbidden(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    session = _FakeSession(
        [
            _FakeResponse(status_code=403),
            _FakeResponse(content=_build_zip({"lens1.zmx": zmx_bytes})),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_edmund_catalog()

        assert session.calls[0] == EDMUND_ZEMAX_PAGE_URL
        assert session.calls[1] == EDMUND_FALLBACK_ARCHIVE_URL
        assert result.source_url == EDMUND_FALLBACK_ARCHIVE_URL
        assert result.imported_count == 1
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_edmund_catalog_keeps_archive_when_no_supported_files(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    html = '<a href="/media/abc/2019zmf.zip">Download Now</a>'
    session = _FakeSession(
        [
            _FakeResponse(text=html),
            _FakeResponse(content=_build_zip({"catalog.zmf": _build_test_zmf("08068", zmx_bytes)})),
            _FakeResponse(text="<html></html>", url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=08068"),
            _FakeResponse(text="<html></html>", url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=08-068"),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_edmund_catalog()

        assert result.imported_count == 1
        assert "imported 1 catalog entries from 1 ZMF catalog file(s)" in result.message
        assert Path(result.archive_path).is_file()
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_edmund_catalog_mentions_saved_zmf_alongside_imported_zmx(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zmf_bytes = _build_test_zmf("08068", zmx_bytes)
    html = '<a href="/media/abc/2019zmf.zip">Download Now</a>'
    session = _FakeSession(
        [
            _FakeResponse(text=html),
            _FakeResponse(
                content=_build_zip(
                    {
                        "catalog.zmf": zmf_bytes,
                        "lens1.zmx": zmx_bytes,
                    }
                )
            ),
            _FakeResponse(text="<html></html>", url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=08068"),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_edmund_catalog()

        assert result.imported_count == 1
        assert "imported 1 supported catalog files" in result.message
        assert "1 ZMF catalog file(s)" in result.message
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_supports_direct_zmf(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmf_path = tmp_path / "catalog.zmf"
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zmf_path.write_bytes(_build_test_zmf("08068", zmx_bytes))
    service = CatalogService(MagicMock())

    try:
        count = service.import_catalog_file("Edmund", str(zmf_path))
        summaries = service.search({"manufacturer": "Edmund"})

        assert count == 1
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "08068"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_supports_direct_zip_with_zmf(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zip_path = tmp_path / "edmund_catalog.zip"
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zip_path.write_bytes(_build_zip({"catalog.zmf": _build_test_zmf("08068", zmx_bytes)}))
    service = CatalogService(MagicMock())

    try:
        count = service.import_catalog_file("Edmund", str(zip_path))
        summaries = service.search({"manufacturer": "Edmund"})

        assert count == 1
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "08068"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_enriches_missing_metadata_from_local_product_name(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    json_path = tmp_path / "edmund_local_enrichment.json"
    json_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "catalog_id": "edmund:49-847",
                        "manufacturer": "Edmund",
                        "part_number": "49-847",
                        "product_name": "25.4 mm Diameter x 50.0 mm EFL Uncoated Plano-Convex Lens N-BK7",
                        "category": "",
                        "efl_mm": None,
                        "diameter_mm": None,
                        "material_summary": "",
                        "coating": "",
                        "surfaces": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = CatalogService(MagicMock(), session=_FakeSession([]))

    try:
        service.import_catalog_file("Edmund", str(json_path))
        details = service.get_record_details("edmund:49-847")

        assert details is not None
        assert details["category"] == "plano-convex"
        assert details["efl_mm"] == 50.0
        assert details["diameter_mm"] == 25.4
        assert details["material_summary"] == "N-BK7"
        assert details["coating"] == "Uncoated"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_enriches_compact_edmund_name_without_units(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    json_path = tmp_path / "edmund_compact_enrichment.json"
    json_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "catalog_id": "edmund:39469",
                        "manufacturer": "Edmund",
                        "part_number": "39469",
                        "product_name": "Lens Asphere ZnSe 12.7 x 6.35 Unctd",
                        "category": "",
                        "efl_mm": None,
                        "diameter_mm": None,
                        "material_summary": "ZNSE",
                        "coating": "",
                        "surfaces": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    service = CatalogService(MagicMock(), session=_FakeSession([]))

    try:
        service.import_catalog_file("Edmund", str(json_path))
        details = service.get_record_details("edmund:39469")

        assert details is not None
        assert details["category"] == "asphere"
        assert details["diameter_mm"] == 12.7
        assert details["efl_mm"] == 6.35
        assert details["material_summary"] == "ZNSE"
        assert details["coating"] == "Uncoated"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_enriches_missing_metadata_from_official_product_page(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    json_path = tmp_path / "edmund_online_enrichment.json"
    json_path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "catalog_id": "edmund:49-848",
                        "manufacturer": "Edmund",
                        "part_number": "49-848",
                        "product_name": "Demo Lens",
                        "category": "",
                        "efl_mm": None,
                        "diameter_mm": None,
                        "material_summary": "",
                        "coating": "",
                        "url": "https://www.edmundoptics.com/p/demo-lens/12345/",
                        "surfaces": [],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    session = _FakeSession(
        [
            _FakeResponse(
                text=(
                    "<html><body>"
                    "Plano-Convex Lens 25.4 mm Diameter 75.0 mm EFL "
                    "Material: N-BK7 Coating: VIS 0"
                    "</body></html>"
                ),
                url="https://www.edmundoptics.com/p/demo-lens/12345/",
            )
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        service.import_catalog_file("Edmund", str(json_path))
        details = service.get_record_details("edmund:49-848")

        assert details is not None
        assert details["category"] == "plano-convex"
        assert details["efl_mm"] == 75.0
        assert details["diameter_mm"] == 25.4
        assert details["material_summary"] == "N-BK7"
        assert details["coating"] == "VIS 0"
        assert session.calls == ["https://www.edmundoptics.com/p/demo-lens/12345/"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_import_catalog_file_skips_unreadable_paths_when_others_succeed(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    good_zmf_path = tmp_path / "catalog.zmf"
    broken_zmx_path = tmp_path / "broken.zmx"
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    good_zmf_path.write_bytes(_build_test_zmf("08068", zmx_bytes))
    broken_zmx_path.write_text("not a readable zemax file", encoding="utf-8")
    service = CatalogService(MagicMock())

    try:
        count = service.import_catalog_file(
            "Edmund",
            [str(good_zmf_path), str(broken_zmx_path)],
        )
        summaries = service.search({"manufacturer": "Edmund"})

        assert count == 1
        assert len(summaries) == 1
        assert summaries[0]["part_number"] == "08068"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_download_thorlabs_catalog_downloads_and_imports_supported_zmx(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/thorlabs_lj1598l1.zmx").read_bytes()
    html = '<a href="/_sd.cfm?fileName=Thorlabs_Zemax_Catalog.zip">Download</a>'
    session = _FakeSession(
        [
            _FakeResponse(text=html, url=THORLABS_ZEMAX_PAGE_URL),
            _FakeResponse(content=_build_zip({"thorlabs_lj1598l1.zmx": zmx_bytes})),
            _FakeResponse(
                text="<html><body>25.4 mm Diameter 150.0 mm EFL</body></html>",
                url="https://www.thorlabs.com/thorproduct.cfm?partnumber=LJ1598L1",
            ),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        result = service.download_thorlabs_catalog()

        assert session.calls[0] == THORLABS_ZEMAX_PAGE_URL
        assert result.imported_count == 1
        assert Path(result.archive_path).is_file()
        assert service.get_manufacturers() == ["Thorlabs"]
        summaries = service.search({"manufacturer": "Thorlabs"})
        assert len(summaries) == 1
        assert summaries[0]["part_number"]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_resolve_product_url_prefers_redirected_edmund_product_page(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zmf_path = tmp_path / "catalog.zmf"
    zmf_path.write_bytes(_build_test_zmf("49-847", zmx_bytes))
    session = _FakeSession(
        [
            _FakeResponse(
                text="",
                url="https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/",
            ),
            _FakeResponse(
                text="<html><body>25.4 mm Diameter 25.4 mm EFL Plano-Convex Lens</body></html>",
                url="https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/",
            ),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        service.import_catalog_file("Edmund", str(zmf_path))
        resolved = service.resolve_product_url("edmund:49-847")

        assert resolved == "https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/"
        assert session.calls == [
            f"{EDMUND_PRODUCTS_PAGE_URL}?Query=49-847",
            "https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/",
        ]
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_resolve_product_url_extracts_matching_edmund_product_link_from_search_html(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zmf_path = tmp_path / "catalog.zmf"
    zmf_path.write_bytes(_build_test_zmf("49-847", zmx_bytes))
    html = """
    <html>
      <body>
        <a href="/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/">Lens</a>
        <div>Stock #49-847</div>
      </body>
    </html>
    """
    session = _FakeSession(
        [
            _FakeResponse(text=html, url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=49-847"),
            _FakeResponse(
                text="<html><body>25.4 mm Diameter 25.4 mm EFL Plano-Convex Lens</body></html>",
                url="https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/",
            ),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        service.import_catalog_file("Edmund", str(zmf_path))
        resolved = service.resolve_product_url("edmund:49-847")

        assert resolved == "https://www.edmundoptics.com/p/254mm-dia-x-254mm-fl-uncoated-plano-convex-lens/10319/"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)


def test_resolve_product_url_falls_back_to_live_edmund_search_page(monkeypatch) -> None:
    tmp_path = _workspace_tmp_dir()
    monkeypatch.setattr(
        "optiland_gui.catalogs.storage.QStandardPaths.writableLocation",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    zmx_bytes = Path("tests/zemax_files/lens1.zmx").read_bytes()
    zmf_path = tmp_path / "catalog.zmf"
    zmf_path.write_bytes(_build_test_zmf("49-847", zmx_bytes))
    session = _FakeSession(
        [
            _FakeResponse(text="<html></html>", url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=49-847"),
            _FakeResponse(text="<html></html>", url=f"{EDMUND_PRODUCTS_PAGE_URL}?Query=49847"),
        ]
    )
    service = CatalogService(MagicMock(), session=session)

    try:
        service.import_catalog_file("Edmund", str(zmf_path))
        resolved = service.resolve_product_url("edmund:49-847")

        assert resolved == f"{EDMUND_PRODUCTS_PAGE_URL}?Query=49-847"
    finally:
        shutil.rmtree(tmp_path.parent, ignore_errors=True)
