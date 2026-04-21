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
from sequencer_gui.ui.device_row import (
    LABEL_COL_MIN_WIDTH_PX,
    STEP_COLUMN_WIDTH_PX,
    DeviceRowWidget,
    timeline_content_width_px,
)

_PAIR_V_SPACING_PX = 4
_TIME_AFTER_GAP_PX = 14
_STEP_GROUP_GAP_PX = 10
# Per timeline column: fixed step width + grid horizontal spacing (matches device_row).
_STEP_COL_MIN_PX = STEP_COLUMN_WIDTH_PX + 4
_GRID_H_SPACING_PX = 4
# Group box frame + layout margins (approx.) so horizontal scroll appears when needed.
_MATRIX_MIN_WIDTH_EXTRA_PX = 48


def min_width_for_timeline_cols(cols: int) -> int:
    """Outer width of the Sequencer group box (timeline + margins) for horizontal scroll."""
    return timeline_content_width_px(cols) + _MATRIX_MIN_WIDTH_EXTRA_PX


class ChannelMatrix(QGroupBox):
    """Time row, then one DeviceRowWidget per logical row (variable analog rows per object)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequencer", parent)
        self._state = state
        self._device_rows: list[DeviceRowWidget] = []
        self._delay_spins: list[QDoubleSpinBox] = []
        self._built_rows = -1
        self._built_cols = -1

        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(_PAIR_V_SPACING_PX)
        self._outer.setContentsMargins(8, 12, 8, 8)

        self._build_content(state.model)
        state.model_changed.connect(self._sync_from_model)

    def commit_row_labels_to_model(self) -> None:
        for dr in self._device_rows:
            self._state.set_row_label(dr.logical_row, dr.row_edit().text())

    def _apply_timeline_read_only(self) -> None:
        ro = self._state.timeline_read_only
        for sp in self._delay_spins:
            sp.setEnabled(not ro)

    def _make_delay_handler(self, col: int):
        def on_value(value: float) -> None:
            self._state.set_delay_us(col, value)

        return on_value

    def _clear_content(self) -> None:
        self._device_rows.clear()
        self._delay_spins.clear()
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _build_content(self, model: SequenceModel) -> None:
        self._clear_content()
        self._built_rows = model.rows
        self._built_cols = model.cols

        time_row = QWidget()
        grid = QGridLayout(time_row)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(_GRID_H_SPACING_PX)
        grid.setVerticalSpacing(_PAIR_V_SPACING_PX)
        grid.setColumnMinimumWidth(0, LABEL_COL_MIN_WIDTH_PX)
        for col in range(1, model.cols + 1):
            grid.setColumnMinimumWidth(col, STEP_COLUMN_WIDTH_PX)
            grid.setColumnStretch(col, 0)
        grid.setColumnStretch(0, 0)

        corner = QLabel("Time")
        corner.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        corner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid.addWidget(corner, 0, 0)

        for c in range(model.cols):
            spin = QDoubleSpinBox()
            spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
            spin.setRange(0.0, 1e9)
            spin.setDecimals(3)
            spin.setSingleStep(1.0)
            spin.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            spin.setValue(model.delay_us(c, 0.0))
            spin.valueChanged.connect(self._make_delay_handler(c))
            self._delay_spins.append(spin)
            spin.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            grid.addWidget(spin, 0, c + 1)

        time_gap = QWidget()
        time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        time_gap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        grid.addWidget(time_gap, 1, 0, 1, model.cols + 1)

        tw = timeline_content_width_px(model.cols)
        time_row.setFixedWidth(tw)
        time_row.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._outer.addWidget(time_row, 0, Qt.AlignLeft)

        for r in range(model.rows):
            dr = DeviceRowWidget(r, state=self._state)
            self._device_rows.append(dr)
            self._outer.addWidget(dr, 0, Qt.AlignLeft)
            if r < model.rows - 1:
                gap = QWidget()
                gap.setMinimumHeight(_STEP_GROUP_GAP_PX)
                gap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
                self._outer.addWidget(gap)

        self._outer.addStretch(1)
        self._apply_timeline_read_only()
        self.setFixedWidth(min_width_for_timeline_cols(model.cols))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.updateGeometry()

    def _sync_from_model(self, model: SequenceModel) -> None:
        if model.rows != self._built_rows or model.cols != self._built_cols:
            self._build_content(model)
            return
        for c, spin in enumerate(self._delay_spins):
            if c >= model.cols:
                break
            v = model.delay_us(c, 0.0)
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
        for dr in self._device_rows:
            dr.sync_from_model(model)
        self._apply_timeline_read_only()
