from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from sequencer_gui.domain.analog_stored import (
    ANALOG_HOLD,
    AnalogStored,
    is_hold_signal,
    is_holdish,
)
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object

# Change this to bump the number of device rows; older JSON is upscaled on load (see `sequence_io`).
DEFAULT_DEVICE_ROWS: int = 20


@dataclass(frozen=True)
class SequenceModel:
    """Pure data for channel grid, per-column delays, analog values, row labels, and per-row software."""

    rows: int = DEFAULT_DEVICE_ROWS
    cols: int = 8
    channels: Dict[Tuple[int, int], bool] = field(default_factory=dict)
    delays_us: Dict[int, float] = field(default_factory=dict)
    analog: Dict[Tuple[int, str, int], AnalogStored] = field(default_factory=dict)
    row_labels: Tuple[str, ...] = field(default_factory=tuple)
    row_software: Tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.rows < 1 or self.cols < 1:
            raise ValueError("rows and cols must be positive")
        if len(self.row_labels) != self.rows:
            labels = tuple(
                self.row_labels[i] if i < len(self.row_labels) else str(i + 1)
                for i in range(self.rows)
            )
            object.__setattr__(self, "row_labels", labels)
        if len(self.row_software) != self.rows:
            rs = tuple(
                self.row_software[i] if i < len(self.row_software) else DEFAULT_ON_OBJECT
                for i in range(self.rows)
            )
            object.__setattr__(self, "row_software", rs)

    def row_label(self, row: int) -> str:
        return self.row_labels[row]

    def row_software_name(self, row: int) -> str:
        return self.row_software[row]

    def channel(self, row: int, col: int) -> bool:
        return self.channels.get((row, col), False)

    def _default_analog_for_param(self, row: int, param_id: str) -> float:
        obj = get_object(self.row_software_name(row))
        for p in obj.analog_parameters:
            if p.param_id == param_id:
                return float(p.default)
        return 0.0

    def analog_value(self, row: int, param_id: str, col: int) -> float:
        """Resolved numeric value (hold → previous step or parameter default)."""
        key = (row, param_id, col)
        if key in self.analog:
            v = self.analog[key]
            if is_holdish(v):
                if col <= 0:
                    return self._default_analog_for_param(row, param_id)
                return self.analog_value(row, param_id, col - 1)
            return float(v)
        obj = get_object(self.row_software_name(row))
        for p in obj.analog_parameters:
            if p.param_id == param_id:
                return float(p.default)
        return 0.0

    def analog_display_text(self, row: int, param_id: str, col: int, *, decimals: int) -> str:
        """Text shown in the cell: '-' for hold, else formatted resolved number."""
        key = (row, param_id, col)
        if key in self.analog and is_holdish(self.analog[key]):
            return "-"
        v = self.analog_value(row, param_id, col)
        if is_hold_signal(v):
            return "-"
        return format(v, f".{decimals}f")

    def with_channel(self, row: int, col: int, on: bool) -> SequenceModel:
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise IndexError("channel index out of range")
        new = dict(self.channels)
        new[(row, col)] = on
        return SequenceModel(
            rows=self.rows,
            cols=self.cols,
            channels=new,
            delays_us=dict(self.delays_us),
            analog=dict(self.analog),
            row_labels=self.row_labels,
            row_software=self.row_software,
        )

    def with_row_software(self, row: int, object_name: str) -> SequenceModel:
        if not (0 <= row < self.rows):
            raise IndexError("row index out of range")
        lst = list(self.row_software)
        lst[row] = object_name
        obj = get_object(object_name)
        valid_ids = {p.param_id for p in obj.analog_parameters}
        a = dict(self.analog)
        for key in list(a.keys()):
            r, pid, _c = key
            if r == row and pid not in valid_ids:
                del a[key]
        return SequenceModel(
            rows=self.rows,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=a,
            row_labels=self.row_labels,
            row_software=tuple(lst),
        )

    def with_delay_us(self, col: int, value_us: float) -> SequenceModel:
        if not (0 <= col < self.cols):
            raise IndexError("delay column out of range")
        d = dict(self.delays_us)
        d[col] = value_us
        return SequenceModel(
            rows=self.rows,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=d,
            analog=dict(self.analog),
            row_labels=self.row_labels,
            row_software=self.row_software,
        )

    def with_analog(self, row: int, param_id: str, col: int, value: AnalogStored) -> SequenceModel:
        if not (0 <= row < self.rows and 0 <= col < self.cols):
            raise IndexError("analog index out of range")
        a = dict(self.analog)
        a[(row, param_id, col)] = (
            ANALOG_HOLD if is_holdish(value) else float(value)  # type: ignore[arg-type]
        )
        return SequenceModel(
            rows=self.rows,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=a,
            row_labels=self.row_labels,
            row_software=self.row_software,
        )

    def with_row_label(self, row: int, text: str) -> SequenceModel:
        if not (0 <= row < self.rows):
            raise IndexError("row index out of range")
        lst = list(self.row_labels)
        lst[row] = text
        return SequenceModel(
            rows=self.rows,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=dict(self.analog),
            row_labels=tuple(lst),
            row_software=self.row_software,
        )

    def delay_us(self, col: int, default: float = 10.0) -> float:
        return self.delays_us.get(col, default)
