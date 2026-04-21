"""Tests for the stock-lens catalog browser panel."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget

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

    def resolve_catalog_product_url(self, catalog_id: str) -> str | None:
        return None

    def import_catalog_file(self, manufacturer: str, paths: list[str]) -> int:
        self.import_calls.append((manufacturer, paths))
        return 3

    def download_edmund_catalog(self):  # noqa: ANN202
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

    download_actions = [action.text() for action in panel.download_catalog_button.menu().actions()]
    assert download_actions == ["Edmund Optics...", "Thorlabs..."]

    assert panel.results_table.columnCount() == 8
    assert panel.results_table.horizontalHeader().sectionsMovable()
    assert panel.manufacturer_filter.parentWidget() is panel.filter_row_container
    assert panel.material_filter.parentWidget() is panel.filter_row_container
    assert panel.coating_filter.parentWidget() is panel.filter_row_container
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
    panel.manufacturer_filter.setCurrentIndex(1)

    panel._reset_filters()

    assert panel.search_edit.text() == ""
    assert panel.part_number_filter.text() == ""
    assert panel.name_filter.text() == ""
    assert panel.category_filter.text() == ""
    assert panel.efl_filter.text() == ""
    assert panel.diameter_filter.text() == ""
    assert panel.material_filter.text() == ""
    assert panel.coating_filter.text() == ""
    assert panel.manufacturer_filter.currentData() == ""


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


def test_catalog_browser_numeric_columns_are_right_aligned_with_two_decimals(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    efl_item = panel.results_table.item(0, 4)
    diameter_item = panel.results_table.item(0, 5)

    assert efl_item.text() == "12.35"
    assert diameter_item.text() == "25.00"
    assert bool(efl_item.textAlignment() & int(Qt.AlignmentFlag.AlignRight))
    assert bool(diameter_item.textAlignment() & int(Qt.AlignmentFlag.AlignRight))
    assert panel.results_table.item(0, 6).text() == "N-BK7"
    assert panel.results_table.item(0, 7).text() == "VIS"


def test_catalog_browser_copy_shortcuts_copy_current_cell_and_row(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())
    panel.results_table.setCurrentCell(0, 1)

    panel._copy_current_cell_to_clipboard()
    assert qapp.clipboard().text() == "49-847"

    panel._copy_selected_row_to_clipboard()
    header = panel.results_table.horizontalHeader()
    expected = []
    for visual_column in range(panel.results_table.columnCount()):
        logical_column = header.logicalIndex(visual_column)
        expected.append(panel.results_table.item(0, logical_column).text())
    assert qapp.clipboard().text() == "\t".join(expected)


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


def test_catalog_browser_filter_row_filters_material_and_part_number(qapp) -> None:
    panel = CatalogBrowserPanel(_ResultConnector())

    panel.part_number_filter.setText("49-847")
    panel.material_filter.setText("BK7")
    panel.refresh()

    assert panel.results_table.rowCount() == 1
    assert panel.results_table.item(0, 1).text() == "49-847"


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
