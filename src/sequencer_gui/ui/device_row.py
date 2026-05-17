from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.analog_stored import ANALOG_HOLD
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import get_object
from sequencer_gui.software_objects.types import AnalogParameterSpec
from sequencer_gui.ui.row_software_selector import LABEL_COL_MIN_WIDTH_PX, RowSoftwareSelector
from sequencer_gui.ui.value_input import AnalogValueLineEdit, parse_analog_value

_ROW_CHECKED_COLORS = (
    "#1f77b4",
    "#ff7f0e",
    "#2ca02c",
    "#d62728",
    "#9467bd",
    "#8c564b",
    "#e377c2",
    "#7f7f7f",
    "#bcbd22",
    "#17becf",
)

# One timeline step: delay spin, optional per-device on/off toggle, analog line edit (same width every row).
STEP_COLUMN_WIDTH_PX = 72
# Match QLineEdit / combo row height in the device header.
_CHANNEL_BTN_HEIGHT_PX = 25
# Must match QGridLayout.setHorizontalSpacing on timeline + matrix step grids.
GRID_H_SPACING_PX = 3
_GRID_V_SPACING_PX = 2


def timeline_steps_width_px(cols: int) -> int:
    """Width of the scrollable step columns only."""
    if cols < 1:
        cols = 1
    return cols * STEP_COLUMN_WIDTH_PX + max(0, cols - 1) * GRID_H_SPACING_PX


def timeline_content_width_px(cols: int) -> int:
    """Full row width (label column + gap + step columns)."""
    return LABEL_COL_MIN_WIDTH_PX + GRID_H_SPACING_PX + timeline_steps_width_px(cols)


def _channel_button_stylesheet(row_index: int) -> str:
    c = _ROW_CHECKED_COLORS[row_index % len(_ROW_CHECKED_COLORS)]
    return f"""
        QPushButton {{
            border-radius: 6px;
            padding: 0px 0px;
            min-width: 32px;
            min-height: 0;
            max-height: {_CHANNEL_BTN_HEIGHT_PX}px;
            font-size: 13px;
            font-weight: 500;
            outline: none;
        }}
        QPushButton:!checked {{
            background-color: #eceff1;
            color: #37474f;
            border: 1px solid #b0bec5;
        }}
        QPushButton:!checked:hover {{
            background-color: #e3e8ec;
            border: 1px solid #90a4ae;
        }}
        QPushButton:!checked:pressed {{
            background-color: #cfd8dc;
            border: 1px solid #78909c;
        }}
        QPushButton:checked {{
            background-color: {c};
            color: #ffffff;
            border: 1px solid rgba(0, 0, 0, 0.22);
            font-weight: 600;
        }}
        QPushButton:checked:hover {{
            border: 1px solid rgba(255, 255, 255, 0.55);
        }}
        QPushButton:checked:pressed {{
            border: 1px solid rgba(0, 0, 0, 0.35);
        }}
    """


_HEADER_COL_SPACING_PX = 4
_DEVICE_INDEX_WIDTH_PX = 24


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class DeviceRowWidget:
    """One sequencer row split into a fixed label panel and a scrollable steps panel."""

    def __init__(
        self,
        row: int,
        state: SequenceAppState,
        model: SequenceModel,
        parent: QWidget | None = None,
    ) -> None:
        self._row = row
        self._state = state
        self._buttons: list[QPushButton] = []
        self._analog_edits: list[list[AnalogValueLineEdit]] = []
        self._param_sig: tuple[str, ...] = ()
        self._analog_row_widgets: list[QWidget] = []

        self._label_panel = QWidget(parent)
        self._steps_panel = QWidget(parent)
        self._label_grid = QGridLayout(self._label_panel)
        self._steps_grid = QGridLayout(self._steps_panel)
        for grid in (self._label_grid, self._steps_grid):
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(GRID_H_SPACING_PX)
            grid.setVerticalSpacing(_GRID_V_SPACING_PX)

        m = model
        self._label_panel.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        self._label_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self._steps_panel.setFixedWidth(timeline_steps_width_px(m.cols))
        self._steps_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        for col in range(m.cols):
            self._steps_grid.setColumnMinimumWidth(col, STEP_COLUMN_WIDTH_PX)
            self._steps_grid.setColumnStretch(col, 0)

        header = QWidget()
        header.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        header.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        hlay = QHBoxLayout(header)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(_HEADER_COL_SPACING_PX)

        index_lab = QLabel(str(row))
        index_lab.setAlignment(Qt.AlignCenter)
        index_lab.setFixedWidth(_DEVICE_INDEX_WIDTH_PX)
        index_lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        index_lab.setStyleSheet("color: #78909c; font-size: 11px;")
        hlay.addWidget(index_lab)

        self._edit = QLineEdit(m.row_label(row))
        self._edit.setMinimumWidth(36)
        self._edit.editingFinished.connect(self._on_row_label_finished)
        self._edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hlay.addWidget(self._edit, 1)

        self._sw = RowSoftwareSelector(row, state)
        hlay.addWidget(self._sw, 1)

        self._label_grid.addWidget(header, 0, 0)

        self._sync_channel_strip(m)

        self._rebuild_analog_section()

        self.sync_panel_heights()
        self.set_timeline_read_only(state.timeline_read_only)

    def label_panel(self) -> QWidget:
        return self._label_panel

    def steps_panel(self) -> QWidget:
        return self._steps_panel

    def set_steps_width(self, steps_w: int) -> None:
        self._steps_panel.setFixedWidth(steps_w)

    def _sync_paired_grid_rows(self) -> None:
        rows = max(self._label_grid.rowCount(), self._steps_grid.rowCount())
        for r in range(rows):
            row_h = 0
            for grid in (self._label_grid, self._steps_grid):
                for c in range(grid.columnCount()):
                    item = grid.itemAtPosition(r, c)
                    if item is None:
                        continue
                    w = item.widget()
                    if w is None:
                        continue
                    # Only size the anchor row of a rowspan — otherwise each spanned
                    # row gets the full widget height and doubles the header block.
                    idx = grid.indexOf(w)
                    if idx < 0:
                        continue
                    anchor_row, _col, _rowspan, _colspan = grid.getItemPosition(idx)
                    if anchor_row != r:
                        continue
                    row_h = max(row_h, w.sizeHint().height())
            if row_h > 0:
                self._label_grid.setRowMinimumHeight(r, row_h)
                self._steps_grid.setRowMinimumHeight(r, row_h)

    def sync_panel_heights(self) -> None:
        self._sync_paired_grid_rows()
        h = max(self._label_panel.sizeHint().height(), self._steps_panel.sizeHint().height())
        if h > 0:
            self._label_panel.setFixedHeight(h)
            self._steps_panel.setFixedHeight(h)

    def set_timeline_read_only(self, read_only: bool) -> None:
        for btn in self._buttons:
            btn.setEnabled(not read_only)
        for row in self._analog_edits:
            for ed in row:
                ed.setEnabled(not read_only)

    @property
    def logical_row(self) -> int:
        return self._row

    def row_edit(self) -> QLineEdit:
        return self._edit

    def row_software_selector(self) -> RowSoftwareSelector:
        return self._sw

    def _on_row_label_finished(self) -> None:
        self._state.set_row_label(self._row, self._edit.text())

    def _clear_channel_buttons(self) -> None:
        for btn in self._buttons:
            self._steps_grid.removeWidget(btn)
            btn.deleteLater()
        self._buttons.clear()

    def _add_channel_buttons(self, model: SequenceModel) -> None:
        for c in range(model.cols):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            btn.setFixedHeight(_CHANNEL_BTN_HEIGHT_PX)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            btn.setStyleSheet(_channel_button_stylesheet(self._row))
            btn.setChecked(model.channel(self._row, c))

            def make_toggle(rr: int, cc: int):
                def on_toggled(checked: bool) -> None:
                    self._state.set_channel(rr, cc, checked)

                return on_toggled

            btn.toggled.connect(make_toggle(self._row, c))
            self._buttons.append(btn)
            self._steps_grid.addWidget(btn, 0, c, 1, 1)

    def _sync_channel_buttons_from_model(self, model: SequenceModel) -> None:
        for c in range(min(model.cols, len(self._buttons))):
            btn = self._buttons[c]
            btn.blockSignals(True)
            btn.setChecked(model.channel(self._row, c))
            btn.blockSignals(False)

    def _sync_channel_strip(self, model: SequenceModel) -> None:
        want = get_object(model.row_software_name(self._row)).has_on_off
        have = len(self._buttons) > 0
        if want != have:
            self._clear_channel_buttons()
            if want:
                self._add_channel_buttons(model)
        elif want:
            self._sync_channel_buttons_from_model(model)
        self.sync_panel_heights()

    def _param_signature(self, model: SequenceModel) -> tuple[str, ...]:
        obj = get_object(model.row_software_name(self._row))
        return tuple(p.param_id for p in obj.analog_parameters)

    def _clear_analog_section(self) -> None:
        for w in self._analog_row_widgets:
            if isinstance(w, QLabel):
                self._label_grid.removeWidget(w)
            else:
                self._steps_grid.removeWidget(w)
            w.deleteLater()
        self._analog_row_widgets.clear()
        self._analog_edits = []

    def _on_analog_return_pressed(self, line: AnalogValueLineEdit, spec: AnalogParameterSpec, col: int) -> None:
        model = self._state.model
        display_ok = model.analog_display_text(self._row, spec.param_id, col, decimals=spec.decimals)

        def revert() -> None:
            line.set_committed_display(display_ok)

        s = line.text().strip()
        if s in ("-", "\u2212"):
            self._state.set_analog(self._row, spec.param_id, col, ANALOG_HOLD)
            line.set_committed_display(self._state.model.analog_display_text(self._row, spec.param_id, col, decimals=spec.decimals))
            return
        if not s:
            revert()
            return
        parsed = parse_analog_value(s)
        if parsed == "hold":
            self._state.set_analog(self._row, spec.param_id, col, ANALOG_HOLD)
            line.set_committed_display(self._state.model.analog_display_text(self._row, spec.param_id, col, decimals=spec.decimals))
            return
        if parsed is None:
            revert()
            return
        x = _clamp(parsed, spec.minimum, spec.maximum)
        self._state.set_analog(self._row, spec.param_id, col, x)
        line.set_committed_display(self._state.model.analog_display_text(self._row, spec.param_id, col, decimals=spec.decimals))

    def _rebuild_analog_section(self) -> None:
        model = self._state.model
        self._param_sig = self._param_signature(model)
        self._clear_analog_section()
        obj = get_object(model.row_software_name(self._row))
        cols = model.cols
        base_row = 1
        for pi, spec in enumerate(obj.analog_parameters):
            g_row = base_row + pi
            lab = QLabel(spec.label)
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lab.setWordWrap(False)
            lab.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self._label_grid.addWidget(lab, g_row, 0)
            self._analog_row_widgets.append(lab)

            edits_row: list[AnalogValueLineEdit] = []
            for c in range(cols):
                ed = AnalogValueLineEdit(spec)
                ed.setFixedWidth(STEP_COLUMN_WIDTH_PX)
                ed.set_committed_display(model.analog_display_text(self._row, spec.param_id, c, decimals=spec.decimals))

                def make_return(edt: AnalogValueLineEdit, sp: AnalogParameterSpec, cc: int):
                    def on_return() -> None:
                        self._on_analog_return_pressed(edt, sp, cc)

                    return on_return

                ed.set_on_return(make_return(ed, spec, c))
                ed.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                self._steps_grid.addWidget(ed, g_row, c)
                edits_row.append(ed)
                self._analog_row_widgets.append(ed)
            self._analog_edits.append(edits_row)
        self.sync_panel_heights()
        self.set_timeline_read_only(self._state.timeline_read_only)

    def sync_from_model(self, model: SequenceModel) -> None:
        if self._row >= model.rows:
            return
        t = model.row_label(self._row)
        if self._edit.text() != t:
            self._edit.blockSignals(True)
            self._edit.setText(t)
            self._edit.blockSignals(False)
        self._sw.apply_from_model(model)
        self._sync_channel_strip(model)
        sig = self._param_signature(model)
        if sig != self._param_sig:
            self._rebuild_analog_section()
        else:
            obj = get_object(model.row_software_name(self._row))
            for pi, spec in enumerate(obj.analog_parameters):
                if pi >= len(self._analog_edits):
                    break
                for c in range(min(model.cols, len(self._analog_edits[pi]))):
                    ed = self._analog_edits[pi][c]
                    txt = model.analog_display_text(self._row, spec.param_id, c, decimals=spec.decimals)
                    ed.set_committed_display(txt)
        self.set_timeline_read_only(self._state.timeline_read_only)
