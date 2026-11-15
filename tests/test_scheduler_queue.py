"""Scan panel "Queue in scheduler" (remote_control/scheduler_client.py) against a fake scheduler.

Nothing reaches hardware or the real scheduler: the fake scheduler listens on its own name in a
worker thread, and the queue folder and PyCam data go to a temp folder.
"""

from __future__ import annotations

import os
import threading

from PyQt5 import sip
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QApplication

# Widgets need a QApplication; create it before conftest's ``app`` fixture makes a QCoreApplication.
_qapp = QApplication.instance() or QApplication([])

import pytest  # noqa: E402

from sequencer_gui import pycam_repository  # noqa: E402
from sequencer_gui.app.state import SequenceAppState  # noqa: E402
from sequencer_gui.domain.document import default_document  # noqa: E402
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS  # noqa: E402
from sequencer_gui.domain.scan import ScanParameter  # noqa: E402
from sequencer_gui.remote_control import scheduler_client  # noqa: E402
from sequencer_gui.remote_control.scheduler_link import (  # noqa: E402
    LinkError,
    SchedulerRequestServer,
)
from sequencer_gui.sequence_io import load_sequence_file  # noqa: E402
from sequencer_gui.ui.scan_panel import ScanPanel  # noqa: E402

SERVER_NAME = f"scheduler-queue-test-{os.getpid()}"
LABEL = "queue_test"


class FakeScheduler(QThread):
    """Serves ``queue_scan`` like the Sequence Scheduler, on its own thread."""

    def __init__(self, *, refuse: str = "") -> None:
        super().__init__()
        self.refuse = refuse
        self.requests: list[dict] = []
        self.ready = threading.Event()

    def run(self) -> None:
        server = SchedulerRequestServer(SERVER_NAME, {"queue_scan": self._queue_scan})
        self.listening = server.listen()
        self.ready.set()
        self.exec_()
        server.close()

    def _queue_scan(self, request: dict) -> dict:
        self.requests.append(request)
        if self.refuse:
            raise LinkError(self.refuse)
        return {"queue_position": len(self.requests), "task_id": "abc"}


def _start(fake: FakeScheduler) -> FakeScheduler:
    fake.start()
    assert fake.ready.wait(5) and fake.listening
    return fake


@pytest.fixture
def scheduler():
    fake = _start(FakeScheduler())
    yield fake
    fake.quit()
    fake.wait(5000)


@pytest.fixture
def panel(tmp_path, monkeypatch):
    monkeypatch.setattr(pycam_repository, "PYCAM_DATA_DIRECTORY", str(tmp_path / "pycam"))
    monkeypatch.setattr(scheduler_client, "SCHEDULER_QUEUE_DIR", tmp_path / "queue")
    document = default_document(tuple(str(i + 1) for i in range(DEFAULT_DEVICE_ROWS)))
    state = SequenceAppState(document=document, sequence_name=str(tmp_path / "open.json"))
    state.set_scan_plan(LABEL, 2, (ScanParameter("time", "time", "0", "10, 20"),))
    widget = ScanPanel(state)
    yield widget, state, tmp_path
    widget._label_color_poll.stop()
    widget._pycam_poll.stop()
    sip.delete(widget)
    _qapp.processEvents()


def test_queue_holds_the_scan_for_the_scheduler_not_with_the_data(panel, scheduler):
    widget, state, tmp = panel
    assert widget.queue_in_scheduler(server_name=SERVER_NAME) is None

    held = tmp / "queue" / f"{LABEL}.json"
    assert scheduler.requests == [{"action": "queue_scan", "sequence_path": str(held.resolve())}]
    assert load_sequence_file(held).scan == state.scan_plan
    assert not (tmp / "pycam").exists()  # saved with the data only when the scan runs
    assert widget._btn_queue_scan.text() == "Queued · position 1"


def test_second_queue_with_same_label_gets_its_own_file(panel, scheduler):
    widget, _state, tmp = panel
    assert widget.queue_in_scheduler(server_name=SERVER_NAME) is None
    assert widget.queue_in_scheduler(server_name=SERVER_NAME) is None
    names = [os.path.basename(r["sequence_path"]) for r in scheduler.requests]
    assert names == [f"{LABEL}.json", f"{LABEL}_2.json"]


def test_label_is_made_safe_for_a_file_name(panel, scheduler):
    widget, _state, _tmp = panel
    widget._label.setText("a/b:c")
    assert widget.queue_in_scheduler(server_name=SERVER_NAME) is None
    assert os.path.basename(scheduler.requests[0]["sequence_path"]) == "a_b_c.json"


def test_no_scheduler_running_writes_nothing(panel):
    widget, _state, tmp = panel
    error = widget.queue_in_scheduler(server_name=SERVER_NAME)
    assert "not running" in error
    assert not (tmp / "queue").exists()


def test_refused_scan_reports_where_it_was_saved(panel):
    widget, _state, tmp = panel
    fake = _start(FakeScheduler(refuse="Invalid scan sequence: broken"))
    try:
        error = widget.queue_in_scheduler(server_name=SERVER_NAME)
    finally:
        fake.quit()
        fake.wait(5000)
    assert "Invalid scan sequence: broken" in error
    assert str(tmp / "queue" / f"{LABEL}.json") in error


def test_scan_without_label_is_refused_before_contacting_the_scheduler(panel, scheduler):
    widget, _state, tmp = panel
    widget._label.setText("")
    assert "scan label" in widget.queue_in_scheduler(server_name=SERVER_NAME)
    assert scheduler.requests == [] and not (tmp / "queue").exists()


def test_disabled_while_a_scan_runs(panel, scheduler):
    widget, state, _tmp = panel
    state.set_scan_running(True)
    assert not widget._btn_queue_scan.isEnabled()
    assert "running scan" in widget.queue_in_scheduler(server_name=SERVER_NAME)
    assert scheduler.requests == []
