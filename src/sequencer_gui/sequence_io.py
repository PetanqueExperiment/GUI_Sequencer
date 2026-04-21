"""
Save/load sequence definitions to disk.

**Recommended: JSON** (`.json`) — human-readable, stdlib-only, versioned wrapper.

This module implements JSON with a small header (`format`, `version`, `name`).

Version 1: `analog` was a dense rows×cols matrix (one value per row/step).
Version 2: `analog_entries` lists `{row, param_id, col, value}` for per-parameter analog.

Migrating v1 → v2: for each row `r`, legacy values `analog[r][c]` are mapped to the
**first** `param_id` of `get_object(row_software[r])` when that object has at least
one analog parameter; rows with zero analog parameters discard legacy values.
Multi-parameter devices only receive the legacy column on the first parameter; others
default until edited.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object

FORMAT_ID = "sequencer_gui_sequence"
FORMAT_VERSION = 2


class SequenceFileError(ValueError):
    pass


def model_to_payload(model: SequenceModel) -> dict[str, Any]:
    analog_entries: list[dict[str, Any]] = []
    for (r, param_id, c), v in model.analog.items():
        analog_entries.append(
            {"row": r, "param_id": param_id, "col": c, "value": float(v)}
        )
    return {
        "rows": model.rows,
        "cols": model.cols,
        "channels": [
            [model.channel(r, c) for c in range(model.cols)] for r in range(model.rows)
        ],
        "row_software": [model.row_software_name(r) for r in range(model.rows)],
        "delays_us": [model.delay_us(c, 0.0) for c in range(model.cols)],
        "analog_entries": analog_entries,
        "row_labels": list(model.row_labels),
    }


def _migrate_v1_analog(
    rows: int,
    cols: int,
    an_rows: list[list[Any]],
    row_software: tuple[str, ...],
) -> dict[tuple[int, str, int], float]:
    analog: dict[tuple[int, str, int], float] = {}
    for r in range(rows):
        obj = get_object(row_software[r])
        params = obj.analog_parameters
        if not params:
            continue
        pid = params[0].param_id
        for c in range(cols):
            analog[(r, pid, c)] = float(an_rows[r][c])
    return analog


def model_from_payload(data: dict[str, Any], *, format_version: int) -> SequenceModel:
    try:
        rows = int(data["rows"])
        cols = int(data["cols"])
        ch_rows = data["channels"]
        delays = data["delays_us"]
        labels = tuple(str(x) for x in data["row_labels"])
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid sequence payload") from e

    if len(labels) != rows:
        raise SequenceFileError("row_labels length must match rows")
    if len(ch_rows) != rows or any(len(row) != cols for row in ch_rows):
        raise SequenceFileError("channels shape must match rows × cols")
    if len(delays) != cols:
        raise SequenceFileError("delays_us length must match cols")

    channels: dict[tuple[int, int], bool] = {}
    for r, row in enumerate(ch_rows):
        for c, v in enumerate(row):
            channels[(r, c)] = bool(v)

    delays_us = {c: float(delays[c]) for c in range(cols)}

    rs_raw = data.get("row_software")
    if isinstance(rs_raw, list) and len(rs_raw) == rows:
        row_software = tuple(str(rs_raw[i]) for i in range(rows))
    else:
        row_software = tuple(DEFAULT_ON_OBJECT for _ in range(rows))

    if format_version >= 2:
        analog: dict[tuple[int, str, int], float] = {}
        raw_entries = data.get("analog_entries")
        if raw_entries is not None:
            if not isinstance(raw_entries, list):
                raise SequenceFileError("analog_entries must be a list")
            for item in raw_entries:
                try:
                    r = int(item["row"])
                    pid = str(item["param_id"])
                    c = int(item["col"])
                    v = float(item["value"])
                except (KeyError, TypeError, ValueError) as e:
                    raise SequenceFileError("Invalid analog_entries item") from e
                if not (0 <= r < rows and 0 <= c < cols):
                    raise SequenceFileError("analog_entries index out of range")
                analog[(r, pid, c)] = v
    else:
        an_rows = data.get("analog")
        if not isinstance(an_rows, list):
            raise SequenceFileError("analog must be a list (v1)")
        if len(an_rows) != rows or any(len(row) != cols for row in an_rows):
            raise SequenceFileError("analog shape must match rows × cols (v1)")
        analog = _migrate_v1_analog(rows, cols, an_rows, row_software)

    return SequenceModel(
        rows=rows,
        cols=cols,
        channels=channels,
        delays_us=delays_us,
        analog=analog,
        row_labels=labels,
        row_software=row_software,
    )


def save_sequence(path: Path | str, name: str, model: SequenceModel) -> None:
    p = Path(path)
    doc = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": name,
        "model": model_to_payload(model),
    }
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def load_sequence(path: Path | str) -> tuple[str, SequenceModel]:
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SequenceFileError(f"Could not read JSON: {e}") from e

    if doc.get("format") != FORMAT_ID:
        raise SequenceFileError("Not a sequencer_gui sequence file (wrong format).")
    ver = int(doc.get("version", 0))
    if ver < 1 or ver > FORMAT_VERSION:
        raise SequenceFileError("Unsupported sequence file version.")

    name = str(doc.get("name", "Untitled"))
    model = model_from_payload(doc["model"], format_version=ver)
    return name, model
