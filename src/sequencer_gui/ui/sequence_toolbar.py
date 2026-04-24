from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.persistence import save_last_sequence_path
from sequencer_gui.sequence_io import (
    SequenceFileError,
    load_sequence,
    save_sequence,
    validate_document_for_ui,
)


class SequenceToolbar(QGroupBox):
    """Name, save, and load sequence files (JSON)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequence", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.addWidget(QLabel("Name:"))
        self._name = QLineEdit(state.sequence_name)
        self._name.setPlaceholderText("Sequence name")
        self._name.setMinimumWidth(200)
        self._name.setMaximumWidth(360)
        self._name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._name.editingFinished.connect(self._on_name_edited)
        row.addWidget(self._name, 0)

        btn_save = QPushButton("Save…")
        btn_save.clicked.connect(self._on_save)
        row.addWidget(btn_save)

        btn_load = QPushButton("Load…")
        btn_load.clicked.connect(self._on_load)
        row.addWidget(btn_load)

        state.sequence_name_changed.connect(self._on_sequence_name_changed)

    def _on_sequence_name_changed(self, name: str) -> None:
        if self._name.text() != name:
            self._name.blockSignals(True)
            self._name.setText(name)
            self._name.blockSignals(False)

    def _on_name_edited(self) -> None:
        self._state.set_sequence_name(self._name.text())

    def _on_save(self) -> None:
        self._state.set_sequence_name(self._name.text())
        name = self._state.sequence_name.strip() or "Untitled"
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in name)[:80]
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save sequence",
            str(Path.home() / f"{safe}.json"),
            "JSON sequence (*.json);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            save_sequence(path_str, name, self._state.document)
            save_last_sequence_path(str(Path(path_str).resolve()))
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))

    def _on_load(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Load sequence",
            str(Path.home()),
            "JSON sequence (*.json);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            _, document = load_sequence(path_str)
        except SequenceFileError as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return
        except OSError as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return

        err = validate_document_for_ui(document)
        if err is not None:
            QMessageBox.warning(self, "Load failed", err)
            return

        self._state.set_sequence_name(Path(path_str).name)
        self._state.replace_document(document, active_tab=0)
