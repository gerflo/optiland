"""Tests for the material database browser panel."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMessageBox

from optiland_gui.material_browser_panel import MaterialBrowserPanel


class _DummyConnector(QObject):
    materialsChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.import_calls: list[str] = []
        self.deleted_material_ids: list[str] = []

    def search_materials(self, query: dict | None = None) -> list[dict]:
        query = query or {}
        record = {
            "material_id": "Schott|N-BK7|glass/schott/N-BK7.yml",
            "reference": "Schott",
            "name": "N-BK7",
            "display_name": "N-BK7",
            "group": "glass",
            "category": "SCHOTT-BK",
            "category_full": "SCHOTT - BK (Borosilicate crown)",
            "source": "Built-in Glass",
            "filename": "glass/schott/N-BK7.yml",
            "absolute_filename": r"C:\materials\N-BK7.yml",
            "min_wavelength": 0.3,
            "max_wavelength": 2.5,
            "is_local_import": False,
        }
        local_record = {
            "material_id": "Hoya|ADC1|glass/winlens/hoya/ADC1.yml",
            "reference": "Hoya",
            "name": "ADC1",
            "display_name": "ADC1",
            "group": "glass",
            "category": "WinLens",
            "category_full": "WinLens imported Hoya",
            "source": "WinLens Import",
            "filename": "glass/winlens/hoya/ADC1.yml",
            "absolute_filename": r"C:\materials\winlens\ADC1.yml",
            "min_wavelength": 0.36501,
            "max_wavelength": 1.01398,
            "is_local_import": True,
        }
        text = str(query.get("text", "")).casefold()
        reference = str(query.get("reference", "")).casefold()
        name = str(query.get("name", "")).casefold()
        category = str(query.get("category", "")).casefold()
        source = str(query.get("source", "")).casefold()
        records = [record, local_record]
        if text:
            records = [
                item
                for item in records
                if text in " ".join(
                    [
                        item["reference"],
                        item["name"],
                        item["category"],
                        item["source"],
                    ]
                ).casefold()
            ]
        if reference:
            records = [item for item in records if item["reference"].casefold() == reference]
        if name:
            records = [item for item in records if name in item["name"].casefold()]
        if category:
            records = [item for item in records if category in item["category"].casefold()]
        if source:
            records = [item for item in records if item["source"].casefold() == source]
        return records

    def get_material_references(self) -> list[str]:
        return ["Hoya", "Schott"]

    def get_material_details(self, material_id: str) -> dict | None:
        for item in self.search_materials({}):
            if item["material_id"] == material_id:
                return item
        return None

    def import_winlens_materials(self, root_path: str):  # noqa: ANN202
        self.import_calls.append(root_path)
        return type(
            "_Result",
            (),
            {
                "imported_count": 4,
                "skipped_existing": 2,
                "skipped_unsupported": 0,
                "catalog_csv": "catalog_nk_winlens.csv",
                "message": "Imported 4 WinLens material(s), skipped 2 existing and 0 unsupported.",
            },
        )()

    def delete_materials(self, material_ids: list[str]) -> int:
        self.deleted_material_ids.extend(material_ids)
        return len(material_ids)


def test_material_browser_panel_renders_result_and_details(qapp) -> None:
    panel = MaterialBrowserPanel(_DummyConnector())

    assert panel.results_table.rowCount() == 2
    assert panel.results_table.item(0, 1).text() == "Schott"
    assert panel.results_table.item(1, 1).text() == "Hoya"
    assert "N-BK7" in panel.details_text.text()
    assert "Built-in Glass" in panel.details_text.text()


def test_material_browser_panel_filters_by_search_text(qapp) -> None:
    panel = MaterialBrowserPanel(_DummyConnector())

    panel.search_edit.setText("does-not-match")

    assert panel.results_table.rowCount() == 0
    assert panel.status_label.text() == "No materials found."


def test_material_browser_import_calls_connector(monkeypatch, qapp) -> None:
    connector = _DummyConnector()
    panel = MaterialBrowserPanel(connector)

    monkeypatch.setattr(
        "optiland_gui.material_browser_panel.QFileDialog.getExistingDirectory",
        lambda *args, **kwargs: r"C:\WinLens Library 2002",
    )

    def _run_now(task, *, success_handler, error_title):  # noqa: ANN001
        success_handler(task())

    panel._run_task = _run_now  # type: ignore[method-assign]
    panel._import_winlens_materials()

    assert connector.import_calls == [r"C:\WinLens Library 2002"]


def test_material_browser_open_selected_material_file(monkeypatch, qapp) -> None:
    panel = MaterialBrowserPanel(_DummyConnector())
    opened_urls: list[str] = []
    monkeypatch.setattr(
        "optiland_gui.material_browser_panel.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url.toLocalFile()),
    )

    panel.results_table.selectRow(0)
    panel._open_selected_material_file()

    assert [value.replace("\\", "/") for value in opened_urls] == ["C:/materials/N-BK7.yml"]


def test_material_browser_delete_marked_imported_materials(monkeypatch, qapp) -> None:
    connector = _DummyConnector()
    panel = MaterialBrowserPanel(connector)
    panel.source_filter.setCurrentText("WinLens Import")
    panel.refresh()

    monkeypatch.setattr(
        "optiland_gui.material_browser_panel.QMessageBox.question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    panel._mark_filtered_results()
    panel._delete_marked_results()

    assert connector.deleted_material_ids == ["Hoya|ADC1|glass/winlens/hoya/ADC1.yml"]
