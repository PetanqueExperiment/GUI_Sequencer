"""Names and limits of the local IPC between the Sequence Scheduler and the sequencer GUI.

Shared by both programs: the scheduler (separate repository) imports this module from the
installed sequencer package, so changing a name here needs the scheduler restarted too.

Every request is one JSON object on one line over a new local connection; the reply is one JSON
line, ``{"ok": true, ...}`` or ``{"ok": false, "error": "..."}``, and the connection closes.

Requests served by the sequencer (``remote_control/scheduler_link.py``):

    {"action": "start_scan", "sequence_path": "...", "task_id": "..."}
    {"action": "get_task_status", "task_id": "..."}
    {"action": "stop_scan", "task_id": "..."}
    {"action": "start_free_run", "sequence_path": "...", "task_id": "..."}
    {"action": "stop_free_run", "task_id": "..."}

Scan replies carry ``task_state`` (one of the ``TASK_*`` values), ``progress_completed`` and
``progress_total`` (shots) and ``error``.

Request served by the scheduler (sent by the Scan panel's Queue in scheduler button,
``remote_control/scheduler_client.py``); the reply carries ``queue_position`` and ``task_id``:

    {"action": "queue_scan", "sequence_path": "..."}
"""

from __future__ import annotations

# Qt local server names (named pipes on Windows, per-user local sockets elsewhere).
SCHEDULER_SERVER_NAME = "petanque-sequence-scheduler"
SEQUENCER_SERVER_NAME = "petanque-sequencer-scheduler-link"
# Hardware-free sequencer simulator shipped with the scheduler.
SEQUENCER_SIMULATION_SERVER_NAME = "petanque-sequencer-scheduler-link-simulation"

MAX_IPC_LINE_BYTES = 64 * 1024

TASK_STARTING = "starting"
TASK_RUNNING = "running"
TASK_COMPLETED = "completed"
TASK_STOPPED = "stopped"
TASK_FAILED = "failed"
TASK_UNKNOWN = "unknown"
