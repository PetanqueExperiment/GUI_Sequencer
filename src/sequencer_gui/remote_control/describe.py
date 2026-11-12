"""Read-only, JSON-ready descriptions of the sequence for remote clients (no Qt).

Used by :class:`sequencer_gui.remote_control.control_hero.SequencerControl_HERO`. Every function
returns plain ``dict`` / ``list`` / ``str`` / ``float`` / ``bool`` / ``None`` values so the result
can go through :func:`json.dumps` unchanged.

Conventions (shared with the scan panel):

- Rows, blocks and timesteps are addressed by **label** first; a string of digits that matches
  no label is read as a 0-based index.
- Analog cells are reported as stored: a number, ``"hold"`` (keep the previous step's value) or
  ``"ramp"`` (AOM / piezo only). The Complete view also gives ``resolved`` numbers, where hold is
  replaced by the value actually played.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sequencer_gui.domain.analog_stored import (
    ANALOG_HOLD,
    ANALOG_RAMP,
    is_hold_signal,
    is_holdish,
    is_ramp_signal,
    is_rampish,
    ramp_applies_to_software,
)
from sequencer_gui.domain.document import (
    SequenceDocument,
    block_to_sequence_model,
    complete_cycle_rate_hz,
    complete_timeline_duration_us,
    merge_blocks,
    merged_enabled_block_spans,
)
from sequencer_gui.domain.model import DEFAULT_DELAY_US, SequenceModel
from sequencer_gui.software_objects import get_object, get_static_object
from sequencer_gui.software_objects.types import AnalogParameterSpec
from sequencer_gui.sequence_io import live_sequence_file_dict, sequence_display_name

# Bumped when the shape of a description changes, so clients can detect an incompatible GUI.
API_VERSION = 1


@dataclass(frozen=True)
class ScanConfig:
    """Scan panel settings as plain values (built from ``SequenceAppState`` on the GUI thread)."""

    running: bool
    label: str
    repetitions: int
    # One dict per axis: device_label, param_id, timestep_label, values_text.
    parameters: tuple[dict[str, str], ...]


def document_revision(document: SequenceDocument, sequence_name: str) -> str:
    """Short hash of the live sequence JSON; changes whenever the sequence content changes."""
    payload = json.dumps(
        live_sequence_file_dict(sequence_name, document), sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _json_number(value: float) -> float | str:
    """HOLD / RAMP float sentinels become their string names; other floats pass through."""
    if is_hold_signal(value):
        return ANALOG_HOLD
    if is_ramp_signal(value):
        return ANALOG_RAMP
    return float(value)


def _param_spec(spec: AnalogParameterSpec) -> dict[str, Any]:
    return {
        "param_id": spec.param_id,
        "label": spec.label,
        "default": _json_number(spec.default),
        "minimum": float(spec.minimum),
        "maximum": float(spec.maximum),
        "decimals": int(spec.decimals),
    }


def _stored_cell(model: SequenceModel, row: int, param_id: str, col: int) -> float | str:
    """Cell as the user typed it: number, ``"hold"`` or ``"ramp"`` (missing key = hold)."""
    key = (row, param_id, col)
    if key not in model.analog:
        return ANALOG_HOLD
    stored = model.analog[key]
    if is_holdish(stored):
        return ANALOG_HOLD
    if is_rampish(stored) and ramp_applies_to_software(model.row_software_name(row)):
        return ANALOG_RAMP
    # A ramp on a device without ramp support plays the default (see SequenceModel.analog_value).
    return _json_number(model.analog_value(row, param_id, col))


def _timeline(model: SequenceModel, *, with_resolved: bool) -> dict[str, Any]:
    columns = [
        {
            "index": c,
            "label": model.col_label(c),
            "delay_us": float(model.delays_us.get(c, DEFAULT_DELAY_US)),
        }
        for c in range(model.cols)
    ]
    rows: list[dict[str, Any]] = []
    for r in range(model.rows):
        obj = get_object(model.row_software_name(r))
        params: dict[str, Any] = {}
        for spec in obj.analog_parameters:
            pid = spec.param_id
            entry: dict[str, Any] = {
                "stored": [_stored_cell(model, r, pid, c) for c in range(model.cols)]
            }
            if with_resolved:
                entry["resolved"] = [
                    _json_number(model.analog_value(r, pid, c)) for c in range(model.cols)
                ]
            params[pid] = entry
        rows.append(
            {
                "index": r,
                "label": model.row_label(r),
                "device": obj.id,
                # None for analog-only devices (always on, no ON/OFF strip in the GUI).
                "on": [model.channel(r, c) for c in range(model.cols)] if obj.has_on_off else None,
                "params": params,
            }
        )
    return {"columns": columns, "rows": rows}


def _resolve_block_index(document: SequenceDocument, block: str) -> int:
    """Block by exact name, else by 0-based index; ``ValueError`` names the known blocks."""
    text = (block or "").strip()
    names = [b.name for b in document.blocks]
    matches = [i for i, n in enumerate(names) if n == text]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Several blocks are named {text!r} (indices {matches}); use the 0-based index."
        )
    if text.isdigit() and int(text) < len(names):
        return int(text)
    raise ValueError(f"Unknown block {text!r}. Blocks (index: name): {_block_listing(names)}")


def _block_listing(names: list[str]) -> str:
    return ", ".join(f"{i}: {n!r}" for i, n in enumerate(names))


def describe_overview(
    document: SequenceDocument, sequence_name: str, *, run_sequence: bool, scan: ScanConfig
) -> dict[str, Any]:
    """Sequence name, blocks with durations, run / scan state. The starting point for a client."""
    spans = {s.block_index: s.merged_start_col for s in merged_enabled_block_spans(document)}
    blocks = []
    for i, b in enumerate(document.blocks):
        duration_us = sum(float(b.delays_us.get(c, DEFAULT_DELAY_US)) for c in range(b.cols))
        blocks.append(
            {
                "index": i,
                "name": b.name,
                "enabled": b.enabled,
                "cols": b.cols,
                "duration_us": duration_us,
                # First column of this block in the Complete timeline; None if disabled.
                "complete_start_col": spans.get(i),
            }
        )
    return {
        "api_version": API_VERSION,
        "revision": document_revision(document, sequence_name),
        "sequence_name": sequence_display_name(sequence_name),
        "sequence_path": sequence_name,
        "n_rows": document.rows,
        "n_static_devices": document.static_rows,
        "blocks": blocks,
        "complete_duration_us": complete_timeline_duration_us(document),
        "cycle_rate_Hz": complete_cycle_rate_hz(document),
        "run_sequence": run_sequence,
        "scan": {
            "running": scan.running,
            "label": scan.label,
            "repetitions": scan.repetitions,
            "parameters": [dict(p) for p in scan.parameters],
        },
    }


def describe_devices(document: SequenceDocument) -> dict[str, Any]:
    """Timeline rows and static devices with their parameter ranges (labels carry units)."""
    rows = []
    for r in range(document.rows):
        obj = get_object(document.row_software[r])
        rows.append(
            {
                "index": r,
                "label": document.row_labels[r],
                "device": obj.id,
                "device_name": obj.display_name,
                "has_on_off": obj.has_on_off,
                "ramp_allowed": ramp_applies_to_software(obj.id),
                "params": [_param_spec(p) for p in obj.analog_parameters],
            }
        )
    static = []
    for r in range(document.static_rows):
        obj = get_static_object(document.static_software_name(r))
        static.append(
            {
                "index": r,
                "label": document.static_label(r),
                "device": obj.id,
                "device_name": obj.display_name,
                # Remote static devices are applied through their own HERO (name = label).
                "remote_hero": document.static_hero_name(r) or None,
                "params": [
                    {**_param_spec(p), "value": document.static_value(r, p.param_id)}
                    for p in obj.analog_parameters
                ],
            }
        )
    return {"rows": rows, "static_devices": static}


def describe_block(document: SequenceDocument, sequence_name: str, block: str) -> dict[str, Any]:
    """One block's own timeline (stored cells; a hold at column 0 continues the previous block)."""
    index = _resolve_block_index(document, block)
    b = document.blocks[index]
    return {
        "revision": document_revision(document, sequence_name),
        "block": {"index": index, "name": b.name, "enabled": b.enabled, "cols": b.cols},
        **_timeline(block_to_sequence_model(document, index), with_resolved=False),
    }


def describe_complete(document: SequenceDocument, sequence_name: str) -> dict[str, Any]:
    """Enabled blocks concatenated, as played: stored cells plus resolved values."""
    spans = [
        {"name": s.name, "block_index": s.block_index, "start_col": s.merged_start_col, "cols": s.ncol}
        for s in merged_enabled_block_spans(document)
    ]
    return {
        "revision": document_revision(document, sequence_name),
        "block_spans": spans,
        **_timeline(merge_blocks(document, enabled_only=True), with_resolved=True),
    }
