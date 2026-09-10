"""Dialog offering corrections for design-file validation findings.

Shown by the main window when :func:`~optiland_gui.design_validation.
validate_design` reports findings while opening a file. Fixable findings get
a checkbox (pre-checked according to ``apply_by_default``); accepting applies
the selected fixes to the in-memory design before it is loaded.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

if TYPE_CHECKING:
    from ..design_validation import ValidationFinding

_SEVERITY_LABELS = {"error": "Error", "warning": "Warning", "info": "Info"}
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class DesignValidationDialog(QDialog):
    """List validation findings and let the user pick which fixes to apply."""

    def __init__(
        self, findings: list[ValidationFinding], filepath: str, parent=None
    ) -> None:  # noqa: ANN001
        super().__init__(parent)
        self._findings = sorted(
            findings,
            key=lambda f: (_SEVERITY_ORDER.get(f.severity, 3), f.surface_index or 0),
        )
        self._checkboxes: dict[int, QCheckBox] = {}
        self.selected_findings: list[ValidationFinding] = []

        self.setWindowTitle("Design File Check")
        self.setObjectName("DesignValidationDialog")
        self.setMinimumSize(760, 360)

        layout = QVBoxLayout(self)
        intro = QLabel(
            f"<b>{os.path.basename(filepath)}</b> contains "
            f"{len(self._findings)} finding(s). Selected corrections are "
            "applied to the loaded design (the file on disk is only changed "
            "when you save)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        table = QTableWidget(len(self._findings), 4)
        table.setObjectName("DesignValidationTable")
        table.setHorizontalHeaderLabels(["Apply", "Severity", "Finding", "Correction"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setWordWrap(True)
        for row, finding in enumerate(self._findings):
            if finding.fixable:
                checkbox = QCheckBox()
                checkbox.setChecked(finding.apply_by_default)
                self._checkboxes[row] = checkbox
                table.setCellWidget(row, 0, _center(checkbox))
            else:
                table.setItem(row, 0, QTableWidgetItem("—"))
            table.setItem(
                row, 1, QTableWidgetItem(_SEVERITY_LABELS.get(finding.severity, "?"))
            )
            table.setItem(row, 2, QTableWidgetItem(finding.message))
            table.setItem(row, 3, QTableWidgetItem(finding.fix_description or ""))
        table.setColumnWidth(0, 50)
        table.setColumnWidth(1, 70)
        table.setColumnWidth(2, 380)
        table.horizontalHeader().setStretchLastSection(True)
        table.resizeRowsToContents()
        layout.addWidget(table)
        self._table = table

        buttons = QDialogButtonBox()
        self._apply_button = QPushButton("Apply Selected Corrections && Load")
        self._apply_button.setDefault(True)
        buttons.addButton(self._apply_button, QDialogButtonBox.ButtonRole.AcceptRole)
        load_raw = QPushButton("Load Unchanged")
        buttons.addButton(load_raw, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def checked_findings(self) -> list[ValidationFinding]:
        """Findings whose checkbox is currently checked."""
        return [
            self._findings[row]
            for row, checkbox in self._checkboxes.items()
            if checkbox.isChecked()
        ]

    def accept(self) -> None:  # noqa: D102 - QDialog override
        self.selected_findings = self.checked_findings()
        super().accept()


def _center(widget):  # noqa: ANN001
    """Wrap a widget so it renders centered inside a table cell."""
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    container = QWidget()
    box = QHBoxLayout(container)
    box.setContentsMargins(0, 0, 0, 0)
    box.setAlignment(Qt.AlignmentFlag.AlignCenter)
    box.addWidget(widget)
    return container
