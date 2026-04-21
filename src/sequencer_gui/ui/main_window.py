from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QMainWindow, QTabBar, QVBoxLayout, QWidget

from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.persistence import save_row_labels
from sequencer_gui.ui.block_strip import BlockStripWidget
from sequencer_gui.ui.channel_matrix import ChannelMatrix
from sequencer_gui.ui.sequence_toolbar import SequenceToolbar


class MainWindow(QMainWindow):
    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._update_window_title(state.sequence_name)
        state.sequence_name_changed.connect(self._update_window_title)
        self.resize(560, 820)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        toolbar = SequenceToolbar(state)
        layout.addWidget(toolbar, 0, Qt.AlignLeft | Qt.AlignTop)

        self._strip = BlockStripWidget(state)
        layout.addWidget(self._strip, 0)

        self._tab_bar = QTabBar()
        self._tab_bar.setExpanding(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tab_bar, 0)

        self._matrix = ChannelMatrix(state)
        layout.addWidget(self._matrix, 1)

        state.document_changed.connect(self._sync_tab_titles)
        state.active_tab_changed.connect(self._sync_tab_selection)

        self._sync_tab_titles()

    def _sync_tab_titles(self) -> None:
        self._tab_bar.blockSignals(True)
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        doc = self._state.document
        for b in doc.blocks:
            self._tab_bar.addTab(b.name)
        self._tab_bar.addTab("Complete")
        at = self._state.active_tab_index
        n = len(doc.blocks)
        if at == COMPLETE_TAB_INDEX:
            self._tab_bar.setCurrentIndex(n)
        else:
            self._tab_bar.setCurrentIndex(min(at, n - 1))
        self._tab_bar.blockSignals(False)

    def _sync_tab_selection(self, _active: int) -> None:
        self._tab_bar.blockSignals(True)
        doc = self._state.document
        n = len(doc.blocks)
        at = self._state.active_tab_index
        if at == COMPLETE_TAB_INDEX:
            self._tab_bar.setCurrentIndex(n)
        else:
            self._tab_bar.setCurrentIndex(min(at, n - 1))
        self._tab_bar.blockSignals(False)

    def _on_tab_changed(self, index: int) -> None:
        n = len(self._state.document.blocks)
        if index == n:
            self._state.set_active_tab(COMPLETE_TAB_INDEX)
        else:
            self._state.set_active_tab(index)

    def _update_window_title(self, name: str) -> None:
        self.setWindowTitle(f"{name} — ArtiQ experimental sequencer")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._matrix.commit_row_labels_to_model()
        save_row_labels(self._state.document.row_labels)
        super().closeEvent(event)
