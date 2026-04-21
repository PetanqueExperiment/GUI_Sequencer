"""
Save/load sequence definitions to disk.

**Recommended: JSON** (`.json`) — human-readable, stdlib-only, versioned wrapper.

This module implements JSON with a small header (`format`, `version`, `name`).

Version 1: `analog` was a dense rows×cols matrix (one value per row/step).
Version 2: `analog_entries` lists `{row, param_id, col, value}` for per-parameter analog.
Version 3: multi-block `document` with shared rows and per-block timelines.

Migrating v1 → v2: for each row `r`, legacy values `analog[r][c]` are mapped to the
**first** `param_id` of `get_object(row_software[r])` when that object has at least
one analog parameter; rows with zero analog parameters discard legacy values.
Multi-parameter devices only receive the legacy column on the first parameter; others
default until edited.

Migrating v2 → v3: single-block document from the flat `model` payload.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sequencer_gui.domain.document import SequenceBlock, SequenceDocument, document_from_single_model
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object

FORMAT_ID = "sequencer_gui_sequence"
FORMAT_VERSION = 3

# Fixed hardware rows for this build (matches toolbar validation).
_REQUIRED_ROWS = 4


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


def _block_payload(block: SequenceBlock, rows: int) -> dict[str, Any]:
    analog_entries: list[dict[str, Any]] = []
    for (r, param_id, c), v in block.analog.items():
        analog_entries.append(
            {"row": r, "param_id": param_id, "col": c, "value": float(v)}
        )
    return {
        "name": block.name,
        "enabled": block.enabled,
        "cols": block.cols,
        "channels": [
            [block.channels.get((r, c), True) for c in range(block.cols)] for r in range(rows)
        ],
        "delays_us": [block.delays_us.get(c, 0.0) for c in range(block.cols)],
        "analog_entries": analog_entries,
    }


def document_to_payload(document: SequenceDocument) -> dict[str, Any]:
    return {
        "rows": document.rows,
        "row_labels": list(document.row_labels),
        "row_software": [document.row_software[r] for r in range(document.rows)],
        "blocks": [_block_payload(b, document.rows) for b in document.blocks],
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


def _block_from_payload(data: dict[str, Any], rows: int) -> SequenceBlock:
    try:
        name = str(data["name"])
        enabled = bool(data.get("enabled", True))
        cols = int(data["cols"])
        ch_rows = data["channels"]
        delays = data["delays_us"]
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid block payload") from e

    if cols < 1:
        raise SequenceFileError("block cols must be positive")
    if len(ch_rows) != rows or any(len(row) != cols for row in ch_rows):
        raise SequenceFileError("block channels shape must match rows × cols")
    if len(delays) != cols:
        raise SequenceFileError("block delays_us length must match cols")

    channels: dict[tuple[int, int], bool] = {}
    for r, row in enumerate(ch_rows):
        for c, v in enumerate(row):
            channels[(r, c)] = bool(v)

    delays_us = {c: float(delays[c]) for c in range(cols)}

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

    return SequenceBlock(
        name=name,
        enabled=enabled,
        cols=cols,
        channels=channels,
        delays_us=delays_us,
        analog=analog,
    )


def document_from_payload(data: dict[str, Any]) -> SequenceDocument:
    try:
        rows = int(data["rows"])
        labels = tuple(str(x) for x in data["row_labels"])
        raw_blocks = data["blocks"]
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid document payload") from e

    if len(labels) != rows:
        raise SequenceFileError("row_labels length must match rows")
    if not isinstance(raw_blocks, list) or len(raw_blocks) < 1:
        raise SequenceFileError("document must have at least one block")

    rs_raw = data.get("row_software")
    if isinstance(rs_raw, list) and len(rs_raw) == rows:
        row_software = tuple(str(rs_raw[i]) for i in range(rows))
    else:
        row_software = tuple(DEFAULT_ON_OBJECT for _ in range(rows))

    blocks = tuple(_block_from_payload(b, rows) for b in raw_blocks)
    return SequenceDocument(rows=rows, row_labels=labels, row_software=row_software, blocks=blocks)


def save_sequence(path: Path | str, name: str, document: SequenceDocument) -> None:
    p = Path(path)
    doc = {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": name,
        "document": document_to_payload(document),
    }
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def load_sequence(path: Path | str) -> tuple[str, SequenceDocument]:
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

    if ver <= 2:
        raw_model = doc.get("model")
        if not isinstance(raw_model, dict):
            raise SequenceFileError("Missing model payload (v1/v2).")
        model = model_from_payload(raw_model, format_version=ver)
        return name, document_from_single_model(model, "Block 1")

    raw_document = doc.get("document")
    if not isinstance(raw_document, dict):
        raise SequenceFileError("Missing document payload (v3).")
    document = document_from_payload(raw_document)
    return name, document


def validate_document_for_ui(document: SequenceDocument) -> str | None:
    """Return an error message if the document cannot be loaded in this build, else None."""
    if document.rows != _REQUIRED_ROWS:
        return f"This build only supports {_REQUIRED_ROWS} rows (file has {document.rows})."
    for i, b in enumerate(document.blocks):
        if b.cols < 1:
            return f"Block {i + 1} has invalid length."
    return None
