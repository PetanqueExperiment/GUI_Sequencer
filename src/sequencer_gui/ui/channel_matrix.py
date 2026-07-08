from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.domain.document import (
    MergedBlockSpan,
    merged_enabled_block_spans,
    merged_timeline_col_offset_for_block,
)
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.ui.device_row import (
    GRID_H_SPACING_PX,
    STEP_COLUMN_WIDTH_PX,
    DeviceRowWidget,
    block_band_stylesheet,
    block_column_tint_stylesheet,
    block_span_width_px,
    column_block_accents_from_spans,
    column_block_indices_from_spans,
    is_block_column_start,
    resolve_block_accent_color,
    timeline_steps_width_px,
)
from sequencer_gui.ui.row_software_selector import LABEL_COL_MIN_WIDTH_PX
from sequencer_gui.ui.value_input import CommitFloatLineEdit, parse_float_field

_PAIR_V_SPACING_PX = 4
_TIME_AFTER_GAP_PX = 14
_STEP_GROUP_GAP_PX = 4
_MATRIX_MIN_WIDTH_EXTRA_PX = 48
# Fallback when layout has not resolved line-edit height yet.
_INDEX_ROW_MIN_HEIGHT_PX = 20
_BLOCK_BAND_ROW_MIN_HEIGHT_PX = 20
_LABEL_ROW_MIN_HEIGHT_PX = 24
_TIME_ROW_MIN_HEIGHT_PX = 28

_DELAY_MIN_US = 0.0
_DELAY_MAX_US = 1e9
_DELAY_DECIMALS = 3
_US_PER_MS = 1000.0
_US_PER_10MS = 10_000.0  # 10 ms

# Light backgrounds hinting at delay order of magnitude (values stored in µs).
_DELAY_MAGNITUDE_BG = {
    "10ms": "#ffe6e8",   # >= 10 ms
    "ms": "#f2fff3",  # >= 1 ms and < 10 ms
    "us": "#ebf6ff",  # >= 1 µs and < 1 ms
    "ns": "#fcebff",  # < 1 µs
}


def _format_delay_us(v: float) -> str:
    return format(v, f".{_DELAY_DECIMALS}f")


def _delay_magnitude_background_us(value_us: float) -> str:
    if value_us >= _US_PER_10MS:
        return _DELAY_MAGNITUDE_BG["10ms"]
    if value_us >= _US_PER_MS:
        return _DELAY_MAGNITUDE_BG["ms"]
    if value_us >= 1.0:
        return _DELAY_MAGNITUDE_BG["us"]
    return _DELAY_MAGNITUDE_BG["ns"]


class _DelayUsLineEdit(CommitFloatLineEdit):
    """Delay field with magnitude background tint; preserves tint while editing."""

    def __init__(
        self,
        minimum: float,
        maximum: float,
        decimals: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(minimum, maximum, decimals, parent)
        self._delay_us = 0.0
        self._block_accent: str | None = None
        self._block_separator = False

    def set_block_column_context(self, accent: str | None, *, block_separator: bool) -> None:
        self._block_accent = accent
        self._block_separator = block_separator
        self._refresh_style(editing=self.text() != self._committed_text)

    def set_delay_us_value(self, value_us: float) -> None:
        self._delay_us = value_us
        self._refresh_style(editing=self.text() != self._committed_text)

    def _effective_delay_us_for_style(self) -> float:
        if self.text() != self._committed_text:
            parsed = parse_float_field(self.text())
            if parsed is not None:
                return max(self.minimum(), min(self.maximum(), parsed))
        return self._delay_us

    def minimum(self) -> float:
        return self._minimum

    def maximum(self) -> float:
        return self._maximum

    def _refresh_style(self, *, editing: bool) -> None:
        bg = _delay_magnitude_background_us(self._effective_delay_us_for_style())
        parts = [f"background-color: {bg};"]
        parts.append("color: #9e9e9e;" if editing else "color: #212121;")
        if self._block_accent is not None and self._block_separator:
            parts.append(f"border-left: 2px solid {self._block_accent};")
        self.setStyleSheet(" ".join(parts))

    def set_committed_display(self, text: str) -> None:
        pos_before = self.cursorPosition()
        self._style_guard = True
        self._committed_text = text
        self.blockSignals(True)
        self.setText(text)
        self.blockSignals(False)
        self._style_guard = False
        self.setCursorPosition(min(pos_before, len(text)))
        self._refresh_style(editing=False)

    def _on_text_changed(self, _text: str) -> None:
        if self._style_guard:
            return
        self._refresh_style(editing=True)

    def focusOutEvent(self, event: QEvent) -> None:  # type: ignore[override]
        if self.text() != self._committed_text:
            self.set_committed_display(self._committed_text)
        else:
            self._refresh_style(editing=False)
        QLineEdit.focusOutEvent(self, event)

    def _try_arrow_step(self, direction: int) -> bool:
        result = super()._try_arrow_step(direction)
        if result:
            self._refresh_style(editing=True)
        return result


def _make_timestep_index_label(
    col: int,
    *,
    accent: str | None = None,
    block_separator: bool = False,
) -> QLabel:
    lab = QLabel(str(col))
    lab.setAlignment(Qt.AlignCenter)
    lab.setFixedWidth(STEP_COLUMN_WIDTH_PX)
    lab.setFixedHeight(_INDEX_ROW_MIN_HEIGHT_PX)
    lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    style = "color: #78909c; font-size: 11px;"
    if accent is not None:
        style += " " + block_column_tint_stylesheet(accent, block_separator=block_separator)
    lab.setStyleSheet(style)
    return lab


def _make_block_band_label(name: str, accent: str, ncol: int) -> QLabel:
    lab = QLabel(name)
    lab.setAlignment(Qt.AlignCenter)
    lab.setFixedHeight(_BLOCK_BAND_ROW_MIN_HEIGHT_PX)
    lab.setMinimumWidth(block_span_width_px(ncol))
    lab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    lab.setStyleSheet(block_band_stylesheet(accent))
    lab.setToolTip(name)
    return lab


def _apply_block_column_hint(widget: QWidget, accent: str, *, block_separator: bool) -> None:
    widget.setStyleSheet(
        widget.styleSheet() + block_column_tint_stylesheet(accent, block_separator=block_separator)
    )


def min_width_for_timeline_cols(_cols: int) -> int:
    """Minimum outer width of the Sequence Matrix group (label column + at least one step)."""
    return (
        LABEL_COL_MIN_WIDTH_PX
        + GRID_H_SPACING_PX
        + STEP_COLUMN_WIDTH_PX
        + _MATRIX_MIN_WIDTH_EXTRA_PX
    )


def _wheel_delta(event: QWheelEvent) -> int:
    pd = event.pixelDelta()
    if pd.y() != 0:
        return pd.y()
    if pd.x() != 0:
        return pd.x()
    ad = event.angleDelta()
    if ad.y() != 0:
        return ad.y()
    return ad.x()


def _shift_wheel_scrolls_horizontal(event: QWheelEvent, bar: QScrollBar) -> bool:
    if not (event.modifiers() & Qt.ShiftModifier):
        return False
    delta = _wheel_delta(event)
    if delta == 0:
        return False
    bar.setValue(bar.value() - delta)
    return True


class _ScrollPanel(QScrollArea):
    """Scroll area; Shift + wheel scrolls horizontally (own bar or an external one)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shift_horizontal_bar: QScrollBar | None = None

    def set_shift_horizontal_bar(self, bar: QScrollBar | None) -> None:
        self._shift_horizontal_bar = bar

    def wheelEvent(self, event: QWheelEvent) -> None:
        bar = self._shift_horizontal_bar or self.horizontalScrollBar()
        if _shift_wheel_scrolls_horizontal(event, bar):
            event.accept()
            return
        super().wheelEvent(event)


def _make_scroll_panel(
    content: QWidget,
    *,
    h_policy: Qt.ScrollBarPolicy,
    v_policy: Qt.ScrollBarPolicy,
) -> _ScrollPanel:
    scroll = _ScrollPanel()
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidgetResizable(False)
    scroll.setHorizontalScrollBarPolicy(h_policy)
    scroll.setVerticalScrollBarPolicy(v_policy)
    scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
    scroll.setWidget(content)
    return scroll


def _link_scroll_bars(*bars: QScrollBar) -> None:
    """Keep scroll bar positions in sync (bidirectional, loop-safe)."""

    def on_changed(source: QScrollBar, value: int) -> None:
        for bar in bars:
            if bar is not source and bar.value() != value:
                bar.setValue(value)

    for bar in bars:
        bar.valueChanged.connect(lambda value, b=bar: on_changed(b, value))


class _TimelinePanel(QScrollArea):
    """Pinned delay row in a scroll area (horizontal bar hidden; follows matrix scroll)."""

    def __init__(self, time_steps: QWidget, row_height: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._shift_horizontal_bar: QScrollBar | None = None
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setWidget(time_steps)
        self.setFixedHeight(row_height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_shift_horizontal_bar(self, bar: QScrollBar | None) -> None:
        self._shift_horizontal_bar = bar

    def set_scroll_x(self, px: int) -> None:
        self.horizontalScrollBar().setValue(max(0, px))

    def wheelEvent(self, event: QWheelEvent) -> None:
        bar = self._shift_horizontal_bar or self.horizontalScrollBar()
        if _shift_wheel_scrolls_horizontal(event, bar):
            event.accept()
            return
        super().wheelEvent(event)

    def refresh_range(self, content_w: int) -> None:
        viewport_w = max(self.viewport().width(), 1)
        bar = self.horizontalScrollBar()
        bar.setRange(0, max(0, content_w - viewport_w))
        bar.setPageStep(viewport_w)
        bar.setSingleStep(STEP_COLUMN_WIDTH_PX + GRID_H_SPACING_PX)


class ChannelMatrix(QGroupBox):
    """Labels panel + timeline strip + matrix panel (matrix owns scrollbars)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequence Matrix", parent)
        self._state = state
        self._device_rows: list[DeviceRowWidget] = []
        self._col_label_edits: list[QLineEdit] = []
        self._delay_edits: list[_DelayUsLineEdit] = []
        self._built_rows = -1
        self._built_cols = -1
        self._built_tab = -2
        self._built_block_band_sig: tuple[tuple[int, int, str], ...] = ()
        self._corner_block: QWidget | None = None
        self._labels_panel: _ScrollPanel | None = None
        self._timeline_panel: _TimelinePanel | None = None
        self._time_row_height_px = _TIME_ROW_MIN_HEIGHT_PX
        self._matrix_panel: _ScrollPanel | None = None
        self._time_steps: QWidget | None = None
        self._steps_host: QWidget | None = None
        self._steps_content_width_px = 0

        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(_PAIR_V_SPACING_PX)
        self._outer.setContentsMargins(8, 12, 8, 8)

        self._build_content(self._state.model)
        state.model_changed.connect(self._sync_from_model)
        state.document_changed.connect(self._on_document_changed)
        state.active_tab_changed.connect(self._on_active_tab_changed)

    def commit_row_labels_to_model(self) -> None:
        for dr in self._device_rows:
            self._state.set_row_label(dr.logical_row, dr.row_edit().text())

    def commit_col_labels_to_model(self) -> None:
        for c, ed in enumerate(self._col_label_edits):
            self._state.set_col_label(c, ed.text())

    def _apply_timeline_read_only(self) -> None:
        ro = self._state.timeline_read_only
        for ed in self._col_label_edits:
            ed.setEnabled(not ro)
        for ed in self._delay_edits:
            ed.setEnabled(not ro)

    def _on_delay_return_pressed(self, col: int) -> None:
        line = self._delay_edits[col]
        model = self._state.model

        def revert() -> None:
            line.set_committed_display(_format_delay_us(model.delay_us(col)))

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
        committed = self._state.model.delay_us(col)
        line.set_delay_us_value(committed)
        line.set_committed_display(_format_delay_us(committed))

    def _clear_content(self) -> None:
        self._device_rows.clear()
        self._col_label_edits.clear()
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

    @staticmethod
    def _viewport_margins(scroll: QScrollArea) -> tuple[int, int, int, int]:
        m = scroll.viewportMargins()
        return m.left(), m.top(), m.right(), m.bottom()

    def _sync_scrollbar_gutters(self) -> None:
        """Match timeline/labels viewport size to the matrix (matrix owns the bars)."""
        if self._matrix_panel is None:
            return
        matrix_vp_h = self._matrix_panel.viewport().height()
        matrix_vp_w = self._matrix_panel.viewport().width()
        if self._timeline_panel is not None:
            l, t, r, b = self._viewport_margins(self._timeline_panel)
            delta_w = self._timeline_panel.viewport().width() - matrix_vp_w
            self._timeline_panel.setViewportMargins(l, t, max(0, r + delta_w), b)
        if self._labels_panel is not None:
            l, t, r, b = self._viewport_margins(self._labels_panel)
            delta_h = self._labels_panel.viewport().height() - matrix_vp_h
            self._labels_panel.setViewportMargins(l, t, r, max(0, b + delta_h))

    def _sync_scroll_hosts_height(self) -> None:
        """Keep labels and steps scroll content the same height for vertical sync."""
        if self._labels_panel is None or self._matrix_panel is None:
            return
        labels_host = self._labels_panel.widget()
        steps_host = self._matrix_panel.widget()
        if labels_host is None or steps_host is None:
            return
        h = max(labels_host.sizeHint().height(), steps_host.sizeHint().height())
        if h < 1:
            return
        labels_host.setFixedHeight(h)
        steps_host.setFixedHeight(h)

    def _refresh_horizontal_ranges(self) -> None:
        content_w = self._steps_content_width_px
        if content_w < 1:
            return
        self._sync_scrollbar_gutters()
        for panel in (self._matrix_panel, self._timeline_panel):
            if panel is None:
                continue
            viewport_w = max(panel.viewport().width(), 1)
            bar = panel.horizontalScrollBar()
            bar.setRange(0, max(0, content_w - viewport_w))
            bar.setPageStep(viewport_w)
            bar.setSingleStep(STEP_COLUMN_WIDTH_PX + GRID_H_SPACING_PX)
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

        def on_v_range_changed(_lo: int, _hi: int) -> None:
            self._refresh_horizontal_ranges()

        h_matrix.valueChanged.connect(on_matrix_h)
        h_matrix.rangeChanged.connect(on_h_range_changed)
        v_matrix.rangeChanged.connect(on_v_range_changed)
        _link_scroll_bars(v_matrix, v_labels)
        self._labels_panel.set_shift_horizontal_bar(h_matrix)
        self._timeline_panel.set_shift_horizontal_bar(h_matrix)

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
        for dr in self._device_rows:
            dr.sync_panel_heights()
        self._sync_scroll_hosts_height()
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
        self._sync_scroll_hosts_height()
        self._refresh_horizontal_ranges()

    def _timeline_column_index_offset(self) -> int:
        tab = self._state.active_tab_index
        if tab == COMPLETE_TAB_INDEX:
            return 0
        return merged_timeline_col_offset_for_block(self._state.document, tab)

    def _timeline_block_spans(self, model: SequenceModel) -> tuple[MergedBlockSpan, ...]:
        tab = self._state.active_tab_index
        doc = self._state.document
        if tab == COMPLETE_TAB_INDEX:
            return merged_enabled_block_spans(doc)
        if 0 <= tab < len(doc.blocks):
            b = doc.blocks[tab]
            return (MergedBlockSpan(0, model.cols, tab, b.name),)
        return ()

    def _block_band_signature(self) -> tuple[tuple[int, int, str, str | None], ...]:
        doc = self._state.document
        return tuple(
            (
                s.block_index,
                s.ncol,
                s.name,
                doc.blocks[s.block_index].accent_color if s.block_index < len(doc.blocks) else None,
            )
            for s in self._timeline_block_spans(self._state.model)
        )

    def _column_block_indices(self, model: SequenceModel) -> tuple[int, ...] | None:
        return column_block_indices_from_spans(model.cols, self._timeline_block_spans(model))

    def _column_block_accents(self, model: SequenceModel) -> tuple[str, ...] | None:
        return column_block_accents_from_spans(
            model.cols, self._timeline_block_spans(model), self._state.document.blocks
        )

    def _build_time_steps(self, model: SequenceModel) -> int:
        self._time_steps = QWidget()
        ts_grid = QGridLayout(self._time_steps)
        ts_grid.setContentsMargins(0, 0, 0, 0)
        ts_grid.setHorizontalSpacing(GRID_H_SPACING_PX)
        ts_grid.setVerticalSpacing(_PAIR_V_SPACING_PX)
        for col in range(model.cols):
            ts_grid.setColumnMinimumWidth(col, STEP_COLUMN_WIDTH_PX)
            ts_grid.setColumnStretch(col, 0)

        spans = self._timeline_block_spans(model)
        block_indices = self._column_block_indices(model)
        block_accents = self._column_block_accents(model)
        doc = self._state.document
        show_block_band = bool(spans)
        index_row = 1 if show_block_band else 0
        label_row = index_row + 1
        delay_row = label_row + 1
        gap_row = delay_row + 1

        if show_block_band:
            for span in spans:
                accent = resolve_block_accent_color(
                    span.block_index, doc.blocks[span.block_index].accent_color
                )
                ts_grid.addWidget(
                    _make_block_band_label(span.name, accent, span.ncol),
                    0,
                    span.merged_start_col,
                    1,
                    span.ncol,
                )

        col_index_offset = self._timeline_column_index_offset()
        for c in range(model.cols):
            accent = block_accents[c] if block_accents is not None else None
            block_separator = False
            if block_indices is not None and accent is not None:
                bi = block_indices[c]
                block_separator = is_block_column_start(c, block_indices) and bi > 0
            ts_grid.addWidget(
                _make_timestep_index_label(
                    col_index_offset + c,
                    accent=accent,
                    block_separator=block_separator,
                ),
                index_row,
                c,
            )

            label_ed = QLineEdit(model.col_label(c))
            label_ed.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            label_ed.setPlaceholderText("...")
            label_ed.editingFinished.connect(
                lambda idx=c, e=label_ed: self._state.set_col_label(idx, e.text())
            )
            self._col_label_edits.append(label_ed)
            label_ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            if accent is not None:
                _apply_block_column_hint(label_ed, accent, block_separator=block_separator)
            ts_grid.addWidget(label_ed, label_row, c)

            delay_us = model.delay_us(c)
            ed = _DelayUsLineEdit(_DELAY_MIN_US, _DELAY_MAX_US, _DELAY_DECIMALS)
            ed.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            ed.set_block_column_context(accent, block_separator=block_separator)
            ed.set_delay_us_value(delay_us)
            ed.set_committed_display(_format_delay_us(delay_us))

            def make_return(cc: int):
                def on_return() -> None:
                    self._on_delay_return_pressed(cc)

                return on_return

            ed.set_on_return(make_return(c))
            self._delay_edits.append(ed)
            ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            ts_grid.addWidget(ed, delay_row, c)

        steps_time_gap = QWidget()
        steps_time_gap.setFixedHeight(_TIME_AFTER_GAP_PX)
        steps_time_gap.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        ts_grid.addWidget(steps_time_gap, gap_row, 0, 1, model.cols)

        self._time_steps.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._time_steps.adjustSize()
        steps_w = max(timeline_steps_width_px(model.cols), self._time_steps.sizeHint().width())
        band_extra = (
            (_BLOCK_BAND_ROW_MIN_HEIGHT_PX + _PAIR_V_SPACING_PX) if show_block_band else 0
        )
        time_h = max(
            self._time_steps.sizeHint().height(),
            band_extra
            + _INDEX_ROW_MIN_HEIGHT_PX
            + _PAIR_V_SPACING_PX
            + _LABEL_ROW_MIN_HEIGHT_PX
            + _PAIR_V_SPACING_PX
            + _TIME_ROW_MIN_HEIGHT_PX
            + _PAIR_V_SPACING_PX
            + _TIME_AFTER_GAP_PX,
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
        self._built_block_band_sig = self._block_band_signature()
        block_indices = self._column_block_indices(model)
        block_accents = self._column_block_accents(model)

        self._corner_block = QWidget()
        self._corner_block.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        self._corner_block.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        corner_lay = QVBoxLayout(self._corner_block)
        corner_lay.setContentsMargins(0, 0, 0, 0)
        corner_lay.setSpacing(_PAIR_V_SPACING_PX)
        if self._built_block_band_sig:
            corner_block = QLabel("Block")
            corner_block.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
            corner_block.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
            corner_block.setFixedHeight(_BLOCK_BAND_ROW_MIN_HEIGHT_PX)
            corner_block.setStyleSheet("color: #78909c; font-size: 11px;")
            corner_block.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            corner_lay.addWidget(corner_block)
        corner_index = QLabel("#")
        corner_index.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner_index.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        corner_index.setFixedHeight(_INDEX_ROW_MIN_HEIGHT_PX)
        corner_index.setStyleSheet("color: #78909c; font-size: 11px;")
        corner_index.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        corner_lay.addWidget(corner_index)
        corner_timestep = QLabel("Timestep label")
        corner_timestep.setAlignment(Qt.AlignCenter | Qt.AlignVCenter)
        corner_timestep.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        corner_timestep.setFixedHeight(_LABEL_ROW_MIN_HEIGHT_PX)
        corner_timestep.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        corner_lay.addWidget(corner_timestep)
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
            dr = DeviceRowWidget(
                r,
                state=self._state,
                model=model,
                parent=labels_host,
                column_block_indices=block_indices,
                column_block_accents=block_accents,
            )
            self._device_rows.append(dr)
            labels_lay.addWidget(dr.label_panel(), 0, Qt.AlignLeft)
            steps_lay.addWidget(dr.steps_panel(), 0, Qt.AlignLeft)
            if r < model.rows - 1 and _STEP_GROUP_GAP_PX > 0:
                label_gap = QWidget()
                label_gap.setFixedHeight(_STEP_GROUP_GAP_PX)
                label_gap.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                labels_lay.addWidget(label_gap)
                steps_gap = QWidget()
                steps_gap.setFixedHeight(_STEP_GROUP_GAP_PX)
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
        main_hbox.setSpacing(GRID_H_SPACING_PX)
        main_hbox.addWidget(left_col, 0, Qt.AlignLeft | Qt.AlignTop)
        main_hbox.addWidget(right_col, 1)

        self._outer.addWidget(main_row, 0)
        self._outer.addStretch(1)
        self._wire_panel_scroll_sync()
        for dr in self._device_rows:
            dr.sync_panel_heights()
        self._sync_scroll_hosts_height()
        self._layout_panel_heights()

        self._apply_timeline_read_only()
        self.setMinimumWidth(min_width_for_timeline_cols(model.cols))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.updateGeometry()
        QTimer.singleShot(0, self._after_layout)

    def _on_document_changed(self, _document) -> None:
        self._rebuild_for_current_view()

    def _on_active_tab_changed(self, _tab: int) -> None:
        self._build_content(self._state.model)

    def _rebuild_for_current_view(self) -> None:
        model = self._state.model
        if (
            model.rows != self._built_rows
            or model.cols != self._built_cols
            or len(self._delay_edits) != model.cols
            or len(self._col_label_edits) != model.cols
            or self._block_band_signature() != self._built_block_band_sig
        ):
            self._build_content(model)
            return
        for c, label_ed in enumerate(self._col_label_edits):
            if c >= model.cols:
                break
            t = model.col_label(c)
            if label_ed.text() != t:
                label_ed.blockSignals(True)
                label_ed.setText(t)
                label_ed.blockSignals(False)
        for c, ed in enumerate(self._delay_edits):
            if c >= model.cols:
                break
            v = model.delay_us(c)
            ed.set_delay_us_value(v)
            ed.set_committed_display(_format_delay_us(v))
        for dr in self._device_rows:
            dr.sync_from_model(model)
        for dr in self._device_rows:
            dr.update_matrix_param_indices(model)
        self._apply_steps_width(model)
        self._apply_timeline_read_only()
        self._after_layout()

    def _sync_from_model(self, _model: SequenceModel) -> None:
        self._rebuild_for_current_view()
