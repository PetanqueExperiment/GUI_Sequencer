from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QStringListModel, QTimer
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QCompleter,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import ScanParameter, SequenceAppState
from sequencer_gui.process_identity import PYCAM_HERO_INSTANCE_NAME
from sequencer_gui.pycam_repository import ScanLabelAvailability, classify_scan_label
from sequencer_gui.pycam_experiment import (
    prepare_and_start_experiment,
    set_parameter_scan_order,
    shots_seen,
    stop_experiment_if_running,
)
from sequencer_gui.scan_plan import (
    anticipated_scan_duration_s,
    build_scan_tags,
    format_duration_hms,
    is_delay_scan_device,
    resolve_scan_bindings,
)
from sequencer_gui.software_objects import get_object
from sequencer_gui.ui.row_software_selector import _NoWheelComboBox

_PYCAM_PREP_DELAY_S = 0.3

_LABEL_STYLE_DEFAULT = "color: #212121;"
_LABEL_STYLE_BY_AVAILABILITY = {
    ScanLabelAvailability.UNUSED: "color: #c62828;",
    ScanLabelAvailability.USED_TODAY: "color: #1565c0;",
    ScanLabelAvailability.IN_PROGRESS: "color: #2e7d32;",
}
_LABEL_TOOLTIP = (
    "Name of the scan experiment to perform (PyCam data folder for today).\n"
    "Red: new name (no folder yet today).\n"
    "Blue: name already used today.\n"
    "Green: scan in progress with this name."
)


class ScanPanel(QGroupBox):
    """Scan configuration: matrix values per step, repetitions per value, PyCam tagging."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Scan", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        controls = QVBoxLayout()
        controls.setSpacing(6)

        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_row.addWidget(QLabel("Label:"))
        self._label = QLineEdit(state.scan_label)
        self._label.setPlaceholderText("Experiment name")
        self._label.setMinimumWidth(140)
        self._label.setToolTip(_LABEL_TOOLTIP)
        self._label.textChanged.connect(self._update_label_color)
        self._label.editingFinished.connect(self._on_label_edited)
        label_row.addWidget(self._label, 1)
        controls.addLayout(label_row)

        reps = QHBoxLayout()
        reps.setSpacing(8)
        reps.addWidget(QLabel("Repetitions:"))
        self._repetitions = QLineEdit(str(state.scan_repetitions))
        self._repetitions.setValidator(QIntValidator(1, 999_999, self))
        self._repetitions.setMaximumWidth(72)
        self._repetitions.setToolTip("Number of shots at each scan parameter value")
        self._repetitions.editingFinished.connect(self._on_repetitions_edited)
        reps.addWidget(self._repetitions, 0)
        controls.addLayout(reps)

        scan_actions = QHBoxLayout()
        scan_actions.setSpacing(8)
        self._btn_start_scan = QPushButton("Start scan")
        self._btn_start_scan.setToolTip("Start the configured scan")
        self._btn_start_scan.clicked.connect(self._on_start_scan)
        scan_actions.addWidget(self._btn_start_scan)
        self._btn_interrupt = QPushButton("Interrupt")
        self._btn_interrupt.setEnabled(False)
        self._btn_interrupt.setToolTip("Stop the running scan")
        self._btn_interrupt.clicked.connect(self._on_interrupt)
        scan_actions.addWidget(self._btn_interrupt)
        controls.addLayout(scan_actions)

        self._duration_label = QLabel()
        self._duration_label.setToolTip(
            "Estimated total sequence runtime for all scan points and repetitions "
            "(enabled blocks only; per-point duration when scanning timestep delays)."
        )
        controls.addWidget(self._duration_label)

        controls.addStretch(1)

        row.addLayout(controls, 0)

        self._cards_host = QWidget()
        self._cards_layout = QHBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._cards_scroll.setWidget(self._cards_host)
        row.addWidget(self._cards_scroll, 1)

        self._btn_add_param = QPushButton("Add parameter")
        self._btn_add_param.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_add_param.setToolTip("Add a parameter axis to the scan (name and list of values)")
        self._btn_add_param.clicked.connect(self._state.add_scan_parameter)
        row.addWidget(self._btn_add_param, 0, Qt.AlignTop)

        state.scan_label_changed.connect(self._sync_label_from_state)
        state.scan_repetitions_changed.connect(self._sync_repetitions_from_state)
        state.scan_parameters_changed.connect(self._rebuild_param_cards)
        state.row_labels_changed.connect(self._rebuild_param_cards)
        state.scan_running_changed.connect(self._apply_scan_running_ui)
        state.scan_running_changed.connect(lambda _running: self._update_label_color())
        state.document_changed.connect(self._update_anticipated_duration)
        state.delays_changed.connect(self._update_anticipated_duration)
        state.scan_parameters_changed.connect(self._update_anticipated_duration)
        state.scan_repetitions_changed.connect(self._update_anticipated_duration)
        self._rebuild_param_cards()
        self._apply_scan_running_ui(state.scan_running)
        self._update_anticipated_duration()

        self._label_color_poll = QTimer(self)
        self._label_color_poll.timeout.connect(self._update_label_color)
        self._label_color_poll.start(2000)
        self._update_label_color()

        self._scan_expected_shots = 0
        self._scan_repetitions = 1
        self._scan_points: list = []
        self._scan_step_index = 0
        self._pycam_poll = QTimer(self)
        self._pycam_poll.timeout.connect(self._poll_scan_shots)

    def _sync_label_from_state(self, value: str) -> None:
        self._label.blockSignals(True)
        self._label.setText(value)
        self._label.blockSignals(False)
        self._update_label_color()

    def _on_label_edited(self) -> None:
        self._state.set_scan_label(self._label.text().strip())

    def _update_label_color(self) -> None:
        status = classify_scan_label(
            self._label.text(),
            scan_running=self._state.scan_running,
            active_scan_label=self._state.scan_label,
        )
        style = _LABEL_STYLE_BY_AVAILABILITY.get(status, _LABEL_STYLE_DEFAULT)
        if self._label.styleSheet() != style:
            self._label.setStyleSheet(style)

    def _sync_repetitions_from_state(self, value: int) -> None:
        self._repetitions.blockSignals(True)
        self._repetitions.setText(str(value))
        self._repetitions.blockSignals(False)

    def _on_scan_param_combo_changed(self, index: int, combo: _NoWheelComboBox) -> None:
        if combo.currentIndex() < 0:
            return
        param_id = combo.currentData()
        if param_id is None:
            return
        self._state.set_scan_parameter_param_id(index, str(param_id))

    def _on_repetitions_edited(self) -> None:
        text = self._repetitions.text().strip()
        if not text:
            self._sync_repetitions_from_state(self._state.scan_repetitions)
            return
        n = int(text)
        self._state.set_scan_repetitions(n)

    def _update_anticipated_duration(self) -> None:
        seconds = anticipated_scan_duration_s(
            self._state.document,
            self._state.scan_parameters,
            self._state.scan_repetitions,
        )
        if seconds is None:
            self._duration_label.setText("Anticipated duration: —")
            return
        self._duration_label.setText(
            f"Anticipated duration: {format_duration_hms(seconds)}"
        )

    def _apply_scan_running_ui(self, running: bool) -> None:
        self._btn_start_scan.setEnabled(not running)
        self._btn_start_scan.setText("Scan running" if running else "Start scan")
        self._btn_interrupt.setEnabled(running)
        self._label.setEnabled(not running)
        self._repetitions.setEnabled(not running)
        self._btn_add_param.setEnabled(not running)
        self._cards_scroll.setEnabled(not running)

    def _on_start_scan(self) -> None:
        if self._state.scan_running:
            return
        self._on_label_edited()
        self._on_repetitions_edited()
        name = self._state.scan_label.strip()
        if not name:
            QMessageBox.warning(self, "Start scan", "Enter a scan label (PyCam experiment name).")
            return
        shots = self._state.scan_repetitions
        try:
            if self._state.scan_parameters:
                resolve_scan_bindings(self._state.document, self._state.scan_parameters)
            scan_points = self._state.build_scan_points()
            scan_tags = build_scan_tags(self._state.scan_parameters, shots)
        except ValueError as e:
            QMessageBox.warning(self, "Start scan", str(e))
            return
        self._scan_expected_shots = len(scan_tags)
        self._scan_repetitions = shots
        self._scan_points = scan_points
        self._scan_step_index = 0

        self._state.set_run_sequence(False)
        if self._state.run_sequence:
            QMessageBox.warning(self, "Start scan", "Sequence did not pause.")
            return

        time.sleep(_PYCAM_PREP_DELAY_S)

        try:
            from heros import RemoteHERO
        except ImportError:
            QMessageBox.warning(
                self,
                "Start scan",
                "HERO support is not installed; cannot reach PyCam.",
            )
            return
        try:
            with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as pycam_hero:
                set_parameter_scan_order(pycam_hero, scan_tags)
                prepare_and_start_experiment(pycam_hero, name)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Start scan",
                f"PyCam scan start failed ({PYCAM_HERO_INSTANCE_NAME}):\n{e}",
            )
            return

        self._state.prepare_scan_matrix_restore()
        self._state.set_scan_running(True)
        self._begin_scan_step(0)
        self._pycam_poll.start(500)

    def _pycam_shots_done_for_step(self, shots_seen_count: int, step_index: int) -> bool:
        return shots_seen_count >= (step_index + 1) * self._scan_repetitions

    def _begin_scan_step(self, step_index: int) -> None:
        if not (0 <= step_index < len(self._scan_points)):
            return
        self._scan_step_index = step_index
        if self._state.run_sequence:
            self._state.set_run_sequence(False)
        self._state.apply_scan_point(self._scan_points[step_index])
        self._state.resume_sequence_for_scan_shots(self._scan_repetitions)

    def _advance_scan_if_ready(self, shots_seen_count: int) -> None:
        if not self._pycam_shots_done_for_step(shots_seen_count, self._scan_step_index):
            return
        next_step = self._scan_step_index + 1
        if next_step < len(self._scan_points):
            self._begin_scan_step(next_step)
            return
        if shots_seen_count >= self._scan_expected_shots:
            self._finish_scan()

    def _finish_scan(self) -> None:
        self._pycam_poll.stop()
        self._scan_expected_shots = 0
        self._scan_points = []
        self._scan_step_index = 0
        if self._state.run_sequence:
            self._state.set_run_sequence(False)
        self._state.restore_scan_matrix()
        self._state.set_scan_running(False)
        self._state.poll_host_run_sequence()
        try:
            from heros import RemoteHERO
        except ImportError:
            return
        try:
            with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
                stop_experiment_if_running(hero)
        except Exception:
            pass

    def _poll_scan_shots(self) -> None:
        if not self._state.scan_running:
            return
        try:
            from heros import RemoteHERO
        except ImportError:
            return
        try:
            with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
                seen = shots_seen(hero)
                if self._scan_points:
                    self._advance_scan_if_ready(seen)
                elif seen >= self._scan_expected_shots:
                    self._finish_scan()
        except Exception:
            return

    def _on_interrupt(self) -> None:
        if not self._state.scan_running:
            return
        try:
            from heros import RemoteHERO
        except ImportError:
            QMessageBox.warning(
                self,
                "Interrupt",
                "HERO support is not installed; cannot reach PyCam.",
            )
            return
        try:
            with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
                stop_experiment_if_running(hero)
        except Exception as e:
            QMessageBox.warning(
                self,
                "Interrupt",
                f"Failed to stop PyCam ({PYCAM_HERO_INSTANCE_NAME}):\n{e}",
            )
            return
        self._state.set_run_sequence(False)
        self._finish_scan()

    def _rebuild_param_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for i, p in enumerate(self._state.scan_parameters):
            self._cards_layout.addWidget(self._make_param_card(i, p))

        self._cards_host.adjustSize()
        self._update_anticipated_duration()
        if self._state.scan_parameters:
            card_h = max(
                self._cards_layout.itemAt(i).widget().sizeHint().height()
                for i in range(self._cards_layout.count())
            )
            self._cards_scroll.setMinimumHeight(card_h)
        else:
            self._cards_scroll.setMinimumHeight(0)
        self.updateGeometry()

    def _row_index_for_device_label(self, device_label: str) -> int | None:
        label = device_label.strip()
        if not label:
            return None
        try:
            return self._state.document.row_labels.index(label)
        except ValueError:
            return None

    def _label_from_index_field_text(self, raw: str, labels: tuple[str, ...]) -> str:
        """0-based index (as in the channel matrix header) -> label; otherwise unchanged."""
        text = raw.strip()
        if not text.isdigit():
            return text
        idx = int(text)
        if 0 <= idx < len(labels):
            label = labels[idx].strip()
            if label:
                return label
        return text

    def _device_label_from_field_text(self, raw: str) -> str:
        return self._label_from_index_field_text(raw, self._state.document.row_labels)

    def _timestep_label_from_field_text(self, raw: str) -> str:
        return self._label_from_index_field_text(raw, self._state.model.col_labels)

    def _populate_param_combo(
        self, combo: _NoWheelComboBox, device_label: str, selected_param_id: str
    ) -> str:
        combo.blockSignals(True)
        combo.clear()
        if is_delay_scan_device(device_label):
            combo.addItem("Duration (µs)", "time")
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
            combo.blockSignals(False)
            return "time"
        combo.setEnabled(True)
        row = self._row_index_for_device_label(device_label)
        param_id = selected_param_id
        if row is not None:
            obj = get_object(self._state.document.row_software[row])
            for spec in obj.analog_parameters:
                combo.addItem(spec.label, spec.param_id)
        if combo.count() > 0:
            idx = combo.findData(param_id) if param_id else -1
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            data = combo.itemData(idx)
            param_id = str(data) if data is not None else ""
        else:
            param_id = ""
        combo.blockSignals(False)
        return param_id

    def _make_param_card(self, index: int, p: ScanParameter) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setFixedWidth(400)
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(6)

        btn_remove = QPushButton("\u00d7")
        btn_remove.setFixedSize(22, 22)
        btn_remove.setFlat(True)
        btn_remove.setToolTip("Remove parameter")
        btn_remove.clicked.connect(lambda checked=False, idx=index: self._state.remove_scan_parameter(idx))
        top.addWidget(btn_remove, 0, Qt.AlignLeft | Qt.AlignVCenter)

        device_labels = list(self._state.document.row_labels)
        for alias in ("time", "t"):
            if alias not in device_labels:
                device_labels.append(alias)
        device_edit = QLineEdit(p.device_label)
        device_edit.setPlaceholderText("Device or time")
        device_edit.setToolTip(
            "Row label of the device in the sequence, or time / t to scan the "
            "selected timestep duration (µs). "
            "Enter a 0-based row index and press Enter to fill the label."
        )
        device_edit.setCompleter(QCompleter(QStringListModel(device_labels), device_edit))
        param_combo = _NoWheelComboBox()
        param_combo.setMinimumWidth(110)
        param_combo.setToolTip(
            "Analog parameter of the selected device (fixed to duration when device is time / t)"
        )
        current_param_id = self._populate_param_combo(param_combo, p.device_label, p.param_id)
        if current_param_id != p.param_id:
            self._state.set_scan_parameter_param_id(index, current_param_id)

        def on_device_edited(
            idx: int = index,
            dev: QLineEdit = device_edit,
            combo: _NoWheelComboBox = param_combo,
        ) -> None:
            raw = dev.text().strip()
            if is_delay_scan_device(raw):
                label = raw.lower()
            else:
                label = self._device_label_from_field_text(dev.text())
            if label != dev.text().strip():
                dev.blockSignals(True)
                dev.setText(label)
                dev.blockSignals(False)
            self._state.set_scan_parameter_device_label(idx, label)
            new_param_id = self._populate_param_combo(combo, label, self._state.scan_parameters[idx].param_id)
            if new_param_id != self._state.scan_parameters[idx].param_id:
                self._state.set_scan_parameter_param_id(idx, new_param_id)

        device_edit.editingFinished.connect(on_device_edited)
        top.addWidget(device_edit, 1)

        param_combo.currentIndexChanged.connect(
            lambda _i, idx=index, combo=param_combo: self._on_scan_param_combo_changed(idx, combo)
        )
        top.addWidget(param_combo, 0)

        timestep_edit = QLineEdit(p.timestep_label)
        timestep_edit.setPlaceholderText("Timestep label")
        timestep_edit.setMinimumWidth(100)
        timestep_edit.setToolTip(
            "Label of the timestep this parameter drives. "
            "Enter a 0-based column index and press Enter to fill the label."
        )
        timestep_edit.setCompleter(
            QCompleter(QStringListModel(list(self._state.model.col_labels)), timestep_edit)
        )

        def on_timestep_edited(idx: int = index, edit: QLineEdit = timestep_edit) -> None:
            label = self._timestep_label_from_field_text(edit.text())
            if label != edit.text().strip():
                edit.blockSignals(True)
                edit.setText(label)
                edit.blockSignals(False)
            self._state.set_scan_parameter_timestep_label(idx, label)

        timestep_edit.editingFinished.connect(on_timestep_edited)
        top.addWidget(timestep_edit, 0)

        outer.addLayout(top)

        values_edit = QLineEdit(p.values_text)
        values_edit.setPlaceholderText("e.g. 1, 2, 3")
        values_edit.setToolTip(
            "Comma-separated values for this parameter (µs when device is time / t)"
        )
        values_edit.editingFinished.connect(
            lambda idx=index, e=values_edit: self._state.set_scan_parameter_values_text(idx, e.text())
        )
        values_edit.editingFinished.connect(lambda: self._update_anticipated_duration())
        outer.addWidget(values_edit)

        return frame
