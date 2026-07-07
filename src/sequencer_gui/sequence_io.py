"""
Save/load sequence definitions to disk (JSON, versioned).

Top-level: ``format`` / ``version`` (must match :data:`FORMAT_VERSION`) / ``name`` / ``document``.

If a file has fewer top-level device ``rows`` than ``DEFAULT_DEVICE_ROWS`` in
:mod:`sequencer_gui.domain.model`, it is **upgraded** on load: new rows
get the default per-row software object, all-on ``states``, and no explicit analog (defaults apply).
Missing ``device_rows[…]`` keys for an index in a block are treated the same for that row.

Each **block** uses ``device_rows``: ``"0"`` … (device row index) -> ``{ "states": [ bool, … ], "frequency": [ … ], "amplitude": [ … ], … }`` —
``states[s]`` is that device’s bool for time slot ``s``; each analog ``param_id`` (e.g. ``frequency``) is a sibling list: cell is a float, ``"hold"``, ``"ramp"``, or ``null`` (default). Reserved key: ``states`` only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sequencer_gui.domain.analog_stored import ANALOG_HOLD, ANALOG_RAMP, AnalogStored, is_holdish, is_rampish
from sequencer_gui.domain.document import SequenceBlock, SequenceDocument
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS, SequenceModel
from sequencer_gui.domain.static_defaults import (
    DEFAULT_STATIC_ROWS,
    default_static_analog,
    default_static_labels,
    default_static_software,
)
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object, get_static_object

FORMAT_ID = "sequencer_gui_sequence"
FORMAT_VERSION = 8


def _analog_to_json_value(v: AnalogStored) -> float | str:
    if is_holdish(v):
        return "hold"
    if is_rampish(v):
        return "ramp"
    return float(v)


def _analog_cell_from_json(raw: Any) -> AnalogStored:
    if raw == "hold":
        return ANALOG_HOLD
    if raw == "ramp":
        return ANALOG_RAMP
    try:
        return float(raw)
    except (TypeError, ValueError) as e:
        raise SequenceFileError("Invalid analog cell value") from e


def _analog_param_lists_for_row(
    analog: dict[tuple[int, str, int], AnalogStored],
    r: int,
    cols: int,
    row_software: tuple[str, ...],
) -> dict[str, list[Any]]:
    """``param_id`` -> list of length ``cols`` (``null`` = default)."""
    if not (0 <= r < len(row_software)):
        return {}
    row_d: dict[str, list[Any]] = {}
    for p in get_object(row_software[r]).analog_parameters:
        seq: list[Any] = []
        for c in range(cols):
            key = (r, p.param_id, c)
            if key in analog:
                seq.append(_analog_to_json_value(analog[key]))
            else:
                seq.append(None)
        if any(x is not None for x in seq):
            row_d[p.param_id] = seq
    return row_d


def _device_rows_from_block(
    block: SequenceBlock, rows: int, row_software: tuple[str, ...]
) -> dict[str, dict[str, Any]]:
    """``device_rows["<row>"] = { "states": [...], "frequency": [...], ... }`` (analog params as sibling keys)."""
    out: dict[str, dict[str, Any]] = {}
    for r in range(rows):
        obj = get_object(row_software[r])
        if obj.has_on_off:
            state_list = [bool(block.channels.get((r, c), True)) for c in range(block.cols)]
        else:
            state_list = [True] * block.cols
        an = _analog_param_lists_for_row(block.analog, r, block.cols, row_software)
        row: dict[str, Any] = {"states": state_list}
        row.update(an)
        out[str(r)] = row
    return out


def _parse_device_rows(
    device_rows: Any,
    n_device_rows: int,
    cols: int,
    row_software: tuple[str, ...],
) -> tuple[dict[tuple[int, int], bool], dict[tuple[int, str, int], AnalogStored]]:
    if not isinstance(device_rows, dict):
        raise SequenceFileError("device_rows must be an object")
    channels: dict[tuple[int, int], bool] = {}
    analog: dict[tuple[int, str, int], AnalogStored] = {}
    for r in range(n_device_rows):
        skey = str(r)
        if skey not in device_rows:
            for c in range(cols):
                channels[(r, c)] = True
            continue
        row = device_rows[skey]
        if not isinstance(row, dict):
            raise SequenceFileError("device row must be an object")
        states = row.get("states")
        if not isinstance(states, list) or len(states) != cols:
            raise SequenceFileError("device row states must be a list of length cols")
        for c, v in enumerate(states):
            channels[(r, c)] = bool(v)
        if 0 <= r < len(row_software):
            valid_param = {p.param_id for p in get_object(row_software[r]).analog_parameters}
        else:
            valid_param = set()
        for param_id, seq in row.items():
            if param_id == "states":
                continue
            if param_id not in valid_param:
                continue
            if not isinstance(seq, list):
                continue
            pid = str(param_id)
            for c, cell in enumerate(seq):
                if c >= cols:
                    break
                if cell is None:
                    continue
                analog[(r, pid, c)] = _analog_cell_from_json(cell)
    return channels, analog


class SequenceFileError(ValueError):
    pass


def _block_payload(block: SequenceBlock, document: SequenceDocument) -> dict[str, Any]:
    rows = document.rows
    payload: dict[str, Any] = {
        "name": block.name,
        "enabled": block.enabled,
        "cols": block.cols,
        "delays_us": [block.delays_us.get(c, 0.0) for c in range(block.cols)],
        "col_labels": [block.col_label(c) for c in range(block.cols)],
        "device_rows": _device_rows_from_block(block, rows, document.row_software),
    }
    if block.accent_color:
        payload["accent_color"] = block.accent_color
    return payload


def _static_payload(document: SequenceDocument) -> dict[str, Any]:
    values: dict[str, dict[str, float]] = {}
    for (r, param_id), val in document.static_analog.items():
        skey = str(int(r))
        values.setdefault(skey, {})[param_id] = float(val)
    return {
        "rows": document.static_rows,
        "labels": list(document.static_labels),
        "software": [document.static_software[r] for r in range(document.static_rows)],
        "values": values,
    }


def _parse_static_payload(data: Any) -> tuple[int, tuple[str, ...], tuple[str, ...], dict[tuple[int, str], float]]:
    if not isinstance(data, dict):
        rows = DEFAULT_STATIC_ROWS
        return (
            rows,
            default_static_labels(rows),
            default_static_software(rows),
            default_static_analog(rows),
        )
    try:
        rows = int(data.get("rows", DEFAULT_STATIC_ROWS))
    except (TypeError, ValueError) as e:
        raise SequenceFileError("Invalid static.rows") from e
    if rows < 0:
        raise SequenceFileError("static.rows must be non-negative")
    if rows == 0:
        return 0, (), (), {}

    raw_labels = data.get("labels")
    if isinstance(raw_labels, list) and raw_labels:
        labels = tuple(str(x) for x in raw_labels[:rows])
        if len(labels) < rows:
            labels = labels + default_static_labels(rows)[len(labels) :]
    else:
        labels = default_static_labels(rows)

    raw_sw = data.get("software")
    if isinstance(raw_sw, list) and raw_sw:
        software = tuple(
            str(raw_sw[i]) if i < len(raw_sw) else default_static_software(1)[0] for i in range(rows)
        )
    else:
        software = default_static_software(rows)

    analog: dict[tuple[int, str], float] = {}
    raw_values = data.get("values")
    if isinstance(raw_values, dict):
        for skey, row in raw_values.items():
            try:
                r = int(skey)
            except (TypeError, ValueError):
                continue
            if not (0 <= r < rows) or not isinstance(row, dict):
                continue
            valid_param = {p.param_id for p in get_static_object(software[r]).analog_parameters}
            for param_id, cell in row.items():
                if param_id not in valid_param:
                    continue
                try:
                    analog[(r, str(param_id))] = float(cell)
                except (TypeError, ValueError):
                    continue
    return rows, labels, software, analog


def document_to_payload(document: SequenceDocument) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "rows": document.rows,
        "row_labels": list(document.row_labels),
        "row_software": [document.row_software[r] for r in range(document.rows)],
        "blocks": [_block_payload(b, document) for b in document.blocks],
    }
    if document.static_rows > 0:
        payload["static"] = _static_payload(document)
    return payload


def _block_from_payload(
    data: dict[str, Any], rows: int, row_software: tuple[str, ...]
) -> SequenceBlock:
    try:
        name = str(data["name"])
        enabled = bool(data.get("enabled", True))
        cols = int(data["cols"])
        delays = data["delays_us"]
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid block payload") from e

    if cols < 1:
        raise SequenceFileError("block cols must be positive")
    if len(delays) != cols:
        raise SequenceFileError("block delays_us length must match cols")

    channels, analog = _parse_device_rows(
        data.get("device_rows"), rows, cols, row_software
    )

    delays_us = {c: float(delays[c]) for c in range(cols)}

    raw_labels = data.get("col_labels", ())
    if isinstance(raw_labels, list):
        col_labels = tuple(str(x) for x in raw_labels)
    else:
        col_labels = ()

    raw_accent = data.get("accent_color")
    accent_color = str(raw_accent) if raw_accent else None

    return SequenceBlock(
        name=name,
        enabled=enabled,
        cols=cols,
        channels=channels,
        delays_us=delays_us,
        analog=analog,
        col_labels=col_labels,
        accent_color=accent_color,
    )


def sequence_model_from_hero_block(
    document: dict[str, Any], block: dict[str, Any]
) -> SequenceModel:
    """
    One block + document header as in :func:`live_sequence_file_dict` / :func:`set_sequence_data`.
    Resolves ``hold`` the same as the GUI via :meth:`~sequencer_gui.domain.model.SequenceModel.analog_value`.
    """
    try:
        file_rows = int(document["rows"])
    except (KeyError, TypeError, ValueError) as e:
        raise ValueError("invalid document for sequence_model_from_hero_block") from e
    nrows = max(file_rows, DEFAULT_DEVICE_ROWS)
    labels = tuple(str(x) for x in document.get("row_labels", ()))
    rs = document.get("row_software")
    if not isinstance(rs, list):
        rs = []
    row_software = tuple(
        str(rs[i]) if i < len(rs) else DEFAULT_ON_OBJECT for i in range(nrows)
    )
    sb = _block_from_payload(block, nrows, row_software)
    return SequenceModel(
        rows=nrows,
        cols=sb.cols,
        channels=dict(sb.channels),
        delays_us=dict(sb.delays_us),
        analog=dict(sb.analog),
        col_labels=sb.col_labels,
        row_labels=labels,
        row_software=row_software,
    )


def document_from_payload(data: dict[str, Any]) -> SequenceDocument:
    try:
        file_rows = int(data["rows"])
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid document payload") from e

    if file_rows < 1:
        raise SequenceFileError("rows must be positive")
    try:
        raw_labels = data["row_labels"]
        raw_blocks = data["blocks"]
    except KeyError as e:
        raise SequenceFileError("Invalid document payload") from e
    if not isinstance(raw_labels, list):
        raise SequenceFileError("row_labels must be a list")
    if not isinstance(raw_blocks, list) or len(raw_blocks) < 1:
        raise SequenceFileError("document must have at least one block")
    if len(raw_labels) > file_rows:
        raw_labels = raw_labels[:file_rows]
    labels = tuple(str(x) for x in raw_labels)

    # Older files with fewer device rows are upgraded so the rest use defaults.
    rows = max(file_rows, DEFAULT_DEVICE_ROWS)
    rs_raw = data.get("row_software")
    if not isinstance(rs_raw, list):
        rs_raw = []
    if len(rs_raw) > file_rows:
        rs_raw = rs_raw[:file_rows]
    row_software = tuple(
        str(rs_raw[i]) if i < len(rs_raw) else DEFAULT_ON_OBJECT for i in range(rows)
    )

    blocks = tuple(_block_from_payload(b, rows, row_software) for b in raw_blocks)
    static_rows, static_labels, static_software, static_analog = _parse_static_payload(data.get("static"))
    return SequenceDocument(
        rows=rows,
        row_labels=labels,
        row_software=row_software,
        blocks=blocks,
        static_rows=static_rows,
        static_labels=static_labels,
        static_software=static_software,
        static_analog=static_analog,
    )


def live_sequence_file_dict(name: str, document: SequenceDocument) -> dict[str, Any]:
    """Same top-level object as written by ``save_sequence`` (for in-memory sync, e.g. HERO)."""
    return {
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "name": name,
        "document": document_to_payload(document),
    }


def save_sequence(path: Path | str, name: str, document: SequenceDocument) -> None:
    p = Path(path)
    p.write_text(
        json.dumps(live_sequence_file_dict(name, document), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_sequence(path: Path | str) -> tuple[str, SequenceDocument]:
    p = Path(path)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise SequenceFileError(f"Could not read JSON: {e}") from e

    if doc.get("format") != FORMAT_ID:
        raise SequenceFileError("Not a sequencer_gui sequence file (wrong format).")
    try:
        ver = int(doc["version"])
    except (KeyError, TypeError, ValueError) as e:
        raise SequenceFileError("Invalid or missing sequence file version.") from e
    if ver != FORMAT_VERSION:
        raise SequenceFileError("Unsupported sequence file version.")

    name = str(doc.get("name", "Untitled"))

    raw_document = doc.get("document")
    if not isinstance(raw_document, dict):
        raise SequenceFileError("Missing document payload.")
    document = document_from_payload(raw_document)
    return name, document


def validate_document_for_ui(document: SequenceDocument) -> str | None:
    """Return an error message if the document cannot be loaded in this build, else None."""
    if document.rows < DEFAULT_DEVICE_ROWS:
        return f"This build supports at least {DEFAULT_DEVICE_ROWS} device rows (document has {document.rows})."
    for i, b in enumerate(document.blocks):
        if b.cols < 1:
            return f"Block {i + 1} has invalid length."
    return None
