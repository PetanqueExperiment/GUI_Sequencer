from __future__ import annotations

from PyQt5.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
)

from sequencer_gui.atomiq_actions import (
    interrupt_running_experiment,
    list_repository_experiment_keys,
    scan_repository_head,
    submit_experiment,
    submit_sequencer_mode,
)
from sequencer_gui.ui.row_software_selector import _NoWheelComboBox
from sequencer_gui.atomiq_status import (
    RunSummary,
    SchedulerSnapshot,
    connect_artiq_heroes,
    release_experimentdb_hero,
    release_scheduler_hero,
    snapshot_from_scheduler,
)
from sequencer_gui.process_identity import (
    ATOMIQ_EXPERIMENTDB_HERO_NAME,
    ATOMIQ_SCHEDULER_HERO_NAME,
    ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY,
)

_STYLE_DISCONNECTED = "color: #c62828;"
_STYLE_IDLE = "color: #616161;"
_STYLE_ACTIVE = "color: #1565c0;"
_STYLE_QUEUED = "color: #6a1b9a;"


def _format_run_line(run: RunSummary) -> str:
    return f"{run.file_name} · {run.status}"


class _HeroConnectWorker(QThread):
    finished_ok = pyqtSignal(object, object)
    finished_err = pyqtSignal(str)

    def run(self) -> None:
        try:
            scheduler, experimentdb = connect_artiq_heroes()
        except ImportError as e:
            self.finished_err.emit(f"HERO not installed ({e!r})")
        except Exception as e:
            self.finished_err.emit(str(e))
        else:
            self.finished_ok.emit(scheduler, experimentdb)


class ArtiqPanel(QGroupBox):
    """Live ARTIQ master experiment status from the atomiq-scheduler HERO."""

    def __init__(self, parent=None) -> None:
        super().__init__("ArtiQ", parent)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)
        self.setToolTip(
            f"Experiment status from HERO {ATOMIQ_SCHEDULER_HERO_NAME!r} "
            "(ARTIQ master started via atomiq.frontend.atomiq_master)."
        )

        self._scheduler: object | None = None
        self._experimentdb: object | None = None
        self._heros_import_error: str | None = None
        self._experiment_list_stale = True
        self._actions_busy = False
        self._interrupt_available = False
        self._heroes_connecting = False
        self._connect_worker: _HeroConnectWorker | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        self._experiment = QLabel("Experiment: …")
        self._experiment.setWordWrap(True)
        layout.addWidget(self._experiment)

        self._queue = QLabel()
        self._queue.setWordWrap(True)
        self._queue.hide()
        layout.addWidget(self._queue)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._btn_scan_repo = QPushButton("Scan Repository head")
        self._btn_scan_repo.setToolTip(
            f"Rescan the ARTIQ repository on {ATOMIQ_EXPERIMENTDB_HERO_NAME!r}."
        )
        self._btn_scan_repo.clicked.connect(self._on_scan_repository_head)
        actions.addWidget(self._btn_scan_repo)
        self._btn_submit_sequencer = QPushButton("Submit Sequencer mode")
        self._btn_submit_sequencer.setToolTip(
            f"Submit {ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY!r} to "
            f"{ATOMIQ_SCHEDULER_HERO_NAME!r}."
        )
        self._btn_submit_sequencer.clicked.connect(self._on_submit_sequencer_mode)
        actions.addWidget(self._btn_submit_sequencer)
        layout.addLayout(actions)

        submit_row = QHBoxLayout()
        submit_row.setSpacing(8)
        self._experiment_combo = _NoWheelComboBox()
        self._experiment_combo.setMinimumWidth(160)
        self._experiment_combo.setToolTip(
            f"Experiment file known to {ATOMIQ_EXPERIMENTDB_HERO_NAME!r}."
        )
        submit_row.addWidget(self._experiment_combo, 1)
        self._btn_submit_selected = QPushButton("Submit")
        self._btn_submit_selected.setToolTip("Submit the selected repository experiment.")
        self._btn_submit_selected.clicked.connect(self._on_submit_selected_experiment)
        submit_row.addWidget(self._btn_submit_selected, 0)
        layout.addLayout(submit_row)

        interrupt_row = QHBoxLayout()
        interrupt_row.setSpacing(8)
        self._btn_interrupt = QPushButton("Stop ArtiQ")
        self._btn_interrupt.setEnabled(False)
        self._btn_interrupt.setToolTip(
            f"Stop the currently running experiment on {ATOMIQ_SCHEDULER_HERO_NAME!r}."
        )
        self._btn_interrupt.clicked.connect(self._on_interrupt)
        interrupt_row.addWidget(self._btn_interrupt)
        interrupt_row.addStretch(1)
        layout.addLayout(interrupt_row)

        self._poll = QTimer(self)
        self._poll.timeout.connect(self._poll_scheduler)
        self._poll.start(300)
        self.destroyed.connect(lambda: self._drop_heroes(reconnect=False))
        self._start_hero_connect()

    def _set_actions_enabled(self, enabled: bool) -> None:
        self._actions_busy = not enabled
        self._btn_scan_repo.setEnabled(enabled)
        self._btn_submit_sequencer.setEnabled(enabled)
        self._experiment_combo.setEnabled(enabled)
        self._btn_submit_selected.setEnabled(
            enabled and self._experiment_combo.count() > 0
        )
        self._update_interrupt_button()

    def _update_interrupt_button(self) -> None:
        self._btn_interrupt.setEnabled(
            not self._actions_busy and self._interrupt_available
        )

    def _start_hero_connect(self) -> None:
        if self._heroes_connecting or (
            self._scheduler is not None and self._experimentdb is not None
        ):
            return
        if self._heros_import_error is not None:
            return
        self._heroes_connecting = True
        self._set_actions_enabled(False)
        self._set_label(self._experiment, "Experiment: connecting…", _STYLE_IDLE)
        worker = _HeroConnectWorker(self)
        worker.finished_ok.connect(self._on_heroes_connected)
        worker.finished_err.connect(self._on_heroes_connect_failed)
        worker.finished.connect(worker.deleteLater)
        self._connect_worker = worker
        worker.start()

    def _stop_connect_worker(self) -> None:
        worker = self._connect_worker
        self._connect_worker = None
        self._heroes_connecting = False
        if worker is None:
            return
        if worker.isRunning():
            worker.wait(3000)

    def _on_heroes_connected(self, scheduler: object, experimentdb: object) -> None:
        self._heroes_connecting = False
        self._connect_worker = None
        self._scheduler = scheduler
        self._experimentdb = experimentdb
        self._set_actions_enabled(True)
        self._refresh_experiment_list()
        self._poll_scheduler()

    def _on_heroes_connect_failed(self, message: str) -> None:
        self._heroes_connecting = False
        self._connect_worker = None
        self._heros_import_error = message
        self._set_actions_enabled(True)
        self._apply_snapshot(SchedulerSnapshot(False, message, None, (), ()))

    def _ensure_scheduler(self) -> object | None:
        if self._scheduler is not None:
            return self._scheduler
        if self._heroes_connecting or self._heros_import_error is not None:
            return None
        self._start_hero_connect()
        return None

    def _ensure_experimentdb(self) -> object | None:
        if self._experimentdb is not None:
            return self._experimentdb
        if self._heroes_connecting or self._heros_import_error is not None:
            return None
        self._start_hero_connect()
        return None

    def _drop_heroes(self, *, reconnect: bool = True) -> None:
        self._stop_connect_worker()
        release_scheduler_hero(self._scheduler)
        self._scheduler = None
        release_experimentdb_hero(self._experimentdb)
        self._experimentdb = None
        if reconnect:
            self._heros_import_error = None
            self._start_hero_connect()

    def _drop_scheduler(self) -> None:
        self._drop_heroes()

    def _hero_unavailable_message(self) -> str:
        return self._heros_import_error or "ARTIQ master HEROs not reachable."

    def _on_scan_repository_head(self) -> None:
        experimentdb = self._ensure_experimentdb()
        if experimentdb is None:
            QMessageBox.warning(self, "Scan Repository head", self._hero_unavailable_message())
            return
        self._set_actions_enabled(False)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            scan_repository_head(experimentdb)
        except Exception as e:
            self._drop_heroes()
            QMessageBox.warning(
                self,
                "Scan Repository head",
                f"Repository scan failed ({ATOMIQ_EXPERIMENTDB_HERO_NAME}):\n{e}",
            )
        else:
            QMessageBox.information(self, "Scan Repository head", "Repository scan finished.")
            self._experiment_list_stale = True
            self._refresh_experiment_list()
        finally:
            QApplication.restoreOverrideCursor()
            self._set_actions_enabled(True)
            self._poll_scheduler()

    def _on_submit_sequencer_mode(self) -> None:
        scheduler = self._ensure_scheduler()
        experimentdb = self._ensure_experimentdb()
        if scheduler is None or experimentdb is None:
            QMessageBox.warning(self, "Submit Sequencer mode", self._hero_unavailable_message())
            return
        self._set_actions_enabled(False)
        try:
            submit_sequencer_mode(scheduler, experimentdb)
        except Exception as e:
            self._drop_heroes()
            QMessageBox.warning(
                self,
                "Submit Sequencer mode",
                f"Submit failed ({ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY}):\n{e}",
            )
        finally:
            self._set_actions_enabled(True)
            self._poll_scheduler()

    def _refresh_experiment_list(self) -> None:
        experimentdb = self._ensure_experimentdb()
        if experimentdb is None:
            return
        selected = self._experiment_combo.currentData()
        try:
            keys = list_repository_experiment_keys(experimentdb)
        except Exception:
            self._drop_heroes()
            return
        self._experiment_combo.blockSignals(True)
        self._experiment_combo.clear()
        for key in keys:
            self._experiment_combo.addItem(key, key)
        if selected is not None:
            index = self._experiment_combo.findData(selected)
            if index >= 0:
                self._experiment_combo.setCurrentIndex(index)
        self._experiment_combo.blockSignals(False)
        self._experiment_list_stale = False
        self._btn_submit_selected.setEnabled(self._experiment_combo.count() > 0)

    def _on_submit_selected_experiment(self) -> None:
        experiment_key = self._experiment_combo.currentData()
        if experiment_key is None:
            QMessageBox.warning(self, "Submit", "Select an experiment from the list.")
            return
        scheduler = self._ensure_scheduler()
        experimentdb = self._ensure_experimentdb()
        if scheduler is None or experimentdb is None:
            QMessageBox.warning(self, "Submit", self._hero_unavailable_message())
            return
        self._set_actions_enabled(False)
        try:
            submit_experiment(scheduler, experimentdb, str(experiment_key))
        except Exception as e:
            self._drop_heroes()
            QMessageBox.warning(
                self,
                "Submit",
                f"Submit failed ({experiment_key}):\n{e}",
            )
        finally:
            self._set_actions_enabled(True)
            self._poll_scheduler()

    def _on_interrupt(self) -> None:
        scheduler = self._ensure_scheduler()
        if scheduler is None:
            QMessageBox.warning(self, "Stop ArtiQ run", self._hero_unavailable_message())
            return
        self._set_actions_enabled(False)
        try:
            if not interrupt_running_experiment(scheduler):
                QMessageBox.warning(self, "Stop ArtiQ run", "No running experiment to stop.")
        except Exception as e:
            self._drop_heroes()
            QMessageBox.warning(
                self,
                "Stop ArtiQ",
                f"Failed to stop ({ATOMIQ_SCHEDULER_HERO_NAME}):\n{e}",
            )
        finally:
            self._set_actions_enabled(True)
            self._poll_scheduler()

    def _poll_scheduler(self) -> None:
        if self._heroes_connecting:
            return
        scheduler = self._scheduler
        if scheduler is None:
            if self._heros_import_error is None:
                return
            self._apply_snapshot(
                SchedulerSnapshot(False, self._heros_import_error, None, (), ())
            )
            return
        try:
            snap = snapshot_from_scheduler(scheduler)
        except Exception as e:
            self._drop_scheduler()
            snap = SchedulerSnapshot(False, str(e), None, (), ())
        self._apply_snapshot(snap)
        if snap.connected and self._experiment_list_stale:
            self._refresh_experiment_list()

    def _apply_snapshot(self, snap: SchedulerSnapshot) -> None:
        self._interrupt_available = snap.connected and snap.active is not None
        self._update_interrupt_button()

        if not snap.connected:
            detail = snap.error or "not reachable"
            self._set_label(
                self._experiment,
                f"Experiment: offline ({detail})",
                _STYLE_DISCONNECTED,
            )
            self._queue.hide()
            return

        if snap.active is not None:
            self._set_label(
                self._experiment,
                f"Experiment: {_format_run_line(snap.active)}",
                _STYLE_ACTIVE,
            )
        elif snap.queued:
            first = snap.queued[0]
            extra = len(snap.queued) - 1
            suffix = f" (+{extra} queued)" if extra else ""
            self._set_label(
                self._experiment,
                f"Experiment: next {_format_run_line(first)}{suffix}",
                _STYLE_QUEUED,
            )
        else:
            self._set_label(self._experiment, "Experiment: idle", _STYLE_IDLE)

        if snap.other_runs:
            lines = ", ".join(_format_run_line(r) for r in snap.other_runs[:3])
            if len(snap.other_runs) > 3:
                lines += f", … (+{len(snap.other_runs) - 3})"
            self._set_label(self._queue, f"Other: {lines}", _STYLE_IDLE)
            self._queue.show()
        else:
            self._queue.hide()

    @staticmethod
    def _set_label(label: QLabel, text: str, style: str) -> None:
        if label.text() != text:
            label.setText(text)
        if label.styleSheet() != style:
            label.setStyleSheet(style)
