from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.ui.device_row import (
    STEP_COLUMN_WIDTH_PX,
    DeviceRowWidget,
    timeline_steps_width_px,
)
from sequencer_gui.ui.row_software_selector import LABEL_COL_MIN_WIDTH_PX
from sequencer_gui.ui.value_input import CommitFloatLineEdit, parse_float_field

_PAIR_V_SPACING_PX = 4
_TIME_AFTER_GAP_PX = 14
_STEP_GROUP_GAP_PX = 10
_GRID_H_SPACING_PX = 4
_MATRIX_MIN_WIDTH_EXTRA_PX = 48
# Fallback when layout has not resolved line-edit height yet.
_TIME_ROW_MIN_HEIGHT_PX = 28

_DELAY_MIN_US = 0.0
_DELAY_MAX_US = 1e9
_DELAY_DECIMALS = 3


def _format_delay_us(v: float) -> str:
    return format(v, f".{_DELAY_DECIMALS}f")


def min_width_for_timeline_cols(_cols: int) -> int:
    """Minimum outer width of the Sequencer group (label column + at least one step)."""
    return (
        LABEL_COL_MIN_WIDTH_PX
        + _GRID_H_SPACING_PX
        + STEP_COLUMN_WIDTH_PX
        + _MATRIX_MIN_WIDTH_EXTRA_PX
    )


def _make_scroll_panel(
    content: QWidget,
    *,
    h_policy: Qt.ScrollBarPolicy,
    v_policy: Qt.ScrollBarPolicy,
) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidgetResizable(False)
    scroll.setHorizontalScrollBarPolicy(h_policy)
    scroll.setVerticalScrollBarPolicy(v_policy)
    scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    scroll.setWidget(content)
    return scroll


def _link_scroll_bar(master: QScrollBar, slave: QScrollBar) -> None:
    """Mirror master scrollbar position onto slave (one-way)."""

    def on_master(value: int) -> None:
        if slave.value() != value:
            slave.setValue(value)

    master.valueChanged.connect(on_master)


class _TimelinePanel(QScrollArea):
    """Pinned delay row in a scroll area (horizontal bar hidden; follows matrix scroll)."""

    def __init__(self, time_steps: QWidget, row_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setWidget(time_steps)
        self.setFixedHeight(row_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_scroll_x(self, px: int) -> None:
        self.horizontalScrollBar().setValue(max(0, px))

    def refresh_range(self, content_w: int) -> None:
        viewport_w = max(self.viewport().width(), 1)
        bar = self.horizontalScrollBar()
        bar.setRange(0, max(0, content_w - viewport_w))
        bar.setPageStep(viewport_w)
        bar.setSingleStep(STEP_COLUMN_WIDTH_PX + _GRID_H_SPACING_PX)


class ChannelMatrix(QGroupBox):
    """Labels panel + timeline strip + matrix panel (matrix owns scrollbars)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequencer", parent)
        self._state = state
        self._device_rows: list[DeviceRowWidget] = []
        self._delay_edits: list[CommitFloatLineEdit] = []
        self._built_rows = -1
        self._built_cols = -1
        self._built_tab = -2
        self._corner_block: QWidget | None = None
        self._labels_panel: QScrollArea | None = None
        self._timeline_panel: _TimelinePanel | None = None
        self._time_row_height_px = _TIME_ROW_MIN_HEIGHT_PX
        self._matrix_panel: QScrollArea | None = None
        self._time_steps: QWidget | None = None
        self._steps_host: QWidget | None = None
        self._steps_content_width_px = 0

        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(_PAIR_V_SPACING_PX)
        self._outer.setContentsMargins(8, 12, 8, 8)

        self._build_content(self._state.model)
        state.model_changed.connect(self._sync_from_model)
        state.active_tab_changed.connect(self._on_active_tab_changed)

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
        self._corner_block = None
        self._labels_panel = None
        self._timeline_panel = None
        self._time_row_height_px = _TIME_ROW_MIN_HEIGHT_PX
        self._matrix_panel = None
        self._time_steps = None
        self._steps_host = None
        self._steps_content_width_px = 0
        while self._outer.count():
            item = self._outer.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _refresh_horizontal_ranges(self) -> None:
        content_w = self._steps_content_width_px
        if content_w < 1:
            return
        for panel in (self._matrix_panel, self._timeline_panel):
            if panel is None:
                continue
            viewport_w = max(panel.viewport().width(), 1)
            bar = panel.horizontalScrollBar()
            bar.setRange(0, max(0, content_w - viewport_w))
            bar.setPageStep(viewport_w)
            bar.setSingleStep(STEP_COLUMN_WIDTH_PX + _GRID_H_SPACING_PX)
        if self._matrix_panel is not None and self._timeline_panel is not None:
            self._timeline_panel.set_scroll_x(self._matrix_panel.horizontalScrollBar().value())

    def _wire_panel_scroll_sync(self) -> None:
        assert (
            self._labels_panel is not None
            and self._timeline_panel is not None
            and self._matrix_panel is not None
        )
        h_matrix = self._matrix_panel.horizontalScrollBar()
        v_matrix = self._matrix_panel.verticalScrollBar()
        v_labels = self._labels_panel.verticalScrollBar()

        def on_matrix_h(value: int) -> None:
            self._timeline_panel.set_scroll_x(value)

        def on_h_range_changed(_lo: int, _hi: int) -> None:
            self._refresh_horizontal_ranges()

        h_matrix.valueChanged.connect(on_matrix_h)
        h_matrix.rangeChanged.connect(on_h_range_changed)
        _link_scroll_bar(v_matrix, v_labels)

    def _layout_panel_heights(self) -> None:
        if (
            self._labels_panel is None
            or self._timeline_panel is None
            or self._matrix_panel is None
            or self._corner_block is None
            or self._time_steps is None
            or self._steps_host is None
        ):
            return
        time_h = self._time_row_height_px
        matrix_content_h = self._steps_host.sizeHint().height()

        m = self._outer.contentsMargins()
        title_chrome = 28
        avail = self.height() - m.top() - m.bottom() - title_chrome

        if time_h + matrix_content_h > avail and avail > time_h:
            matrix_panel_h = avail - time_h
        elif time_h + matrix_content_h > avail:
            matrix_panel_h = max(avail - time_h, 0)
        else:
            matrix_panel_h = matrix_content_h

        self._timeline_panel.setFixedHeight(time_h)
        self._matrix_panel.setFixedHeight(matrix_panel_h)
        self._labels_panel.setFixedHeight(max(matrix_panel_h, 0))

    def resizeEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._layout_panel_heights()
        self._refresh_horizontal_ranges()

    def showEvent(self, event: QEvent) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._after_layout)

    def _after_layout(self) -> None:
        self._layout_panel_heights()
        self._refresh_horizontal_ranges()

    def reset_horizontal_scroll(self) -> None:
        if self._matrix_panel is not None:
            self._matrix_panel.horizontalScrollBar().setValue(0)
        if self._timeline_panel is not None:
            self._timeline_panel.set_scroll_x(0)

    def _apply_steps_width(self, model: SequenceModel) -> None:
        steps_w = max(
            timeline_steps_width_px(model.cols),
            self._time_steps.sizeHint().width() if self._time_steps is not None else 0,
        )
        self._steps_content_width_px = steps_w
        if self._time_steps is not None:
            self._time_steps.setMinimumWidth(steps_w)
            self._time_steps.setFixedWidth(steps_w)
        if self._steps_host is not None:
            self._steps_host.setMinimumWidth(steps_w)
            self._steps_host.setFixedWidth(steps_w)
        for dr in self._device_rows:
            dr.set_steps_width(steps_w)
        self._refresh_horizontal_ranges()

    def _build_time_steps(self, model: SequenceModel) -> int:
        self._time_steps = QWidget()
        ts_grid = QGridLayout(self._time_steps)
        ts_grid.setContentsMargins(0, 0, 0, 0)
        ts_grid.setHorizontalSpacing(_GRID_H_SPACING_PX)
        ts_grid.setVerticalSpacing(_PAIR_V_SPACING_PX)
        for col in range(model.cols):
            ts_grid.setColumnMinimumWidth(col, STEP_COLUMN_WIDTH_PX)
            ts_grid.setColumnStretch(col, 0)

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
            ts_grid.addWidget(ed, 0, c)

        steps_time_gap = QWidget()
        steps_time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        steps_time_gap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        ts_grid.addWidget(steps_time_gap, 1, 0, 1, model.cols)

        self._time_steps.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._time_steps.adjustSize()
        steps_w = max(timeline_steps_width_px(model.cols), self._time_steps.sizeHint().width())
        time_h = max(
            self._time_steps.sizeHint().height(),
            _TIME_ROW_MIN_HEIGHT_PX + _PAIR_V_SPACING_PX + _TIME_AFTER_GAP_PX,
        )
        self._time_steps.setFixedWidth(steps_w)
        self._time_steps.setFixedHeight(time_h)
        self._time_row_height_px = time_h
        return steps_w

    def _build_content(self, model: SequenceModel) -> None:
        self._clear_content()
        self._built_rows = model.rows
        self._built_cols = model.cols
        self._built_tab = self._state.active_tab_index

        self._corner_block = QWidget()
        self._corner_block.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        self._corner_block.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        corner_lay = QVBoxLayout(self._corner_block)
        corner_lay.setContentsMargins(0, 0, 0, 0)
        corner_lay.setSpacing(_PAIR_V_SPACING_PX)
        corner = QLabel("Time (µs)")
        corner.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        corner.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        corner_lay.addWidget(corner)
        label_time_gap = QWidget()
        label_time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        label_time_gap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        corner_lay.addWidget(label_time_gap)
        steps_w = self._build_time_steps(model)
        self._corner_block.setFixedHeight(self._time_row_height_px)
        self._corner_block.adjustSize()
        self._steps_content_width_px = steps_w

        labels_host = QWidget()
        labels_lay = QVBoxLayout(labels_host)
        labels_lay.setContentsMargins(0, 0, 0, 0)
        labels_lay.setSpacing(_PAIR_V_SPACING_PX)

        self._steps_host = QWidget()
        steps_lay = QVBoxLayout(self._steps_host)
        steps_lay.setContentsMargins(0, 0, 0, 0)
        steps_lay.setSpacing(_PAIR_V_SPACING_PX)

        for r in range(model.rows):
            dr = DeviceRowWidget(r, state=self._state, model=model, parent=labels_host)
            self._device_rows.append(dr)
            labels_lay.addWidget(dr.label_panel(), 0, Qt.AlignLeft)
            steps_lay.addWidget(dr.steps_panel(), 0, Qt.AlignLeft)
            if r < model.rows - 1:
                gap_h = _STEP_GROUP_GAP_PX
                label_gap = QWidget()
                label_gap.setMinimumHeight(gap_h)
                label_gap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                labels_lay.addWidget(label_gap)
                steps_gap = QWidget()
                steps_gap.setMinimumHeight(gap_h)
                steps_gap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                steps_lay.addWidget(steps_gap)

        labels_host.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        labels_host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._steps_host.setMinimumWidth(steps_w)
        self._steps_host.setFixedWidth(steps_w)
        self._steps_host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._labels_panel = _make_scroll_panel(
            labels_host,
            h_policy=Qt.ScrollBarAlwaysOff,
            v_policy=Qt.ScrollBarAlwaysOff,
        )
        self._labels_panel.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        self._labels_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self._timeline_panel = _TimelinePanel(self._time_steps, self._time_row_height_px)

        self._matrix_panel = _make_scroll_panel(
            self._steps_host,
            h_policy=Qt.ScrollBarAsNeeded,
            v_policy=Qt.ScrollBarAsNeeded,
        )
        self._matrix_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        left_col = QWidget()
        left_lay = QVBoxLayout(left_col)
        left_lay.setContentsMargins(0, 0, 0, 0)
        left_lay.setSpacing(0)
        left_lay.addWidget(self._corner_block, 0, Qt.AlignLeft | Qt.AlignTop)
        left_lay.addWidget(self._labels_panel, 1)

        right_col = QWidget()
        right_lay = QVBoxLayout(right_col)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(self._timeline_panel, 0, Qt.AlignTop)
        right_lay.addWidget(self._matrix_panel, 1)

        main_row = QWidget()
        main_hbox = QHBoxLayout(main_row)
        main_hbox.setContentsMargins(0, 0, 0, 0)
        main_hbox.setSpacing(_GRID_H_SPACING_PX)
        main_hbox.addWidget(left_col, 0, Qt.AlignLeft | Qt.AlignTop)
        main_hbox.addWidget(right_col, 1)

        self._outer.addWidget(main_row, 0)
        self._outer.addStretch(1)
        self._wire_panel_scroll_sync()
        self._layout_panel_heights()

        self._apply_timeline_read_only()
        self.setMinimumWidth(min_width_for_timeline_cols(model.cols))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.updateGeometry()
        QTimer.singleShot(0, self._after_layout)

    def _on_active_tab_changed(self, _tab: int) -> None:
        self._build_content(self._state.model)

    def _rebuild_for_current_view(self) -> None:
        model = self._state.model
        if (
            model.rows != self._built_rows
            or model.cols != self._built_cols
            or len(self._delay_edits) != model.cols
        ):
            self._build_content(model)
            return
        for c, ed in enumerate(self._delay_edits):
            if c >= model.cols:
                break
            v = model.delay_us(c, 0.0)
            ed.set_committed_display(_format_delay_us(v))
        for dr in self._device_rows:
            dr.sync_from_model(model)
        self._apply_steps_width(model)
        self._apply_timeline_read_only()
        self._after_layout()

    def _sync_from_model(self, _model: SequenceModel) -> None:
        self._rebuild_for_current_view()
