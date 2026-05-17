"""Build PyCam scan tags and matrix scan steps from GUI scan parameters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import product

from sequencer_gui.app.state import ScanParameter
from sequencer_gui.domain.document import SequenceDocument, merge_blocks, merged_enabled_timeline_col_to_block
from sequencer_gui.software_objects import get_object

# Device field aliases for scanning per-step delay (µs) instead of an analog parameter.
_DELAY_SCAN_DEVICES = frozenset({"time", "t"})
_DELAY_SCAN_PARAM_ID = "time"


def is_delay_scan_device(device_label: str) -> bool:
    return device_label.strip().lower() in _DELAY_SCAN_DEVICES


def _scan_axis_label(p: ScanParameter) -> str:
    if is_delay_scan_device(p.device_label):
        return p.device_label.strip().lower()
    return f"{p.device_label!r} / {p.param_id!r}"


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
                f"Scan parameter {_scan_axis_label(p)} has no values "
                "(use comma-separated numbers)."
            )
        if is_delay_scan_device(p.device_label):
            prefix = _sanitize_tag_part(p.device_label.strip().lower())
        else:
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


@dataclass(frozen=True)
class ScanCellBinding:
    """One matrix cell in the merged enabled-blocks timeline."""

    row: int
    param_id: str
    merged_col: int
    is_delay: bool = False


@dataclass(frozen=True)
class ScanPoint:
    """One scan step: set each bound cell, then play ``repetitions`` shots."""

    bindings: tuple[ScanCellBinding, ...]
    values: tuple[float, ...]


def merged_col_for_timestep_label(document: SequenceDocument, timestep_label: str) -> int | None:
    """Resolve a timestep label (or 0-based merged column index) on the enabled timeline."""
    label = timestep_label.strip()
    if not label:
        return None
    model = merge_blocks(document, enabled_only=True)
    matches = [c for c in range(model.cols) if model.col_labels[c] == label]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return matches[0]
    if label.isdigit():
        idx = int(label)
        if 0 <= idx < model.cols:
            return idx
    return None


def resolve_scan_bindings(
    document: SequenceDocument, parameters: tuple[ScanParameter, ...]
) -> tuple[ScanCellBinding, ...]:
    """Validate scan cards and return one matrix cell per parameter axis."""
    if not parameters:
        return ()
    bindings: list[ScanCellBinding] = []
    for p in parameters:
        device = p.device_label.strip()
        if not device:
            raise ValueError(
                "Each scan parameter needs a device row label, or "
                f"{' / '.join(sorted(_DELAY_SCAN_DEVICES))} to scan timestep duration."
            )
        merged_col = merged_col_for_timestep_label(document, p.timestep_label)
        if merged_col is None:
            raise ValueError(
                f"Unknown timestep {p.timestep_label!r} for {device!r} "
                "(use a column label on the enabled timeline)."
            )
        if merged_enabled_timeline_col_to_block(document, merged_col) is None:
            raise ValueError(
                f"Timestep {p.timestep_label!r} is not on an enabled block timeline."
            )
        if is_delay_scan_device(device):
            bindings.append(
                ScanCellBinding(
                    row=-1,
                    param_id=_DELAY_SCAN_PARAM_ID,
                    merged_col=merged_col,
                    is_delay=True,
                )
            )
            continue
        try:
            row = document.row_labels.index(device)
        except ValueError:
            raise ValueError(f"Unknown device row label {device!r}.")
        param_id = (p.param_id or "").strip()
        if not param_id:
            raise ValueError(f"Select an analog parameter for device {device!r}.")
        obj = get_object(document.row_software[row])
        if param_id not in {spec.param_id for spec in obj.analog_parameters}:
            raise ValueError(
                f"Parameter {param_id!r} is not valid for device {device!r} "
                f"({obj.display_name})."
            )
        bindings.append(ScanCellBinding(row=row, param_id=param_id, merged_col=merged_col))
    return tuple(bindings)


def build_scan_points(
    document: SequenceDocument, parameters: tuple[ScanParameter, ...]
) -> list[ScanPoint]:
    """
    Cartesian product of comma-separated value lists; one point per combination.
    Matrix cells are updated once per point, then the host plays ``repetitions`` shots.
    """
    bindings = resolve_scan_bindings(document, parameters)
    if not bindings:
        return [ScanPoint(bindings=(), values=())]

    axes: list[list[float]] = []
    for p in parameters:
        vals = parse_scan_values(p.values_text)
        if not vals:
            raise ValueError(
                f"Scan parameter {_scan_axis_label(p)} has no values "
                "(use comma-separated numbers)."
            )
        axes.append(vals)

    return [
        ScanPoint(bindings=bindings, values=tuple(combo))
        for combo in product(*axes)
    ]
