from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QShowEvent
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.software_objects import get_static_object, iter_static_objects
from sequencer_gui.software_objects.types import AnalogParameterSpec
from sequencer_gui.ui.value_input import AnalogValueLineEdit, parse_analog_value

_PANEL_EXPANDED_WIDTH_PX = 300
_COLLAPSED_STRIP_WIDTH_PX = 28
_LABEL_MIN_WIDTH_PX = 108


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class StaticParametersPanel(QWidget):
    """Between-shot parameters: one value per device for the full sequence (not per timeline step)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._expanded = True
        self._structure_sig: tuple[int, tuple[str, ...]] | None = None
        self._row_widgets: list[_StaticRowWidgets] = []

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
            "Values held constant for the whole sequence (not per timestep in the matrix)."
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
        self._body_layout.setSpacing(6)
        self._scroll.setWidget(self._body)
        content_layout.addWidget(self._scroll, 1)

        outer.addWidget(self._content, 0)

        state.document_changed.connect(self._on_document_changed)
        state.static_labels_changed.connect(self._sync_labels)
        state.static_changed.connect(self._sync_values)
        self._on_document_changed(state.document)

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

    def _structure_signature(self, doc: SequenceDocument) -> tuple[int, tuple[str, ...]]:
        return (doc.static_rows, doc.static_software)

    def _on_document_changed(self, doc: SequenceDocument) -> None:
        sig = self._structure_signature(doc)
        if sig != self._structure_sig:
            self._rebuild(doc)
        else:
            self._sync_values()

    def _clear_rows(self) -> None:
        for rw in self._row_widgets:
            rw.delete()
        self._row_widgets.clear()
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _rebuild(self, doc: SequenceDocument) -> None:
        self._clear_rows()
        self._structure_sig = self._structure_signature(doc)

        if doc.static_rows < 1 or not iter_static_objects():
            hint = QLabel(
                "No static device types yet.\n\n"
                "Register types under software_objects/static/."
            )
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignTop)
            hint.setStyleSheet("color: #616161;")
            self._body_layout.addWidget(hint)
            self._body_layout.addStretch(1)
            return

        for row in range(doc.static_rows):
            rw = _StaticRowWidgets(row, self._state, self._body)
            self._body_layout.addWidget(rw.container)
            self._row_widgets.append(rw)

        self._body_layout.addStretch(1)
        self._sync_labels()
        self._sync_values()

    def _sync_labels(self) -> None:
        doc = self._state.document
        for rw in self._row_widgets:
            if rw.row < doc.static_rows:
                rw.sync_label(doc.static_label(rw.row))

    def _sync_values(self) -> None:
        doc = self._state.document
        for rw in self._row_widgets:
            if rw.row < doc.static_rows:
                rw.sync_values(doc)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_expanded_state()


class _StaticRowWidgets:
    def __init__(self, row: int, state: SequenceAppState, parent: QWidget) -> None:
        self.row = row
        self._state = state
        self.container = QWidget(parent)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(4)
        self._label_edit = QLineEdit()
        self._label_edit.setMinimumWidth(_LABEL_MIN_WIDTH_PX)
        self._label_edit.setPlaceholderText("Label")
        self._label_edit.editingFinished.connect(self._on_label_finished)
        head.addWidget(self._label_edit, 1)

        self._combo = QComboBox()
        for obj in iter_static_objects():
            self._combo.addItem(obj.display_name, obj.id)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        head.addWidget(self._combo, 0)
        layout.addLayout(head)

        self._value_edits: list[tuple[AnalogParameterSpec, AnalogValueLineEdit]] = []
        self._value_box = QVBoxLayout()
        self._value_box.setSpacing(2)
        layout.addLayout(self._value_box)

    def delete(self) -> None:
        self.container.deleteLater()

    def _on_label_finished(self) -> None:
        self._state.set_static_label(self.row, self._label_edit.text().strip())

    def _on_combo_changed(self, idx: int) -> None:
        if idx < 0:
            return
        oid = self._combo.itemData(idx)
        if oid is None:
            oid = self._combo.itemText(idx)
        self._state.set_static_software(self.row, str(oid))

    def sync_label(self, text: str) -> None:
        if self._label_edit.text() != text:
            self._label_edit.blockSignals(True)
            self._label_edit.setText(text)
            self._label_edit.blockSignals(False)

    def _rebuild_value_edits(self, doc: SequenceDocument) -> None:
        while self._value_box.count():
            item = self._value_box.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._value_edits.clear()

        obj = get_static_object(doc.static_software_name(self.row))
        for spec in obj.analog_parameters:
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(QLabel(spec.label))
            ed = AnalogValueLineEdit(spec)

            def make_return(edt: AnalogValueLineEdit, sp: AnalogParameterSpec):
                def on_return() -> None:
                    self._commit_value(edt, sp)

                return on_return

            ed.set_on_return(make_return(ed, spec))
            row.addWidget(ed, 1)
            wrap = QWidget()
            wrap.setLayout(row)
            self._value_box.addWidget(wrap)
            self._value_edits.append((spec, ed))

    def sync_values(self, doc: SequenceDocument) -> None:
        obj = get_static_object(doc.static_software_name(self.row))
        sig = tuple(p.param_id for p in obj.analog_parameters)
        if tuple(s.param_id for s, _ in self._value_edits) != sig:
            self._rebuild_value_edits(doc)

        self._combo.blockSignals(True)
        oid = doc.static_software_name(self.row)
        idx = self._combo.findData(oid)
        if idx < 0:
            idx = self._combo.findText(oid)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        self._combo.blockSignals(False)

        for spec, ed in self._value_edits:
            txt = doc.static_display_text(self.row, spec.param_id, decimals=spec.decimals)
            ed.set_committed_display(txt)

    def _commit_value(self, line: AnalogValueLineEdit, spec: AnalogParameterSpec) -> None:
        doc = self._state.document
        display_ok = doc.static_display_text(self.row, spec.param_id, decimals=spec.decimals)

        def revert() -> None:
            line.set_committed_display(display_ok)

        s = line.text().strip()
        if not s:
            revert()
            return
        parsed = parse_analog_value(s)
        if parsed is None or parsed == "hold":
            revert()
            return
        x = _clamp(float(parsed), spec.minimum, spec.maximum)
        self._state.set_static_value(self.row, spec.param_id, x)
        line.set_committed_display(
            self._state.document.static_display_text(self.row, spec.param_id, decimals=spec.decimals)
        )
