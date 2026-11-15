"""Sending a saved scan to the Sequence Scheduler's queue (Scan panel: Queue in scheduler).

The scheduler (separate program) serves ``{"action": "queue_scan", "sequence_path": ...}`` on
``SCHEDULER_SERVER_NAME`` (see :mod:`sequencer_gui.scheduler_protocol`) and re-reads the file when
the scan starts. The connection is opened first and the request sent later, so the caller can
write the file only once it knows the scheduler is running.

Queued scans wait in ``SCHEDULER_QUEUE_DIR`` as ``<scan label>.json``. When the scheduler runs
one, Start scan saves the usual copy next to the PyCam data; the held file is deleted once the
scan has completed or been stopped, and kept after a failure (the scheduler queues it again).

Both are blocking but short: the scheduler answers at once, and a missing scheduler fails
immediately (no named pipe to connect to).
"""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5.QtNetwork import QLocalSocket

from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.domain.scan import ScanPlan
from sequencer_gui.scheduler_protocol import MAX_IPC_LINE_BYTES, SCHEDULER_SERVER_NAME
from sequencer_gui.sequence_io import save_sequence

# Sequences queued in the scheduler wait here until their scan has run.
SCHEDULER_QUEUE_DIR = Path.home() / ".sequencer_gui" / "scheduler_queue"

CONNECT_TIMEOUT_MS = 500
REPLY_TIMEOUT_MS = 3000


class SchedulerQueueError(Exception):
    """The scan could not be queued; the message is meant for the operator."""


def save_queued_scan(
    label: str, sequence_name: str, document: SequenceDocument, scan: ScanPlan
) -> Path:
    """Write the sequence and scan to ``SCHEDULER_QUEUE_DIR/<label>.json`` (``_2``, ... if taken)."""
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in label.strip())[:80] or "scan"
    SCHEDULER_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    path = SCHEDULER_QUEUE_DIR / f"{stem}.json"
    n = 2
    while path.exists():
        path = SCHEDULER_QUEUE_DIR / f"{stem}_{n}.json"
        n += 1
    save_sequence(path, sequence_name, document, scan)
    return path


def is_queued_scan_file(path: str | Path) -> bool:
    """True if ``path`` is a file held in ``SCHEDULER_QUEUE_DIR``."""
    try:
        return Path(path).resolve().parent == SCHEDULER_QUEUE_DIR.resolve()
    except OSError:
        return False


def connect_to_scheduler(server_name: str = SCHEDULER_SERVER_NAME) -> QLocalSocket:
    """Open a connection to the running scheduler, or raise if it is not running."""
    socket = QLocalSocket()
    socket.connectToServer(server_name)
    if not socket.waitForConnected(CONNECT_TIMEOUT_MS):
        socket.abort()
        raise SchedulerQueueError(
            "The Sequence Scheduler is not running. Start it, then queue the scan again."
        )
    return socket


def send_queue_scan(socket: QLocalSocket, sequence_path: str | Path) -> dict:
    """Ask the scheduler to append the saved scan to its queue; returns its reply.

    The reply holds ``queue_position`` and ``task_id``. Closes ``socket`` in every case.
    """
    request = {"action": "queue_scan", "sequence_path": str(Path(sequence_path).resolve())}
    payload = json.dumps(request).encode("utf-8") + b"\n"
    try:
        if len(payload) > MAX_IPC_LINE_BYTES:
            raise SchedulerQueueError("The sequence path is too long to send to the scheduler.")
        socket.write(payload)
        if not socket.waitForBytesWritten(REPLY_TIMEOUT_MS):
            raise SchedulerQueueError("Could not send the scan to the Sequence Scheduler.")
        while not socket.canReadLine():
            if not socket.waitForReadyRead(REPLY_TIMEOUT_MS):
                raise SchedulerQueueError("The Sequence Scheduler did not answer.")
        try:
            response = json.loads(bytes(socket.readLine()).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SchedulerQueueError("The Sequence Scheduler sent an invalid answer.") from error
    finally:
        socket.abort()
    if not isinstance(response, dict):
        raise SchedulerQueueError("The Sequence Scheduler sent an invalid answer.")
    if not response.get("ok"):
        raise SchedulerQueueError(
            str(response.get("error") or "The Sequence Scheduler refused the scan.")
        )
    return response
