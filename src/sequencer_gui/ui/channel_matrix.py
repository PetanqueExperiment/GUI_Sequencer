from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QLabel,
    QScrollArea,
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
from sequencer_gui.ui.value_input import CommitFloatLineEdit, parse_float_field

_PAIR_V_SPACING_PX = 4
_TIME_AFTER_GAP_PX = 14
_STEP_GROUP_GAP_PX = 10
_GRID_H_SPACING_PX = 4
_MATRIX_MIN_WIDTH_EXTRA_PX = 48

_DELAY_MIN_US = 0.0
_DELAY_MAX_US = 1e9
_DELAY_DECIMALS = 3


def _format_delay_us(v: float) -> str:
    return format(v, f".{_DELAY_DECIMALS}f")


def min_width_for_timeline_cols(cols: int) -> int:
    """Outer width of the Sequencer group box (timeline + margins) for horizontal scroll."""
    return timeline_content_width_px(cols) + _MATRIX_MIN_WIDTH_EXTRA_PX


class ChannelMatrix(QGroupBox):
    """Time row, then one DeviceRowWidget per logical row (variable analog rows per object)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequencer", parent)
        self._state = state
        self._device_rows: list[DeviceRowWidget] = []
        self._delay_edits: list[CommitFloatLineEdit] = []
        self._built_rows = -1
        self._built_cols = -1
        self._header_scroll: QScrollArea | None = None
        self._body_scroll: QScrollArea | None = None
        self._h_scroll_syncing = False

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
        for ed in self._delay_edits:
            ed.setEnabled(not ro)

    def _on_delay_return_pressed(self, col: int) -> None:
        line = self._delay_edits[col]
        model = self._state.model

        def revert() -> None:
            line.set_committed_display(_format_delay_us(model.delay_us(col, 0.0)))

        s = line.text().strip()
        if not s:
            revert()
            return
        parsed = parse_float_field(s)
        if parsed is None:
            revert()
            return
        x = max(_DELAY_MIN_US, min(_DELAY_MAX_US, parsed))
        self._state.set_delay_us(col, x)
        line.set_committed_display(_format_delay_us(self._state.model.delay_us(col, 0.0)))

    def _clear_content(self) -> None:
        self._device_rows.clear()
        self._delay_edits.clear()
        self._header_scroll = None
        self._body_scroll = None
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _wire_horizontal_scroll_sync(self) -> None:
        assert self._header_scroll is not None and self._body_scroll is not None
        h_head = self._header_scroll.horizontalScrollBar()
        h_body = self._body_scroll.horizontalScrollBar()

        def on_head(v: int) -> None:
            if self._h_scroll_syncing:
                return
            self._h_scroll_syncing = True
            h_body.setValue(v)
            self._h_scroll_syncing = False

        def on_body(v: int) -> None:
            if self._h_scroll_syncing:
                return
            self._h_scroll_syncing = True
            h_head.setValue(v)
            self._h_scroll_syncing = False

        h_head.valueChanged.connect(on_head)
        h_body.valueChanged.connect(on_body)

    def reset_horizontal_scroll(self) -> None:
        if self._header_scroll is not None:
            self._header_scroll.horizontalScrollBar().setValue(0)
        if self._body_scroll is not None:
            self._body_scroll.horizontalScrollBar().setValue(0)

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

        corner = QLabel("Time (µs)")
        corner.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        corner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        grid.addWidget(corner, 0, 0)

        for c in range(model.cols):
            ed = CommitFloatLineEdit(_DELAY_MIN_US, _DELAY_MAX_US, _DELAY_DECIMALS)
            ed.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            ed.set_committed_display(_format_delay_us(model.delay_us(c, 0.0)))

            def make_return(cc: int):
                def on_return() -> None:
                    self._on_delay_return_pressed(cc)

                return on_return

            ed.set_on_return(make_return(c))
            self._delay_edits.append(ed)
            ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            grid.addWidget(ed, 0, c + 1)

        time_gap = QWidget()
        time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        time_gap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        grid.addWidget(time_gap, 1, 0, 1, model.cols + 1)

        tw = timeline_content_width_px(model.cols)
        time_row.setFixedWidth(tw)
        time_row.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        time_row.adjustSize()
        header_h = max(time_row.sizeHint().height(), time_row.height())

        self._header_scroll = QScrollArea()
        self._header_scroll.setFrameShape(QFrame.NoFrame)
        self._header_scroll.setWidgetResizable(False)
        self._header_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._header_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._header_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._header_scroll.setWidget(time_row)
        self._header_scroll.setFixedHeight(header_h)
        self._header_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        body_host = QWidget()
        body_lay = QVBoxLayout(body_host)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(_PAIR_V_SPACING_PX)

        for r in range(model.rows):
            dr = DeviceRowWidget(r, state=self._state)
            self._device_rows.append(dr)
            body_lay.addWidget(dr, 0, Qt.AlignLeft)
            if r < model.rows - 1:
                gap = QWidget()
                gap.setMinimumHeight(_STEP_GROUP_GAP_PX)
                gap.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                body_lay.addWidget(gap)

        body_host.setFixedWidth(tw)
        body_host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._body_scroll = QScrollArea()
        self._body_scroll.setFrameShape(QFrame.NoFrame)
        self._body_scroll.setWidgetResizable(False)
        self._body_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._body_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._body_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._body_scroll.setWidget(body_host)
        self._body_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        self._outer.addWidget(self._header_scroll)
        self._outer.addWidget(self._body_scroll, 1)
        self._wire_horizontal_scroll_sync()

        self._apply_timeline_read_only()
        self.setFixedWidth(min_width_for_timeline_cols(model.cols))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self.updateGeometry()

    def _sync_from_model(self, model: SequenceModel) -> None:
        if model.rows != self._built_rows or model.cols != self._built_cols:
            self._build_content(model)
            return
        for c, ed in enumerate(self._delay_edits):
            if c >= model.cols:
                break
            v = model.delay_us(c, 0.0)
            ed.set_committed_display(_format_delay_us(v))
        for dr in self._device_rows:
            dr.sync_from_model(model)
        self._apply_timeline_read_only()
