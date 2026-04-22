"""Tabbed container for stock-lens and material catalog tools."""

from __future__ import annotations

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class CatalogsPanel(QWidget):
    """Host the catalog and material browsers in a shared tabbed panel."""

    def __init__(
        self,
        catalog_browser: QWidget,
        material_browser: QWidget,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.catalog_browser = catalog_browser
        self.material_browser = material_browser

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.catalog_browser, "Stock Parts Catalog")
        self.tab_widget.addTab(self.material_browser, "Material Database")
        layout.addWidget(self.tab_widget)

    def show_catalog_tab(self) -> None:
        """Activate the stock-lens catalog tab."""
        self.tab_widget.setCurrentWidget(self.catalog_browser)

    def show_material_tab(self) -> None:
        """Activate the material database tab."""
        self.tab_widget.setCurrentWidget(self.material_browser)
