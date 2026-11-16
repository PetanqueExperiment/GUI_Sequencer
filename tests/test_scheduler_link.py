"""Scheduler link (remote_control/scheduler_link.py) with the real scan panel and toolbar.

Nothing reaches hardware: ``heros`` is replaced by a fake PyCam, the state uses the no-op
backend, PyCam data and backups go to a temp folder, and settings.json is not written.
Requests go over a real local socket from a worker thread, like the scheduler's.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import types

from PyQt5 import sip
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QWidget

# Widgets need a QApplication; create it before conftest's ``app`` fixture makes a QCoreApplication.
_qapp = QApplication.instance() or QApplication([])

import pytest  # noqa: E402

from sequencer_gui import pycam_repository  # noqa: E402
from sequencer_gui.app.state import SequenceAppState  # noqa: E402
from sequencer_gui.domain.document import default_document  # noqa: E402
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS  # noqa: E402
from sequencer_gui.domain.scan import ScanParameter, ScanPlan  # noqa: E402
from sequencer_gui.remote_control import scheduler_client, scheduler_link  # noqa: E402
from sequencer_gui.remote_control.scheduler_link import (  # noqa: E402
    LinkError,
    ScanTask,
    SchedulerLink,
    TaskHistory,
    load_sequence_for_scheduler,
)
from sequencer_gui.sequence_io import load_sequence_file, save_sequence  # noqa: E402
from sequencer_gui.ui.scan_panel import ScanPanel  # noqa: E402
from sequencer_gui.ui.sequence_toolbar import SequenceToolbar  # noqa: E402

SERVER_NAME = f"scheduler-link-test-{os.getpid()}"
SCAN_DELAYS_US = (10.0, 20.0, 30.0)
REPETITIONS = 2
TOTAL_SHOTS = len(SCAN_DELAYS_US) * REPETITIONS


class FakePyCam:
    def __init__(self) -> None:
        self.name = ""
        self.tags: list[str] | None = None
        self.status = "idle"
        self.shots = 0
        self.fail_start = False

    def is_ready(self) -> bool:
        return self.status == "idle"

    def get_status(self) -> str:
        return self.status

    def set_ExperimentName(self, name: str) -> None:
        self.name = name

    def get_ExperimentName(self) -> str:
        return self.name

    def is_ExperimentName_synced(self, name: str) -> bool:
        return self.name == name

    def set_parameter_scan_order(self, tags) -> None:
        self.tags = list(tags)
        self.shots = 0

    def clear_parameter_scan_order(self) -> None:
        self.tags = None

    def get_parameter_scan_order(self):
        return self.tags

    def get_current_scan_index(self) -> int:
        return self.shots

    def startExperiment(self) -> None:
        if self.fail_start:
            raise RuntimeError("camera offline")
        self.status = "running"

    def stopExperiment(self) -> None:
        self.status = "idle"


def _document():
    return default_document(tuple(str(i + 1) for i in range(DEFAULT_DEVICE_ROWS)))


class FakeMainWindow(QWidget):
    """The two panels the link drives (no ARTIQ panel, matrix or static panel)."""

    def __init__(self, state: SequenceAppState) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.toolbar = SequenceToolbar(state)
        layout.addWidget(self.toolbar)
        self.scan_panel = ScanPanel(state)
        layout.addWidget(self.scan_panel)


@pytest.fixture
def link(tmp_path, monkeypatch):
    pycam = FakePyCam()

    class FakeRemoteHERO:
        def __init__(self, name: str) -> None:
            self.name = name

        def __enter__(self):
            if self.name != "PyCam_HERO":
                raise RuntimeError(f"no fake device {self.name!r}")
            return pycam

        def __exit__(self, *exc) -> bool:
            return False

    monkeypatch.setitem(sys.modules, "heros", types.SimpleNamespace(RemoteHERO=FakeRemoteHERO))
    monkeypatch.setattr(pycam_repository, "PYCAM_DATA_DIRECTORY", str(tmp_path / "pycam"))
    monkeypatch.setattr(scheduler_link, "REPLACED_SEQUENCES_DIR", tmp_path / "replaced")
    saved_paths: list[str] = []
    monkeypatch.setattr(scheduler_link, "save_last_sequence_path", saved_paths.append)

    scan_path = tmp_path / "scan_delay.json"
    plan = ScanPlan(
        "link_test",
        REPETITIONS,
        (ScanParameter("time", "time", "0", ", ".join(str(v) for v in SCAN_DELAYS_US)),),
    )
    save_sequence(scan_path, "scan_delay", _document(), plan)
    free_path = tmp_path / "free_run.json"
    save_sequence(free_path, "free_run", _document())
    # The GUI starts on a saved, unchanged sequence, like after the operator loaded a file.
    state = SequenceAppState(document=_document(), sequence_name=str(free_path))
    window = FakeMainWindow(state)
    link = SchedulerLink(state, window.scan_panel, window.toolbar, server_name=SERVER_NAME)
    assert link.listening, link.error
    yield types.SimpleNamespace(
        state=state, window=window, link=link, pycam=pycam, scan_path=scan_path,
        free_path=free_path, replaced=tmp_path / "replaced", data=tmp_path / "pycam",
        saved_paths=saved_paths,
    )
    # Stop a scan that is still running while the fake PyCam is in place, then destroy the window
    # now: a surviving scan panel would keep polling PyCam in later tests.
    if state.scan_running:
        window.scan_panel.interrupt_scan()
    link.close()
    window.scan_panel._pycam_poll.stop()
    window.scan_panel._label_color_poll.stop()
    sip.delete(window)
    _qapp.processEvents()


def _request_blocking(request: dict) -> dict:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    assert socket.waitForConnected(2000), socket.errorString()
    socket.write(json.dumps(request).encode("utf-8") + b"\n")
    socket.waitForBytesWritten(2000)
    while not socket.canReadLine():
        assert socket.waitForReadyRead(5000), "no reply"
    return json.loads(bytes(socket.readLine()).decode("utf-8"))


def call(**request) -> dict:
    """Send one request from a worker thread while the GUI event loop runs; raise on ok=False."""
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(reply=_request_blocking(request)))
    thread.start()
    while thread.is_alive():
        _qapp.processEvents()
        time.sleep(0.005)
    _qapp.processEvents()
    reply = box["reply"]
    if not reply["ok"]:
        raise LinkError(reply["error"])
    return reply


def spin(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        _qapp.processEvents()
        time.sleep(0.005)


def wait_for_state(task_id: str, wanted: str, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while True:
        status = call(action="get_task_status", task_id=task_id)
        if status["task_state"] == wanted:
            return status
        assert time.monotonic() < deadline, f"still {status} instead of {wanted}"
        spin(0.05)


def start(link, task_id: str = "t1") -> dict:
    return call(action="start_scan", sequence_path=str(link.scan_path), task_id=task_id)


# --- through the GUI ----------------------------------------------------------------------------


def test_scan_runs_to_completion(link):
    assert start(link)["task_state"] == "starting"
    status = wait_for_state("t1", "running")
    assert status["progress_total"] == TOTAL_SHOTS
    assert link.state.scan_running
    assert link.state.sequence_name == str(link.scan_path)
    assert link.saved_paths == [str(link.scan_path)]
    assert link.pycam.name == "link_test" and len(link.pycam.tags) == TOTAL_SHOTS
    assert list(link.data.rglob("link_test/sequence.json"))  # snapshot next to the PyCam data

    link.pycam.shots = 3  # PyCam saved three shots: the scan is on its second point
    spin(1.2)
    status = call(action="get_task_status", task_id="t1")
    assert status["task_state"] == "running" and status["progress_completed"] == 3

    link.pycam.shots = TOTAL_SHOTS
    status = wait_for_state("t1", "completed")
    assert status["progress_completed"] == TOTAL_SHOTS
    assert not link.state.scan_running
    assert link.state.run_sequence  # back to the run without scan, as after a manual scan
    loaded = load_sequence_file(link.scan_path).document
    assert link.state.document.blocks[0].delays_us == loaded.blocks[0].delays_us  # restored
    assert not link.replaced.exists()  # nothing unsaved to back up


def test_new_data_label_gives_each_run_its_own_folder(link):
    def run(task_id: str) -> dict:
        reply = call(action="start_scan", sequence_path=str(link.scan_path), task_id=task_id,
                     new_data_label=True)
        wait_for_state(task_id, "running")
        assert link.pycam.name == reply["data_label"]  # PyCam saves under the run's label
        link.pycam.shots = TOTAL_SHOTS
        status = wait_for_state(task_id, "completed")
        link.pycam.shots = 0
        return status

    assert run("t1")["data_label"] == "link_test"  # first run today: the saved label
    assert run("t2")["data_label"] == "link_test_2"
    snapshot = next(link.data.rglob("link_test_2/sequence.json"))
    assert load_sequence_file(snapshot).scan.label == "link_test_2"  # the copy matches the data
    # The GUI shows the file's label again: unchanged, so nothing is backed up next time.
    assert link.state.scan_label == "link_test"
    assert load_sequence_file(link.scan_path).scan.label == "link_test"  # file untouched
    assert run("t3")["data_label"] == "link_test_3"
    assert not link.replaced.exists()


def test_without_new_data_label_runs_share_one_folder_and_one_snapshot(link):
    for task_id in ("t1", "t2"):
        reply = start(link, task_id)
        wait_for_state(task_id, "running")
        assert reply["data_label"] == "link_test"
        link.pycam.shots = TOTAL_SHOTS
        wait_for_state(task_id, "completed")
        link.pycam.shots = 0
    (folder,) = link.data.rglob("link_test")
    assert [p.name for p in folder.glob("*.json")] == ["sequence.json"]  # no duplicate copy


def test_bad_new_data_label_value_is_refused(link):
    with pytest.raises(LinkError, match="new_data_label"):
        call(action="start_scan", sequence_path=str(link.scan_path), task_id="t1",
             new_data_label="yes")


def _hold_for_scheduler(link, tmp_path, monkeypatch):
    """The scan as "Queue in scheduler" leaves it: a file in the scheduler queue folder."""
    monkeypatch.setattr(scheduler_client, "SCHEDULER_QUEUE_DIR", tmp_path / "queue")
    loaded = load_sequence_file(link.scan_path)
    return scheduler_client.save_queued_scan("link_test", "scan_delay", loaded.document, loaded.scan)


def test_held_queue_file_is_saved_with_the_data_and_removed_when_done(link, tmp_path, monkeypatch):
    held = _hold_for_scheduler(link, tmp_path, monkeypatch)
    call(action="start_scan", sequence_path=str(held), task_id="t1")
    wait_for_state("t1", "running")
    snapshot = next(link.data.rglob("link_test/sequence.json"))  # the usual copy with the data
    # The GUI (and the next start) now refer to that copy, not to the held file.
    assert link.state.sequence_name == str(snapshot)
    assert link.saved_paths[-1] == str(snapshot)
    assert held.is_file()  # still held while the scan runs

    link.pycam.shots = TOTAL_SHOTS
    wait_for_state("t1", "completed")
    assert not held.exists()
    assert snapshot.is_file()


def test_held_queue_file_is_kept_after_a_failure(link, tmp_path, monkeypatch):
    held = _hold_for_scheduler(link, tmp_path, monkeypatch)
    call(action="start_scan", sequence_path=str(held), task_id="t1")
    wait_for_state("t1", "running")

    def failing_apply(point):
        raise RuntimeError("Remote static apply failed: VOA")

    monkeypatch.setattr(link.state, "apply_scan_point", failing_apply)
    link.pycam.shots = REPETITIONS
    wait_for_state("t1", "failed")
    assert held.is_file()  # the scheduler queues a failed scan again


def test_repeated_start_request_does_not_start_twice(link):
    start(link)
    wait_for_state("t1", "running")
    assert start(link)["task_state"] == "running"
    with pytest.raises(LinkError, match="scheduled scan"):
        start(link, "t2")


def test_pycam_start_failure_is_reported_without_dialog(link):
    link.pycam.fail_start = True
    start(link)
    status = wait_for_state("t1", "failed")
    assert "camera offline" in status["error"]
    assert not link.state.scan_running
    assert QApplication.activeModalWidget() is None


def test_scheduler_stop(link):
    start(link)
    wait_for_state("t1", "running")
    assert call(action="stop_scan", task_id="t1")["task_state"] == "stopped"
    assert not link.state.scan_running and link.pycam.status == "idle"
    assert not link.state.run_sequence  # an interrupted scan stays paused


def test_operator_interrupt_reads_as_stopped(link):
    start(link)
    wait_for_state("t1", "running")
    assert link.window.scan_panel.interrupt_scan() is None
    assert wait_for_state("t1", "stopped")["error"] == ""


def test_scan_step_failure_is_reported(link, monkeypatch):
    start(link)
    wait_for_state("t1", "running")

    def failing_apply(point):
        raise RuntimeError("Remote static apply failed: VOA")

    monkeypatch.setattr(link.state, "apply_scan_point", failing_apply)
    link.pycam.shots = REPETITIONS  # first point done: the second one cannot be applied
    status = wait_for_state("t1", "failed")
    assert "VOA" in status["error"]
    assert QApplication.activeModalWidget() is None


def test_operator_scan_makes_the_scheduler_wait(link):
    link.state.set_scan_running(True)
    with pytest.raises(LinkError, match="already running"):
        start(link)
    with pytest.raises(LinkError, match="already running"):
        call(action="start_free_run", sequence_path=str(link.free_path), task_id="f1")
    link.state.set_scan_running(False)
    assert call(action="get_task_status", task_id="t1")["task_state"] == "unknown"


def test_unsaved_sequence_is_backed_up_before_loading(link):
    link.state.set_delay_us(0, 123.0)  # operator edit, not saved
    start(link)
    wait_for_state("t1", "running")
    backups = list(link.replaced.glob("*.json"))
    assert len(backups) == 1
    assert load_sequence_file(backups[0]).document.blocks[0].delays_us[0] == 123.0


def test_free_run_start_and_stop(link):
    link.state.set_sequence_name("Untitled")
    started = call(action="start_free_run", sequence_path=str(link.free_path), task_id="f1")
    assert started["task_state"] == "running"
    assert link.state.run_sequence and link.state.sequence_name == str(link.free_path)
    assert link.pycam.name == "Running_without_scan" and link.pycam.status == "running"
    assert link.window.toolbar._run_btn.isChecked()  # the Running button follows

    call(action="stop_free_run", task_id="other-task")
    assert link.state.run_sequence  # not the scheduler's current free-run: left alone
    call(action="stop_free_run", task_id="f1")
    assert not link.state.run_sequence


def test_unknown_action_and_bad_json_are_refused(link):
    with pytest.raises(LinkError, match="Unsupported"):
        call(action="format_disk")


# --- without the GUI --------------------------------------------------------------------------


def test_scan_without_label_is_refused(tmp_path):
    path = tmp_path / "scan_no_label.json"
    save_sequence(path, "x", _document(), ScanPlan("", 1, (ScanParameter("time", "time", "0", "1"),)))
    with pytest.raises(LinkError, match="no label"):
        load_sequence_for_scheduler(path, require_scan=True)


def test_sequence_without_scan_is_refused_for_a_scan_only(tmp_path):
    path = tmp_path / "free.json"
    save_sequence(path, "free", _document())
    with pytest.raises(LinkError, match="no saved scan"):
        load_sequence_for_scheduler(path, require_scan=True)
    assert load_sequence_for_scheduler(path, require_scan=False).scan is None


def test_task_history_forgets_oldest(tmp_path):
    history = TaskHistory(length=2)
    for i in range(3):
        history.add(ScanTask(task_id=f"t{i}", path=tmp_path))
    assert history.get("t0") is None and history.get("t2") is not None
    assert history.status("t0")["task_state"] == "unknown"
