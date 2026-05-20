from __future__ import annotations

from PyQt5.QtCore import QByteArray, Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QGuiApplication, QShowEvent
from PyQt5.QtWidgets import QHBoxLayout, QMainWindow, QTabBar, QVBoxLayout, QWidget

from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.persistence import load_window_geometry, save_row_labels, save_window_geometry
from sequencer_gui.ui.artiq_panel import ArtiqPanel
from sequencer_gui.ui.block_strip import BlockStripWidget
from sequencer_gui.ui.channel_matrix import ChannelMatrix
from sequencer_gui.ui.scan_panel import ScanPanel
from sequencer_gui.ui.sequence_toolbar import SequenceToolbar


class MainWindow(QMainWindow):
    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._update_window_title(state.sequence_name)
        state.sequence_name_changed.connect(self._update_window_title)
        self._geometry_restore_done = False
        self.resize(560, 820)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        top_row = QWidget()
        top_row_layout = QHBoxLayout(top_row)
        top_row_layout.setContentsMargins(0, 0, 0, 0)
        top_row_layout.setSpacing(10)
        toolbar = SequenceToolbar(state)
        top_row_layout.addWidget(toolbar, 0, Qt.AlignLeft)
        self._artiq_panel = ArtiqPanel()
        top_row_layout.addWidget(self._artiq_panel, 0)
        self._scan_panel = ScanPanel(state)
        # Stretch so Scan (and its parameter cards) uses width to the right of Sequence, not a few pixels.
        top_row_layout.addWidget(self._scan_panel, 1)
        layout.addWidget(top_row, 0)

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

        self._run_poll = QTimer(self)
        self._run_poll.timeout.connect(state.poll_host_run_sequence)
        self._run_poll.start(300)

        self._sync_tab_titles()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._geometry_restore_done:
            return
        self._geometry_restore_done = True
        raw = load_window_geometry()
        if raw and self.restoreGeometry(QByteArray(raw)):
            self._ensure_on_screen()

    def _ensure_on_screen(self) -> None:
        frame = self.frameGeometry()
        screen = QGuiApplication.screenAt(frame.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        if avail.contains(frame):
            return
        x = frame.x()
        y = frame.y()
        w = frame.width()
        h = frame.height()
        if x + w > avail.right():
            x = avail.right() - w
        if y + h > avail.bottom():
            y = avail.bottom() - h
        if x < avail.left():
            x = avail.left()
        if y < avail.top():
            y = avail.top()
        self.move(x, y)
        frame = self.frameGeometry()
        if frame.width() > avail.width():
            self.resize(avail.width() - 8, frame.height())
        frame = self.frameGeometry()
        if frame.height() > avail.height():
            self.resize(self.width(), avail.height() - 8)

    def _sync_tab_titles(self) -> None:
        self._tab_bar.blockSignals(True)
        while self._tab_bar.count() > 0:
            self._tab_bar.removeTab(0)
        doc = self._state.document
        self._tab_bar.addTab("Complete")
        for b in doc.blocks:
            self._tab_bar.addTab(b.name)
        at = self._state.active_tab_index
        n = len(doc.blocks)
        if at == COMPLETE_TAB_INDEX:
            self._tab_bar.setCurrentIndex(0)
        else:
            self._tab_bar.setCurrentIndex(min(at + 1, n))
        self._tab_bar.blockSignals(False)

    def _sync_tab_selection(self, _active: int) -> None:
        self._tab_bar.blockSignals(True)
        doc = self._state.document
        n = len(doc.blocks)
        at = self._state.active_tab_index
        if at == COMPLETE_TAB_INDEX:
            self._tab_bar.setCurrentIndex(0)
        else:
            self._tab_bar.setCurrentIndex(min(at + 1, n))
        self._tab_bar.blockSignals(False)

    def _on_tab_changed(self, index: int) -> None:
        self._matrix.reset_horizontal_scroll()
        if index == 0:
            self._state.set_active_tab(COMPLETE_TAB_INDEX)
        else:
            self._state.set_active_tab(index - 1)

    def _update_window_title(self, name: str) -> None:
        self.setWindowTitle(f"{name} — ArtiQ experimental sequencer")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._matrix.commit_row_labels_to_model()
        self._matrix.commit_col_labels_to_model()
        save_row_labels(self._state.document.row_labels)
        save_window_geometry(bytes(self.saveGeometry()))
        super().closeEvent(event)
