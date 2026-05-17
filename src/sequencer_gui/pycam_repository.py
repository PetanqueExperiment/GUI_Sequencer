"""PyCam experiment folders on disk (same layout as :mod:`PyCam` data management)."""

from __future__ import annotations

import os
import time
from enum import Enum
from pathlib import Path

# Root used by PyCam.PyCam.DATA_DIRECTORY; override via env for non-default installs.
PYCAM_DATA_DIRECTORY = os.environ.get("PYCAM_DATA_DIRECTORY", r"D:\Experimental_Data")


class ScanLabelAvailability(Enum):
    UNUSED = "unused"
    USED_TODAY = "used_today"
    IN_PROGRESS = "in_progress"


def today_data_directory(data_root: str | Path | None = None) -> Path:
    """``{data_root}/{year}/{month}/{day}/`` — matches PyCam.updateExperimentName()."""
    root = Path(data_root or PYCAM_DATA_DIRECTORY)
    return Path(
        os.path.expanduser(
            os.path.join(
                str(root),
                time.strftime("%Y").lstrip("0"),
                time.strftime("%m"),
                time.strftime("%d"),
            )
        )
    )


def experiment_names_used_today(data_root: str | Path | None = None) -> set[str]:
    """Experiment folder names already present under today's date directory."""
    day_dir = today_data_directory(data_root)
    if not day_dir.is_dir():
        return set()
    return {p.name for p in day_dir.iterdir() if p.is_dir()}


def classify_scan_label(
    name: str,
    *,
    scan_running: bool,
    active_scan_label: str,
    data_root: str | Path | None = None,
) -> ScanLabelAvailability | None:
    """Classify a proposed scan label; ``None`` when ``name`` is empty."""
    label = name.strip()
    if not label:
        return None
    if scan_running and label == active_scan_label.strip():
        return ScanLabelAvailability.IN_PROGRESS
    if label in experiment_names_used_today(data_root):
        return ScanLabelAvailability.USED_TODAY
    return ScanLabelAvailability.UNUSED
