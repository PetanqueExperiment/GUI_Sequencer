"""ARTIQ master actions via atomiq-scheduler and atomiq-experimentdb HEROs."""

from __future__ import annotations

from sequencer_gui.atomiq_status import parse_scheduler_status
from sequencer_gui.process_identity import (
    ATOMIQ_DEFAULT_PIPELINE,
    ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY,
)


def scan_repository_head(experimentdb: object) -> None:
    """Rescan the ARTIQ repository on the master (blocking on the server)."""
    experimentdb.scan_repository_sync()


def list_repository_experiment_keys(experimentdb: object) -> list[str]:
    """Sorted ``list_experiments()`` keys (repository file names)."""
    experiments = experimentdb.list_experiments()
    if not isinstance(experiments, dict):
        return []
    return sorted(str(key) for key in experiments.keys())


def submit_experiment(
    scheduler: object, experimentdb: object, experiment_key: str
) -> object:
    """Schedule an experiment by repository key; returns the new RID."""
    expid = experimentdb.get_experiment(experiment_key)
    return scheduler.submit(ATOMIQ_DEFAULT_PIPELINE, expid)


def submit_sequencer_mode(scheduler: object, experimentdb: object) -> object:
    """Schedule ``Sequencer_mode.py`` on the default pipeline; returns the new RID."""
    return submit_experiment(scheduler, experimentdb, ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY)


def interrupt_running_experiment(scheduler: object) -> bool:
    """
    Delete the running or paused experiment run.

    Returns ``True`` if a run was stopped, ``False`` if none was active.
    """
    raw = scheduler.get_status()
    if not isinstance(raw, dict):
        return False
    active = parse_scheduler_status(raw).active
    if active is None:
        return False
    scheduler.delete(active.rid)
    return True
