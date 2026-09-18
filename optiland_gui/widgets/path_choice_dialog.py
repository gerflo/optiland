"""A small dialog that asks which optical path of a system an action applies to.

Used when exporting one path as an Optiland JSON file and when opening a
sequential design into a system that already has several paths.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class PathChoiceDialog(QDialog):
    """Pick one path name from a list.

    Args:
        names: The path names to choose from (non-empty).
        default: The name selected initially (the first one if unknown).
        title: Window title.
        prompt: Text above the pull-down.
        accept_text: Label of the accept button.
        extra_text: Label of an optional third button (e.g. ``"New system"``);
            choosing it accepts the dialog with :attr:`extra_chosen` set.
        parent: Parent widget.
    """

    def __init__(
        self,
        names: list[str],
        default: str | None = None,
        *,
        title: str = "Choose optical path",
        prompt: str = "Optical path:",
        accept_text: str = "OK",
        extra_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        if not names:
            raise ValueError("PathChoiceDialog needs at least one path name.")
        self.setWindowTitle(title)
        self.extra_chosen = False

        layout = QVBoxLayout(self)
        label = QLabel(prompt)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.combo = QComboBox()
        self.combo.setObjectName("PathChoiceCombo")
        self.combo.addItems(list(names))
        index = names.index(default) if default in names else 0
        self.combo.setCurrentIndex(index)
        layout.addWidget(self.combo)

        buttons = QDialogButtonBox()
        self.accept_button = buttons.addButton(
            accept_text, QDialogButtonBox.ButtonRole.AcceptRole
        )
        self.extra_button: QPushButton | None = None
        if extra_text:
            self.extra_button = buttons.addButton(
                extra_text, QDialogButtonBox.ButtonRole.ActionRole
            )
            self.extra_button.clicked.connect(self._choose_extra)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.accept_button.setDefault(True)

    def _choose_extra(self) -> None:
        self.extra_chosen = True
        self.accept()

    @property
    def selected_name(self) -> str:
        """The path name currently selected."""
        return self.combo.currentText()

    @classmethod
    def choose(
        cls,
        parent: QWidget | None,
        names: list[str],
        default: str | None = None,
        **kwargs,
    ) -> tuple[str | None, bool]:
        """Run the dialog modally.

        Returns:
            ``(name, extra)``: the chosen path name, or ``None`` when
            cancelled; ``extra`` is true when the extra button was chosen
            (``name`` is then ``None``).
        """
        dialog = cls(names, default, parent=parent, **kwargs)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if not accepted:
            return None, False
        if dialog.extra_chosen:
            return None, True
        return dialog.selected_name, False
