from __future__ import annotations

from PySide6.QtWidgets import QLabel

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
