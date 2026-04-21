from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QMainWindow, QVBoxLayout, QWidget

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.persistence import save_row_labels
from sequencer_gui.ui.channel_matrix import ChannelMatrix
from sequencer_gui.ui.sequence_toolbar import SequenceToolbar


class MainWindow(QMainWindow):
    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._update_window_title(state.sequence_name)
        state.sequence_name_changed.connect(self._update_window_title)
        self.resize(520, 780)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        toolbar = SequenceToolbar(state)
        layout.addWidget(toolbar, 0, Qt.AlignLeft | Qt.AlignTop)
        self._matrix = ChannelMatrix(state)
        layout.addWidget(self._matrix, 1)

    def _update_window_title(self, name: str) -> None:
        self.setWindowTitle(f"{name} — ArtiQ experimental sequencer")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._matrix.commit_row_labels_to_model()
        save_row_labels(self._state.model.row_labels)
        super().closeEvent(event)
