"""Hardware-free stand-in for the sequencer GUI, e.g. to try the Sequence Scheduler.

Run with ``python -m sequencer_gui.simulator [--speed FACTOR]``. It answers the same requests as
the scheduler link (:mod:`sequencer_gui.remote_control.scheduler_link`) on the simulation IPC name
(``SEQUENCER_SIMULATION_SERVER_NAME``), reads saved sequence files like the GUI does, and plays
scans as a progress bar, ``FACTOR`` times faster than their real duration. It never connects to
ARTIQ, PyCam, HERO or any device. The scheduler uses it when started with ``--simulate-sequencer``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.domain.document import complete_timeline_duration_us
from sequencer_gui.remote_control.scheduler_link import (
    LinkError,
    ScanTask,
    SchedulerRequestServer,
    TaskHistory,
    load_sequence_for_scheduler,
    request_new_data_label,
    request_sequence_path,
    request_task_id,
    scan_data_label,
)
from sequencer_gui.scheduler_protocol import (
    SEQUENCER_SIMULATION_SERVER_NAME,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
    TASK_STOPPED,
)
from sequencer_gui.scan_plan import anticipated_scan_duration_s, expected_shot_count

_TICK_MS = 100


class SequencerSimulatorWindow(QMainWindow):
    def __init__(
        self, *, speed: float = 1.0, server_name: str = SEQUENCER_SIMULATION_SERVER_NAME
    ) -> None:
        super().__init__()
        self.setWindowTitle("Sequencer simulator — no hardware")
        self.resize(520, 240)

        self._tasks = TaskHistory()
        self._task: ScanTask | None = None
        self._scan_duration_s = 0.0
        self._scan_elapsed_s = 0.0
        self._last_tick = time.monotonic()
        self._free_run_task_id: str | None = None

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        form = QFormLayout()
        self._sequence_label = QLabel("(none)")
        self._sequence_label.setWordWrap(True)
        form.addRow("Sequence:", self._sequence_label)
        self._state_label = QLabel("Paused")
        form.addRow("State:", self._state_label)
        self._speed = QDoubleSpinBox()
        self._speed.setRange(1.0, 100000.0)
        self._speed.setDecimals(0)
        self._speed.setValue(speed)
        self._speed.setPrefix("× ")
        self._speed.setToolTip("Simulated scans run this many times faster than the real sequence.")
        form.addRow("Speed:", self._speed)
        layout.addLayout(form)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        layout.addWidget(self._progress)

        buttons = QHBoxLayout()
        self._interrupt_btn = QPushButton("Interrupt scan")
        self._interrupt_btn.setToolTip("As if the operator pressed Interrupt in the sequencer.")
        self._interrupt_btn.clicked.connect(lambda: self._end_scan(TASK_STOPPED))
        buttons.addWidget(self._interrupt_btn)
        self._fail_btn = QPushButton("Make scan fail")
        self._fail_btn.setToolTip("As if the sequencer reported an error during the scan.")
        self._fail_btn.clicked.connect(
            lambda: self._end_scan(TASK_FAILED, "Simulated scan failure.")
        )
        buttons.addWidget(self._fail_btn)
        buttons.addStretch(1)
        layout.addLayout(buttons)
        layout.addStretch(1)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_TICK_MS)

        self._server = SchedulerRequestServer(
            server_name,
            {
                "start_scan": self._start_scan,
                "get_task_status": lambda request: self._tasks.status(request_task_id(request)),
                "stop_scan": self._stop_scan,
                "start_free_run": self._start_free_run,
                "stop_free_run": self._stop_free_run,
                "load_sequence": self._load_sequence,
            },
            self,
        )
        if not self._server.listen():
            self._state_label.setText(f"Scheduler link unavailable: {self._server.error}")
        self._sync_buttons()

    def closeEvent(self, event) -> None:
        self._server.close()
        super().closeEvent(event)

    def _sync_buttons(self) -> None:
        scanning = self._task is not None
        self._interrupt_btn.setEnabled(scanning)
        self._fail_btn.setEnabled(scanning)

    def _show_idle(self, text: str) -> None:
        self._state_label.setText(text)
        self._progress.setValue(0)
        self._progress.setFormat("%p%")

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed_s = now - self._last_tick
        self._last_tick = now
        task = self._task
        if task is None:
            return
        self._scan_elapsed_s += elapsed_s * self._speed.value()
        if self._scan_duration_s <= 0.0:
            fraction = 1.0
        else:
            fraction = min(1.0, self._scan_elapsed_s / self._scan_duration_s)
        task.completed = min(task.total, int(fraction * task.total))
        self._progress.setValue(round(100 * fraction))
        self._progress.setFormat(f"%p% · {task.completed:,}/{task.total:,} shots")
        if fraction >= 1.0:
            self._end_scan(TASK_COMPLETED)

    def _end_scan(self, state: str, error: str = "") -> None:
        task = self._task
        if task is None:
            return
        task.state = state
        task.error = error
        if state == TASK_COMPLETED:
            task.completed = task.total
        self._task = None
        self._sync_buttons()
        # Like the sequencer: after a complete scan the sequence keeps running without a scan.
        self._show_idle(
            "Running (no scan)" if state == TASK_COMPLETED else f"Paused · last scan {state}"
        )

    def _start_scan(self, request: dict) -> dict:
        task_id = request_task_id(request)
        known = self._tasks.get(task_id)
        if known is not None:
            return known.status()
        path = request_sequence_path(request)
        new_data_label = request_new_data_label(request)
        if self._task is not None:
            raise LinkError("A scan is already running in the sequencer simulator.")
        loaded = load_sequence_for_scheduler(path, require_scan=True)
        scan = loaded.scan
        # Reads today's PyCam folder names only; the simulator writes no data.
        data_label = scan_data_label(scan.label, new_data_label=new_data_label)
        try:
            total = expected_shot_count(scan.parameters, scan.repetitions)
        except ValueError as error:
            raise LinkError(f"The scan saved in {path.name} is invalid: {error}") from error
        duration_s = anticipated_scan_duration_s(loaded.document, scan.parameters, scan.repetitions)
        if duration_s is None:
            raise LinkError(
                f"The scan saved in {path.name} does not fit its sequence "
                "(unknown device, parameter or timestep)."
            )
        task = ScanTask(task_id=task_id, path=path, state=TASK_RUNNING, total=total,
                        file_label=scan.label, data_label=data_label)
        self._tasks.add(task)
        self._task = task
        self._scan_duration_s = duration_s
        self._scan_elapsed_s = 0.0
        self._free_run_task_id = None
        self._sequence_label.setText(str(path))
        self._state_label.setText(f"Scan running · data label {data_label}")
        self._sync_buttons()
        return task.status()

    def _stop_scan(self, request: dict) -> dict:
        task = self._tasks.get(request_task_id(request))
        if task is None:
            raise LinkError("The sequencer simulator does not know this scan task.")
        if task is self._task:
            self._end_scan(TASK_STOPPED)
        return task.status()

    def _load_free_sequence(self, request: dict) -> tuple[Path, float]:
        """Show a sequence without scan; returns its path and duration per shot in µs."""
        path = request_sequence_path(request)
        if self._task is not None:
            raise LinkError("A scan is already running in the sequencer simulator.")
        loaded = load_sequence_for_scheduler(path, require_scan=False)
        self._sequence_label.setText(str(path))
        return path, complete_timeline_duration_us(loaded.document)

    def _start_free_run(self, request: dict) -> dict:
        task_id = request_task_id(request)
        _path, duration_us = self._load_free_sequence(request)
        self._free_run_task_id = task_id
        self._show_idle(f"Running free-run · {duration_us / 1000:.0f} ms per shot")
        return {"task_state": TASK_RUNNING}

    def _stop_free_run(self, request: dict) -> dict:
        if self._free_run_task_id == request_task_id(request):
            self._free_run_task_id = None
            if self._task is None:
                self._show_idle("Paused")
        return {"task_state": TASK_STOPPED}

    def _load_sequence(self, request: dict) -> dict:
        path, _duration_us = self._load_free_sequence(request)
        self._free_run_task_id = None
        self._show_idle("Paused")
        return {"sequence_path": str(path)}


def main() -> None:
    speed = 1.0
    args = sys.argv[1:]
    if "--speed" in args:
        try:
            speed = max(1.0, float(args[args.index("--speed") + 1]))
        except (IndexError, ValueError):
            print("Usage: python -m sequencer_gui.simulator [--speed FACTOR]", file=sys.stderr)
            sys.exit(2)
    app = QApplication(sys.argv[:1])
    window = SequencerSimulatorWindow(speed=speed)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
