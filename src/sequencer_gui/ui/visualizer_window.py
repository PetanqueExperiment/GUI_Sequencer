from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.domain.document import complete_cycle_rate_hz, complete_timeline_duration_us
from sequencer_gui.sequence_io import SequenceFileError, load_sequence, validate_document_for_ui
from sequencer_gui.ui.block_strip import BlockStripWidget
from sequencer_gui.ui.channel_matrix import ChannelMatrix
from sequencer_gui.ui.static_parameters_panel import StaticParametersPanel


class VisualizerWindow(QMainWindow):
    """Read-only browser for saved sequence JSON files (no HERO / run / scan)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        if not state.is_read_only:
            raise ValueError("VisualizerWindow requires SequenceAppState(read_only=True)")
        super().__init__(parent)
        self._state = state
        self._path: Path | None = None
        self.resize(960, 820)
        self._update_window_title()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        layout.addWidget(self._build_header(), 0)

        self._strip = BlockStripWidget(state)
        layout.addWidget(self._strip, 0)

        self._tab_bar = QTabBar()
        self._tab_bar.setExpanding(False)
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tab_bar, 0)

        matrix_row = QWidget()
        matrix_row_layout = QHBoxLayout(matrix_row)
        matrix_row_layout.setContentsMargins(0, 0, 0, 0)
        matrix_row_layout.setSpacing(6)
        self._matrix = ChannelMatrix(state)
        matrix_row_layout.addWidget(self._matrix, 1)
        self._static_panel = StaticParametersPanel(state)
        matrix_row_layout.addWidget(self._static_panel, 0)
        layout.addWidget(matrix_row, 1)

        state.document_changed.connect(self._sync_tab_titles)
        state.document_changed.connect(self._refresh_timing)
        state.delays_changed.connect(self._refresh_timing)
        state.active_tab_changed.connect(self._sync_tab_selection)
        state.sequence_name_changed.connect(lambda _n: self._update_window_title())

        self._sync_tab_titles()
        self._refresh_timing()

    def _build_header(self) -> QWidget:
        box = QGroupBox("Sequence viewer")
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        file_row = QHBoxLayout()
        file_row.setSpacing(8)
        file_row.addWidget(QLabel("File:"))
        self._file_label = QLabel(self._state.sequence_name or "(no file loaded)")
        self._file_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        file_row.addWidget(self._file_label, 1)
        btn_open = QPushButton("Open…")
        btn_open.clicked.connect(self._on_open)
        file_row.addWidget(btn_open, 0)
        outer.addLayout(file_row)

        timing_row = QHBoxLayout()
        timing_row.setSpacing(8)
        timing_row.addWidget(QLabel("Duration:"))
        self._duration = QLabel()
        self._duration.setToolTip("Total time of the Complete sequence (enabled blocks only).")
        timing_row.addWidget(self._duration)
        timing_row.addSpacing(12)
        timing_row.addWidget(QLabel("Cycle rate:"))
        self._cycle_rate = QLabel()
        self._cycle_rate.setToolTip("Expected experiment rate: 1 / duration (enabled blocks only).")
        timing_row.addWidget(self._cycle_rate)
        timing_row.addStretch(1)
        hint = QLabel("Read-only")
        hint.setStyleSheet("color: #616161;")
        timing_row.addWidget(hint)
        outer.addLayout(timing_row)
        return box

    def load_path(self, path: Path | str) -> bool:
        """Load a sequence file. Returns False if the file could not be opened."""
        p = Path(path)
        try:
            name, document = load_sequence(p)
        except (OSError, SequenceFileError) as e:
            QMessageBox.warning(self, "Open sequence", str(e))
            return False
        err = validate_document_for_ui(document)
        if err is not None:
            QMessageBox.warning(self, "Open sequence", err)
            return False
        resolved = str(p.resolve())
        self._path = p.resolve()
        self._state.replace_document(document, active_tab=COMPLETE_TAB_INDEX)
        self._state.set_sequence_name(resolved)
        self._file_label.setText(resolved if resolved else name)
        self._matrix.reset_horizontal_scroll()
        self._update_window_title()
        return True

    def _on_open(self) -> None:
        start = str(self._path.parent) if self._path is not None else str(Path.home())
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Open sequence",
            start,
            "Sequence JSON (*.json);;All files (*.*)",
        )
        if path_str:
            self.load_path(path_str)

    def _refresh_timing(self) -> None:
        doc = self._state.document
        ms = complete_timeline_duration_us(doc) / 1000.0
        self._duration.setText(f"{ms:.0f} ms")
        hz = complete_cycle_rate_hz(doc)
        self._cycle_rate.setText("—" if hz is None else f"{hz:.1f} Hz")

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

    def _update_window_title(self) -> None:
        name = self._state.sequence_name or "Sequence"
        short = Path(name).name if name not in {"", "Untitled"} else name
        self.setWindowTitle(f"{short} — Sequence viewer")
