from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractSpinBox,
    QDoubleSpinBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import get_object
from sequencer_gui.ui.row_software_selector import RowSoftwareSelector

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

# Match RowSoftwareSelector maximum width; shared with ChannelMatrix Time row column 0.
LABEL_COL_MIN_WIDTH_PX = 160


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


class DeviceRowWidget(QWidget):
    """One sequencer row: label + software combo, tall channel toggles, 0..N analog parameter rows."""

    def __init__(self, row: int, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self._state = state
        self._buttons: list[QPushButton] = []
        self._analog_spins: list[list[QDoubleSpinBox]] = []
        self._param_sig: tuple[str, ...] = ()
        self._analog_row_widgets: list[QWidget] = []

        m = state.model
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(4)
        self._grid.setVerticalSpacing(4)
        self._grid.setColumnMinimumWidth(0, LABEL_COL_MIN_WIDTH_PX)

        header = QWidget()
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
        hlay.addWidget(self._sw)

        self._grid.addWidget(header, 0, 0, 2, 1)

        for c in range(m.cols):
            btn = QPushButton()
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumWidth(40)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
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

        self.set_timeline_read_only(state.timeline_read_only)

    def set_timeline_read_only(self, read_only: bool) -> None:
        for btn in self._buttons:
            btn.setEnabled(not read_only)
        for row in self._analog_spins:
            for sp in row:
                sp.setEnabled(not read_only)

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
        self._analog_spins = []

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
            lab.setMinimumWidth(LABEL_COL_MIN_WIDTH_PX)
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            self._grid.addWidget(lab, g_row, 0)
            self._analog_row_widgets.append(lab)

            spins_row: list[QDoubleSpinBox] = []
            for c in range(cols):
                sp = QDoubleSpinBox()
                sp.setButtonSymbols(QAbstractSpinBox.NoButtons)
                sp.setRange(spec.minimum, spec.maximum)
                sp.setDecimals(spec.decimals)
                sp.setSingleStep(spec.single_step)
                sp.setMinimumWidth(72)
                sp.setValue(model.analog_value(self._row, spec.param_id, c))
                pid = spec.param_id

                def make_a(rr: int, param_id: str, cc: int):
                    def on_value(v: float) -> None:
                        self._state.set_analog(rr, param_id, cc, v)

                    return on_value

                sp.valueChanged.connect(make_a(self._row, pid, c))
                sp.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
                self._grid.addWidget(sp, g_row, c + 1)
                spins_row.append(sp)
                self._analog_row_widgets.append(sp)
            self._analog_spins.append(spins_row)
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
                if pi >= len(self._analog_spins):
                    break
                for c in range(min(model.cols, len(self._analog_spins[pi]))):
                    sp = self._analog_spins[pi][c]
                    v = model.analog_value(self._row, spec.param_id, c)
                    sp.blockSignals(True)
                    sp.setValue(v)
                    sp.blockSignals(False)
        for c in range(min(model.cols, len(self._buttons))):
            btn = self._buttons[c]
            btn.blockSignals(True)
            btn.setChecked(model.channel(self._row, c))
            btn.blockSignals(False)
        self.set_timeline_read_only(self._state.timeline_read_only)
