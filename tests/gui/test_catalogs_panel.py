from __future__ import annotations

from PySide6.QtWidgets import QLabel
from PySide6.QtWidgets import QWidget

from optiland_gui.catalogs_panel import CatalogsPanel


def test_catalogs_panel_hosts_catalog_and_material_tabs(qapp) -> None:
    panel = CatalogsPanel(QLabel("catalog"), QLabel("material"))

    assert panel.tab_widget.count() == 2
    assert panel.tab_widget.tabText(0) == "Stock Parts Catalog"
    assert panel.tab_widget.tabText(1) == "Material Database"

    panel.show_material_tab()
    assert panel.tab_widget.currentIndex() == 1

    panel.show_catalog_tab()
    assert panel.tab_widget.currentIndex() == 0


def test_catalogs_panel_forwards_theme_updates(qapp) -> None:
    class _Child(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.calls: list[str] = []

        def update_theme(self, theme_name: str) -> None:
            self.calls.append(theme_name)

    catalog = _Child()
    material = _Child()
    panel = CatalogsPanel(catalog, material)

    panel.update_theme("light")

    assert catalog.calls == ["light"]
    assert material.calls == ["light"]
