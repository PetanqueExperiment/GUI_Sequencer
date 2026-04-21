from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
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

# One timeline step: delay spin, channel toggle, analog line edit (same width every row).
STEP_COLUMN_WIDTH_PX = 72
# Must match QGridLayout.setHorizontalSpacing on the row grid.
_GRID_H_SPACING_PX = 4


def timeline_content_width_px(cols: int) -> int:
    """Exact width of the timeline grid (label column + steps + inter-column spacing)."""
    if cols < 1:
        cols = 1
    return LABEL_COL_MIN_WIDTH_PX + cols * (STEP_COLUMN_WIDTH_PX + _GRID_H_SPACING_PX)


def _channel_button_stylesheet(row_index: int) -> str:
    c = _ROW_CHECKED_COLORS[row_index % len(_ROW_CHECKED_COLORS)]
    return f"""
        QPushButton {{
            border-radius: 6px;
            padding: 6px 8px;
            min-width: 32px;
            min-height: 22px;
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


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class DeviceRowWidget(QWidget):
    """One sequencer row: label + software combo, tall channel toggles, 0..N analog parameter rows."""

    def __init__(self, row: int, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self._state = state
        self._buttons: list[QPushButton] = []
        self._analog_edits: list[list[AnalogValueLineEdit]] = []
        self._param_sig: tuple[str, ...] = ()
        self._analog_row_widgets: list[QWidget] = []

        m = state.model
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(_GRID_H_SPACING_PX)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnMinimumWidth(0, LABEL_COL_MIN_WIDTH_PX)
        for col in range(1, m.cols + 1):
            self._grid.setColumnMinimumWidth(col, STEP_COLUMN_WIDTH_PX)
            self._grid.setColumnStretch(col, 0)
        self._grid.setColumnStretch(0, 0)

        header = QWidget()
        header.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        header.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        hlay = QVBoxLayout(header)
        hlay.setContentsMargins(0, 0, 0, 0)
        hlay.setSpacing(_HEADER_COL_SPACING_PX)

        self._edit = QLineEdit(m.row_label(row))
        self._edit.setMinimumWidth(40)
        self._edit.setMaximumWidth(120)
        self._edit.editingFinished.connect(self._on_row_label_finished)
        self._edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        hlay.addWidget(self._edit)

        self._sw = RowSoftwareSelector(row, state)
        self._sw.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
        hlay.addWidget(self._sw)

        self._grid.addWidget(header, 0, 0, 2, 1)

        for c in range(m.cols):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedWidth(STEP_COLUMN_WIDTH_PX)
            btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.MinimumExpanding)
            btn.setStyleSheet(_channel_button_stylesheet(row))
            btn.setChecked(m.channel(row, c))

            def make_toggle(rr: int, cc: int):
                def on_toggled(checked: bool) -> None:
                    self._state.set_channel(rr, cc, checked)

                return on_toggled

            btn.toggled.connect(make_toggle(row, c))
            self._buttons.append(btn)
            self._grid.addWidget(btn, 0, c + 1, 2, 1)

        self._rebuild_analog_section()

        self.setFixedWidth(timeline_content_width_px(m.cols))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        self.set_timeline_read_only(state.timeline_read_only)

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

    def _param_signature(self, model: SequenceModel) -> tuple[str, ...]:
        obj = get_object(model.row_software_name(self._row))
        return tuple(p.param_id for p in obj.analog_parameters)

    def _clear_analog_section(self) -> None:
        for w in self._analog_row_widgets:
            self._grid.removeWidget(w)
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
        base_row = 2
        for pi, spec in enumerate(obj.analog_parameters):
            g_row = base_row + pi
            lab = QLabel(spec.label)
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lab.setWordWrap(False)
            lab.setFixedWidth(LABEL_COL_MIN_WIDTH_PX)
            lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            self._grid.addWidget(lab, g_row, 0)
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
                self._grid.addWidget(ed, g_row, c + 1)
                edits_row.append(ed)
                self._analog_row_widgets.append(ed)
            self._analog_edits.append(edits_row)
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
        for c in range(min(model.cols, len(self._buttons))):
            btn = self._buttons[c]
            btn.blockSignals(True)
            btn.setChecked(model.channel(self._row, c))
            btn.blockSignals(False)
        self.set_timeline_read_only(self._state.timeline_read_only)
