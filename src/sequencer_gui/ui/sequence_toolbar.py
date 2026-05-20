from __future__ import annotations

from pathlib import Path

from PyQt5.QtWidgets import (
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import complete_cycle_rate_hz, complete_timeline_duration_us
from sequencer_gui.persistence import save_last_sequence_path
from sequencer_gui.process_identity import PYCAM_HERO_INSTANCE_NAME, PYCAM_LIVE_EXPERIMENT_NAME
from sequencer_gui.pycam_experiment import prepare_live_experiment, sync_live_experiment_name
from sequencer_gui.sequence_io import (
    SequenceFileError,
    load_sequence,
    save_sequence,
    validate_document_for_ui,
)


class SequenceToolbar(QGroupBox):
    """Name, save, and load sequence files (JSON)."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Sequence", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(QLabel("File:"))
        self._name = QLineEdit(state.sequence_name)
        self._name.setPlaceholderText("Sequence file (.json)")
        self._name.setMinimumWidth(280)
        self._name.setToolTip("Saved sequence path, or a name before the first save.")
        self._name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._name.editingFinished.connect(self._on_name_edited)
        name_row.addWidget(self._name, 1)
        outer.addLayout(name_row)

        timing_row = QHBoxLayout()
        timing_row.setSpacing(8)
        timing_row.addWidget(QLabel("Duration:"))
        self._duration = QLabel()
        self._duration.setToolTip("Total time of the Complete sequence (enabled blocks only).")
        timing_row.addWidget(self._duration)
        timing_row.addSpacing(12)
        timing_row.addWidget(QLabel("Cycle rate:"))
        self._cycle_rate = QLabel()
        self._cycle_rate.setToolTip("Expected experiment rate: 1 / duration (enabled blocks only).")
        timing_row.addWidget(self._cycle_rate)
        timing_row.addStretch(1)
        outer.addLayout(timing_row)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(8)
        self._run_btn = QPushButton()
        self._run_btn.setCheckable(True)
        self._run_btn.setChecked(state.run_sequence)
        self._run_btn.setToolTip(
            "Live run/pause (PyCam repo "
            f"{PYCAM_LIVE_EXPERIMENT_NAME!r}; disabled while a scan is running)."
        )
        self._run_btn.toggled.connect(self._on_run_toggled)
        self._update_run_button_text(state.run_sequence)
        state.run_sequence_changed.connect(self._on_run_sequence_changed)
        state.scan_running_changed.connect(self._on_scan_running_changed)
        self._on_scan_running_changed(state.scan_running)
        actions_row.addWidget(self._run_btn, 0)

        btn_save = QPushButton("Save…")
        btn_save.clicked.connect(self._on_save)
        actions_row.addWidget(btn_save)

        btn_load = QPushButton("Load…")
        btn_load.clicked.connect(self._on_load)
        actions_row.addWidget(btn_load)
        actions_row.addStretch(1)
        outer.addLayout(actions_row)
        outer.addStretch(1)

        state.sequence_name_changed.connect(self._on_sequence_name_changed)
        state.document_changed.connect(self._refresh_timing)
        state.delays_changed.connect(self._refresh_timing)
        self._refresh_timing()

    def _refresh_timing(self) -> None:
        doc = self._state.document
        ms = complete_timeline_duration_us(doc) / 1000.0
        self._duration.setText(f"{ms:.0f} ms")
        hz = complete_cycle_rate_hz(doc)
        self._cycle_rate.setText("—" if hz is None else f"{hz:.1f} Hz")

    def _on_sequence_name_changed(self, name: str) -> None:
        if self._name.text() != name:
            self._name.blockSignals(True)
            self._name.setText(name)
            self._name.blockSignals(False)

    def _update_run_button_text(self, on: bool) -> None:
        # ``on`` = allow running; button shows "Pause" to mean "click to pause".
        self._run_btn.setText("Running" if on else "Paused")

    def _on_scan_running_changed(self, running: bool) -> None:
        self._run_btn.setEnabled(not running)

    def _sync_pycam_live_experiment(self, *, start: bool) -> None:
        try:
            from heros import RemoteHERO
        except ImportError as e:
            raise RuntimeError("HERO support is not installed; cannot reach PyCam.") from e
        with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
            if start:
                prepare_live_experiment(hero)
            else:
                sync_live_experiment_name(hero)

    def _on_run_toggled(self, checked: bool) -> None:
        if self._state.scan_running:
            return
        try:
            self._sync_pycam_live_experiment(start=checked)
        except Exception as e:
            QMessageBox.warning(self, "Run / pause", str(e))
            self._run_btn.blockSignals(True)
            self._run_btn.setChecked(not checked)
            self._run_btn.blockSignals(False)
            self._update_run_button_text(not checked)
            return
        if checked:
            self._state.resume_live_sequence()
        else:
            self._state.set_run_sequence(False)
        self._update_run_button_text(checked)

    def _on_run_sequence_changed(self, on: bool) -> None:
        if self._run_btn.isChecked() != on:
            self._run_btn.blockSignals(True)
            self._run_btn.setChecked(on)
            self._run_btn.blockSignals(False)
        self._update_run_button_text(on)

    def _on_name_edited(self) -> None:
        self._state.set_sequence_name(self._name.text())

    @staticmethod
    def _name_for_json_file(raw: str) -> str:
        text = raw.strip()
        if not text:
            return "Untitled"
        p = Path(text)
        if p.suffix.lower() == ".json":
            return p.stem or "Untitled"
        return text

    def _save_dialog_initial_path(self, default_stem: str) -> str:
        raw = self._name.text().strip()
        if raw:
            p = Path(raw)
            if p.suffix.lower() == ".json":
                if p.is_file():
                    return str(p.resolve())
                parent = p.parent if p.parent != Path(".") else Path.home()
                return str(parent / p.name)
        safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in default_stem)[:80]
        return str(Path.home() / f"{safe}.json")

    def _on_save(self) -> None:
        name = self._name_for_json_file(self._name.text())
        path_str, _ = QFileDialog.getSaveFileName(
            self,
            "Save sequence",
            self._save_dialog_initial_path(name),
            "JSON sequence (*.json);;All files (*.*)",
        )
        if not path_str:
            return
        resolved = str(Path(path_str).resolve())
        try:
            save_sequence(path_str, name, self._state.document)
            save_last_sequence_path(resolved)
        except OSError as e:
            QMessageBox.warning(self, "Save failed", str(e))
            return
        self._state.set_sequence_name(resolved)

    def _on_load(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self,
            "Load sequence",
            str(Path.home()),
            "JSON sequence (*.json);;All files (*.*)",
        )
        if not path_str:
            return
        try:
            _, document = load_sequence(path_str)
        except SequenceFileError as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return
        except OSError as e:
            QMessageBox.warning(self, "Load failed", str(e))
            return

        err = validate_document_for_ui(document)
        if err is not None:
            QMessageBox.warning(self, "Load failed", err)
            return

        resolved = str(Path(path_str).resolve())
        save_last_sequence_path(resolved)
        self._state.set_sequence_name(resolved)
        self._state.replace_document(document, active_tab=0)
