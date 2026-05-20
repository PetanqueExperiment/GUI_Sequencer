"""Fetch and summarize ARTIQ master scheduler status via the atomiq-scheduler HERO."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sequencer_gui.process_identity import (
    ATOMIQ_EXPERIMENTDB_HERO_NAME,
    ATOMIQ_SCHEDULER_HERO_NAME,
)

_ACTIVE_STATUSES = frozenset({"running", "paused"})
_QUEUED_STATUSES = frozenset(
    {"pending", "flushing", "preparing", "prepare_done"}
)


@dataclass(frozen=True)
class RunSummary:
    rid: int
    status: str
    pipeline: str
    file: str

    @property
    def file_name(self) -> str:
        path = self.file.strip()
        if not path:
            return "—"
        return Path(path).name


@dataclass(frozen=True)
class SchedulerSnapshot:
    connected: bool
    error: str | None
    active: RunSummary | None
    queued: tuple[RunSummary, ...]
    other_runs: tuple[RunSummary, ...]


def _run_summary(rid: Any, run: dict[str, Any]) -> RunSummary:
    expid = run.get("expid") or {}
    if not isinstance(expid, dict):
        expid = {}
    return RunSummary(
        rid=int(rid),
        status=str(run.get("status") or "unknown"),
        pipeline=str(run.get("pipeline") or ""),
        file=str(expid.get("file") or ""),
    )


def parse_scheduler_status(raw: dict[Any, Any] | None) -> SchedulerSnapshot:
    """Turn ``scheduler.get_status()`` into a display-oriented snapshot."""
    if not raw:
        return SchedulerSnapshot(True, None, None, (), ())

    runs = [_run_summary(rid, run) for rid, run in raw.items() if isinstance(run, dict)]
    active = next((r for r in runs if r.status in _ACTIVE_STATUSES), None)
    queued = tuple(r for r in runs if r.status in _QUEUED_STATUSES)
    other = tuple(
        r
        for r in runs
        if r not in ({active} if active else set())
        and r not in queued
    )
    return SchedulerSnapshot(True, None, active, queued, other)


def snapshot_from_scheduler(scheduler: object) -> SchedulerSnapshot:
    """Read status from an already-connected scheduler HERO stub."""
    raw = scheduler.get_status()
    if not isinstance(raw, dict):
        return SchedulerSnapshot(
            False,
            f"Unexpected get_status() type: {type(raw).__name__}",
            None,
            (),
            (),
        )
    return parse_scheduler_status(raw)


def connect_scheduler_hero(hero_name: str = ATOMIQ_SCHEDULER_HERO_NAME) -> object:
    """Open a long-lived RemoteHERO to the scheduler (do not use per-tick ``with``)."""
    from heros import RemoteHERO

    return RemoteHERO(hero_name)


def connect_experimentdb_hero(hero_name: str = ATOMIQ_EXPERIMENTDB_HERO_NAME) -> object:
    """Open a long-lived RemoteHERO to the experiment database."""
    from heros import RemoteHERO

    return RemoteHERO(hero_name)


def connect_artiq_heroes() -> tuple[object, object]:
    """Connect scheduler and experiment-database HEROs (slow discovery; reuse stubs)."""
    return connect_scheduler_hero(), connect_experimentdb_hero()


def release_scheduler_hero(scheduler: object | None) -> None:
    """Tear down a scheduler stub created by :func:`connect_scheduler_hero`."""
    release_remote_hero(scheduler)


def release_experimentdb_hero(experimentdb: object | None) -> None:
    """Tear down an experiment-db stub created by :func:`connect_experimentdb_hero`."""
    release_remote_hero(experimentdb)


def release_remote_hero(hero: object | None) -> None:
    if hero is None:
        return
    destroy = getattr(hero, "_destroy_hero", None)
    if callable(destroy):
        destroy()


def fetch_scheduler_snapshot(
    hero_name: str = ATOMIQ_SCHEDULER_HERO_NAME,
) -> SchedulerSnapshot:
    """One-shot status read (opens and closes a HERO connection; slow for polling)."""
    try:
        scheduler = connect_scheduler_hero(hero_name)
    except ImportError as e:
        return SchedulerSnapshot(False, f"HERO not installed ({e!r})", None, (), ())
    except Exception as e:
        return SchedulerSnapshot(False, str(e), None, (), ())
    try:
        return snapshot_from_scheduler(scheduler)
    except Exception as e:
        return SchedulerSnapshot(False, str(e), None, (), ())
    finally:
        release_scheduler_hero(scheduler)
