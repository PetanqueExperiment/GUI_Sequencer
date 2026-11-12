"""Compact text views of the remote API replies, for AI agents (no Qt, no heros, no mcp).

Input: the ``result`` dicts produced by :mod:`sequencer_gui.remote_control.describe`.
Output: short plain text. Only what is set is listed:

- ON/OFF strips as column ranges (``on: c0-3, c7``).
- Analog values as the columns where a value is stored (``frequency: c0=-12, c5=0``); every
  other column holds the previous value, exactly as in the GUI.
- Rows that are never ON and store no value are listed by name only.

Column names ``cN`` are 0-based indices in the timeline shown (block-local for a block view,
merged for the Complete view).
"""

from __future__ import annotations

from typing import Any, Sequence

HOLD = "hold"


def _num(value: float | str) -> str:
    """Numbers without float noise (``0.1`` not ``0.1000000001``); hold / ramp unchanged."""
    if isinstance(value, str):
        return value
    return format(float(value), ".10g")


def _us(value_us: float) -> str:
    return f"{_num(value_us)} us"


def _ranges(indices: Sequence[int]) -> str:
    """``[0, 1, 2, 5]`` → ``c0-2, c5``."""
    parts: list[str] = []
    start = prev = None
    for i in indices:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            parts.append(f"c{start}" if start == prev else f"c{start}-{prev}")
            start = prev = i
    if start is not None:
        parts.append(f"c{start}" if start == prev else f"c{start}-{prev}")
    return ", ".join(parts)


def _row_name(row: dict[str, Any]) -> str:
    return f'[{row["index"]}] "{row["label"]}"'


# --- overview ---------------------------------------------------------------------------------


def format_overview(ov: dict[str, Any]) -> str:
    rate = ov.get("cycle_rate_Hz")
    rate_text = f"{rate:.4g} Hz" if rate else "n/a"
    lines = [
        f'Sequence "{ov["sequence_name"]}" (revision {ov["revision"]})',
        f'  file: {ov["sequence_path"]}',
        f'  complete cycle: {_us(ov["complete_duration_us"])} ({rate_text}), '
        f'{ov["n_rows"]} timeline rows, {ov["n_static_devices"]} static devices',
        f'  run: {"RUNNING" if ov["run_sequence"] else "paused"}',
        "Blocks (index, name, state, columns, duration, columns in Complete view):",
    ]
    for b in ov["blocks"]:
        start = b["complete_start_col"]
        where = f'c{start}-{start + b["cols"] - 1}' if start is not None else "not played"
        lines.append(
            f'  {b["index"]}  "{b["name"]}"  {"enabled" if b["enabled"] else "DISABLED"}  '
            f'{b["cols"]} cols  {_us(b["duration_us"])}  {where}'
        )
    scan = ov["scan"]
    lines.append(
        f'Scan: {"RUNNING" if scan["running"] else "not running"}; '
        f'label "{scan["label"]}", {scan["repetitions"]} repetitions per point'
    )
    if not scan["parameters"]:
        lines.append("  no scan axes")
    for p in scan["parameters"]:
        lines.append(
            f'  axis: device "{p["device_label"]}", param "{p["param_id"]}", '
            f'timestep "{p["timestep_label"]}", values [{p["values_text"]}]'
        )
    return "\n".join(lines)


# --- devices ----------------------------------------------------------------------------------


def _spec(p: dict[str, Any]) -> str:
    return (
        f'{p["param_id"]} "{p["label"]}" range {_num(p["minimum"])}..{_num(p["maximum"])}, '
        f'default {_num(p["default"])}'
    )


def format_devices(dev: dict[str, Any]) -> str:
    lines = ["Timeline rows ([index] \"label\" device: parameters):"]
    for r in dev["rows"]:
        flags = []
        if r["has_on_off"]:
            flags.append("ON/OFF")
        if r["ramp_allowed"]:
            flags.append("ramp allowed")
        flag_text = f' ({", ".join(flags)})' if flags else ""
        params = "; ".join(_spec(p) for p in r["params"]) or "no analog parameters"
        lines.append(f'  {_row_name(r)} {r["device"]}{flag_text}: {params}')
    lines.append("Static devices (one value per shot, set between shots):")
    if not dev["static_devices"]:
        lines.append("  none")
    for s in dev["static_devices"]:
        remote = f', via HERO "{s["remote_hero"]}"' if s["remote_hero"] else ""
        params = "; ".join(f'{_spec(p)}, value {_num(p["value"])}' for p in s["params"])
        lines.append(f'  [s{s["index"]}] "{s["label"]}" {s["device"]}{remote}: {params or "-"}')
    return "\n".join(lines)


# --- timeline ---------------------------------------------------------------------------------


def _row_is_used(row: dict[str, Any]) -> bool:
    if row["on"] is not None and any(row["on"]):
        return True
    return any(v != HOLD for p in row["params"].values() for v in p["stored"])


def _select_rows(rows: list[dict[str, Any]], wanted: Sequence[str]) -> list[dict[str, Any]]:
    """Rows by exact label, else by 0-based index; ``ValueError`` lists unknown names."""
    by_label = {r["label"]: r for r in rows}
    out, unknown = [], []
    for w in wanted:
        text = str(w).strip()
        if text in by_label:
            out.append(by_label[text])
        elif text.isdigit() and int(text) < len(rows):
            out.append(rows[int(text)])
        else:
            unknown.append(text)
    if unknown:
        raise ValueError(
            f"Unknown rows {unknown}. Use a row label or index (see the devices tool)."
        )
    return out


def _start_note(param: dict[str, Any], *, merged: bool) -> str:
    """What column 0 plays when it is a hold."""
    if param["stored"][0] != HOLD:
        return ""
    if not merged:
        return " (c0 holds the value from the previous block)"
    start = param["resolved"][0]
    if start == HOLD:
        return " (c0 hold: device keeps its current value)"
    return f" (c0 hold: plays default {_num(start)})"


def _format_row(row: dict[str, Any], *, merged: bool) -> list[str]:
    lines = [f'  {_row_name(row)} {row["device"]}']
    if row["on"] is not None:
        on_cols = [c for c, v in enumerate(row["on"]) if v]
        lines.append(f'    on: {_ranges(on_cols) if on_cols else "never"}')
    for pid, p in row["params"].items():
        set_cells = [f"c{c}={_num(v)}" for c, v in enumerate(p["stored"]) if v != HOLD]
        values = ", ".join(set_cells) if set_cells else "all hold"
        lines.append(f"    {pid}: {values}{_start_note(p, merged=merged)}")
    return lines


def format_timeline(
    timeline: dict[str, Any],
    *,
    rows: Sequence[str] | None = None,
    include_unused: bool = False,
) -> str:
    """Block view (``describe_block``) or Complete view (``describe_complete``) as text."""
    merged = "block_spans" in timeline
    columns = timeline["columns"]
    if merged:
        head = f'Complete timeline (enabled blocks as played, revision {timeline["revision"]})'
        spans = timeline["block_spans"]
    else:
        b = timeline["block"]
        state = "enabled" if b["enabled"] else "DISABLED (not played)"
        head = (
            f'Block {b["index"]} "{b["name"]}", {state}, block-local columns '
            f'(revision {timeline["revision"]})'
        )
        spans = [{"name": b["name"], "start_col": 0, "cols": b["cols"]}]

    lines = [head, "Columns (cN \"label\" delay):"]
    for s in spans:
        cells = [
            f'c{c["index"]} "{c["label"]}" {_us(c["delay_us"])}'
            for c in columns[s["start_col"] : s["start_col"] + s["cols"]]
        ]
        prefix = f'  block "{s["name"]}": ' if merged else "  "
        lines.append(prefix + " | ".join(cells))

    all_rows = timeline["rows"]
    if rows:
        shown = _select_rows(all_rows, rows)
        unused: list[dict[str, Any]] = []
    else:
        shown = [r for r in all_rows if include_unused or _row_is_used(r)]
        unused = [r for r in all_rows if not include_unused and not _row_is_used(r)]

    lines.append("Rows (analog values hold between the listed columns):")
    for r in shown:
        lines.extend(_format_row(r, merged=merged))
    if unused:
        names = ", ".join(_row_name(r) for r in unused)
        lines.append(f"Unused rows (never ON, no value set): {names}")
    return "\n".join(lines)
