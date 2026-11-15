"""Sequencer simulator (sequencer_gui/simulator.py) answering scheduler requests.

Runs on its own pipe name, so a live scheduler on this machine is never reached.
"""

from __future__ import annotations

import json
import os
import threading
import time

from PyQt5 import sip
from PyQt5.QtNetwork import QLocalSocket
from PyQt5.QtWidgets import QApplication

_qapp = QApplication.instance() or QApplication([])

import pytest  # noqa: E402

from sequencer_gui.domain.document import default_document  # noqa: E402
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS  # noqa: E402
from sequencer_gui.domain.scan import ScanParameter, ScanPlan  # noqa: E402
from sequencer_gui.sequence_io import save_sequence  # noqa: E402
from sequencer_gui.simulator import SequencerSimulatorWindow  # noqa: E402

SERVER_NAME = f"sequencer-simulator-test-{os.getpid()}"


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
    box: dict = {}
    thread = threading.Thread(target=lambda: box.update(reply=_request_blocking(request)))
    thread.start()
    while thread.is_alive():
        _qapp.processEvents()
        time.sleep(0.005)
    return box["reply"]


@pytest.fixture
def simulator(tmp_path):
    document = default_document(tuple(str(i + 1) for i in range(DEFAULT_DEVICE_ROWS)))
    scan_path = tmp_path / "scan.json"
    # 2 points x 3 shots; each shot is 100 ms at col 0 plus the default delays.
    plan = ScanPlan("sim", 3, (ScanParameter("time", "time", "0", "100000, 100000"),))
    save_sequence(scan_path, "scan", document, plan)
    free_path = tmp_path / "free.json"
    save_sequence(free_path, "free", document)
    window = SequencerSimulatorWindow(speed=100_000, server_name=SERVER_NAME)
    yield window, scan_path, free_path
    window.close()
    sip.delete(window)
    _qapp.processEvents()


def test_scan_runs_to_completion(simulator):
    _window, scan_path, _free = simulator
    reply = call(action="start_scan", sequence_path=str(scan_path), task_id="t1")
    assert reply["ok"] and reply["task_state"] == "running" and reply["progress_total"] == 6
    deadline = time.monotonic() + 5
    while True:
        status = call(action="get_task_status", task_id="t1")
        if status["task_state"] == "completed":
            break
        assert time.monotonic() < deadline, status
    assert status["progress_completed"] == 6


def test_stop_and_free_run(simulator):
    window, scan_path, free_path = simulator
    window._speed.setValue(1)  # slow enough to still be running when stopped
    call(action="start_scan", sequence_path=str(scan_path), task_id="t1")
    busy = call(action="start_free_run", sequence_path=str(free_path), task_id="f1")
    assert not busy["ok"] and "already running" in busy["error"]
    assert call(action="stop_scan", task_id="t1")["task_state"] == "stopped"
    assert call(action="start_free_run", sequence_path=str(free_path), task_id="f1")["ok"]
    assert call(action="stop_free_run", task_id="f1")["task_state"] == "stopped"


def test_scan_without_saved_scan_is_refused(simulator):
    _window, _scan, free_path = simulator
    reply = call(action="start_scan", sequence_path=str(free_path), task_id="t1")
    assert not reply["ok"] and "no saved scan" in reply["error"]
