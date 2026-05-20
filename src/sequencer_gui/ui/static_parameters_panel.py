from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.software_objects import iter_static_objects

_PANEL_EXPANDED_WIDTH_PX = 260
_COLLAPSED_STRIP_WIDTH_PX = 28


class StaticParametersPanel(QWidget):
    """Foldable side panel for shot-to-shot (static) parameter values."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._expanded = True

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._toggle = QPushButton("\u25c0")
        self._toggle.setFixedWidth(_COLLAPSED_STRIP_WIDTH_PX)
        self._toggle.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._toggle.setToolTip("Collapse static parameters panel")
        self._toggle.setFlat(True)
        self._toggle.clicked.connect(self._on_toggle)
        outer.addWidget(self._toggle, 0)

        self._content = QGroupBox("Static parameters")
        self._content.setToolTip(
            "Values applied between shots (not per timestep in the sequence matrix)."
        )
        self._content.setMinimumWidth(_PANEL_EXPANDED_WIDTH_PX)
        self._content.setMaximumWidth(_PANEL_EXPANDED_WIDTH_PX)
        self._content.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(10, 12, 10, 10)
        content_layout.setSpacing(8)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(10)
        self._scroll.setWidget(self._body)
        content_layout.addWidget(self._scroll, 1)

        outer.addWidget(self._content, 0)

        state.document_changed.connect(self._rebuild)
        state.row_labels_changed.connect(self._rebuild)
        self._rebuild()

    def _on_toggle(self) -> None:
        self._expanded = not self._expanded
        self._apply_expanded_state()

    def _apply_expanded_state(self) -> None:
        self._content.setVisible(self._expanded)
        if self._expanded:
            self._toggle.setText("\u25c0")
            self._toggle.setToolTip("Collapse static parameters panel")
            self.setFixedWidth(_PANEL_EXPANDED_WIDTH_PX + _COLLAPSED_STRIP_WIDTH_PX)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        else:
            self._toggle.setText("\u25b6")
            self._toggle.setToolTip("Expand static parameters panel")
            self.setFixedWidth(_COLLAPSED_STRIP_WIDTH_PX)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def _rebuild(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        static_objects = iter_static_objects()
        if not static_objects:
            hint = QLabel(
                "No static device types yet.\n\n"
                "Add software objects under\n"
                "software_objects/static/ to edit\n"
                "between-shot parameters here."
            )
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignTop)
            hint.setStyleSheet("color: #616161;")
            self._body_layout.addWidget(hint)
        else:
            for obj in static_objects:
                title = QLabel(obj.display_name)
                title.setStyleSheet("font-weight: 600;")
                self._body_layout.addWidget(title)
                for spec in obj.analog_parameters:
                    row = QHBoxLayout()
                    row.setSpacing(6)
                    row.addWidget(QLabel(spec.label))
                    row.addStretch(1)
                    self._body_layout.addLayout(row)

        self._body_layout.addStretch(1)
        self._body.adjustSize()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_expanded_state()
