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
    EdmundCatalogImporter,
    ThorlabsCatalogImporter,
)
from optiland_gui.catalogs.search import CatalogSearchQuery, CatalogSearchService
from optiland_gui.catalogs.storage import CatalogStorage
from optiland_gui.catalogs.schema import CatalogLensRecord

EDMUND_ZEMAX_PAGE_URL = "https://www.edmundoptics.com/products/services/zemax-catalog/"
EDMUND_PRODUCTS_PAGE_URL = "https://www.edmundoptics.com/products/"
THORLABS_ZEMAX_PAGE_URL = "https://www.thorlabs.com/software_pages/ViewSoftwarePage.cfm?Code=Zemax"
THORLABS_PRODUCTS_PAGE_URL = "https://www.thorlabs.com/navigation.cfm?guide_id=1"
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
        self._importers = {
            "edmund": EdmundCatalogImporter(),
            "thorlabs": ThorlabsCatalogImporter(),
        }

    def import_catalog_file(self, manufacturer: str, filepath: str | list[str]) -> int:
        """Import one or more manufacturer catalog files and persist them locally."""
        key = manufacturer.strip().lower()
        importer = self._importers.get(key)
        if importer is None:
            raise ValueError(f"Unsupported manufacturer: {manufacturer}")
        input_paths = [filepath] if isinstance(filepath, str) else filepath
        extracted_dirs = self._extract_zip_archives(importer.manufacturer, input_paths)
        search_paths = [*input_paths, *[str(path) for path in extracted_dirs]]
        zmf_paths = self._find_zmf_paths(search_paths)
        expanded_paths = self._expand_import_paths(search_paths)
        import_paths = [*expanded_paths, *zmf_paths]
        if not import_paths:
            raise ValueError(
                "No supported catalog files were selected. "
                "Choose .zip, .zmx, .zmf, or normalized .json files."
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
        imported_records = self._enrich_imported_records(importer.manufacturer, imported_records)

        merged_records = {
            record.catalog_id: record
            for record in self._records
            if record.manufacturer.casefold() == importer.manufacturer.casefold()
        }
        for record in imported_records:
            merged_records[record.catalog_id] = record

        self._storage.save_records(
            importer.manufacturer,
            sorted(
                merged_records.values(),
                key=lambda item: (
                    item.part_number.casefold(),
                    item.product_name.casefold(),
                ),
            ),
        )
        self._reload_all()
        return len(imported_records)

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
        )
        return [record.to_summary_dict() for record in self._search_service.search(self._records, query)]

    def get_record(self, catalog_id: str) -> CatalogLensRecord | None:
        """Return a full record by id."""
        for record in self._records:
            if record.catalog_id == catalog_id:
                return record
        return None

    def get_record_details(self, catalog_id: str) -> dict | None:
        """Return a full record payload for GUI detail display."""
        record = self.get_record(catalog_id)
        return None if record is None else record.to_dict()

    def resolve_product_url(self, catalog_id: str) -> str | None:
        """Resolve a current product webpage URL for *catalog_id*."""
        record = self.get_record(catalog_id)
        if record is None:
            return None
        return self._resolve_record_product_url(record)

    def _reload_all(self) -> None:
        self._records = self._storage.load_all_records()

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

    def _expand_import_paths(self, raw_paths: Iterable[str]) -> list[Path]:
        """Return supported files from *raw_paths*, expanding directories recursively."""
        return self._collect_paths(raw_paths, {".json", ".zmx"})

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


def _extract_pair_value(text: str, index: int) -> float | None:
    """Extract values from compact vendor names like `12.7 x 6.35`."""
    match = _DIAMETER_EFL_PAIR_RE.search(text)
    if not match:
        return None
    try:
        return float(match.group(index + 1))
    except (TypeError, ValueError, IndexError):
        return None
