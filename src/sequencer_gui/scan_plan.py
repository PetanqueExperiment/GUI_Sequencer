"""Build PyCam parameter-scan tag lists from GUI scan parameters."""

from __future__ import annotations

import re
from itertools import product

from sequencer_gui.app.state import ScanParameter


def _format_param_value(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.6g}"


def _sanitize_tag_part(text: str) -> str:
    text = str(text).strip()
    text = re.sub(r"[^\w.-]", "_", text)
    return text.strip("._") or "p"


def parse_scan_values(values_text: str) -> list[float]:
    raw = values_text.strip()
    if not raw:
        return []
    out: list[float] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        out.append(float(part))
    return out


def build_scan_tags(parameters: tuple[ScanParameter, ...], repetitions: int) -> list[str]:
    """
  One tag per shot PyCam should record.

  Multi-parameter scans use the Cartesian product of value lists; each point is
  repeated ``repetitions`` times (separate tags when repetitions > 1).
    """
    reps = max(1, repetitions)
    if not parameters:
        return [f"rep_{i + 1}" for i in range(reps)]

    axes: list[list[tuple[str, float]]] = []
    for p in parameters:
        vals = parse_scan_values(p.values_text)
        if not vals:
            raise ValueError(
                f"Scan parameter {p.device_label!r} / {p.param_id!r} has no values "
                "(use comma-separated numbers)."
            )
        prefix = _sanitize_tag_part(p.param_id or "p")
        axes.append([(prefix, v) for v in vals])

    tags: list[str] = []
    for combo in product(*axes):
        base = "_".join(f"{pid}_{_format_param_value(v)}" for pid, v in combo)
        if reps == 1:
            tags.append(base)
        else:
            for r in range(reps):
                tags.append(f"{base}_rep{r + 1}")
    return tags


def expected_shot_count(parameters: tuple[ScanParameter, ...], repetitions: int) -> int:
    return len(build_scan_tags(parameters, repetitions))
