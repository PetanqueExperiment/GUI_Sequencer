from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.ui.device_row import LABEL_COL_MIN_WIDTH_PX, DeviceRowWidget

_PAIR_V_SPACING_PX = 4
_TIME_AFTER_GAP_PX = 14
_STEP_GROUP_GAP_PX = 10


class ChannelMatrix(QGroupBox):
    """Time row, then one DeviceRowWidget per logical row (variable analog rows per object)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequencer", parent)
        self._state = state
        self._device_rows: list[DeviceRowWidget] = []
        self._delay_spins: list[QDoubleSpinBox] = []

        outer = QVBoxLayout(self)
        outer.setSpacing(_PAIR_V_SPACING_PX)
        outer.setContentsMargins(8, 12, 8, 8)

        time_row = QWidget()
        grid = QGridLayout(time_row)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(_PAIR_V_SPACING_PX)
        grid.setColumnMinimumWidth(0, LABEL_COL_MIN_WIDTH_PX)

        corner = QLabel("Time")
        corner.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner.setMinimumWidth(28)
        grid.addWidget(corner, 0, 0)

        m = state.model
        for c in range(m.cols):
            spin = QDoubleSpinBox()
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setRange(0.0, 1e9)
            spin.setDecimals(3)
            spin.setSingleStep(1.0)
            spin.setMinimumWidth(72)
            spin.setValue(m.delay_us(c, 0.0))
            spin.valueChanged.connect(self._make_delay_handler(c))
            self._delay_spins.append(spin)
            spin.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            grid.addWidget(spin, 0, c + 1)

        time_gap = QWidget()
        time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        time_gap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        grid.addWidget(time_gap, 1, 0, 1, m.cols + 1)

        corner.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        outer.addWidget(time_row)

        for r in range(m.rows):
            dr = DeviceRowWidget(r, state)
            self._device_rows.append(dr)
            outer.addWidget(dr)
            if r < m.rows - 1:
                gap = QWidget()
                gap.setMinimumHeight(_STEP_GROUP_GAP_PX)
                gap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                outer.addWidget(gap)

        outer.addStretch(1)

        state.model_changed.connect(self._sync_from_model)

    def commit_row_labels_to_model(self) -> None:
        for dr in self._device_rows:
            self._state.set_row_label(dr.logical_row, dr.row_edit().text())

    def _make_delay_handler(self, col: int):
        def on_value(value: float) -> None:
            self._state.set_delay_us(col, value)

        return on_value

    def _sync_from_model(self, model: SequenceModel) -> None:
        for c, spin in enumerate(self._delay_spins):
            if c >= model.cols:
                break
            v = model.delay_us(c, 0.0)
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        for dr in self._device_rows:
            dr.sync_from_model(model)
