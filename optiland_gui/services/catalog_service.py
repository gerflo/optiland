"""Catalog service for stock-lens import, search, cache, and insertion lookup."""

from __future__ import annotations

import html
import re
import warnings
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse

import requests

from optiland_gui.catalogs.importers import (
    ExcelitasCatalogImporter,
    EdmundCatalogImporter,
    ThorlabsCatalogImporter,
    WinLensCatalogImporter,
)
from optiland_gui.catalogs.importers.winlens_spd import (
    is_winlens_catalog_path,
    load_winlens_alias_groups,
)
from optiland_gui.catalogs.importers.excelitas_linos import (
    EXCELITAS_DISCOVERY_PAGE_URLS,
    EXCELITAS_DEFAULT_FAMILY_URLS,
    extract_excelitas_document_urls,
    extract_excelitas_family_urls,
    extract_excelitas_zemax_urls,
    looks_like_excelitas_family_page,
)
from optiland_gui.catalogs.matching import build_winlens_match_map
from optiland_gui.catalogs.search import CatalogSearchQuery, CatalogSearchService
from optiland_gui.catalogs.storage import CatalogStorage
from optiland_gui.catalogs.schema import CatalogLensRecord, LensSurfaceSpec

EDMUND_ZEMAX_PAGE_URL = "https://www.edmundoptics.com/products/services/zemax-catalog/"
EDMUND_PRODUCTS_PAGE_URL = "https://www.edmundoptics.com/products/"
THORLABS_ZEMAX_PAGE_URL = "https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Zemax"
THORLABS_PRODUCTS_PAGE_URL = "https://www.thorlabs.com/navigation.cfm?guide_id=1"
EXCELITAS_SHOP_ROOT_URL = "https://linosoptics.excelitas.com/"
EDMUND_FALLBACK_ARCHIVE_URL = (
    "https://www.edmundoptics.com/media/onujl21f/edmund-optics-2019zmf.zip"
)
_ZIP_HREF_RE = re.compile(r'href="([^"]+\.zip)"', re.IGNORECASE)
_CATALOG_FILE_HREF_RE = re.compile(r'href="([^"]+\.(?:zip|zmf|zmx))"', re.IGNORECASE)
_EDMUND_PRODUCT_HREF_RE = re.compile(r'href="([^"]*/p/[^"]+)"', re.IGNORECASE)
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
_CATEGORY_KEYWORDS = (
    ("cylindrical", "cylindrical"),
    ("achromat", "achromat"),
    ("doublet", "doublet"),
    ("triplet", "triplet"),
    ("double-convex", "bi-convex"),
    ("double convex", "bi-convex"),
    ("double-concave", "bi-concave"),
    ("double concave", "bi-concave"),
    ("plano-convex", "plano-convex"),
    ("planoconvex", "plano-convex"),
    ("plano-concave", "plano-concave"),
    ("planoconcave", "plano-concave"),
    ("bi-convex", "bi-convex"),
    ("biconvex", "bi-convex"),
    ("bi-concave", "bi-concave"),
    ("biconcave", "bi-concave"),
    ("meniscus", "meniscus"),
    ("aspheric", "asphere"),
    ("asphere", "asphere"),
    ("tube lens", "tube lens"),
    ("scan lens", "scan lens"),
    ("f-theta", "f-theta"),
)
_FOCAL_MM_RE = re.compile(r"\bf\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*mm\b", re.IGNORECASE)
_FOCAL_MM_ALT_RE = re.compile(
    r"\b([0-9]+(?:\.[0-9]+)?)\s*mm\s*(?:efl|fl|focal length)\b",
    re.IGNORECASE,
)
_DIAMETER_EFL_PAIR_RE = re.compile(
    r"\b([0-9]+(?:\.[0-9]+)?)\s*x\s*([0-9]+(?:\.[0-9]+)?)\b",
    re.IGNORECASE,
)
_DIAMETER_MM_RE = re.compile(
    r"(?:[Øø]|diameter\s*=?|dia\.\s*=?|d\s*=)\s*([0-9]+(?:\.[0-9]+)?)\s*mm\b",
    re.IGNORECASE,
)
_DIAMETER_MM_ALT_RE = re.compile(
    r"\b([0-9]+(?:\.[0-9]+)?)\s*mm\s*(?:diameter|dia\.?)\b",
    re.IGNORECASE,
)
_MATERIAL_RE = re.compile(
    r"\b(?:material|substrate|glass)\s*[:\-]?\s*([A-Z0-9\-+_/., ]{2,40})",
    re.IGNORECASE,
)
_COATING_RE = re.compile(
    r"\b(?:coating|ar coated|arc)\s*[:\-]?\s*([A-Z0-9\-+_/., ]{2,60})",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_SPACE_RE = re.compile(r"\s+")
_MAX_ONLINE_ENRICHMENT_RECORDS = 100
_MAX_EXCELITAS_DISCOVERY_DEPTH = 2
_MAX_EXCELITAS_DISCOVERY_PAGES = 40
_EDMUND_PART_RE = re.compile(r"^(?:\d{2}-\d{3}|\d{5})$")
_THORLABS_PART_RE = re.compile(r"^[A-Z]{1,6}\d{2,}[A-Z0-9-]*$")


@dataclass(slots=True)
class CatalogDownloadResult:
    """Result payload for an online catalog download attempt."""

    manufacturer: str
    archive_path: str
    source_url: str
    imported_count: int
    extracted_files: list[str]
    message: str


@dataclass(slots=True)
class CatalogImportResult:
    """Result payload for local catalog imports."""

    manufacturer: str
    imported_count: int
    linked_count: int = 0
    message: str = ""


class CatalogService:
    """Manage locally cached stock-lens records and vendor importers."""

    def __init__(self, connector: object, session: requests.Session | None = None) -> None:
        self._connector = connector
        self._storage = CatalogStorage()
        self._search_service = CatalogSearchService()
        self._session = session or requests.Session()
        self._records: list[CatalogLensRecord] = self._storage.load_all_records()
        self._metadata_page_cache: dict[tuple[str, str], dict[str, object]] = {}
        self._product_url_cache: dict[tuple[str, str], str | None] = {}
        self._record_by_id: dict[str, CatalogLensRecord] = {}
        self._surface_records: list[CatalogLensRecord] = []
        self._surface_records_by_part: dict[str, list[CatalogLensRecord]] = {}
        self._winlens_records: list[CatalogLensRecord] = []
        self._winlens_match_links_cache: dict[str, list[dict[str, object]]] | None = None
        self._winlens_alias_groups_cache: list | None = None
        self._insertable_record_cache: dict[str, CatalogLensRecord | None] = {}
        self._importers = {
            "excelitas": ExcelitasCatalogImporter(),
            "edmund": EdmundCatalogImporter(),
            "thorlabs": ThorlabsCatalogImporter(),
            "winlens library 2002": WinLensCatalogImporter(),
            "winlens": WinLensCatalogImporter(),
        }
        self._rebuild_record_indexes()

    def import_catalog_file(self, manufacturer: str, filepath: str | list[str]) -> int:
        """Import one or more manufacturer catalog files and persist them locally."""
        key = manufacturer.strip().lower()
        importer = self._importers.get(key)
        if importer is None:
            raise ValueError(f"Unsupported manufacturer: {manufacturer}")
        imported_records = self._load_records_from_import_paths(importer, filepath)
        self._persist_manufacturer_records(importer.manufacturer, imported_records)
        return len(imported_records)

    def import_winlens_library(self, root_path: str) -> CatalogImportResult:
        """Import a WinLens SPD library tree and refresh link suggestions."""
        imported_count = self.import_catalog_file("WinLens Library 2002", root_path)
        links = self._load_winlens_match_links()
        linked_count = sum(1 for candidates in links.values() if candidates)
        return CatalogImportResult(
            manufacturer="WinLens Library 2002",
            imported_count=imported_count,
            linked_count=linked_count,
            message=(
                f"Imported {imported_count} WinLens SPD record(s) and built "
                f"{linked_count} link suggestion(s)."
            ),
        )

    def download_excelitas_catalog(
        self,
        family_urls: list[str] | None = None,
    ) -> CatalogDownloadResult:
        """Download Excelitas / LINOS official family metadata and linked Zemax files."""
        importer = self._importers["excelitas"]
        download_dir = self._storage.downloads_root / "excelitas"
        download_dir.mkdir(parents=True, exist_ok=True)

        prefetched_pages: dict[str, tuple[str, str]] = {}
        if family_urls is None:
            source_urls = self._load_excelitas_cached_family_urls()
            if not source_urls:
                source_urls, prefetched_pages = self._discover_excelitas_family_pages()
                self._save_excelitas_cached_family_urls(source_urls)
        else:
            source_urls = family_urls
        metadata_records: list[CatalogLensRecord] = []
        download_paths: list[str] = []
        extracted_files: list[str] = []
        document_manifest: dict[str, list[str]] = {}

        for family_url in source_urls:
            prefetched = prefetched_pages.get(family_url)
            if prefetched is None:
                response = self._session.get(
                    family_url,
                    timeout=30,
                    headers=_BROWSER_HEADERS,
                )
                response.raise_for_status()
                page_url = response.url or family_url
                page_text = response.text
            else:
                page_url, page_text = prefetched
            metadata_records.extend(importer.import_html_page(page_text, page_url))
            document_urls = extract_excelitas_document_urls(page_text, page_url)
            if document_urls:
                document_manifest[page_url] = document_urls

            for zemax_url in extract_excelitas_zemax_urls(page_text, page_url):
                file_response = self._session.get(
                    zemax_url,
                    timeout=120,
                    headers={
                        **_BROWSER_HEADERS,
                        "Referer": page_url,
                        "Accept": "application/zip,application/octet-stream,*/*",
                    },
                )
                file_response.raise_for_status()
                filename = _download_filename_from_url(
                    zemax_url,
                    f"excelitas_catalog_{len(download_paths) + 1}.zip",
                )
                target_path = download_dir / filename
                target_path.write_bytes(file_response.content)
                download_paths.append(str(target_path))
                if target_path.suffix.lower() == ".zip":
                    extract_dir = download_dir / target_path.stem
                    if extract_dir.exists():
                        for old_path in sorted(extract_dir.rglob("*"), reverse=True):
                            if old_path.is_file():
                                old_path.unlink()
                            elif old_path.is_dir():
                                old_path.rmdir()
                    extract_dir.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(target_path) as archive:
                        archive.extractall(extract_dir)
                        extracted_files.extend(
                            str(extract_dir / name)
                            for name in archive.namelist()
                            if not name.endswith("/")
                        )
                else:
                    extracted_files.append(str(target_path))

        optical_records: list[CatalogLensRecord] = []
        if download_paths:
            optical_records = self._load_records_from_import_paths(importer, download_paths)

        combined_records = self._merge_excelitas_records(metadata_records, optical_records)
        combined_records = self._enrich_imported_records(importer.manufacturer, combined_records)
        self._persist_manufacturer_records(importer.manufacturer, combined_records)
        self._save_excelitas_document_manifest(document_manifest)

        if optical_records:
            message = (
                "Downloaded Excelitas / LINOS catalog metadata and linked Zemax files, "
                f"then imported {len(combined_records)} merged catalog entries."
            )
        else:
            message = (
                "Downloaded Excelitas / LINOS catalog metadata. No linked Zemax files were "
                f"available, so {len(combined_records)} metadata-only records were cached."
            )
        if document_manifest:
            message += f" Found {sum(len(urls) for urls in document_manifest.values())} official document link(s)."

        return CatalogDownloadResult(
            manufacturer=importer.manufacturer,
            archive_path=str(download_dir),
            source_url=source_urls[0] if source_urls else EXCELITAS_SHOP_ROOT_URL,
            imported_count=len(combined_records),
            extracted_files=extracted_files,
            message=message,
        )

    def _discover_excelitas_family_pages(self) -> tuple[list[str], dict[str, tuple[str, str]]]:
        """Discover likely LINOS family pages and reuse already fetched HTML."""
        discovered: list[str] = []
        prefetched_pages: dict[str, tuple[str, str]] = {}
        seen_pages: set[str] = set()
        queued: set[str] = set()
        queue: list[tuple[str, int]] = [
            (url, 0) for url in EXCELITAS_DISCOVERY_PAGE_URLS
        ]
        queued.update(EXCELITAS_DISCOVERY_PAGE_URLS)

        while queue and len(seen_pages) < _MAX_EXCELITAS_DISCOVERY_PAGES:
            discovery_url, depth = queue.pop(0)
            try:
                response = self._session.get(
                    discovery_url,
                    timeout=30,
                    headers=_BROWSER_HEADERS,
                )
                response.raise_for_status()
            except requests.RequestException:
                continue

            page_url = response.url or discovery_url
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            if looks_like_excelitas_family_page(response.text):
                if page_url not in discovered:
                    discovered.append(page_url)
                    prefetched_pages[page_url] = (page_url, response.text)
                continue

            if depth >= _MAX_EXCELITAS_DISCOVERY_DEPTH:
                continue

            for family_url in extract_excelitas_family_urls(response.text, page_url):
                if family_url in queued or family_url in seen_pages:
                    continue
                queued.add(family_url)
                queue.append((family_url, depth + 1))

        if discovered:
            return discovered, prefetched_pages
        return list(EXCELITAS_DEFAULT_FAMILY_URLS), {}

    def _load_excelitas_cached_family_urls(self) -> list[str]:
        """Return cached Excelitas family URLs if available."""
        payload = self._storage.load_cache_payload("excelitas_family_urls")
        urls = payload.get("urls", [])
        if not isinstance(urls, list):
            return []
        return [str(url) for url in urls if isinstance(url, str) and url.strip()]

    def _save_excelitas_cached_family_urls(self, urls: list[str]) -> None:
        """Persist discovered Excelitas family URLs for later reuse."""
        normalized: list[str] = []
        seen: set[str] = set()
        for url in urls:
            clean = url.strip()
            if not clean or clean in seen:
                continue
            seen.add(clean)
            normalized.append(clean)
        self._storage.save_cache_payload(
            "excelitas_family_urls",
            {
                "manufacturer": "Excelitas LINOS",
                "urls": normalized,
            },
        )

    def _save_excelitas_document_manifest(self, manifest: dict[str, list[str]]) -> None:
        """Persist discovered official document links for Excelitas family pages."""
        normalized_manifest: dict[str, list[str]] = {}
        for page_url, urls in manifest.items():
            clean_page = page_url.strip()
            if not clean_page:
                continue
            seen: set[str] = set()
            clean_urls: list[str] = []
            for url in urls:
                clean = url.strip()
                if not clean or clean in seen:
                    continue
                seen.add(clean)
                clean_urls.append(clean)
            if clean_urls:
                normalized_manifest[clean_page] = clean_urls
        self._storage.save_cache_payload(
            "excelitas_document_urls",
            {
                "manufacturer": "Excelitas LINOS",
                "documents": normalized_manifest,
            },
        )

    def _load_records_from_import_paths(
        self,
        importer,
        filepath: str | list[str],
    ) -> list[CatalogLensRecord]:
        """Load records from files/folders for a concrete importer without persisting yet."""
        supported_suffixes = set(getattr(importer, "supported_suffixes", {".json", ".zmx", ".zmf"}))
        input_paths = [filepath] if isinstance(filepath, str) else filepath
        extracted_dirs = self._extract_zip_archives(importer.manufacturer, input_paths)
        search_paths = [*input_paths, *[str(path) for path in extracted_dirs]]
        zmf_paths = self._find_zmf_paths(search_paths) if ".zmf" in supported_suffixes else []
        expanded_paths = self._expand_import_paths(
            search_paths,
            supported_suffixes - {".zmf"},
        )
        import_paths = [*expanded_paths, *zmf_paths]
        if importer.manufacturer.casefold() == "winlens library 2002":
            import_paths = [path for path in import_paths if is_winlens_catalog_path(path)]
        if not import_paths:
            raise ValueError(
                "No supported catalog files were selected. "
                "Choose .zip, .zmx, .zmf, .spd, or normalized .json files."
            )

        imported_records: list[CatalogLensRecord] = []
        failures: list[str] = []
        for path in import_paths:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    warnings.simplefilter("ignore", FutureWarning)
                    imported_records.extend(importer.import_file(str(path)))
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{Path(path).name}: {exc}")
                continue

        if not imported_records:
            summary = "; ".join(failures[:3]) if failures else "No readable catalog records found."
            raise ValueError(
                "No catalog entries could be imported. "
                f"Sample failures: {summary}"
            )
        return self._enrich_imported_records(importer.manufacturer, imported_records)

    def _persist_manufacturer_records(
        self,
        manufacturer: str,
        imported_records: list[CatalogLensRecord],
    ) -> None:
        """Merge *imported_records* into local storage for *manufacturer*."""
        merged_records = {
            record.catalog_id: record
            for record in self._records
            if record.manufacturer.casefold() == manufacturer.casefold()
        }
        for record in imported_records:
            merged_records[record.catalog_id] = record

        self._storage.save_records(
            manufacturer,
            sorted(
                merged_records.values(),
                key=lambda item: (
                    item.part_number.casefold(),
                    item.product_name.casefold(),
                ),
            ),
        )
        self._reload_all()
        self._refresh_winlens_record_links()

    def _merge_excelitas_records(
        self,
        metadata_records: list[CatalogLensRecord],
        optical_records: list[CatalogLensRecord],
    ) -> list[CatalogLensRecord]:
        """Merge Excelitas shop metadata with linked Zemax optical records."""
        merged = {record.catalog_id: record for record in metadata_records}
        for optical in optical_records:
            existing = merged.get(optical.catalog_id)
            if existing is None:
                merged[optical.catalog_id] = optical
                continue
            merged[optical.catalog_id] = _merge_catalog_record_pair(existing, optical)
        return list(merged.values())

    def download_edmund_catalog(self) -> CatalogDownloadResult:
        """Download Edmund's official Zemax catalog archive and import supported files."""
        importer = self._importers["edmund"]
        download_dir = self._storage.downloads_root / "edmund"
        download_dir.mkdir(parents=True, exist_ok=True)

        archive_url = self._resolve_edmund_archive_url()

        archive_response = self._session.get(
            archive_url,
            timeout=120,
            headers={
                **_BROWSER_HEADERS,
                "Referer": EDMUND_ZEMAX_PAGE_URL,
                "Accept": "application/zip,application/octet-stream,*/*",
            },
        )
        try:
            archive_response.raise_for_status()
        except requests.HTTPError as exc:
            raise ValueError(
                "Edmund blocked the catalog download request. The official Zemax page is "
                "reachable, but the archive itself returned an access error. "
                "Try importing a manually downloaded archive or .zmx files instead."
            ) from exc

        archive_name = _download_filename_from_url(archive_url, "edmund_zemax_catalog.zip")
        archive_path = download_dir / archive_name
        archive_path.write_bytes(archive_response.content)

        extract_dir = download_dir / archive_path.stem
        if extract_dir.exists():
            for old_file in sorted(extract_dir.rglob("*"), reverse=True):
                if old_file.is_file():
                    old_file.unlink()
                elif old_file.is_dir():
                    old_file.rmdir()
        extract_dir.mkdir(parents=True, exist_ok=True)

        extracted_paths: list[str] = []
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extract_dir)
            extracted_paths = [
                str(extract_dir / name)
                for name in archive.namelist()
                if not name.endswith("/")
            ]

        supported_paths = self._expand_import_paths([str(extract_dir)])
        zmf_paths = self._find_zmf_paths([str(extract_dir)])
        imported_count = 0
        if supported_paths:
            imported_count = self.import_catalog_file(importer.manufacturer, [str(path) for path in supported_paths])
            if zmf_paths:
                message = (
                    "Downloaded Edmund catalog archive, imported "
                    f"{imported_count} supported catalog files, and detected "
                    f"{len(zmf_paths)} ZMF catalog file(s) that were also saved locally."
                )
            else:
                message = (
                    f"Downloaded Edmund catalog archive and imported {imported_count} supported catalog files."
                )
        elif zmf_paths:
            imported_count = self.import_catalog_file(
                importer.manufacturer,
                [str(path) for path in zmf_paths],
            )
            message = (
                "Downloaded the official Edmund catalog archive and imported "
                f"{imported_count} catalog entries from {len(zmf_paths)} ZMF catalog file(s)."
            )
        else:
            message = (
                "Downloaded the official Edmund catalog archive, but it did not contain "
                "directly importable .zmx or normalized .json files. "
                "The archive was saved locally for manual inspection."
            )

        return CatalogDownloadResult(
            manufacturer=importer.manufacturer,
            archive_path=str(archive_path),
            source_url=archive_url,
            imported_count=imported_count,
            extracted_files=extracted_paths,
            message=message,
        )

    def download_thorlabs_catalog(self) -> CatalogDownloadResult:
        """Download Thorlabs' official Zemax catalog package and import supported files."""
        importer = self._importers["thorlabs"]
        download_dir = self._storage.downloads_root / "thorlabs"
        download_dir.mkdir(parents=True, exist_ok=True)

        archive_url = self._resolve_thorlabs_catalog_url()
        archive_response = self._session.get(
            archive_url,
            timeout=120,
            headers={
                **_BROWSER_HEADERS,
                "Referer": THORLABS_ZEMAX_PAGE_URL,
                "Accept": "application/zip,application/octet-stream,*/*",
            },
        )
        try:
            archive_response.raise_for_status()
        except requests.HTTPError as exc:
            raise ValueError(
                "Thorlabs blocked the catalog download request. "
                "Try importing a manually downloaded archive or .zmx files instead."
            ) from exc

        archive_name = _download_filename_from_url(archive_url, "thorlabs_zemax_catalog.zip")
        archive_path = download_dir / archive_name
        archive_path.write_bytes(archive_response.content)

        extracted_paths: list[str] = []
        imported_count = 0
        suffix = archive_path.suffix.lower()
        if suffix == ".zip":
            extract_dir = download_dir / archive_path.stem
            if extract_dir.exists():
                for old_file in sorted(extract_dir.rglob("*"), reverse=True):
                    if old_file.is_file():
                        old_file.unlink()
                    elif old_file.is_dir():
                        old_file.rmdir()
            extract_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(archive_path) as archive:
                archive.extractall(extract_dir)
                extracted_paths = [
                    str(extract_dir / name)
                    for name in archive.namelist()
                    if not name.endswith("/")
                ]

            supported_paths = self._expand_import_paths([str(extract_dir)])
            zmf_paths = self._find_zmf_paths([str(extract_dir)])
            if supported_paths:
                imported_count = self.import_catalog_file(importer.manufacturer, [str(path) for path in supported_paths])
                if zmf_paths:
                    message = (
                        "Downloaded Thorlabs catalog archive, imported "
                        f"{imported_count} supported catalog files, and detected "
                        f"{len(zmf_paths)} ZMF catalog file(s) that were also saved locally."
                    )
                else:
                    message = (
                        f"Downloaded Thorlabs catalog archive and imported {imported_count} supported catalog files."
                    )
            elif zmf_paths:
                imported_count = self.import_catalog_file(
                    importer.manufacturer,
                    [str(path) for path in zmf_paths],
                )
                message = (
                    "Downloaded the official Thorlabs catalog archive and imported "
                    f"{imported_count} catalog entries from {len(zmf_paths)} ZMF catalog file(s)."
                )
            else:
                message = (
                    "Downloaded the official Thorlabs catalog archive, but it did not contain "
                    "directly importable .zmx or normalized .json files. "
                    "The archive was saved locally for manual inspection."
                )
        else:
            imported_count = self.import_catalog_file(importer.manufacturer, [str(archive_path)])
            message = (
                "Downloaded the official Thorlabs catalog file and imported "
                f"{imported_count} catalog entries."
            )

        return CatalogDownloadResult(
            manufacturer=importer.manufacturer,
            archive_path=str(archive_path),
            source_url=archive_url,
            imported_count=imported_count,
            extracted_files=extracted_paths,
            message=message,
        )

    def _resolve_edmund_archive_url(self) -> str:
        """Return the best available official Edmund archive URL."""
        try:
            page_response = self._session.get(
                EDMUND_ZEMAX_PAGE_URL,
                timeout=30,
                headers=_BROWSER_HEADERS,
            )
            page_response.raise_for_status()
            return extract_edmund_download_url(page_response.text)
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code == 403:
                return EDMUND_FALLBACK_ARCHIVE_URL
            raise

    def _resolve_thorlabs_catalog_url(self) -> str:
        """Return the best available official Thorlabs catalog download URL."""
        page_response = self._session.get(
            THORLABS_ZEMAX_PAGE_URL,
            timeout=30,
            headers=_BROWSER_HEADERS,
        )
        page_response.raise_for_status()
        return extract_thorlabs_download_url(page_response.text, page_response.url or THORLABS_ZEMAX_PAGE_URL)

    def get_manufacturers(self) -> list[str]:
        """Return manufacturer names currently available in the local cache."""
        return sorted({record.manufacturer for record in self._records if record.manufacturer})

    def search(self, query_dict: dict | None = None) -> list[dict]:
        """Return GUI summary dicts matching *query_dict*."""
        query_dict = query_dict or {}
        match_type_text = str(query_dict.get("match_type_text", "")).casefold().strip()
        query = CatalogSearchQuery(
            text=str(query_dict.get("text", "")),
            manufacturer=str(query_dict.get("manufacturer", "")),
            part_number=str(query_dict.get("part_number", "")),
            product_name=str(query_dict.get("product_name", "")),
            category=str(query_dict.get("category", "")),
            efl_min=_float_or_none(query_dict.get("efl_min")),
            efl_max=_float_or_none(query_dict.get("efl_max")),
            diameter_min=_float_or_none(query_dict.get("diameter_min")),
            diameter_max=_float_or_none(query_dict.get("diameter_max")),
            material_text=str(query_dict.get("material_text", "")),
            coating_text=str(query_dict.get("coating_text", "")),
            availability_text=str(query_dict.get("availability_text", "")),
        )
        summaries: list[dict] = []
        link_map = self._load_winlens_match_links()
        for record in self._search_service.search(self._records, query):
            summary = record.to_summary_dict()
            top_link = link_map.get(record.catalog_id, [])
            summary["match_type"] = (
                str(top_link[0].get("match_type", "")).strip() if top_link else ""
            )
            insertable_record = self.resolve_insertable_record(record.catalog_id)
            summary["insertable_surface_count"] = len(
                insertable_record.surfaces if insertable_record is not None else []
            )
            if match_type_text and match_type_text not in summary["match_type"].casefold():
                continue
            summaries.append(summary)
        return summaries

    def get_record(self, catalog_id: str) -> CatalogLensRecord | None:
        """Return a full record by id."""
        return self._record_by_id.get(catalog_id)

    def resolve_insertable_record(self, catalog_id: str) -> CatalogLensRecord | None:
        """Return an insertable record with surfaces for *catalog_id* when possible."""
        if catalog_id in self._insertable_record_cache:
            return self._insertable_record_cache[catalog_id]
        record = self.get_record(catalog_id)
        if record is None:
            self._insertable_record_cache[catalog_id] = None
            return None
        if record.surfaces:
            self._insertable_record_cache[catalog_id] = record
            return record

        if not self._surface_records:
            self._insertable_record_cache[catalog_id] = None
            return None

        normalized_part = _normalize_catalog_part_token(record.part_number)
        exact_candidates = self._surface_records_by_part.get(normalized_part, [])
        if exact_candidates:
            self._insertable_record_cache[catalog_id] = exact_candidates[0]
            return exact_candidates[0]

        linked_candidate = _resolve_insertable_record_from_winlens_links(
            record,
            self._records,
            self._load_winlens_match_links(),
        )
        if linked_candidate is not None:
            self._insertable_record_cache[catalog_id] = linked_candidate
            return linked_candidate

        alias_groups = self._load_winlens_alias_groups(self._winlens_records)
        family_candidate = _resolve_insertable_record_from_winlens_family(
            record,
            self._winlens_records,
            alias_groups,
        )
        if family_candidate is not None:
            self._insertable_record_cache[catalog_id] = family_candidate
            return family_candidate

        if record.manufacturer.casefold() != "winlens library 2002":
            self._insertable_record_cache[catalog_id] = None
            return None

        if not any(
            candidate.manufacturer.casefold() == "winlens library 2002"
            for candidate in self._surface_records
        ):
            self._insertable_record_cache[catalog_id] = None
            return None
        self._insertable_record_cache[catalog_id] = None
        return None

    def get_record_details(self, catalog_id: str) -> dict | None:
        """Return a full record payload for GUI detail display."""
        record = self.get_record(catalog_id)
        return None if record is None else record.to_dict()

    def get_record_document_urls(self, catalog_id: str) -> list[str]:
        """Return cached official vendor-document URLs for *catalog_id*."""
        record = self.get_record(catalog_id)
        if record is None:
            return []
        payload = self._storage.load_cache_payload("excelitas_document_urls")
        documents = payload.get("documents", {})
        if not isinstance(documents, dict):
            return []
        source_url = str(record.source.source_url or "").strip()
        urls = documents.get(source_url, [])
        if not isinstance(urls, list):
            return []
        return [str(url) for url in urls if isinstance(url, str) and url.strip()]

    def get_record_links(self, catalog_id: str) -> list[dict[str, object]]:
        """Return cached candidate record links for *catalog_id*."""
        return list(self._load_winlens_match_links().get(catalog_id, []))

    def get_winlens_review_candidates(self, min_confidence_percent: int = 76) -> list[dict[str, object]]:
        """Return WinLens candidate matches that are strong enough for manual review."""
        link_map = self._load_winlens_match_links()
        review_rows: list[dict[str, object]] = []
        for record in self._records:
            if record.manufacturer.casefold() != "winlens library 2002":
                continue
            links = link_map.get(record.catalog_id, [])
            if not links:
                continue
            top_link = links[0]
            if str(top_link.get("match_type", "")).casefold() != "candidate":
                continue
            confidence = int(top_link.get("confidence_percent", 0) or 0)
            if confidence < min_confidence_percent:
                continue
            review_rows.append(
                {
                    "winlens_catalog_id": record.catalog_id,
                    "winlens_part_number": record.part_number,
                    "winlens_name": record.product_name,
                    "family_key": self._review_family_key(record, top_link),
                    "status": record.availability_status or "",
                    "target_catalog_id": str(top_link.get("catalog_id", "")),
                    "target_part_number": str(top_link.get("part_number", "")),
                    "target_name": str(top_link.get("product_name", "")),
                    "match_type": str(top_link.get("match_type", "")),
                    "score": int(top_link.get("score", 0) or 0),
                    "confidence_percent": confidence,
                    "reasons": [str(reason) for reason in top_link.get("reasons", [])],
                    "preview": self._build_review_preview(record, top_link),
                }
            )
        return sorted(
            review_rows,
            key=lambda item: (
                str(item["family_key"]),
                -int(item["confidence_percent"]),
                str(item["winlens_part_number"]),
            ),
        )

    def _review_family_key(self, record: CatalogLensRecord, top_link: dict[str, object]) -> str:
        winlens_digits = re.sub(r"[^0-9]+", "", record.part_number)
        target_digits = re.sub(r"[^0-9]+", "", str(top_link.get("part_number", "")))
        if len(target_digits) >= 6:
            return target_digits[:6]
        if len(winlens_digits) >= 6:
            return winlens_digits[:6]
        return winlens_digits or record.part_number

    def _build_review_preview(self, record: CatalogLensRecord, top_link: dict[str, object]) -> str:
        target_part = str(top_link.get("part_number", ""))
        family_key = self._review_family_key(record, top_link)
        return f"Confirm family {family_key} -> {target_part}"

    def confirm_winlens_links(self, selections: list[dict[str, str]]) -> int:
        """Persist manually reviewed WinLens links as confirmed mappings."""
        if not selections:
            return 0
        current_map = self._load_winlens_match_links()
        persisted_payload = self._storage.load_cache_payload("winlens_confirmed_links")
        persisted_links = persisted_payload.get("links", {}) if isinstance(persisted_payload, dict) else {}
        if not isinstance(persisted_links, dict):
            persisted_links = {}
        applied = 0
        for selection in selections:
            winlens_catalog_id = str(selection.get("winlens_catalog_id", ""))
            target_catalog_id = str(selection.get("target_catalog_id", ""))
            if not winlens_catalog_id or not target_catalog_id:
                continue
            link = next(
                (
                    dict(item)
                    for item in current_map.get(winlens_catalog_id, [])
                    if str(item.get("catalog_id", "")) == target_catalog_id
                ),
                None,
            )
            if link is None:
                continue
            link["match_type"] = "confirmed"
            link["confidence_percent"] = 100
            reasons = [str(reason) for reason in link.get("reasons", [])]
            if "Manual review apply" not in reasons:
                reasons.append("Manual review apply")
            link["reasons"] = reasons
            persisted_links[winlens_catalog_id] = link
            applied += 1
        self._storage.save_cache_payload(
            "winlens_confirmed_links",
            {
                "manufacturer": "WinLens Library 2002",
                "links": persisted_links,
            },
        )
        self._refresh_winlens_record_links()
        return applied

    def delete_records(self, catalog_ids: list[str]) -> int:
        """Delete cached catalog records by id and persist the remaining records."""
        to_delete = {str(catalog_id) for catalog_id in catalog_ids if str(catalog_id).strip()}
        if not to_delete:
            return 0
        removed = 0
        seen_manufacturers = {record.manufacturer for record in self._records}
        manufacturers: dict[str, list[CatalogLensRecord]] = {}
        for record in self._records:
            if record.catalog_id in to_delete:
                removed += 1
                continue
            manufacturers.setdefault(record.manufacturer, []).append(record)
        for manufacturer in seen_manufacturers:
            self._storage.save_records(manufacturer, manufacturers.get(manufacturer, []))
        self._reload_all()
        self._refresh_winlens_record_links()
        return removed

    def resolve_product_url(self, catalog_id: str) -> str | None:
        """Resolve a current product webpage URL for *catalog_id*."""
        record = self.get_record(catalog_id)
        if record is None:
            return None
        return self._resolve_record_product_url(record)

    def _reload_all(self) -> None:
        self._records = self._storage.load_all_records()
        self._rebuild_record_indexes()

    def _refresh_winlens_record_links(self) -> None:
        """Rebuild cached WinLens record-link suggestions when possible."""
        self._winlens_match_links_cache = None
        self._winlens_alias_groups_cache = None
        self._insertable_record_cache.clear()
        winlens_records = self._winlens_records
        if not winlens_records:
            self._storage.save_cache_payload(
                "winlens_record_links",
                {"manufacturer": "WinLens Library 2002", "links": {}},
            )
            return
        existing_records = [
            record
            for record in self._records
            if record.manufacturer.casefold() != "winlens library 2002"
        ]
        alias_groups = self._load_winlens_alias_groups(winlens_records)
        link_map = build_winlens_match_map(
            winlens_records,
            existing_records,
            alias_groups,
        )
        link_map = self._merge_persisted_confirmed_links(link_map, existing_records)
        self._storage.save_cache_payload(
            "winlens_record_links",
            {
                "manufacturer": "WinLens Library 2002",
                "links": link_map,
            },
        )
        self._save_persisted_confirmed_links(link_map)
        updated_records = self._apply_winlens_availability_statuses(
            winlens_records,
            link_map,
            alias_groups,
        )
        if any(
            old.availability_status != new.availability_status
            for old, new in zip(winlens_records, updated_records, strict=False)
        ):
            self._storage.save_records("WinLens Library 2002", updated_records)
            self._reload_all()

    def _load_winlens_match_links(self) -> dict[str, list[dict[str, object]]]:
        """Load cached WinLens record-link suggestions."""
        if self._winlens_match_links_cache is not None:
            return self._winlens_match_links_cache
        payload = self._storage.load_cache_payload("winlens_record_links")
        links = payload.get("links", {})
        self._winlens_match_links_cache = links if isinstance(links, dict) else {}
        return self._winlens_match_links_cache

    def _load_winlens_alias_groups(self, winlens_records: list[CatalogLensRecord]):
        """Load auxiliary WinLens alias groups near the imported SPD files."""
        if self._winlens_alias_groups_cache is not None:
            return self._winlens_alias_groups_cache
        roots: set[Path] = set()
        for record in winlens_records:
            source_path = (record.source.source_path or "").strip()
            if not source_path:
                continue
            path = Path(source_path)
            for parent in (path.parent, *path.parents):
                if parent.name.casefold() == "winlens library 2002":
                    roots.add(parent)
                    break
        alias_groups = []
        for root in sorted(roots):
            alias_groups.extend(load_winlens_alias_groups(root))
        self._winlens_alias_groups_cache = alias_groups
        return alias_groups

    def _rebuild_record_indexes(self) -> None:
        """Prepare in-memory indexes used on hot catalog search paths."""
        self._record_by_id = {record.catalog_id: record for record in self._records}
        self._surface_records = [record for record in self._records if record.surfaces]
        self._surface_records_by_part = {}
        for record in self._surface_records:
            normalized_part = _normalize_catalog_part_token(record.part_number)
            if not normalized_part:
                continue
            self._surface_records_by_part.setdefault(normalized_part, []).append(record)
        self._winlens_records = [
            record
            for record in self._records
            if record.manufacturer.casefold() == "winlens library 2002"
        ]
        self._winlens_match_links_cache = None
        self._winlens_alias_groups_cache = None
        self._insertable_record_cache.clear()

    def _apply_winlens_availability_statuses(
        self,
        winlens_records: list[CatalogLensRecord],
        link_map: dict[str, list[dict[str, object]]],
        alias_groups: list,
    ) -> list[CatalogLensRecord]:
        """Assign `legacy`/`unknown` to WinLens-only records without a confirmed current match."""
        alias_tokens = self._build_winlens_alias_token_set(alias_groups)
        updated: list[CatalogLensRecord] = []
        for record in winlens_records:
            links = link_map.get(record.catalog_id, [])
            confirmed_links = [
                link for link in links if str(link.get("match_type", "")).casefold() == "confirmed"
            ]
            if confirmed_links:
                record.availability_status = None
            elif links:
                record.availability_status = "unknown"
            elif self._record_has_alias_context(record, alias_tokens):
                record.availability_status = "legacy"
            else:
                record.availability_status = "unknown"
            record.search_blob = record.build_search_blob()
            updated.append(record)
        return updated

    def _build_winlens_alias_token_set(self, alias_groups: list) -> set[str]:
        tokens: set[str] = set()
        for group in alias_groups:
            for token in [*getattr(group, "part_numbers", []), *getattr(group, "family_numbers", [])]:
                clean = re.sub(r"[^0-9]+", "", str(token))
                if clean:
                    tokens.add(clean)
        return tokens

    def _record_has_alias_context(self, record: CatalogLensRecord, alias_tokens: set[str]) -> bool:
        record_digits = re.sub(r"[^0-9]+", "", record.part_number)
        if record_digits and record_digits in alias_tokens:
            return True
        if len(record_digits) >= 6 and record_digits[:6] in alias_tokens:
            return True
        return False

    def _save_persisted_confirmed_links(
        self,
        link_map: dict[str, list[dict[str, object]]],
    ) -> None:
        payload_links: dict[str, dict[str, object]] = {}
        for catalog_id, links in link_map.items():
            confirmed = next(
                (
                    link for link in links
                    if str(link.get("match_type", "")).casefold() == "confirmed"
                ),
                None,
            )
            if confirmed is None:
                continue
            payload_links[catalog_id] = dict(confirmed)
        self._storage.save_cache_payload(
            "winlens_confirmed_links",
            {
                "manufacturer": "WinLens Library 2002",
                "links": payload_links,
            },
        )

    def _merge_persisted_confirmed_links(
        self,
        link_map: dict[str, list[dict[str, object]]],
        existing_records: list[CatalogLensRecord],
    ) -> dict[str, list[dict[str, object]]]:
        payload = self._storage.load_cache_payload("winlens_confirmed_links")
        persisted = payload.get("links", {})
        if not isinstance(persisted, dict):
            return link_map
        valid_catalog_ids = {record.catalog_id for record in existing_records}
        merged = {catalog_id: list(links) for catalog_id, links in link_map.items()}
        for winlens_catalog_id, link in persisted.items():
            if not isinstance(link, dict):
                continue
            target_catalog_id = str(link.get("catalog_id", ""))
            if not target_catalog_id or target_catalog_id not in valid_catalog_ids:
                continue
            current_links = merged.setdefault(winlens_catalog_id, [])
            current_links = [
                item for item in current_links
                if str(item.get("catalog_id", "")) != target_catalog_id
            ]
            current_links.insert(0, dict(link))
            merged[winlens_catalog_id] = current_links[:5]
        return merged

    def _enrich_imported_records(
        self,
        manufacturer: str,
        records: list[CatalogLensRecord],
    ) -> list[CatalogLensRecord]:
        """Fill missing catalog metadata with bounded official-site lookups."""
        enriched: list[CatalogLensRecord] = []
        online_budget = _MAX_ONLINE_ENRICHMENT_RECORDS
        for record in records:
            self._apply_local_metadata_fallbacks(record, record.product_name)
            if (
                self._record_needs_online_enrichment(record)
                and online_budget > 0
                and self._can_attempt_online_enrichment(record)
            ):
                online_data = self._fetch_official_product_metadata(record)
                online_budget -= 1
                if online_data:
                    self._apply_online_metadata(record, online_data)
            record.search_blob = record.build_search_blob()
            enriched.append(record)
        return enriched

    def _record_needs_online_enrichment(self, record: CatalogLensRecord) -> bool:
        """Return whether *record* still misses important searchable metadata."""
        return any(
            value in (None, "")
            for value in (
                record.category,
                record.efl_mm,
                record.diameter_mm,
                record.material_summary,
                record.coating,
            )
        )

    def _can_attempt_online_enrichment(self, record: CatalogLensRecord) -> bool:
        """Return whether a record has enough identity to justify a live lookup."""
        if _looks_like_product_url(record.url) or _looks_like_product_url(record.source.source_url):
            return True
        if _looks_like_thorlabs_product_url(record.url) or _looks_like_thorlabs_product_url(
            record.source.source_url
        ):
            return True
        if record.manufacturer.casefold() == "edmund":
            return bool(_EDMUND_PART_RE.fullmatch(record.part_number.strip()))
        if record.manufacturer.casefold() == "thorlabs":
            return bool(_THORLABS_PART_RE.fullmatch(record.part_number.strip()))
        return False

    def _apply_local_metadata_fallbacks(self, record: CatalogLensRecord, text: str) -> None:
        """Populate still-missing metadata using local heuristic parsing."""
        if not record.category:
            record.category = _infer_category_from_text(text)
        if record.efl_mm is None:
            record.efl_mm = _infer_efl_from_text(text)
        if record.diameter_mm is None:
            record.diameter_mm = _infer_diameter_from_text(text)
        if not record.material_summary:
            record.material_summary = _infer_material_from_text(text)
        if not record.coating:
            record.coating = _infer_coating_from_text(text)

    def _fetch_official_product_metadata(self, record: CatalogLensRecord) -> dict[str, object] | None:
        """Return parsed official-page metadata for *record*, cached by manufacturer/part no."""
        cache_key = (record.manufacturer.casefold(), record.part_number.casefold())
        if cache_key in self._metadata_page_cache:
            return self._metadata_page_cache[cache_key]

        product_url = self._resolve_record_product_url(record)
        if not product_url:
            self._metadata_page_cache[cache_key] = {}
            return {}
        if not _can_fetch_metadata_page(record.manufacturer, product_url):
            self._metadata_page_cache[cache_key] = {}
            return {}
        try:
            response = self._session.get(
                product_url,
                timeout=20,
                headers={
                    **_BROWSER_HEADERS,
                    "Referer": product_url,
                },
            )
            response.raise_for_status()
        except requests.RequestException:
            self._metadata_page_cache[cache_key] = {}
            return {}

        page_text = _html_to_searchable_text(response.text)
        parsed = {
            "category": _infer_category_from_text(page_text),
            "efl_mm": _infer_efl_from_text(page_text),
            "diameter_mm": _infer_diameter_from_text(page_text),
            "material_summary": _infer_material_from_text(page_text),
            "coating": _infer_coating_from_text(page_text),
        }
        self._metadata_page_cache[cache_key] = parsed
        return parsed

    def _resolve_record_product_url(self, record: CatalogLensRecord) -> str | None:
        """Resolve a live or best-effort product URL for an in-memory record."""
        cache_key = (record.manufacturer.casefold(), record.part_number.casefold())
        if cache_key in self._product_url_cache:
            return self._product_url_cache[cache_key]

        if _looks_like_product_url(record.url):
            self._product_url_cache[cache_key] = record.url
            return record.url

        if record.manufacturer.casefold() == "edmund":
            resolved = self._resolve_edmund_product_url(record.part_number)
            self._product_url_cache[cache_key] = resolved
            return resolved

        if _looks_like_thorlabs_product_url(record.url):
            self._product_url_cache[cache_key] = record.url
            return record.url

        if _looks_like_thorlabs_product_url(record.source.source_url):
            self._product_url_cache[cache_key] = record.source.source_url
            return record.source.source_url

        if _looks_like_product_url(record.source.source_url):
            self._product_url_cache[cache_key] = record.source.source_url
            return record.source.source_url
        resolved = record.url or record.source.source_url
        self._product_url_cache[cache_key] = resolved
        return resolved

    def _apply_online_metadata(self, record: CatalogLensRecord, data: dict[str, object]) -> None:
        """Apply parsed online metadata only to fields that are still missing."""
        if not record.category and data.get("category"):
            record.category = str(data["category"])
        if record.efl_mm is None and data.get("efl_mm") is not None:
            record.efl_mm = float(data["efl_mm"])
        if record.diameter_mm is None and data.get("diameter_mm") is not None:
            record.diameter_mm = float(data["diameter_mm"])
        if not record.material_summary and data.get("material_summary"):
            record.material_summary = str(data["material_summary"])
        if not record.coating and data.get("coating"):
            record.coating = str(data["coating"])

    def _resolve_edmund_product_url(self, part_number: str) -> str:
        """Resolve Edmund's live product page for *part_number* using official search."""
        for query in _edmund_part_number_queries(part_number):
            search_url = _build_edmund_search_url(query)
            try:
                response = self._session.get(
                    search_url,
                    timeout=20,
                    headers={
                        **_BROWSER_HEADERS,
                        "Referer": EDMUND_PRODUCTS_PAGE_URL,
                    },
                )
                response.raise_for_status()
            except requests.RequestException:
                continue

            response_url = getattr(response, "url", "") or search_url
            if _looks_like_product_url(response_url):
                return response_url

            resolved = _extract_edmund_product_url_from_html(
                response.text,
                response_url,
                part_number,
            )
            if resolved:
                return resolved

        return _build_edmund_search_url(part_number)

    def _expand_import_paths(
        self,
        raw_paths: Iterable[str],
        suffixes: set[str] | None = None,
    ) -> list[Path]:
        """Return supported files from *raw_paths*, expanding directories recursively."""
        return self._collect_paths(raw_paths, suffixes or {".json", ".zmx"})

    def _find_zmf_paths(self, raw_paths: Iterable[str]) -> list[Path]:
        """Return ZMF files from *raw_paths*, expanding directories recursively."""
        return self._collect_paths(raw_paths, {".zmf"})

    def _collect_paths(self, raw_paths: Iterable[str], suffixes: set[str]) -> list[Path]:
        """Return matching files from *raw_paths*, expanding directories recursively."""
        seen: set[Path] = set()
        expanded: list[Path] = []
        for raw_path in raw_paths:
            path = Path(raw_path)
            if path.is_dir():
                candidates: list[Path] = []
                for suffix in sorted(suffixes):
                    candidates.extend(path.rglob(f"*{suffix}"))
                candidates = sorted(candidates)
            elif path.is_file():
                candidates = [path]
            else:
                continue

            for candidate in candidates:
                suffix = candidate.suffix.lower()
                if suffix not in suffixes:
                    continue
                if candidate.name.startswith("._") or "__MACOSX" in candidate.parts:
                    continue
                resolved = candidate.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                expanded.append(candidate)
        return expanded

    def _extract_zip_archives(
        self,
        manufacturer: str,
        raw_paths: Iterable[str],
    ) -> list[Path]:
        """Extract local catalog ZIP archives and return extraction directories."""
        zip_paths = self._collect_paths(raw_paths, {".zip"})
        if not zip_paths:
            return []

        extract_root = self._storage.downloads_root / manufacturer.strip().lower() / "imports"
        extract_root.mkdir(parents=True, exist_ok=True)
        extracted_dirs: list[Path] = []
        for zip_path in zip_paths:
            target_dir = extract_root / zip_path.stem
            if target_dir.exists():
                for old_path in sorted(target_dir.rglob("*"), reverse=True):
                    if old_path.is_file():
                        old_path.unlink()
                    elif old_path.is_dir():
                        old_path.rmdir()
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(target_dir)
            extracted_dirs.append(target_dir)
        return extracted_dirs


def _float_or_none(value) -> float | None:  # noqa: ANN001
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_edmund_download_url(html: str, base_url: str = EDMUND_ZEMAX_PAGE_URL) -> str:
    """Return Edmund's official catalog archive URL from the Zemax catalog page."""
    matches = _ZIP_HREF_RE.findall(html)
    prioritized = [
        href for href in matches if "zemax" in href.casefold() or "zmf" in href.casefold()
    ]
    candidate = prioritized[0] if prioritized else (matches[0] if matches else "")
    if not candidate:
        raise ValueError("Could not find an official Edmund catalog download link on the Zemax page.")
    return urljoin(base_url, candidate)


def extract_thorlabs_download_url(html: str, base_url: str = THORLABS_ZEMAX_PAGE_URL) -> str:
    """Return Thorlabs' official catalog file URL from the Zemax software page."""
    matches = _CATALOG_FILE_HREF_RE.findall(html)
    prioritized = [
        href
        for href in matches
        if "zemax" in href.casefold() or "catalog" in href.casefold()
    ]
    candidate = prioritized[0] if prioritized else (matches[0] if matches else "")
    if not candidate:
        raise ValueError("Could not find an official Thorlabs catalog download link on the Zemax page.")
    return urljoin(base_url, candidate)


def _build_edmund_search_url(query: str) -> str:
    """Return Edmund's official product-search URL for *query*."""
    return f"{EDMUND_PRODUCTS_PAGE_URL}?Query={quote_plus(query)}"


def _normalize_stock_number(value: str) -> str:
    """Normalize stock-number text for loose matching."""
    return re.sub(r"[^0-9A-Z]+", "", value.upper())


def _edmund_part_number_queries(part_number: str) -> list[str]:
    """Return useful search query variants for an Edmund stock number."""
    base = part_number.strip()
    compact = _normalize_stock_number(base)
    queries = [base]
    if compact and compact != base:
        queries.append(compact)
    if compact.isdigit() and len(compact) == 5:
        hyphenated = f"{compact[:2]}-{compact[2:]}"
        if hyphenated not in queries:
            queries.append(hyphenated)
    return queries


def _extract_edmund_product_url_from_html(html: str, base_url: str, part_number: str) -> str | None:
    """Extract a matching Edmund product URL for *part_number* from HTML."""
    normalized_part = _normalize_stock_number(part_number)
    for match in _EDMUND_PRODUCT_HREF_RE.finditer(html):
        href = match.group(1)
        start = max(0, match.start() - 500)
        end = min(len(html), match.end() + 500)
        context = html[start:end]
        if normalized_part and normalized_part in _normalize_stock_number(context):
            return urljoin(base_url, href)
    return None


def _looks_like_product_url(url: str | None) -> bool:
    """Return whether *url* looks like a direct product page."""
    if not url:
        return False
    return "/p/" in urlparse(url).path.casefold()


def _looks_like_thorlabs_product_url(url: str | None) -> bool:
    """Return whether *url* looks like a direct Thorlabs product page."""
    if not url:
        return False
    lowered = url.casefold()
    return "thorproduct.cfm" in lowered or "partnumber=" in lowered


def _can_fetch_metadata_page(manufacturer: str, product_url: str) -> bool:
    """Return whether *product_url* is suitable for metadata scraping."""
    manufacturer_key = manufacturer.casefold()
    if manufacturer_key == "edmund":
        return _looks_like_product_url(product_url)
    if manufacturer_key == "thorlabs":
        return _looks_like_thorlabs_product_url(product_url)
    return bool(product_url)


def _download_filename_from_url(url: str, default: str) -> str:
    """Return a useful local filename derived from a download URL."""
    parsed = urlparse(url)
    query_name = parse_qs(parsed.query).get("fileName", [])
    if query_name:
        candidate = Path(query_name[0]).name
        if candidate:
            return candidate
    path_name = Path(parsed.path).name
    return path_name or default


def _html_to_searchable_text(html_text: str) -> str:
    """Collapse HTML into searchable plain text."""
    text = _HTML_TAG_RE.sub(" ", html_text)
    text = html.unescape(text)
    return _HTML_SPACE_RE.sub(" ", text).strip()


def _infer_category_from_text(text: str) -> str:
    """Infer a normalized lens category from free-form text."""
    lowered = text.casefold()
    for needle, category in _CATEGORY_KEYWORDS:
        if needle in lowered:
            return category
    return ""


def _infer_efl_from_text(text: str) -> float | None:
    """Infer EFL in mm from free-form text."""
    return _extract_named_float(_FOCAL_MM_RE, text) or _extract_named_float(
        _FOCAL_MM_ALT_RE,
        text,
    ) or _extract_pair_value(text, 1)


def _infer_diameter_from_text(text: str) -> float | None:
    """Infer diameter in mm from free-form text."""
    return _extract_named_float(_DIAMETER_MM_ALT_RE, text) or _extract_named_float(
        _DIAMETER_MM_RE,
        text,
    ) or _extract_pair_value(text, 0)
 
 
def _infer_material_from_text(text: str) -> str | None:
    """Infer substrate/material from free-form text."""
    match = _MATERIAL_RE.search(text)
    if not match:
        for candidate in ("N-BK7", "UVFS", "Fused Silica", "Silicon", "Germanium", "Calcium Fluoride"):
            if candidate.casefold() in text.casefold():
                return candidate
        return None
    return _clean_metadata_value(match.group(1))


def _infer_coating_from_text(text: str) -> str | None:
    """Infer coating from free-form text."""
    lowered = text.casefold()
    if "uncoated" in lowered or "unctd" in lowered:
        return "Uncoated"
    match = _COATING_RE.search(text)
    if not match:
        return None
    return _clean_metadata_value(match.group(1))


def _clean_metadata_value(value: str) -> str:
    """Normalize parsed metadata values from free-form text."""
    cleaned = value.strip(" ,;:-")
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(
        r"\b(add to cart|learn more|specs?|coating)\b.*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" ,;:-")


def _extract_named_float(pattern: re.Pattern[str], text: str) -> float | None:
    """Extract a float from regex group 1."""
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except (TypeError, ValueError):
        return None


def _merge_catalog_record_pair(
    metadata_record: CatalogLensRecord,
    optical_record: CatalogLensRecord,
) -> CatalogLensRecord:
    """Merge metadata-rich and optical-rich records for the same catalog id."""
    product_name = metadata_record.product_name or optical_record.product_name
    if len(optical_record.product_name or "") > len(product_name or ""):
        product_name = optical_record.product_name
    merged = CatalogLensRecord(
        catalog_id=optical_record.catalog_id or metadata_record.catalog_id,
        manufacturer=optical_record.manufacturer or metadata_record.manufacturer,
        part_number=optical_record.part_number or metadata_record.part_number,
        product_name=product_name,
        category=metadata_record.category or optical_record.category,
        url=metadata_record.url or optical_record.url,
        efl_mm=(
            metadata_record.efl_mm
            if metadata_record.efl_mm is not None
            else optical_record.efl_mm
        ),
        bfl_mm=optical_record.bfl_mm or metadata_record.bfl_mm,
        diameter_mm=(
            metadata_record.diameter_mm
            if metadata_record.diameter_mm is not None
            else optical_record.diameter_mm
        ),
        center_thickness_mm=(
            optical_record.center_thickness_mm or metadata_record.center_thickness_mm
        ),
        edge_thickness_mm=optical_record.edge_thickness_mm or metadata_record.edge_thickness_mm,
        material_summary=metadata_record.material_summary or optical_record.material_summary,
        coating=metadata_record.coating or optical_record.coating,
        availability_status=(
            metadata_record.availability_status or optical_record.availability_status
        ),
        wavelength_min_um=optical_record.wavelength_min_um or metadata_record.wavelength_min_um,
        wavelength_max_um=optical_record.wavelength_max_um or metadata_record.wavelength_max_um,
        surfaces=optical_record.surfaces or metadata_record.surfaces,
        stop_surface_offset=(
            optical_record.stop_surface_offset
            if optical_record.stop_surface_offset is not None
            else metadata_record.stop_surface_offset
        ),
        tags=sorted(
            {
                *metadata_record.tags,
                *optical_record.tags,
            }
        ),
        source=optical_record.source,
    )
    merged.search_blob = merged.build_search_blob()
    return merged


def _extract_pair_value(text: str, index: int) -> float | None:
    """Extract values from compact vendor names like `12.7 x 6.35`."""
    match = _DIAMETER_EFL_PAIR_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(index + 1))
    except (TypeError, ValueError, IndexError):
        return None


def _normalize_catalog_part_token(value: str) -> str:
    token = re.sub(r"[^0-9a-z]+", "", str(value).casefold())
    if re.fullmatch(r"g\d{5,}", token):
        return token[1:]
    return token


def _record_matches_alias_tokens(record: CatalogLensRecord, alias_tokens: set[str]) -> bool:
    record_digits = re.sub(r"[^0-9]+", "", record.part_number)
    if record_digits in alias_tokens:
        return True
    return len(record_digits) >= 6 and record_digits[:6] in alias_tokens


def _alias_tokens_for_record(record: CatalogLensRecord, alias_groups: list) -> set[str]:
    record_digits = re.sub(r"[^0-9]+", "", record.part_number)
    family_digits = record_digits[:6] if len(record_digits) >= 6 else ""
    tokens: set[str] = set()
    for group in alias_groups:
        group_tokens = {
            re.sub(r"[^0-9]+", "", str(token))
            for token in [*getattr(group, "part_numbers", []), *getattr(group, "family_numbers", [])]
        }
        group_tokens.discard("")
        if record_digits and record_digits in group_tokens:
            tokens.update(group_tokens)
            continue
        if family_digits and family_digits in group_tokens:
            tokens.update(group_tokens)
    return tokens


def _resolve_insertable_record_from_winlens_links(
    record: CatalogLensRecord,
    records: list[CatalogLensRecord],
    link_map: dict[str, list[dict[str, object]]],
) -> CatalogLensRecord | None:
    candidates: list[tuple[int, int, str, CatalogLensRecord]] = []
    for winlens_catalog_id, links in link_map.items():
        for link in links:
            if str(link.get("catalog_id", "")) != record.catalog_id:
                continue
            source_record = next(
                (candidate for candidate in records if candidate.catalog_id == winlens_catalog_id),
                None,
            )
            if source_record is None or not source_record.surfaces:
                continue
            match_type = str(link.get("match_type", "")).casefold()
            candidates.append(
                (
                    0 if match_type == "confirmed" else 1,
                    -len(source_record.surfaces),
                    source_record.part_number.casefold(),
                    source_record,
                )
            )
            break

    if not candidates:
        return None
    return sorted(candidates)[0][3]


def _resolve_insertable_record_from_winlens_family(
    record: CatalogLensRecord,
    winlens_records: list[CatalogLensRecord],
    alias_groups: list,
) -> CatalogLensRecord | None:
    alias_tokens = _alias_tokens_for_record(record, alias_groups)
    if not alias_tokens:
        return None

    family_candidates = [
        candidate
        for candidate in winlens_records
        if _record_matches_alias_tokens(candidate, alias_tokens)
    ]
    if not family_candidates:
        return None

    surface_candidates = [candidate for candidate in family_candidates if candidate.surfaces]
    if surface_candidates:
        return sorted(
            surface_candidates,
            key=lambda candidate: (
                -len(candidate.surfaces),
                candidate.part_number.casefold(),
            ),
        )[0]

    metadata_candidates = [
        candidate for candidate in family_candidates if _can_build_paraxial_surrogate(candidate)
    ]
    if not metadata_candidates:
        return None
    return _build_paraxial_surrogate_record(
        sorted(
            metadata_candidates,
            key=lambda candidate: (
                _normalize_catalog_part_token(candidate.part_number)
                != _normalize_catalog_part_token(record.part_number),
                _winlens_family_distance(record, candidate),
                candidate.part_number.casefold(),
            ),
        )[0]
    )


def _can_build_paraxial_surrogate(record: CatalogLensRecord) -> bool:
    return (
        record.manufacturer.casefold() == "winlens library 2002"
        and record.source.source_type == "winlens_dat"
        and record.efl_mm not in (None, 0.0)
        and record.diameter_mm not in (None, 0.0)
    )


def _build_paraxial_surrogate_record(record: CatalogLensRecord) -> CatalogLensRecord:
    semi_diameter = (
        float(record.diameter_mm) / 2.0 if record.diameter_mm not in (None, 0.0) else None
    )
    return CatalogLensRecord(
        catalog_id=record.catalog_id,
        manufacturer=record.manufacturer,
        part_number=record.part_number,
        product_name=record.product_name,
        category=record.category,
        url=record.url,
        efl_mm=record.efl_mm,
        bfl_mm=record.bfl_mm,
        diameter_mm=record.diameter_mm,
        center_thickness_mm=record.center_thickness_mm,
        edge_thickness_mm=record.edge_thickness_mm,
        material_summary=record.material_summary,
        coating=record.coating,
        availability_status=record.availability_status,
        wavelength_min_um=record.wavelength_min_um,
        wavelength_max_um=record.wavelength_max_um,
        surfaces=[
            LensSurfaceSpec(
                surface_type="paraxial",
                radius="inf",
                thickness=0.0,
                material="Air",
                semi_diameter=semi_diameter,
                comment=(
                    f"{record.manufacturer} {record.part_number} "
                    f"paraxial surrogate from WinLens DAT family metadata"
                ),
                extra_data={"f": float(record.efl_mm)},
            )
        ],
        stop_surface_offset=None,
        tags=list(record.tags),
        search_blob=record.search_blob,
        source=record.source,
    )


def _winlens_family_distance(record: CatalogLensRecord, candidate: CatalogLensRecord) -> tuple[float, float]:
    record_efl = float(record.efl_mm) if record.efl_mm is not None else float("inf")
    candidate_efl = float(candidate.efl_mm) if candidate.efl_mm is not None else float("inf")
    record_diameter = (
        float(record.diameter_mm) if record.diameter_mm is not None else float("inf")
    )
    candidate_diameter = (
        float(candidate.diameter_mm) if candidate.diameter_mm is not None else float("inf")
    )
    return (
        abs(record_efl - candidate_efl),
        abs(record_diameter - candidate_diameter),
    )
