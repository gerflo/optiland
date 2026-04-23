"""Tests for the stock-lens catalog browser panel."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox, QWidget

from optiland_gui.catalog_browser_panel import CatalogBrowserPanel


class _DummyConnector(QObject):
    """Minimal connector stub for catalog browser tests."""

    catalogChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.import_calls: list[tuple[str, list[str]]] = []

    def search_catalog_lenses(self, query: dict) -> list[dict]:
        return []

    def get_catalog_manufacturers(self) -> list[str]:
        return []

    def get_catalog_lens_details(self, catalog_id: str) -> dict | None:
        return None

    def get_catalog_document_urls(self, catalog_id: str) -> list[str]:
        return []

    def resolve_catalog_product_url(self, catalog_id: str) -> str | None:
        return None

    def get_catalog_record_links(self, catalog_id: str) -> list[dict]:
        return []

    def get_winlens_review_candidates(self, min_confidence_percent: int = 76) -> list[dict]:
        return []

    def confirm_winlens_links(self, selections: list[dict[str, str]]) -> int:
        return len(selections)

    def delete_catalog_records(self, catalog_ids: list[str]) -> int:
        return len(catalog_ids)

    def import_catalog_file(self, manufacturer: str, paths: list[str]) -> int:
        self.import_calls.append((manufacturer, paths))
        return 3

    def import_winlens_library(self, root_path: str):  # noqa: ANN202
        self.import_calls.append(("WinLens Library 2002", [root_path]))
        return type(
            "_Result",
            (),
            {
                "imported_count": 3,
                "linked_count": 2,
                "message": "Imported 3 WinLens SPD record(s) and built 2 link suggestion(s).",
            },
        )()

    def download_edmund_catalog(self):  # noqa: ANN202
        raise AssertionError("Download should not be called in this test")

    def download_excelitas_catalog(self):  # noqa: ANN202
        raise AssertionError("Download should not be called in this test")


class _ResultConnector(_DummyConnector):
    """Connector stub with one result row for table-format tests."""

    def search_catalog_lenses(self, query: dict) -> list[dict]:
        record = {
            "catalog_id": "edmund:49-847",
            "manufacturer": "Edmund",
            "part_number": "49-847",
            "product_name": "Demo Lens",
            "category": "achromat",
            "efl_mm": 12.3456,
            "diameter_mm": 25,
            "material_summary": "N-BK7",
            "coating": "VIS",
            "insertable_surface_count": 2,
        }
        text = str(query.get("text", "")).casefold()
        manufacturer = str(query.get("manufacturer", "")).casefold()
        part_number = str(query.get("part_number", "")).casefold()
        product_name = str(query.get("product_name", "")).casefold()
        category = str(query.get("category", "")).casefold()
        material_text = str(query.get("material_text", "")).casefold()
        coating_text = str(query.get("coating_text", "")).casefold()
        efl_min = query.get("efl_min")
        efl_max = query.get("efl_max")
        diameter_min = query.get("diameter_min")
        diameter_max = query.get("diameter_max")
        search_blob = " ".join(
            [
                record["manufacturer"],
                record["part_number"],
                record["product_name"],
                record["category"],
                record["material_summary"],
                record["coating"],
            ]
        ).casefold()
        if text and text not in search_blob:
            return []
        if manufacturer and manufacturer != str(record["manufacturer"]).casefold():
            return []
        if part_number and part_number not in str(record["part_number"]).casefold():
            return []
        if product_name and product_name not in str(record["product_name"]).casefold():
            return []
        if category and category not in str(record["category"]).casefold():
            return []
        if material_text and material_text not in str(record["material_summary"]).casefold():
            return []
        if coating_text and coating_text not in str(record["coating"]).casefold():
            return []
        if efl_min is not None and float(record["efl_mm"]) < float(efl_min):
            return []
        if efl_max is not None and float(record["efl_mm"]) > float(efl_max):
            return []
        if diameter_min is not None and float(record["diameter_mm"]) < float(diameter_min):
            return []
        if diameter_max is not None and float(record["diameter_mm"]) > float(diameter_max):
            return []
        return [record]

    def get_catalog_manufacturers(self) -> list[str]:
        return ["Edmund"]

    def get_catalog_lens_details(self, catalog_id: str) -> dict | None:
        if catalog_id != "edmund:49-847":
            return None
        return {
            "catalog_id": "edmund:49-847",
            "manufacturer": "Edmund",
            "part_number": "49-847",
            "product_name": "Demo Lens",
            "category": "achromat",
            "efl_mm": 12.3456,
            "diameter_mm": 25,
            "material_summary": "N-BK7",
            "coating": "VIS",
            "surfaces": [{}, {}],
            "url": "https://example.com/product/49-847",
            "source": {
                "source_type": "zmf",
                "source_url": "https://example.com/source/49-847",
                "imported_at": "2026-04-21T16:00:00",
            },
        }

    def resolve_catalog_product_url(self, catalog_id: str) -> str | None:
        if catalog_id == "edmund:49-847":
            return "https://example.com/product/49-847"
        return None

    def get_catalog_document_urls(self, catalog_id: str) -> list[str]:
        if catalog_id == "edmund:49-847":
            return ["https://example.com/docs/49-847.pdf"]
        return []

    def insert_catalog_lens(
        self, catalog_id: str, surface_index: int, mode: str
    ) -> None:
        self.last_insert_call = (catalog_id, surface_index, mode)


class _MultiDocumentConnector(_ResultConnector):
    def get_catalog_document_urls(self, catalog_id: str) -> list[str]:
        if catalog_id == "edmund:49-847":
            return [
                "https://example.com/docs/49-847.pdf",
                "https://example.com/docs/49-847.step",
            ]
        return []


class _WinLensResultConnector(_ResultConnector):
    def search_catalog_lenses(self, query: dict) -> list[dict]:
        return [
            {
                "catalog_id": "winlens library 2002:317703",
                "manufacturer": "WinLens Library 2002",
                "part_number": "317703",
                "product_name": "Asphere demo",
                "category": "asphere",
                "efl_mm": 15.0,
                "diameter_mm": 18.0,
                "material_summary": "N-BK7",
                "coating": "",
            }
        ]

    def get_catalog_lens_details(self, catalog_id: str) -> dict | None:
        if catalog_id != "winlens library 2002:317703":
            return None
        return {
            "catalog_id": catalog_id,
            "manufacturer": "WinLens Library 2002",
            "part_number": "317703",
            "product_name": "Asphere demo",
            "category": "asphere",
            "efl_mm": 15.0,
            "diameter_mm": 18.0,
            "material_summary": "N-BK7",
            "coating": "",
            "availability_status": "unknown",
            "surfaces": [{}, {}],
            "source": {
                "source_type": "winlens_spd",
                "imported_at": "2026-04-21T16:00:00",
            },
        }

    def get_catalog_record_links(self, catalog_id: str) -> list[dict]:
        if catalog_id != "winlens library 2002:317703":
            return []
        return [
            {
                "catalog_id": "excelitas linos:g317703000",
                "manufacturer": "Excelitas LINOS",
                "part_number": "G317703000",
                "product_name": "Asph. condenser lens",
                "score": 140,
                "match_type": "candidate",
                "reasons": ["numeric part number overlap", "matching efl"],
            }
        ]


class _LargeResultConnector(_DummyConnector):
    """Connector stub with enough rows to exercise batched population."""

    def __init__(self, count: int = 600) -> None:
        super().__init__()
        self.count = count

    def search_catalog_lenses(self, query: dict) -> list[dict]:
        return [
            {
                "catalog_id": f"edmund:{index:05d}",
                "manufacturer": "Edmund",
                "part_number": f"{index:05d}",
                "product_name": f"Lens {index}",
                "category": "achromat",
                "efl_mm": float(index),
                "diameter_mm": 25.0,
                "material_summary": "N-BK7",
                "coating": "VIS",
            }
            for index in range(self.count)
        ]

    def get_catalog_manufacturers(self) -> list[str]:
        return ["Edmund"]

    def get_catalog_lens_details(self, catalog_id: str) -> dict | None:
        return {
            "catalog_id": catalog_id,
            "manufacturer": "Edmund",
            "part_number": catalog_id.split(":", 1)[-1],
            "product_name": "Lens",
            "category": "achromat",
            "efl_mm": 1.0,
            "diameter_mm": 25.0,
            "material_summary": "N-BK7",
            "coating": "VIS",
            "surfaces": [{}, {}],
            "source": {
                "source_type": "json",
                "imported_at": "2026-04-21T16:00:00",
            },
        }


class _InsertableFilterConnector(_DummyConnector):
    def search_catalog_lenses(self, query: dict) -> list[dict]:
        return [
            {
                "catalog_id": "edmund:usable",
                "manufacturer": "Edmund",
                "part_number": "49-847",
                "product_name": "Usable Lens",
                "category": "achromat",
                "efl_mm": 25.0,
                "diameter_mm": 25.0,
                "material_summary": "N-BK7",
                "coating": "VIS",
                "insertable_surface_count": 2,
            },
            {
                "catalog_id": "excelitas:metadata-only",
                "manufacturer": "Excelitas LINOS",
                "part_number": "G000000000",
                "product_name": "Metadata Only",
                "category": "achromat",
                "efl_mm": 25.0,
                "diameter_mm": 25.0,
                "material_summary": "N-BK7",
                "coating": "VIS",
                "insertable_surface_count": 0,
            },
        ]


class _FakeSettings:
    """Small in-memory stand-in for QSettings used in panel tests."""

    _store: dict[str, object] = {}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, D401
        pass

    def value(self, key: str, default=None, type=None):  # noqa: ANN001, A002
        value = self._store.get(key, default)
        if type is not None and value is not None:
            return type(value)
        return value

    def setValue(self, key: str, value) -> None:  # noqa: ANN001, N802
        self._store[key] = value


class _ToastRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def notify(self, message: str, level: str) -> None:
        self.calls.append((message, level))


def test_catalog_browser_uses_download_button_and_filter_row(qapp) -> None:
    panel = CatalogBrowserPanel(_DummyConnector())

    assert panel.download_catalog_button.text() == "Download online catalog..."
    assert panel.reset_filters_button.text() == "↻"
    assert panel.reset_filters_button.toolTip() == "Reset all search filters"
    assert panel.insertable_only_button.text() == "Insertable"
    assert panel.insertable_only_button.isCheckable() is True
    assert panel.insertable_only_button.isChecked() is True
    assert panel.insertable_only_button.icon().isNull() is False

    download_actions = [action.text() for action in panel.download_catalog_button.menu().actions()]
    assert download_actions == [
        "Excelitas / LINOS...",
        "Edmund Optics...",
        "Thorlabs...",
        "",
        "Import WinLens Library...",
    ]

    assert panel.results_table.columnCount() == 11
    assert panel.results_table.horizontalHeader().sectionsMovable()
    assert panel.manufacturer_filter.parentWidget() is panel.filter_row_container
    assert panel.material_filter.parentWidget() is panel.filter_row_container
    assert panel.coating_filter.parentWidget() is panel.filter_row_container
    assert panel.match_filter.parentWidget() is panel.filter_row_container
    assert panel.filter_row_container.parentWidget() is panel.table_view_content
    assert panel.results_table.parentWidget() is panel.table_view_content


def test_catalog_browser_import_folder_passes_directory_to_connector(monkeypatch, qapp) -> None:
    connector = _DummyConnector()
    panel = CatalogBrowserPanel(connector)

    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "C:/catalogs/edmund",
    )

    panel._import_catalog_folder("Edmund")
    QTest.qWait(50)

    assert connector.import_calls == [("Edmund", ["C:/catalogs/edmund"])]


def test_catalog_browser_import_winlens_library_passes_directory_to_connector(monkeypatch, qapp) -> None:
    connector = _DummyConnector()
    panel = CatalogBrowserPanel(connector)

    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: "C:/catalogs/winlens",
    )

    panel._import_winlens_library()
    QTest.qWait(50)

    assert connector.import_calls == [("WinLens Library 2002", ["C:/catalogs/winlens"])]


def test_catalog_browser_busy_indicator_toggles_import_ui_state(qapp) -> None:
    connector = _DummyConnector()
    panel = CatalogBrowserPanel(connector)
    panel._set_task_busy(True)
    QTest.qWait(150)

    assert panel.import_busy_indicator.text() in {"|", "/", "-", "\\"}
    assert not panel.download_catalog_button.isEnabled()

    panel._set_task_busy(False)

    assert not panel.import_busy_indicator.isVisible()
    assert panel.download_catalog_button.isEnabled()


def test_catalog_browser_reset_filters_restores_default_values(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    panel.search_edit.setText("BK7")
    panel.part_number_filter.setText("49-847")
    panel.name_filter.setText("Demo")
    panel.category_filter.setText("achromat")
    panel.efl_filter.setText("10-25")
    panel.diameter_filter.setText("5-20")
    panel.material_filter.setText("N-BK7")
    panel.coating_filter.setText("VIS")
    panel.status_filter.setText("legacy")
    panel.match_filter.setText("confirmed")
    panel.manufacturer_filter.setCurrentIndex(1)
    panel.insertable_only_button.setChecked(False)

    panel._reset_filters()

    assert panel.search_edit.text() == ""
    assert panel.part_number_filter.text() == ""
    assert panel.name_filter.text() == ""
    assert panel.category_filter.text() == ""
    assert panel.efl_filter.text() == ""
    assert panel.diameter_filter.text() == ""
    assert panel.material_filter.text() == ""
    assert panel.coating_filter.text() == ""
    assert panel.status_filter.text() == ""
    assert panel.match_filter.text() == ""
    assert panel.manufacturer_filter.currentData() == ""
    assert panel.insertable_only_button.isChecked() is True


def test_catalog_browser_insertable_only_filter_hides_metadata_only_rows(qapp) -> None:
    panel = CatalogBrowserPanel(_InsertableFilterConnector())

    assert [record["catalog_id"] for record in panel._current_results] == ["edmund:usable"]
    assert panel.insertable_only_button.toolTip().startswith("Showing only")

    panel.insertable_only_button.setChecked(False)

    assert [record["catalog_id"] for record in panel._current_results] == [
        "edmund:usable",
        "excelitas:metadata-only",
    ]
    assert panel.insertable_only_button.toolTip().startswith("Showing all")


def test_catalog_browser_restores_saved_column_widths_and_sort(monkeypatch, qapp) -> None:
    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QSettings",
        _FakeSettings,
    )
    _FakeSettings._store = {}

    first_panel = CatalogBrowserPanel(_DummyConnector())
    first_panel.results_table.setColumnWidth(0, 222)
    first_panel.results_table.setColumnWidth(2, 333)
    first_panel.results_table.horizontalHeader().moveSection(7, 1)
    first_panel.results_table.horizontalHeader().setSortIndicator(
        2,
        Qt.SortOrder.DescendingOrder,
    )
    first_panel._save_table_state()

    second_panel = CatalogBrowserPanel(_DummyConnector())
    header = second_panel.results_table.horizontalHeader()

    assert second_panel.results_table.columnWidth(0) == 222
    assert second_panel.results_table.columnWidth(2) == 333
    assert header.visualIndex(7) == 1
    assert header.sortIndicatorSection() == 2
    assert header.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder
    assert second_panel.results_table.horizontalHeaderItem(2).text() == "Part No. ↓"
    assert second_panel.results_table.horizontalHeaderItem(1).text() == "Manufacturer"


def test_catalog_browser_updates_sorted_column_header_label_with_arrow(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    header = panel.results_table.horizontalHeader()

    header.setSortIndicator(3, Qt.SortOrder.AscendingOrder)

    assert panel.results_table.horizontalHeaderItem(3).text() == "Name ↑"
    assert panel.results_table.horizontalHeaderItem(2).text() == "Part No."

    header.setSortIndicator(3, Qt.SortOrder.DescendingOrder)

    assert panel.results_table.horizontalHeaderItem(3).text() == "Name ↓"


def test_catalog_browser_numeric_columns_are_right_aligned_with_two_decimals(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    efl_item = panel.results_table.item(0, 5)
    diameter_item = panel.results_table.item(0, 6)

    assert efl_item.text() == "12.35"
    assert diameter_item.text() == "25.00"
    assert bool(efl_item.textAlignment() & int(Qt.AlignmentFlag.AlignRight))
    assert bool(diameter_item.textAlignment() & int(Qt.AlignmentFlag.AlignRight))
    assert panel.results_table.item(0, 7).text() == "N-BK7"


def test_catalog_browser_context_menu_prioritizes_insert_actions(monkeypatch, qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    action_texts: list[str] = []

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text
            self.enabled = True

        def text(self) -> str:
            return self._text

        def setEnabled(self, enabled: bool) -> None:  # noqa: N802
            self.enabled = enabled

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str) -> _FakeAction:  # noqa: N802
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):  # noqa: ANN201
            action = _FakeAction("")
            self._actions.append(action)
            return action

        def addMenu(self, text: str):  # noqa: ANN201, N802
            action = _FakeAction(text)
            self._actions.append(action)
            return self

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_texts.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr("optiland_gui.catalog_browser_panel.QMenu", _FakeMenu)

    target_item = panel.results_table.item(0, 2)
    assert target_item is not None

    panel._show_results_context_menu(panel.results_table.visualItemRect(target_item).center())

    assert action_texts[:6] == [
        "Insert Before Selected Surface",
        "Insert After Selected Surface",
        "",
        "Copy Cell",
        "Copy Row",
        "",
    ]
    assert panel.results_table.item(0, 8).text() == "VIS"


def test_catalog_browser_context_menu_hides_missing_product_and_vendor_links(
    monkeypatch, qapp
) -> None:
    class _NoUrlConnector(_ResultConnector):
        def resolve_catalog_product_url(self, catalog_id: str) -> str | None:
            return None

        def get_catalog_document_urls(self, catalog_id: str) -> list[str]:
            return []

    panel = CatalogBrowserPanel(_NoUrlConnector())
    action_texts: list[str] = []

    class _FakeAction:
        def __init__(self, text: str) -> None:
            self._text = text
            self.enabled = True

        def text(self) -> str:
            return self._text

        def setEnabled(self, enabled: bool) -> None:  # noqa: N802
            self.enabled = enabled

    class _FakeMenu:
        def __init__(self, *_args, **_kwargs) -> None:
            self._actions: list[_FakeAction] = []

        def addAction(self, text: str) -> _FakeAction:  # noqa: N802
            action = _FakeAction(text)
            self._actions.append(action)
            return action

        def addSeparator(self):  # noqa: ANN201
            action = _FakeAction("")
            self._actions.append(action)
            return action

        def addMenu(self, text: str):  # noqa: ANN201, N802
            action = _FakeAction(text)
            self._actions.append(action)
            return self

        def exec(self, *_args, **_kwargs):  # noqa: ANN201
            action_texts.extend(action.text() for action in self._actions)
            return None

    monkeypatch.setattr("optiland_gui.catalog_browser_panel.QMenu", _FakeMenu)

    target_item = panel.results_table.item(0, 2)
    assert target_item is not None

    panel._show_results_context_menu(panel.results_table.visualItemRect(target_item).center())

    assert "Open Product Webpage" not in action_texts
    assert "Open Vendor Document" not in action_texts


def test_catalog_browser_copy_shortcuts_copy_current_cell_and_row(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    panel.results_table.setCurrentCell(0, 2)

    panel._copy_current_cell_to_clipboard()
    assert qapp.clipboard().text() == "49-847"

    panel._copy_selected_row_to_clipboard()
    header = panel.results_table.horizontalHeader()
    expected = []
    for visual_column in range(panel.results_table.columnCount()):
        logical_column = header.logicalIndex(visual_column)
        expected.append(panel.results_table.item(0, logical_column).text())
    assert qapp.clipboard().text() == "\t".join(expected)


def test_catalog_browser_copy_prefers_last_active_cell_over_current_item(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    panel._results_table_copy._remember_cell(0, 5)
    panel.results_table.setCurrentCell(0, 1)

    panel._copy_current_cell_to_clipboard()

    assert qapp.clipboard().text() == panel.results_table.item(0, 5).text()


def test_catalog_browser_can_open_selected_product_url(monkeypatch, qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    panel.results_table.setCurrentCell(0, 0)
    opened_urls: list[str] = []

    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()),
    )

    panel._open_selected_catalog_url()

    assert opened_urls == ["https://example.com/product/49-847"]


def test_catalog_browser_can_open_selected_vendor_document(monkeypatch, qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    panel.results_table.setCurrentCell(0, 0)
    opened_urls: list[str] = []

    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toString()),
    )

    panel._open_selected_vendor_document()

    assert opened_urls == ["https://example.com/docs/49-847.pdf"]


def test_catalog_browser_context_menu_builds_vendor_document_submenu_for_multiple_links(qapp) -> None:
    panel = CatalogBrowserPanel(_MultiDocumentConnector())
    menu = type(panel.download_catalog_button.menu())(panel)

    panel._populate_vendor_document_menu(
        menu,
        [
            "https://example.com/docs/49-847.pdf",
            "https://example.com/docs/49-847.step",
        ],
    )

    assert [action.text() for action in menu.actions()] == ["49-847.pdf", "49-847.step"]


def test_catalog_browser_filter_row_filters_material_and_part_number(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    panel.part_number_filter.setText("49-847")
    panel.material_filter.setText("BK7")
    panel.refresh()

    assert panel.results_table.rowCount() == 1
    assert panel.results_table.item(0, 2).text() == "49-847"


def test_catalog_browser_filter_row_reduces_results_when_part_number_does_not_match(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    panel.part_number_filter.setText("00-000")
    panel.refresh()

    assert panel.results_table.rowCount() == 0
    assert panel.results_table.currentItem() is None


def test_catalog_browser_filter_row_stays_pinned_when_table_scrolls(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    initial_y = panel.filter_row_container.y()
    panel.results_table.setRowCount(50)
    panel.results_table.verticalScrollBar().setValue(200)
    QTest.qWait(10)

    assert panel.filter_row_container.y() == initial_y


def test_catalog_browser_notify_uses_parent_toast_manager(qapp) -> None:
    host = QWidget()
    host.toast_manager = _ToastRecorder()  # type: ignore[attr-defined]
    panel = CatalogBrowserPanel(_DummyConnector(), parent=host)

    panel._notify("Imported 3 Edmund catalog entries.", "success")

    assert host.toast_manager.calls == [("Imported 3 Edmund catalog entries.", "success")]


def test_catalog_browser_details_show_top_match_for_winlens_records(qapp) -> None:
    panel = CatalogBrowserPanel(_WinLensResultConnector())
    panel.results_table.setCurrentCell(0, 0)
    panel._update_details()

    assert "Top link: Excelitas LINOS G317703000" in panel.details_text.text()
    assert "Status: unknown" in panel.details_text.text()
    assert "[candidate]" in panel.details_text.text()


def test_catalog_browser_match_filter_keeps_confirmed_records(qapp) -> None:
    class _MatchConnector(_WinLensResultConnector):
        def search_catalog_lenses(self, query: dict) -> list[dict]:
            rows = [
                {
                    "catalog_id": "winlens library 2002:322307",
                    "manufacturer": "WinLens Library 2002",
                    "part_number": "322307",
                    "product_name": "Achromat demo",
                    "category": "achromat",
                    "efl_mm": 80.0,
                    "diameter_mm": 25.4,
                    "material_summary": "N-BK7",
                    "coating": "",
                    "availability_status": "",
                    "match_type": "confirmed",
                },
                {
                    "catalog_id": "winlens library 2002:317703",
                    "manufacturer": "WinLens Library 2002",
                    "part_number": "317703",
                    "product_name": "Asphere demo",
                    "category": "asphere",
                    "efl_mm": 15.0,
                    "diameter_mm": 18.0,
                    "material_summary": "N-BK7",
                    "coating": "",
                    "availability_status": "unknown",
                    "match_type": "candidate",
                },
            ]
            match_filter = str(query.get("match_type_text", "")).casefold()
            if not match_filter:
                return rows
            return [row for row in rows if match_filter in str(row.get("match_type", "")).casefold()]

    panel = CatalogBrowserPanel(_MatchConnector())
    panel.match_filter.setText("confirmed")
    panel.refresh()

    assert panel.results_table.rowCount() == 1
    assert panel.results_table.item(0, 2).text() == "322307"


def test_catalog_browser_default_sort_prioritizes_insertable_results(qapp) -> None:
    class _InsertableFirstConnector(_DummyConnector):
        def search_catalog_lenses(self, query: dict) -> list[dict]:
            return [
                {
                    "catalog_id": "excelitas linos:g317704000",
                    "manufacturer": "Excelitas LINOS",
                    "part_number": "G317704000",
                    "product_name": "Asph. condenser lens; D=22.4; F=18",
                    "category": "asphere",
                    "efl_mm": 18.0,
                    "diameter_mm": 22.4,
                    "material_summary": "",
                    "coating": "",
                    "availability_status": "",
                    "match_type": "",
                    "surface_count": 0,
                    "insertable_surface_count": 3,
                },
                {
                    "catalog_id": "winlens library 2002:317704",
                    "manufacturer": "WinLens Library 2002",
                    "part_number": "317704",
                    "product_name": "aspherical condenser lens f = 18",
                    "category": "condenser",
                    "efl_mm": 18.0883,
                    "diameter_mm": 21.4,
                    "material_summary": "B270",
                    "coating": "",
                    "availability_status": "",
                    "match_type": "confirmed",
                    "surface_count": 3,
                    "insertable_surface_count": 3,
                },
            ]

        def get_catalog_lens_details(self, catalog_id: str) -> dict | None:
            return {
                "catalog_id": catalog_id,
                "manufacturer": "WinLens Library 2002",
                "part_number": "317704",
                "product_name": "aspherical condenser lens f = 18",
                "category": "condenser",
                "efl_mm": 18.0883,
                "diameter_mm": 21.4,
                "material_summary": "B270",
                "coating": "",
                "surfaces": [{}, {}, {}],
                "source": {
                    "source_type": "winlens_spd",
                    "imported_at": "2026-04-21T16:00:00",
                },
            }

    panel = CatalogBrowserPanel(_InsertableFirstConnector())

    assert panel.results_table.rowCount() == 2
    assert panel.results_table.item(0, 2).text() == "317704"


def test_catalog_browser_can_mark_filtered_and_delete_marked(monkeypatch, qapp) -> None:
    connector = _ResultConnector()
    deleted: list[str] = []
    connector.delete_catalog_records = lambda catalog_ids: deleted.extend(catalog_ids) or len(catalog_ids)  # type: ignore[method-assign]
    panel = CatalogBrowserPanel(connector)

    panel._mark_filtered_results()
    assert "edmund:49-847" in panel._marked_catalog_ids

    monkeypatch.setattr(
        "optiland_gui.catalog_browser_panel.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    panel._delete_marked_results()

    assert deleted == ["edmund:49-847"]
    assert panel._marked_catalog_ids == set()


def test_catalog_browser_mark_button_switches_to_mark_all_without_selection(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    assert panel.mark_filtered_button.text() == ""
    assert panel.mark_filtered_button.toolTip() == "Mark Filtered"

    panel.results_table.clearSelection()
    panel.results_table.setCurrentCell(-1, -1)
    panel._update_details()

    assert panel.mark_filtered_button.text() == ""
    assert panel.mark_filtered_button.toolTip() == "Mark All"


def test_catalog_browser_populates_large_result_sets_in_batches(qapp) -> None:
    panel = CatalogBrowserPanel(_LargeResultConnector())

    assert panel.results_table.rowCount() == 600
    assert panel.results_table.item(0, 2) is not None
    assert panel.results_table.item(300, 2) is None
    assert panel.status_label.text() == "Loading catalog entries... 250/600"

    QTest.qWait(120)

    assert panel.results_table.item(300, 2) is not None
    assert panel.status_label.text() == "600 catalog entries found."
    assert panel.results_table.currentRow() != -1


def test_insert_before_defaults_to_image_when_no_lde_row_selected(qapp) -> None:
    connector = _ResultConnector()
    panel = CatalogBrowserPanel(connector)
    panel.results_table.selectRow(0)

    class _LensEditorConnector:
        @staticmethod
        def get_surface_count() -> int:
            return 5

    class _LensEditor:
        def __init__(self) -> None:
            self.tableWidget = type(
                "_TableStub",
                (),
                {"currentRow": staticmethod(lambda: -1)},
            )()
            self.connector = _LensEditorConnector()

        @staticmethod
        def map_ui_row_to_surface_index(ui_row: int) -> int:
            return ui_row

    host = QWidget()
    host.panel_manager = type(
        "_PanelManager",
        (),
        {"lens_editor": _LensEditor()},
    )()
    panel.setParent(host)

    panel._insert_selected("before")

    assert connector.last_insert_call == ("edmund:49-847", 4, "before")
