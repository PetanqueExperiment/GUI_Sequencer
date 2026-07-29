"""Shared PyCam experiment helpers (scan label vs live run/pause)."""

from __future__ import annotations

import time

from sequencer_gui.process_identity import PYCAM_HERO_INSTANCE_NAME, PYCAM_LIVE_EXPERIMENT_NAME

_READY_POLL_S = 0.05
_READY_TIMEOUT_S = 30.0


def clear_scan_plan(hero) -> None:
    hero.clear_parameter_scan_order()


def prepare_live_experiment(hero) -> None:
    """Live adjustments: no scan tag plan (PyCam iteration bar stays idle)."""
    prepare_and_start_experiment(
        hero, PYCAM_LIVE_EXPERIMENT_NAME, clear_scan_plan_first=True
    )


def sync_live_experiment_name(hero) -> None:
    sync_experiment_name(hero, PYCAM_LIVE_EXPERIMENT_NAME)


def _pycam_status(hero) -> str:
    return str(hero.get_status())


def wait_until_ready(hero, *, timeout_s: float = _READY_TIMEOUT_S) -> None:
    """
    Block until PyCam reports ``is_ready()`` (safe to call ``startExperiment()``).

    Do not treat ``isPyCamExperimentRunning() == False`` as ready; that flag flips
    too early during start/stop.
    """
    deadline = time.monotonic() + float(timeout_s)
    while not hero.is_ready():
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for PyCam to become ready "
                f"(status={_pycam_status(hero)!r}, timeout={timeout_s}s)."
            )
        time.sleep(_READY_POLL_S)


def ensure_ready_to_start(hero, *, timeout_s: float = _READY_TIMEOUT_S) -> None:
    """Stop mid-lifecycle acquisition if needed, then wait until ``is_ready()``."""
    if hero.is_ready():
        return
    status = _pycam_status(hero)
    if status == "no_camera":
        raise RuntimeError("PyCam is not ready: no camera open.")
    if status in ("running", "starting"):
        hero.stopExperiment()
    wait_until_ready(hero, timeout_s=timeout_s)


def prepare_and_start_experiment(
    hero,
    name: str,
    *,
    scan_tags: list[str] | None = None,
    clear_scan_plan_first: bool = False,
) -> None:
    """
    Recommended remote flow: wait ``is_ready`` → set name → optional scan order → start.
    """
    ensure_ready_to_start(hero)

    hero.set_ExperimentName(name)
    if not hero.is_ExperimentName_synced(name):
        raise RuntimeError(
            f"Experiment name not synced (expected {name!r}, PyCam has {hero.get_ExperimentName()!r})."
        )

    if clear_scan_plan_first:
        clear_scan_plan(hero)
    elif scan_tags is not None:
        set_parameter_scan_order(hero, scan_tags)

    hero.startExperiment()


def sync_experiment_name(hero, name: str) -> None:
    hero.set_ExperimentName(name)
    if not hero.is_ExperimentName_synced(name):
        raise RuntimeError(
            f"Experiment name not synced (expected {name!r}, PyCam has {hero.get_ExperimentName()!r})."
        )


def stop_experiment_if_running(hero) -> None:
    """Stop acquisition if starting/running, then wait until ``is_ready()``."""
    status = _pycam_status(hero)
    if status in ("running", "starting"):
        hero.stopExperiment()
        wait_until_ready(hero)
    elif status == "stopping":
        wait_until_ready(hero)


def is_experiment_running() -> bool:
    try:
        from heros import RemoteHERO
    except ImportError:
        return False
    try:
        with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
            return _pycam_status(hero) == "running"
    except Exception:
        return False


def set_parameter_scan_order(hero, tags: list[str]) -> None:
    hero.set_parameter_scan_order(tags)


def shots_seen(hero) -> int:
    """Shots PyCam has finished saving (index of the next tag in the scan plan)."""
    return int(hero.get_current_scan_index())


def parameter_scan_order_length(hero) -> int | None:
    order = hero.get_parameter_scan_order()
    if order is None:
        return None
    return len(order)
