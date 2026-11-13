"""AI proposals: sequence changes and/or a scan, checked here and approved by the operator (no widgets).

A proposal arrives as JSON (see :data:`PROPOSAL_FORMAT_HELP`). This module

1. parses it (:func:`parse_proposal`) — shape errors become ``ValueError`` with a readable message;
2. checks it against the live document (:func:`resolve_changes`, :func:`check_scan`) — unknown
   rows / columns, out-of-range values, ramp on a device without ramp, ON on an analog-only device;
3. applies the changes the operator ticked (:func:`apply_changes`).

Columns are addressed on the Complete timeline (enabled blocks as played), like the scan panel:
an exact column label first, else ``cN`` or ``N`` as the 0-based index.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from sequencer_gui.app.state import ScanParameter
from sequencer_gui.domain.analog_stored import (
    ANALOG_HOLD,
    ANALOG_RAMP,
    is_hold_signal,
    is_ramp_signal,
    ramp_applies_to_software,
)
from sequencer_gui.domain.document import (
    SequenceDocument,
    merge_blocks,
    merged_enabled_timeline_col_to_block,
)
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.scan_plan import (
    anticipated_scan_duration_s,
    expected_shot_count,
    resolve_scan_bindings,
)
from sequencer_gui.software_objects import get_object
from sequencer_gui.software_objects.types import AnalogParameterSpec

# Same limits as the delay field of the matrix (ui/channel_matrix.py _DELAY_MIN_US / _DELAY_MAX_US).
DELAY_MIN_US = 0.004
DELAY_MAX_US = 1e9

PROPOSAL_FORMAT_HELP = """\
{
  "summary": "one line for the operator",
  "base_revision": "<revision from sequencer_overview>",
  "changes": [
    {"row": "<row label>", "param": "<param_id>", "column": "<col>", "value": <number | "hold" | "ramp">},
    {"row": "<row label>", "column": "<col>", "on": true | false},
    {"column": "<col>", "delay_us": <number>}
  ],
  "scan": {"label": "<PyCam experiment name>", "repetitions": <int>, "reason": "<why>",
           "axes": [{"device": "<row label | static device | time>", "param": "<param_id>",
                     "timestep": "<col>", "values": [<numbers>]}]}
}
<col> = column label, or cN / N (0-based index on the Complete timeline).
"changes" and "scan" are both optional, but at least one is required."""


# --- parsed proposal ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Change:
    """One proposed edit. ``kind`` is ``value`` (analog cell), ``on`` (ON/OFF) or ``delay``."""

    kind: str
    column: str
    row: str = ""
    param: str = ""
    value: float | str | bool = 0.0


@dataclass(frozen=True)
class ScanAxis:
    device: str
    param: str
    timestep: str
    values: tuple[float, ...]


@dataclass(frozen=True)
class ScanProposal:
    label: str
    repetitions: int
    reason: str
    axes: tuple[ScanAxis, ...]


@dataclass(frozen=True)
class Proposal:
    summary: str
    base_revision: str
    changes: tuple[Change, ...]
    scan: ScanProposal | None


def _text(d: dict[str, Any], key: str, where: str, *, required: bool = True) -> str:
    v = d.get(key, "")
    if v is None:
        v = ""
    if not isinstance(v, (str, int)) or isinstance(v, bool):
        raise ValueError(f"{where}: '{key}' must be a string")
    text = str(v).strip()
    if required and not text:
        raise ValueError(f"{where}: '{key}' is required")
    return text


def _number(v: Any, where: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"{where}: expected a number, got {v!r}")
    return float(v)


def _parse_change(raw: Any, i: int) -> Change:
    where = f"changes[{i}]"
    if not isinstance(raw, dict):
        raise ValueError(f"{where}: must be an object")
    kinds = [k for k in ("value", "on", "delay_us") if k in raw]
    if len(kinds) != 1:
        raise ValueError(f"{where}: give exactly one of 'value', 'on', 'delay_us'")
    column = _text(raw, "column", where)
    if kinds[0] == "delay_us":
        return Change("delay", column, value=_number(raw["delay_us"], f"{where}.delay_us"))
    row = _text(raw, "row", where)
    if kinds[0] == "on":
        if not isinstance(raw["on"], bool):
            raise ValueError(f"{where}: 'on' must be true or false")
        return Change("on", column, row=row, value=raw["on"])
    value = raw["value"]
    if isinstance(value, str):
        value = value.strip().lower()
        if value not in (ANALOG_HOLD, ANALOG_RAMP):
            raise ValueError(f"{where}: 'value' must be a number, \"hold\" or \"ramp\"")
    else:
        value = _number(value, f"{where}.value")
    return Change("value", column, row=row, param=_text(raw, "param", where), value=value)


def _parse_scan(raw: Any) -> ScanProposal:
    if not isinstance(raw, dict):
        raise ValueError("scan: must be an object")
    reps = raw.get("repetitions")
    if isinstance(reps, bool) or not isinstance(reps, int) or reps < 1:
        raise ValueError("scan: 'repetitions' must be a positive integer")
    axes_raw = raw.get("axes")
    if not isinstance(axes_raw, list) or not axes_raw:
        raise ValueError("scan: 'axes' must be a non-empty list")
    axes = []
    for k, a in enumerate(axes_raw):
        where = f"scan.axes[{k}]"
        if not isinstance(a, dict):
            raise ValueError(f"{where}: must be an object")
        values = a.get("values")
        if not isinstance(values, list) or not values:
            raise ValueError(f"{where}: 'values' must be a non-empty list of numbers")
        device = _text(a, "device", where)
        axes.append(
            ScanAxis(
                device=device,
                param=_text(a, "param", where),
                timestep=_text(a, "timestep", where, required=False),
                values=tuple(_number(v, f"{where}.values") for v in values),
            )
        )
    return ScanProposal(
        label=_text(raw, "label", "scan"),
        repetitions=reps,
        reason=_text(raw, "reason", "scan", required=False),
        axes=tuple(axes),
    )


def parse_proposal(data: Any) -> Proposal:
    """Check the JSON shape (not the sequence content); ``ValueError`` explains what is wrong."""
    if not isinstance(data, dict):
        raise ValueError("proposal must be a JSON object")
    changes_raw = data.get("changes") or []
    if not isinstance(changes_raw, list):
        raise ValueError("'changes' must be a list")
    changes = tuple(_parse_change(c, i) for i, c in enumerate(changes_raw))
    scan = _parse_scan(data["scan"]) if data.get("scan") else None
    if not changes and scan is None:
        raise ValueError("a proposal needs 'changes', 'scan', or both")
    return Proposal(
        summary=_text(data, "summary", "proposal"),
        base_revision=_text(data, "base_revision", "proposal"),
        changes=changes,
        scan=scan,
    )


# --- checking against the document --------------------------------------------------------------


def _fmt(v: float) -> str:
    return format(float(v), ".10g")


def _unit(spec_label: str) -> str:
    """'Detuning (MHz)' -> ' MHz'; labels without a unit -> ''."""
    m = re.search(r"\(([^)]+)\)\s*$", spec_label)
    return f" {m.group(1)}" if m else ""


def resolve_column(model: SequenceModel, column: str) -> int:
    """Complete-timeline column: exact label, else ``cN`` / ``N``; ``ValueError`` if unknown."""
    text = column.strip()
    matches = [c for c in range(model.cols) if model.col_label(c) == text]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"column label {text!r} is used {len(matches)} times; use cN")
    digits = text[1:] if text[:1].lower() == "c" else text
    if digits.isdigit() and int(digits) < model.cols:
        return int(digits)
    raise ValueError(f"unknown column {text!r} (Complete timeline has c0..c{model.cols - 1})")


def _resolve_row(document: SequenceDocument, row: str) -> int:
    labels = list(document.row_labels)
    matches = [r for r, lab in enumerate(labels) if lab == row]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(f"row label {row!r} is used {len(matches)} times")
    raise ValueError(f"unknown row {row!r}")


def _spec(document: SequenceDocument, row: int, param: str) -> AnalogParameterSpec:
    obj = get_object(document.row_software[row])
    for s in obj.analog_parameters:
        if s.param_id == param:
            return s
    valid = ", ".join(s.param_id for s in obj.analog_parameters) or "none"
    raise ValueError(
        f"row {document.row_labels[row]!r} ({obj.display_name}) has no parameter {param!r} "
        f"(valid: {valid})"
    )


def _played(value: float) -> str:
    if is_hold_signal(value):
        return ANALOG_HOLD
    if is_ramp_signal(value):
        return ANALOG_RAMP
    return _fmt(value)


@dataclass(frozen=True)
class ResolvedChange:
    """A checked change with what the window shows: ``what``, ``old`` → ``new`` ``unit``."""

    change: Change
    merged_col: int
    block_index: int
    local_col: int
    row: int  # -1 for a delay
    what: str
    old: str
    new: str
    unit: str
    tooltip: str


def _resolve_one(document: SequenceDocument, model: SequenceModel, ch: Change) -> ResolvedChange:
    col = resolve_column(model, ch.column)
    located = merged_enabled_timeline_col_to_block(document, col)
    if located is None:
        raise ValueError(f"column c{col} is not on an enabled block")
    bi, local = located
    block_name = document.blocks[bi].name
    if ch.kind == "delay":
        value = float(ch.value)
        if not (DELAY_MIN_US <= value <= DELAY_MAX_US):
            raise ValueError(f"delay {value:g} us outside {DELAY_MIN_US:g}..{DELAY_MAX_US:g} us")
        return ResolvedChange(
            ch, col, bi, local, -1, f"delay c{col}", _fmt(model.delay_us(col)), _fmt(value), " us",
            f'Delay of column c{col} ("{model.col_label(col)}") in block "{block_name}"',
        )
    row = _resolve_row(document, ch.row)
    obj = get_object(document.row_software[row])
    if ch.kind == "on":
        if not obj.has_on_off:
            raise ValueError(f"row {ch.row!r} ({obj.display_name}) has no ON/OFF")
        return ResolvedChange(
            ch, col, bi, local, row, f"{ch.row} c{col}",
            "ON" if model.channel(row, col) else "off", "ON" if ch.value else "off", "",
            f'ON/OFF of "{ch.row}", column c{col} in block "{block_name}"',
        )
    spec = _spec(document, row, ch.param)
    if ch.value == ANALOG_RAMP and not ramp_applies_to_software(obj.id):
        raise ValueError(f"row {ch.row!r} ({obj.display_name}) does not support ramp")
    if isinstance(ch.value, float) and not (spec.minimum <= ch.value <= spec.maximum):
        raise ValueError(
            f"{ch.row} {ch.param} = {ch.value:g} outside {spec.minimum:g}..{spec.maximum:g}"
            f"{_unit(spec.label)}"
        )
    new = ch.value if isinstance(ch.value, str) else _fmt(ch.value)
    return ResolvedChange(
        ch, col, bi, local, row, f"{ch.row} c{col}",
        _played(model.analog_value(row, ch.param, col)), new, _unit(spec.label),
        f'{spec.label} of "{ch.row}", column c{col} in block "{block_name}"',
    )


def _cell_key(r: ResolvedChange) -> tuple:
    return (r.change.kind, r.row, r.change.param, r.merged_col)


def resolve_changes(document: SequenceDocument, changes: tuple[Change, ...]) -> list[ResolvedChange]:
    """Check every change; one ``ValueError`` lists all problems (numbered like the input)."""
    model = merge_blocks(document, enabled_only=True)
    out: list[ResolvedChange] = []
    errors: list[str] = []
    seen: dict[tuple, int] = {}
    for i, ch in enumerate(changes):
        try:
            r = _resolve_one(document, model, ch)
        except ValueError as e:
            errors.append(f"changes[{i}]: {e}")
            continue
        key = _cell_key(r)
        if key in seen:
            errors.append(f"changes[{i}]: same cell as changes[{seen[key]}]")
            continue
        seen[key] = i
        out.append(r)
    if errors:
        raise ValueError("; ".join(errors))
    return out


def apply_changes(document: SequenceDocument, resolved: list[ResolvedChange]) -> SequenceDocument:
    """New document with these changes (column positions are unchanged by any of them)."""
    doc = document
    for r in resolved:
        block = doc.blocks[r.block_index]
        ch = r.change
        if ch.kind == "delay":
            block = block.with_delay_us(r.local_col, float(ch.value))
        elif ch.kind == "on":
            block = block.with_channel(doc.rows, r.row, r.local_col, bool(ch.value))
        else:
            block = block.with_analog(doc.rows, r.row, ch.param, r.local_col, ch.value)
        doc = doc.with_block(r.block_index, block)
    return doc


# --- scan -----------------------------------------------------------------------------------------


def scan_parameters(scan: ScanProposal) -> tuple[ScanParameter, ...]:
    """Scan panel cards; ``cN`` timesteps become ``N`` (the scan panel's index form)."""
    params = []
    for a in scan.axes:
        ts = a.timestep
        if re.fullmatch(r"[cC]\d+", ts):
            ts = ts[1:]
        params.append(ScanParameter(a.device, a.param, ts, ", ".join(_fmt(v) for v in a.values)))
    return tuple(params)


@dataclass(frozen=True)
class ScanCheck:
    points: int
    shots: int
    duration_s: float
    # Per axis: (where, "v1, v2, ...", unit, value now or "").
    axes: tuple[tuple[str, str, str, str], ...]


def check_scan(document: SequenceDocument, scan: ScanProposal) -> ScanCheck:
    """Validate the axes on ``document`` (same rules as Start scan); ``ValueError`` if invalid."""
    params = scan_parameters(scan)
    bindings = resolve_scan_bindings(document, params)
    model = merge_blocks(document, enabled_only=True)
    axes = []
    points = 1
    for a, bd in zip(scan.axes, bindings):
        points *= len(a.values)
        values = ", ".join(_fmt(v) for v in a.values)
        if bd.is_static:
            axes.append((f"{a.device} (static)", values, "", _fmt(document.static_value(bd.row, bd.param_id))))
        elif bd.is_delay:
            axes.append((f"delay c{bd.merged_col}", values, " us", _fmt(model.delay_us(bd.merged_col))))
        else:
            spec = _spec(document, bd.row, bd.param_id)
            now = _played(model.analog_value(bd.row, bd.param_id, bd.merged_col))
            axes.append((f"{a.device} c{bd.merged_col}", values, _unit(spec.label), now))
    return ScanCheck(
        points=points,
        shots=expected_shot_count(params, scan.repetitions),
        duration_s=anticipated_scan_duration_s(document, params, scan.repetitions) or 0.0,
        axes=tuple(axes),
    )
