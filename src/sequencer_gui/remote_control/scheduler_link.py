"""Local IPC link through which the Sequence Scheduler runs saved scans in this GUI.

The scheduler (separate program) sends one JSON request per connection
(see :mod:`sequencer_gui.scheduler_protocol`). The link

- loads a saved sequence with its saved scan and starts the scan,
- reports its progress (shots saved by PyCam) and how it ended, and interrupts it on request,
- loads and runs an optional free-run sequence between scans, and pauses it again.

It acts only through what the operator's controls do: Load, Start scan / Interrupt
(:meth:`ScanPanel.start_scan`, :meth:`ScanPanel.interrupt_scan`) and Running / Paused
(:meth:`SequenceToolbar.set_live_run`), so PyCam, ARTIQ and static devices are driven exactly as
in manual use. Scans are started unattended: no message box waits for a click.

It never takes over from the operator: while a scan the operator started is running, or a dialog
is open, requests are refused and the scheduler retries later. A sequence with unsaved changes is
copied to ``REPLACED_SEQUENCES_DIR`` before a scheduled one replaces it.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QLocalServer, QLocalSocket
from PyQt5.QtWidgets import QApplication

from sequencer_gui.persistence import save_last_sequence_path
from sequencer_gui.remote_control.scheduler_client import is_queued_scan_file
from sequencer_gui.scan_plan import expected_shot_count
from sequencer_gui.scheduler_protocol import (
    MAX_IPC_LINE_BYTES,
    SEQUENCER_SERVER_NAME,
    TASK_COMPLETED,
    TASK_FAILED,
    TASK_RUNNING,
    TASK_STARTING,
    TASK_STOPPED,
    TASK_UNKNOWN,
)
from sequencer_gui.sequence_io import (
    LoadedSequence,
    SequenceFileError,
    document_to_payload,
    load_sequence_file,
    save_sequence,
    sequence_display_name,
    validate_document_for_ui,
)
from sequencer_gui.ui.scan_panel import SCAN_COMPLETED, SCAN_FAILED

if TYPE_CHECKING:
    from sequencer_gui.app.state import SequenceAppState
    from sequencer_gui.domain.document import SequenceDocument
    from sequencer_gui.ui.scan_panel import ScanPanel
    from sequencer_gui.ui.sequence_toolbar import SequenceToolbar

# Sequences replaced by the scheduler while they had unsaved changes are copied here first.
REPLACED_SEQUENCES_DIR = Path.home() / ".sequencer_gui" / "replaced_by_scheduler"

_TASK_HISTORY_LENGTH = 50


class LinkError(Exception):
    """A request cannot be carried out; the message is sent back to the scheduler."""


# --- request server ------------------------------------------------------------------------------


class SchedulerRequestServer(QObject):
    """One JSON request per connection, dispatched by ``action`` to a handler on the GUI thread.

    Also used by the scheduler's hardware-free sequencer simulator.
    """

    def __init__(
        self,
        server_name: str,
        handlers: dict[str, Callable[[dict], dict]],
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._server_name = server_name
        self._handlers = handlers
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.UserAccessOption)
        self._server.newConnection.connect(self._accept_connections)
        self.error = ""

    def listen(self) -> bool:
        """Start listening; on failure ``error`` says why (e.g. another instance is listening)."""
        if self._server.listen(self._server_name):
            return True
        probe = QLocalSocket()
        probe.connectToServer(self._server_name)
        in_use = probe.waitForConnected(250)
        probe.abort()
        if in_use:
            self.error = "another program is already listening for the scheduler"
            return False
        # Stale socket file left by a crash (Unix); named pipes on Windows never go stale.
        QLocalServer.removeServer(self._server_name)
        if self._server.listen(self._server_name):
            return True
        self.error = self._server.errorString()
        return False

    def close(self) -> None:
        if self._server.isListening():
            self._server.close()
            QLocalServer.removeServer(self._server_name)

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda s=socket: self._read_request(s))
            socket.disconnected.connect(lambda s=socket: self._buffers.pop(s, None))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._read_request(socket)

    def _read_request(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_IPC_LINE_BYTES:
            self._buffers.pop(socket, None)
            self._reply(socket, {"ok": False, "error": "Request is too large."})
            return
        if b"\n" not in buffer:
            return
        line = bytes(buffer).partition(b"\n")[0]
        self._buffers.pop(socket, None)  # one reply per connection
        self._reply(socket, self._handle(line))

    def _handle(self, raw_request: bytes) -> dict:
        try:
            request = json.loads(raw_request.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "error": "Request must be one JSON object."}
        if not isinstance(request, dict):
            return {"ok": False, "error": "Request must be one JSON object."}
        handler = self._handlers.get(request.get("action"))
        if handler is None:
            return {"ok": False, "error": f"Unsupported request {request.get('action')!r}."}
        try:
            result = handler(request)
        except LinkError as error:
            return {"ok": False, "error": str(error)}
        except Exception as error:  # a scheduler request must never take the GUI down
            return {"ok": False, "error": f"{type(error).__name__}: {error}"}
        return {"ok": True, **result}

    def _reply(self, socket: QLocalSocket, response: dict) -> None:
        try:
            socket.write(json.dumps(response).encode("utf-8") + b"\n")
            socket.flush()
            socket.disconnectFromServer()
        except RuntimeError:
            pass  # the scheduler gave up waiting and the socket is already gone


# --- request contents and task bookkeeping (no widgets) -----------------------------------------


def request_task_id(request: dict) -> str:
    task_id = request.get("task_id")
    if not isinstance(task_id, str) or not task_id.strip():
        raise LinkError("A task id is required.")
    return task_id


def request_sequence_path(request: dict) -> Path:
    path_text = request.get("sequence_path")
    if not isinstance(path_text, str) or not path_text.strip():
        raise LinkError("A saved sequence path is required.")
    return Path(path_text).expanduser().resolve()


def load_sequence_for_scheduler(path: Path, *, require_scan: bool) -> LoadedSequence:
    """Read and check a saved sequence; with ``require_scan`` it must hold a startable scan."""
    try:
        loaded = load_sequence_file(path)
    except (OSError, SequenceFileError) as error:
        raise LinkError(f"Could not load {path.name}: {error}") from error
    problem = validate_document_for_ui(loaded.document)
    if problem is not None:
        raise LinkError(f"Could not load {path.name}: {problem}")
    if require_scan:
        if loaded.scan_error is not None:
            raise LinkError(f"The scan saved in {path.name} is invalid: {loaded.scan_error}")
        if loaded.scan is None or loaded.scan.is_empty():
            raise LinkError(f"{path.name} has no saved scan settings.")
        if not loaded.scan.label.strip():
            raise LinkError(f"The scan saved in {path.name} has no label (PyCam experiment name).")
    return loaded


def same_sequence(a: SequenceDocument, b: SequenceDocument) -> bool:
    """True if two documents would be saved as the same file content.

    (Dataclass equality is too strict: a loaded file has explicit default cells that a document
    built in memory leaves out.)
    """
    return document_to_payload(a) == document_to_payload(b)


@dataclass
class ScanTask:
    """One scheduler-owned scan as the sequencer side sees it."""

    task_id: str
    path: Path
    state: str = TASK_STARTING
    completed: int = 0
    total: int = 0
    error: str = ""

    @property
    def active(self) -> bool:
        return self.state in (TASK_STARTING, TASK_RUNNING)

    def status(self) -> dict:
        return {
            "task_state": self.state,
            "progress_completed": self.completed,
            "progress_total": self.total,
            "error": self.error,
        }


class TaskHistory:
    """Recent scan tasks by id, so the scheduler can still ask about a finished one."""

    def __init__(self, length: int = _TASK_HISTORY_LENGTH) -> None:
        self._length = length
        self._tasks: dict[str, ScanTask] = {}

    def add(self, task: ScanTask) -> None:
        self._tasks[task.task_id] = task
        while len(self._tasks) > self._length:
            self._tasks.pop(next(iter(self._tasks)))

    def get(self, task_id: str) -> ScanTask | None:
        return self._tasks.get(task_id)

    def status(self, task_id: str) -> dict:
        task = self._tasks.get(task_id)
        if task is None:
            return {"task_state": TASK_UNKNOWN, "progress_completed": 0, "progress_total": 0,
                    "error": ""}
        return task.status()


# --- the link in the sequencer GUI ---------------------------------------------------------------


class SchedulerLink(QObject):
    """Carries out scheduler requests in this GUI. Create on the GUI thread after the main window."""

    def __init__(
        self,
        state: SequenceAppState,
        scan_panel: ScanPanel,
        toolbar: SequenceToolbar,
        *,
        server_name: str = SEQUENCER_SERVER_NAME,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._panel = scan_panel
        self._toolbar = toolbar
        self._tasks = TaskHistory()
        self._task: ScanTask | None = None
        # (task id, sequence path) of the free-run sequence the scheduler started.
        self._free_run: tuple[str, str] | None = None

        scan_panel.scan_progress.connect(self._on_scan_progress)
        scan_panel.scan_ended.connect(self._on_scan_ended)

        self._server = SchedulerRequestServer(
            server_name,
            {
                "start_scan": self._start_scan,
                "get_task_status": self._get_task_status,
                "stop_scan": self._stop_scan,
                "start_free_run": self._start_free_run,
                "stop_free_run": self._stop_free_run,
            },
            self,
        )
        self.listening = self._server.listen()
        self.error = self._server.error

    def close(self) -> None:
        """Stop listening (call before the application quits)."""
        self._server.close()

    # --- following the scan panel ----------------------------------------------------------------

    def _on_scan_progress(self, completed: int, total: int) -> None:
        task = self._task
        if task is not None and task.state == TASK_RUNNING:
            task.completed = max(task.completed, min(completed, task.total or total))

    def _on_scan_ended(self, outcome: str, message: str) -> None:
        task = self._task
        if task is None or not task.active:
            return  # a scan the operator started
        if outcome == SCAN_COMPLETED:
            task.state = TASK_COMPLETED
            task.completed = task.total
        elif outcome == SCAN_FAILED:
            task.state = TASK_FAILED
            task.error = message or "The scan failed in the sequencer."
        else:
            task.state = TASK_STOPPED  # interrupted, by the scheduler or the operator
        self._task = None
        if task.state != TASK_FAILED:
            self._remove_held_queue_file(task.path)  # a failed scan is queued again: keep it

    def _remove_held_queue_file(self, path: Path) -> None:
        """Delete a file held for "Queue in scheduler" once its scan is over (its copy is in the data)."""
        if not is_queued_scan_file(path) or str(path) == self._state.sequence_name:
            return  # never the file the GUI still shows (no copy was saved with the data)
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            print(f"Scheduler link: could not remove {path}: {error}", file=sys.stderr)

    def _show_data_copy(self, task: ScanTask) -> None:
        """For a held queue file, point the GUI (and the next start) at the copy saved with the data."""
        snapshot = self._panel.last_snapshot_path
        if snapshot is None or not is_queued_scan_file(task.path):
            return
        self._state.set_sequence_name(str(snapshot))
        save_last_sequence_path(str(snapshot))

    # --- helpers -----------------------------------------------------------------------------------

    def _busy_reason(self) -> str:
        """Why a new sequence cannot be loaded right now ('' when it can)."""
        if self._task is not None and self._task.active:
            return f"The sequencer is running the scheduled scan {self._task.path.name}."
        if self._state.scan_running:
            return "A scan is already running in the sequencer."
        if QApplication.activeModalWidget() is not None:
            return "The sequencer is showing a dialog; close it to let the scheduler continue."
        return ""

    def _has_unsaved_changes(self) -> bool:
        """True if the sequence or scan shown in the GUI differs from its file on disk."""
        state = self._state
        try:
            path = Path(state.sequence_name)
            if not path.is_file():
                return True
            saved = load_sequence_file(path)
        except (OSError, ValueError):
            return True
        if not same_sequence(saved.document, state.document):
            return True
        plan = state.scan_plan
        return not plan.is_empty() and plan != saved.scan

    def _back_up_unsaved_sequence(self) -> None:
        """Copy the GUI's sequence to ``REPLACED_SEQUENCES_DIR`` if loading would lose changes."""
        if not self._has_unsaved_changes():
            return
        state = self._state
        name = sequence_display_name(state.sequence_name)
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in Path(name).stem)[:60]
        target = REPLACED_SEQUENCES_DIR / f"{time.strftime('%Y%m%d_%H%M%S')}_{stem or 'sequence'}.json"
        try:
            REPLACED_SEQUENCES_DIR.mkdir(parents=True, exist_ok=True)
            save_sequence(target, name, state.document, state.scan_plan)
        except OSError as error:
            raise LinkError(
                "The sequence open in the sequencer has unsaved changes and could not be "
                f"backed up ({error}); nothing was loaded."
            ) from error
        print(f"Scheduler link: unsaved sequence backed up to {target}", file=sys.stderr)

    def _load_into_gui(self, path: Path, loaded: LoadedSequence) -> None:
        """Same as the toolbar's Load button, with the scan panel filled from the file."""
        state = self._state
        self._back_up_unsaved_sequence()
        save_last_sequence_path(str(path))
        state.set_sequence_name(str(path))
        state.replace_document(loaded.document, active_tab=0)
        if loaded.scan is not None and loaded.scan_error is None:
            scan = loaded.scan
            state.set_scan_plan(scan.label, scan.repetitions, scan.parameters)

    # --- requests ----------------------------------------------------------------------------------

    def _start_scan(self, request: dict) -> dict:
        task_id = request_task_id(request)
        known = self._tasks.get(task_id)
        if known is not None:
            return known.status()  # repeated request (the first reply was lost or late)
        path = request_sequence_path(request)
        busy = self._busy_reason()
        if busy:
            raise LinkError(busy)
        loaded = load_sequence_for_scheduler(path, require_scan=True)
        try:
            total = expected_shot_count(loaded.scan.parameters, loaded.scan.repetitions)
        except ValueError as error:
            raise LinkError(f"The scan saved in {path.name} is invalid: {error}") from error
        task = ScanTask(task_id=task_id, path=path, total=total)
        self._tasks.add(task)
        self._task = task
        # Reply first: starting waits for PyCam, which may take longer than the scheduler waits.
        QTimer.singleShot(0, lambda: self._begin_scan(task, loaded))
        return task.status()

    def _begin_scan(self, task: ScanTask, loaded: LoadedSequence) -> None:
        if task.state != TASK_STARTING:
            return  # stopped by the scheduler before it began
        try:
            if self._state.scan_running:
                raise LinkError("A scan was started in the sequencer before the scheduled one.")
            self._load_into_gui(task.path, loaded)
            error = self._panel.start_scan(attended=False)
        except Exception as e:
            error = str(e) if isinstance(e, LinkError) else f"{type(e).__name__}: {e}"
        if error is not None:
            self._fail(task, error)
            return
        self._show_data_copy(task)
        if task.state == TASK_STARTING:  # not already ended by its first scan step
            task.state = TASK_RUNNING

    def _fail(self, task: ScanTask, error: str) -> None:
        task.state = TASK_FAILED
        task.error = error
        if self._task is task:
            self._task = None

    def _get_task_status(self, request: dict) -> dict:
        return self._tasks.status(request_task_id(request))

    def _stop_scan(self, request: dict) -> dict:
        task = self._tasks.get(request_task_id(request))
        if task is None:
            raise LinkError("The sequencer does not know this scan task.")
        if task.state == TASK_STARTING:
            task.state = TASK_STOPPED
            if self._task is task:
                self._task = None
        elif task.state == TASK_RUNNING:
            error = self._panel.interrupt_scan()
            if error is not None:
                raise LinkError(error)
        return task.status()

    def _start_free_run(self, request: dict) -> dict:
        task_id = request_task_id(request)
        path = request_sequence_path(request)
        busy = self._busy_reason()
        if busy:
            raise LinkError(busy)
        loaded = load_sequence_for_scheduler(path, require_scan=False)
        state = self._state
        if state.sequence_name != str(path) or not same_sequence(state.document, loaded.document):
            self._load_into_gui(path, loaded)
        if not state.run_sequence:
            error = self._toolbar.set_live_run(True)
            if error is not None:
                raise LinkError(error)
        self._free_run = (task_id, str(path))
        return {"task_state": TASK_RUNNING}

    def _stop_free_run(self, request: dict) -> dict:
        task_id = request_task_id(request)
        free_run, state = self._free_run, self._state
        if free_run is None or free_run[0] != task_id:
            return {"task_state": TASK_STOPPED}
        self._free_run = None
        # Pause only what the scheduler started: not a scan, not a sequence the operator loaded since.
        if state.scan_running or not state.run_sequence or state.sequence_name != free_run[1]:
            return {"task_state": TASK_STOPPED}
        error = self._toolbar.set_live_run(False)
        if error is not None:
            self._free_run = free_run
            raise LinkError(error)
        return {"task_state": TASK_STOPPED}
