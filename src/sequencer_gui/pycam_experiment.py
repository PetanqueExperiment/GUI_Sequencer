"""Shared PyCam experiment helpers (scan label vs live run/pause)."""

from __future__ import annotations

from sequencer_gui.process_identity import PYCAM_HERO_INSTANCE_NAME, PYCAM_LIVE_EXPERIMENT_NAME


def clear_scan_plan(hero) -> None:
    hero.clear_parameter_scan_order()


def prepare_live_experiment(hero) -> None:
    """Live adjustments: no scan tag plan (PyCam iteration bar stays idle)."""
    clear_scan_plan(hero)
    prepare_and_start_experiment(hero, PYCAM_LIVE_EXPERIMENT_NAME)


def sync_live_experiment_name(hero) -> None:
    sync_experiment_name(hero, PYCAM_LIVE_EXPERIMENT_NAME)


def prepare_and_start_experiment(hero, name: str) -> None:
    if hero.isPyCamExperimentRunning():
        hero.stopExperiment()
    if hero.isPyCamExperimentRunning():
        raise RuntimeError("PyCam experiment is still running after stopExperiment().")

    hero.set_ExperimentName(name)
    if not hero.is_ExperimentName_synced(name):
        raise RuntimeError(
            f"Experiment name not synced (expected {name!r}, PyCam has {hero.get_ExperimentName()!r})."
        )

    hero.startExperiment()


def sync_experiment_name(hero, name: str) -> None:
    hero.set_ExperimentName(name)
    if not hero.is_ExperimentName_synced(name):
        raise RuntimeError(
            f"Experiment name not synced (expected {name!r}, PyCam has {hero.get_ExperimentName()!r})."
        )


def stop_experiment_if_running(hero) -> None:
    if hero.isPyCamExperimentRunning():
        hero.stopExperiment()


def is_experiment_running() -> bool:
    try:
        from heros import RemoteHERO
    except ImportError:
        return False
    try:
        with RemoteHERO(PYCAM_HERO_INSTANCE_NAME) as hero:
            return bool(hero.isPyCamExperimentRunning())
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
