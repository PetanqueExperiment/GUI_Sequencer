from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, pyqtSignal
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
from sequencer_gui.software_objects.static.registry import apply_abs_tol_for
from sequencer_gui.software_objects.types import AnalogParameterSpec
from sequencer_gui.static_remote import (
    ApplyStaticResult,
    DetectRowResult,
    apply_static_param_result,
    detect_remote_hero,
)
from sequencer_gui.ui.value_input import AnalogValueLineEdit, parse_analog_value

_PANEL_EXPANDED_WIDTH_PX = 340
_COLLAPSED_STRIP_WIDTH_PX = 28
_LABEL_MIN_WIDTH_PX = 108

_STYLE_IDLE = "color: #616161;"
_STYLE_OK = "color: #2e7d32;"
_STYLE_ERR = "color: #c62828;"
_STATUS_PREFIX = "Status:"
_ROW_SEPARATOR_STYLE = "background-color: #000000; border: none; min-height: 2px; max-height: 2px;"



def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class _DetectWorker(QThread):
    finished_ok = pyqtSignal(object)  # list[DetectRowResult]
    finished_err = pyqtSignal(str)

    def __init__(self, targets: list[tuple[int, str]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._targets = targets

    def run(self) -> None:
        try:
            results: list[DetectRowResult] = []
            for row, hero_name in self._targets:
                found, err = detect_remote_hero(hero_name)
                results.append(DetectRowResult(row=row, hero_name=hero_name, found=found, error=err))
            self.finished_ok.emit(results)
        except Exception as e:
            self.finished_err.emit(str(e))


class _ApplyWorker(QThread):
    finished_result = pyqtSignal(object)  # ApplyStaticResult

    def __init__(
        self,
        row: int,
        hero_name: str,
        param_id: str,
        value: float,
        *,
        abs_tol: float,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._row = row
        self._hero_name = hero_name
        self._param_id = param_id
        self._value = value
        self._abs_tol = abs_tol

    def run(self) -> None:
        self.finished_result.emit(
            apply_static_param_result(
                self._row,
                self._hero_name,
                self._param_id,
                self._value,
                abs_tol=self._abs_tol,
            )
        )


class StaticParametersPanel(QWidget):
    """Between-shot parameters: one value per device for the full sequence (not per timeline step)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._expanded = False
        self._structure_sig: tuple[int, tuple[str, ...]] | None = None
        self._row_widgets: list[_StaticRowWidgets] = []
        self._detect_worker: _DetectWorker | None = None
        self._apply_workers: list[_ApplyWorker] = []

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

        detect_row = QHBoxLayout()
        detect_row.setSpacing(6)
        self._detect_btn = QPushButton("Detect")
        self._detect_btn.setToolTip(
            "Try to reach every remote static device (HERO) on the network."
        )
        self._detect_btn.clicked.connect(self._on_detect)
        detect_row.addWidget(self._detect_btn, 0)
        self._add_btn = QPushButton("Add")
        self._add_btn.setToolTip("Add a static device (VOA, waveplate, …).")
        self._add_btn.clicked.connect(self._on_add_device)
        detect_row.addWidget(self._add_btn, 0)
        self._detect_summary = QLabel("")
        self._detect_summary.setStyleSheet(_STYLE_IDLE)
        self._detect_summary.setWordWrap(True)
        detect_row.addWidget(self._detect_summary, 1)
        content_layout.addLayout(detect_row)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(8)
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
            self.setMinimumHeight(0)
            self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self._content.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
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
        self._detect_summary.setText("")
        self._detect_summary.setStyleSheet(_STYLE_IDLE)

        has_types = bool(iter_static_objects())
        self._add_btn.setEnabled(has_types)

        if not has_types:
            hint = QLabel(
                "No static device types yet.\n\n"
                "Register types under software_objects/static/."
            )
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignTop)
            hint.setStyleSheet("color: #616161;")
            self._body_layout.addWidget(hint)
            self._body_layout.addStretch(1)
            self._detect_btn.setEnabled(False)
            return

        if doc.static_rows < 1:
            hint = QLabel("No static devices.\n\nUse Add to create one.")
            hint.setWordWrap(True)
            hint.setAlignment(Qt.AlignTop)
            hint.setStyleSheet("color: #616161;")
            self._body_layout.addWidget(hint)
            self._body_layout.addStretch(1)
            self._detect_btn.setEnabled(False)
            return

        self._detect_btn.setEnabled(True)
        for row in range(doc.static_rows):
            if row > 0:
                sep = QFrame()
                sep.setFrameShape(QFrame.HLine)
                sep.setFrameShadow(QFrame.Plain)
                sep.setStyleSheet(_ROW_SEPARATOR_STYLE)
                sep.setFixedHeight(2)
                self._body_layout.addWidget(sep)
            rw = _StaticRowWidgets(row, self._state, self._body)
            rw.apply_requested.connect(self._on_apply_requested)
            rw.remove_requested.connect(self._on_remove_requested)
            self._body_layout.addWidget(rw.container)
            self._row_widgets.append(rw)

        self._body_layout.addStretch(1)
        self._sync_labels()
        self._sync_values()

    def _on_add_device(self) -> None:
        self._state.add_static_device()

    def _on_remove_requested(self, row: int) -> None:
        self._state.remove_static_device(row)

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

    def _on_detect(self) -> None:
        if self._detect_worker is not None and self._detect_worker.isRunning():
            return
        doc = self._state.document
        targets: list[tuple[int, str]] = []
        for row in range(doc.static_rows):
            if not doc.static_is_remote(row):
                continue
            name = doc.static_hero_name(row)
            targets.append((row, name))
            for rw in self._row_widgets:
                if rw.row == row:
                    rw.set_link_status("Detecting…", _STYLE_IDLE)
        if not targets:
            self._detect_summary.setText("No remote devices")
            self._detect_summary.setStyleSheet(_STYLE_IDLE)
            return

        self._detect_btn.setEnabled(False)
        self._detect_summary.setText("Detecting…")
        self._detect_summary.setStyleSheet(_STYLE_IDLE)
        worker = _DetectWorker(targets, self)
        worker.finished_ok.connect(self._on_detect_finished)
        worker.finished_err.connect(self._on_detect_failed)
        worker.finished.connect(worker.deleteLater)
        self._detect_worker = worker
        worker.start()

    def _on_detect_finished(self, results: object) -> None:
        self._detect_worker = None
        self._detect_btn.setEnabled(True)
        rows = list(results) if isinstance(results, list) else []
        found_n = sum(1 for r in rows if isinstance(r, DetectRowResult) and r.found)
        total = len(rows)
        self._detect_summary.setText(f"Detected {found_n}/{total}")
        self._detect_summary.setStyleSheet(_STYLE_OK if found_n == total and total else _STYLE_ERR)
        by_row = {r.row: r for r in rows if isinstance(r, DetectRowResult)}
        for rw in self._row_widgets:
            res = by_row.get(rw.row)
            if res is None:
                continue
            if res.found:
                rw.set_link_status("Found", _STYLE_OK)
            else:
                msg = res.error or "Missing"
                rw.set_link_status(f"Missing ({msg})" if res.error else "Missing", _STYLE_ERR)

    def _on_detect_failed(self, message: str) -> None:
        self._detect_worker = None
        self._detect_btn.setEnabled(True)
        self._detect_summary.setText(message)
        self._detect_summary.setStyleSheet(_STYLE_ERR)

    def _on_apply_requested(self, row: int, param_id: str, value: float) -> None:
        doc = self._state.document
        if not (0 <= row < doc.static_rows) or not doc.static_is_remote(row):
            return
        hero_name = doc.static_hero_name(row)
        abs_tol = apply_abs_tol_for(doc.static_software_name(row))
        for rw in self._row_widgets:
            if rw.row == row:
                rw.set_link_status("Applying…", _STYLE_IDLE)
        worker = _ApplyWorker(
            row, hero_name, param_id, value, abs_tol=abs_tol, parent=self
        )
        worker.finished_result.connect(self._on_apply_finished)
        worker.finished.connect(lambda w=worker: self._drop_apply_worker(w))
        self._apply_workers.append(worker)
        worker.start()

    def _drop_apply_worker(self, worker: _ApplyWorker) -> None:
        if worker in self._apply_workers:
            self._apply_workers.remove(worker)
        worker.deleteLater()

    def _on_apply_finished(self, result: object) -> None:
        if not isinstance(result, ApplyStaticResult):
            return
        for rw in self._row_widgets:
            if rw.row != result.row:
                continue
            if result.ok and result.echoed is not None:
                rw.set_link_status(f"Applied {result.echoed:g}", _STYLE_OK)
            else:
                err = result.error or "Failed"
                rw.set_link_status(f"Failed: {err}", _STYLE_ERR)
            break

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._apply_expanded_state()


class _StaticRowWidgets(QWidget):
    apply_requested = pyqtSignal(int, str, float)  # row, param_id, value
    remove_requested = pyqtSignal(int)  # row

    def __init__(self, row: int, state: SequenceAppState, parent: QWidget) -> None:
        super().__init__(parent)
        self.row = row
        self._state = state
        self.container = self
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(4)
        self._label_edit = QLineEdit()
        self._label_edit.setMinimumWidth(_LABEL_MIN_WIDTH_PX)
        self._label_edit.setPlaceholderText("Name")
        self._label_edit.setToolTip(
            "Device name. For remote devices this is also the HERO instance name."
        )
        self._label_edit.editingFinished.connect(self._on_label_finished)
        head.addWidget(self._label_edit, 1)

        self._combo = QComboBox()
        for obj in iter_static_objects():
            self._combo.addItem(obj.display_name, obj.id)
        self._combo.currentIndexChanged.connect(self._on_combo_changed)
        head.addWidget(self._combo, 0)

        self._remove_btn = QPushButton("\u00d7")
        self._remove_btn.setFixedWidth(28)
        self._remove_btn.setToolTip("Remove this static device")
        self._remove_btn.clicked.connect(lambda: self.remove_requested.emit(self.row))
        head.addWidget(self._remove_btn, 0)
        layout.addLayout(head)

        self._link_status = QLabel(_STATUS_PREFIX)
        self._link_status.setStyleSheet(_STYLE_IDLE)
        self._link_status.setWordWrap(True)
        self._link_status.setVisible(False)
        layout.addWidget(self._link_status)

        self._value_edits: list[tuple[AnalogParameterSpec, AnalogValueLineEdit]] = []
        self._value_box = QVBoxLayout()
        self._value_box.setSpacing(2)
        layout.addLayout(self._value_box)

    def delete(self) -> None:
        self.deleteLater()

    def set_link_status(self, text: str, style: str) -> None:
        detail = (text or "").strip()
        if detail.lower().startswith("status:"):
            detail = detail[7:].strip()
        self._link_status.setText(f"{_STATUS_PREFIX} {detail}" if detail else _STATUS_PREFIX)
        self._link_status.setStyleSheet(style)
        self._link_status.setVisible(True)

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

        remote = doc.static_is_remote(self.row)
        if remote:
            self._link_status.setVisible(True)
            if not self._link_status.text().startswith(_STATUS_PREFIX):
                self.set_link_status("", _STYLE_IDLE)
        else:
            self._link_status.setVisible(False)

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
        if self._state.document.static_is_remote(self.row):
            self.apply_requested.emit(self.row, spec.param_id, x)
