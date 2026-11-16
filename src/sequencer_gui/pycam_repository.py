"""PyCam experiment folders on disk (same layout as :mod:`PyCam` data management)."""

from __future__ import annotations

import os
import time
from enum import Enum
from pathlib import Path

from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.domain.scan import ScanPlan
from sequencer_gui.sequence_io import (
    SequenceFileError,
    document_from_payload,
    document_to_payload,
    load_sequence_file,
    save_sequence,
)

# Root used by PyCam.PyCam.DATA_DIRECTORY; override via env for non-default installs.
PYCAM_DATA_DIRECTORY = os.environ.get("PYCAM_DATA_DIRECTORY", r"D:\Experimental_Data")

# Sequence snapshot written next to the shots of a scan, loadable with the toolbar Load button.
SCAN_SEQUENCE_FILE_STEM = "sequence"


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


def unused_experiment_name(label: str, data_root: str | Path | None = None) -> str:
    """``label`` if no folder of that name exists today, else ``label_2``, ``label_3``, … (first free).

    Lets repeated runs of one saved scan each get their own PyCam data folder.
    """
    name = label.strip()
    if not name:
        raise ValueError("Experiment name is empty; cannot choose a new data label.")
    used = experiment_names_used_today(data_root)
    if name not in used:
        return name
    n = 2
    while f"{name}_{n}" in used:
        n += 1
    return f"{name}_{n}"


def experiment_data_directory(
    experiment_name: str, data_root: str | Path | None = None
) -> Path:
    """Folder PyCam saves this experiment into: ``{today_data_directory}/{experiment_name}/``."""
    name = experiment_name.strip()
    if not name:
        raise ValueError("Experiment name is empty; cannot locate the PyCam data folder.")
    return today_data_directory(data_root) / name


def _unused_sequence_path(folder: Path) -> Path:
    candidate = folder / f"{SCAN_SEQUENCE_FILE_STEM}.json"
    if not candidate.exists():
        return candidate
    # Experiment name reused today: keep earlier snapshots, tag this one with the start time.
    stamp = time.strftime("%H%M%S")
    candidate = folder / f"{SCAN_SEQUENCE_FILE_STEM}_{stamp}.json"
    n = 2
    while candidate.exists():
        candidate = folder / f"{SCAN_SEQUENCE_FILE_STEM}_{stamp}_{n}.json"
        n += 1
    return candidate


def _matching_snapshot(
    folder: Path, document: SequenceDocument, scan: ScanPlan | None
) -> Path | None:
    """An existing snapshot in ``folder`` holding the same sequence and scan, or ``None``.

    The ``name`` field is not compared: it only records which file the sequence was loaded from.
    Both sides are compared as they read back from disk (loading fills in default rows/cells).
    """
    wanted_document = document_to_payload(document_from_payload(document_to_payload(document)))
    wanted_scan = scan if scan is not None and not scan.is_empty() else None
    for path in sorted(folder.glob(f"{SCAN_SEQUENCE_FILE_STEM}*.json")):
        try:
            saved = load_sequence_file(path)
        except (OSError, ValueError, SequenceFileError):
            continue  # unreadable or foreign file: never reuse it
        if saved.scan_error is not None:
            continue
        if document_to_payload(saved.document) == wanted_document and saved.scan == wanted_scan:
            return path
    return None


def save_scan_sequence_snapshot(
    experiment_name: str,
    sequence_name: str,
    document: SequenceDocument,
    *,
    data_root: str | Path | None = None,
    scan: ScanPlan | None = None,
) -> Path:
    """Write the sequence JSON into the PyCam data folder of ``experiment_name``; return its path.

    ``scan`` (the plan being started) is stored in the same file, as the Save button does.
    When the experiment name is reused and the folder already holds a snapshot with the same
    sequence and scan, that file is returned and no copy is written.
    """
    folder = experiment_data_directory(experiment_name, data_root)
    folder.mkdir(parents=True, exist_ok=True)
    existing = _matching_snapshot(folder, document, scan)
    if existing is not None:
        return existing
    path = _unused_sequence_path(folder)
    save_sequence(path, sequence_name, document, scan)
    return path


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
