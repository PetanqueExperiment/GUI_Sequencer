from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, NamedTuple, Tuple

from sequencer_gui.domain.analog_stored import ANALOG_HOLD, AnalogStored, is_holdish
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.domain.static_defaults import (
    DEFAULT_STATIC_ROWS,
    default_static_analog,
    default_static_labels,
    default_static_software,
)
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object, get_static_object


@dataclass(frozen=True)
class SequenceBlock:
    """One named timeline segment: channels, delays, analog (no row metadata)."""

    name: str
    enabled: bool
    cols: int
    channels: Dict[Tuple[int, int], bool] = field(default_factory=dict)
    delays_us: Dict[int, float] = field(default_factory=dict)
    analog: Dict[Tuple[int, str, int], AnalogStored] = field(default_factory=dict)
    col_labels: Tuple[str, ...] = field(default_factory=tuple)
    accent_color: str | None = None

    def __post_init__(self) -> None:
        if self.cols < 1:
            raise ValueError("block cols must be positive")
        if len(self.col_labels) != self.cols:
            labels = tuple(
                self.col_labels[c] if c < len(self.col_labels) else "" for c in range(self.cols)
            )
            object.__setattr__(self, "col_labels", labels)

    def col_label(self, col: int) -> str:
        return self.col_labels[col]

    def _copy(self, **kwargs: object) -> SequenceBlock:
        return SequenceBlock(
            name=kwargs.get("name", self.name),  # type: ignore[arg-type]
            enabled=kwargs.get("enabled", self.enabled),  # type: ignore[arg-type]
            cols=kwargs.get("cols", self.cols),  # type: ignore[arg-type]
            channels=kwargs.get("channels", self.channels),  # type: ignore[arg-type]
            delays_us=kwargs.get("delays_us", self.delays_us),  # type: ignore[arg-type]
            analog=kwargs.get("analog", self.analog),  # type: ignore[arg-type]
            col_labels=kwargs.get("col_labels", self.col_labels),  # type: ignore[arg-type]
            accent_color=kwargs.get("accent_color", self.accent_color),  # type: ignore[arg-type]
        )

    def with_name(self, name: str) -> SequenceBlock:
        return self._copy(name=name)

    def with_enabled(self, enabled: bool) -> SequenceBlock:
        return self._copy(enabled=enabled)

    def with_accent_color(self, accent_color: str | None) -> SequenceBlock:
        return self._copy(accent_color=accent_color)

    def with_cols(self, cols: int) -> SequenceBlock:
        if cols < 1:
            raise ValueError("block cols must be positive")
        if cols == self.cols:
            return self
        channels = {(r, c): v for (r, c), v in self.channels.items() if c < cols}
        delays_us = {c: v for c, v in self.delays_us.items() if c < cols}
        analog = {(r, pid, c): v for (r, pid, c), v in self.analog.items() if c < cols}
        col_labels = self.col_labels[:cols] if len(self.col_labels) >= cols else self.col_labels
        return self._copy(
            cols=cols,
            channels=channels,
            delays_us=delays_us,
            analog=analog,
            col_labels=col_labels,
        )

    def with_channel(self, rows: int, row: int, col: int, on: bool) -> SequenceBlock:
        if not (0 <= row < rows and 0 <= col < self.cols):
            raise IndexError("channel index out of range")
        new = dict(self.channels)
        new[(row, col)] = on
        return self._copy(channels=new)

    def with_delay_us(self, col: int, value_us: float) -> SequenceBlock:
        if not (0 <= col < self.cols):
            raise IndexError("delay column out of range")
        d = dict(self.delays_us)
        d[col] = value_us
        return self._copy(delays_us=d)

    def with_col_label(self, col: int, text: str) -> SequenceBlock:
        if not (0 <= col < self.cols):
            raise IndexError("column index out of range")
        lst = list(self.col_labels)
        lst[col] = text
        return self._copy(col_labels=tuple(lst))

    def with_analog(self, rows: int, row: int, param_id: str, col: int, value: AnalogStored) -> SequenceBlock:
        if not (0 <= row < rows and 0 <= col < self.cols):
            raise IndexError("analog index out of range")
        a = dict(self.analog)
        a[(row, param_id, col)] = (
            ANALOG_HOLD if is_holdish(value) else float(value)  # type: ignore[arg-type]
        )
        return self._copy(analog=a)

    def with_timeline_from_model(self, model: SequenceModel) -> SequenceBlock:
        """Replace timeline fields from a full model (rows/software/labels ignored)."""
        return self._copy(
            cols=model.cols,
            channels=dict(model.channels),
            delays_us=dict(model.delays_us),
            analog=dict(model.analog),
            col_labels=model.col_labels,
        )


@dataclass(frozen=True)
class SequenceDocument:
    """Shared row configuration and one or more ordered timeline blocks."""

    rows: int
    row_labels: Tuple[str, ...]
    row_software: Tuple[str, ...]
    blocks: Tuple[SequenceBlock, ...]
    static_rows: int = DEFAULT_STATIC_ROWS
    static_labels: Tuple[str, ...] = ()
    static_software: Tuple[str, ...] = ()
    static_analog: Dict[Tuple[int, str], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.rows < 1:
            raise ValueError("rows must be positive")
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
        if self.static_rows < 0:
            raise ValueError("static_rows must be non-negative")
        if not self.static_labels:
            object.__setattr__(self, "static_labels", default_static_labels(self.static_rows))
        elif len(self.static_labels) != self.static_rows:
            labels = tuple(
                self.static_labels[i] if i < len(self.static_labels) else f"VOA {i + 1}"
                for i in range(self.static_rows)
            )
            object.__setattr__(self, "static_labels", labels)
        if not self.static_software:
            object.__setattr__(self, "static_software", default_static_software(self.static_rows))
        elif len(self.static_software) != self.static_rows:
            rs = tuple(
                self.static_software[i] if i < len(self.static_software) else default_static_software(1)[0]
                for i in range(self.static_rows)
            )
            object.__setattr__(self, "static_software", rs)
        if self.static_rows > 0 and not self.static_analog:
            object.__setattr__(
                self, "static_analog", default_static_analog(self.static_rows)
            )
        if len(self.blocks) < 1:
            raise ValueError("at least one block is required")

    def static_label(self, row: int) -> str:
        return self.static_labels[row]

    def static_software_name(self, row: int) -> str:
        return self.static_software[row]

    def static_value(self, row: int, param_id: str) -> float:
        """Resolved static value (one number for the whole sequence)."""
        key = (row, param_id)
        if key in self.static_analog:
            return float(self.static_analog[key])
        obj = get_static_object(self.static_software_name(row))
        for p in obj.analog_parameters:
            if p.param_id == param_id:
                return float(p.default)
        return 0.0

    def static_display_text(self, row: int, param_id: str, *, decimals: int) -> str:
        return format(self.static_value(row, param_id), f".{decimals}f")

    def with_static_value(self, row: int, param_id: str, value: float) -> SequenceDocument:
        if not (0 <= row < self.static_rows):
            raise IndexError("static row index out of range")
        a = dict(self.static_analog)
        a[(row, param_id)] = float(value)
        return replace(self, static_analog=a)

    def with_static_label(self, row: int, text: str) -> SequenceDocument:
        if not (0 <= row < self.static_rows):
            raise IndexError("static row index out of range")
        lst = list(self.static_labels)
        lst[row] = text
        return replace(self, static_labels=tuple(lst))

    def with_static_software(self, row: int, object_name: str) -> SequenceDocument:
        if not (0 <= row < self.static_rows):
            raise IndexError("static row index out of range")
        lst = list(self.static_software)
        lst[row] = object_name
        obj = get_static_object(object_name)
        valid_ids = {p.param_id for p in obj.analog_parameters}
        a = dict(self.static_analog)
        for key in list(a.keys()):
            r, pid = key
            if r == row and pid not in valid_ids:
                del a[key]
        return replace(self, static_software=tuple(lst), static_analog=a)

    def with_block(self, index: int, block: SequenceBlock) -> SequenceDocument:
        if not (0 <= index < len(self.blocks)):
            raise IndexError("block index out of range")
        lst = list(self.blocks)
        lst[index] = block
        return replace(self, blocks=tuple(lst))

    def with_blocks(self, blocks: Tuple[SequenceBlock, ...]) -> SequenceDocument:
        if len(blocks) < 1:
            raise ValueError("at least one block is required")
        return replace(self, blocks=blocks)

    def with_move_block(self, from_index: int, to_index: int) -> SequenceDocument:
        """Move one block to a new index in the ordered list (0..len-1)."""
        n = len(self.blocks)
        if not (0 <= from_index < n and 0 <= to_index < n):
            raise IndexError("block index out of range")
        if from_index == to_index:
            return self
        blocks = list(self.blocks)
        b = blocks.pop(from_index)
        blocks.insert(to_index, b)
        return self.with_blocks(tuple(blocks))

    def with_row_label(self, row: int, text: str) -> SequenceDocument:
        if not (0 <= row < self.rows):
            raise IndexError("row index out of range")
        lst = list(self.row_labels)
        lst[row] = text
        return replace(self, row_labels=tuple(lst))

    def with_row_software(self, row: int, object_name: str) -> SequenceDocument:
        if not (0 <= row < self.rows):
            raise IndexError("row index out of range")
        lst = list(self.row_software)
        lst[row] = object_name
        obj = get_object(object_name)
        valid_ids = {p.param_id for p in obj.analog_parameters}
        new_blocks: list[SequenceBlock] = []
        for b in self.blocks:
            a = dict(b.analog)
            for key in list(a.keys()):
                r, pid, _c = key
                if r == row and pid not in valid_ids:
                    del a[key]
            ch = dict(b.channels)
            if not obj.has_on_off:
                for c in range(b.cols):
                    ch.pop((row, c), None)
            new_blocks.append(
                b._copy(channels=ch, analog=a)
            )
        return replace(self, row_software=tuple(lst), blocks=tuple(new_blocks))


def block_to_sequence_model(doc: SequenceDocument, block_index: int) -> SequenceModel:
    b = doc.blocks[block_index]
    return SequenceModel(
        rows=doc.rows,
        cols=b.cols,
        channels=dict(b.channels),
        delays_us=dict(b.delays_us),
        analog=dict(b.analog),
        col_labels=b.col_labels,
        row_labels=doc.row_labels,
        row_software=doc.row_software,
    )


def merge_blocks(doc: SequenceDocument, *, enabled_only: bool) -> SequenceModel:
    """Concatenate block timelines in order. enabled_only skips disabled blocks for runtime."""
    if enabled_only:
        use = [b for b in doc.blocks if b.enabled]
    else:
        use = list(doc.blocks)
    if not use:
        # No enabled blocks: backend receives a single idle step (avoids empty cols).
        return SequenceModel(
            rows=doc.rows,
            cols=1,
            channels={},
            delays_us={0: 0.0},
            analog={},
            col_labels=("",),
            row_labels=doc.row_labels,
            row_software=doc.row_software,
        )
    total_cols = sum(b.cols for b in use)
    channels: Dict[Tuple[int, int], bool] = {}
    delays_us: Dict[int, float] = {}
    analog: Dict[Tuple[int, str, int], AnalogStored] = {}
    col_labels: list[str] = []
    col_off = 0
    for b in use:
        for c in range(b.cols):
            delays_us[col_off + c] = b.delays_us.get(c, 0.0)
            col_labels.append(b.col_label(c))
        for (r, c), v in b.channels.items():
            if 0 <= r < doc.rows and 0 <= c < b.cols:
                channels[(r, col_off + c)] = v
        for (r, pid, c), v in b.analog.items():
            if 0 <= r < doc.rows and 0 <= c < b.cols:
                analog[(r, pid, col_off + c)] = v
        col_off += b.cols
    return SequenceModel(
        rows=doc.rows,
        cols=total_cols,
        channels=channels,
        delays_us=delays_us,
        analog=analog,
        col_labels=tuple(col_labels),
        row_labels=doc.row_labels,
        row_software=doc.row_software,
    )


class MergedBlockSpan(NamedTuple):
    merged_start_col: int
    ncol: int
    block_index: int
    name: str


def merged_enabled_block_spans(doc: SequenceDocument) -> tuple[MergedBlockSpan, ...]:
    """Column ranges per enabled block in the merged Complete timeline."""
    spans: list[MergedBlockSpan] = []
    col_off = 0
    for bi, b in enumerate(doc.blocks):
        if not b.enabled:
            continue
        spans.append(MergedBlockSpan(col_off, b.cols, bi, b.name))
        col_off += b.cols
    return tuple(spans)


def merged_timeline_col_offset_for_block(doc: SequenceDocument, block_index: int) -> int:
    """First column index for a block in ``merge_blocks(doc, enabled_only=True)``."""
    if not (0 <= block_index < len(doc.blocks)):
        return 0
    col_off = 0
    for bi, b in enumerate(doc.blocks):
        if bi == block_index:
            return col_off
        if b.enabled:
            col_off += b.cols
    return col_off


def merged_enabled_timeline_col_to_block(doc: SequenceDocument, merged_col: int) -> Tuple[int, int] | None:
    """Map a column in ``merge_blocks(doc, enabled_only=True)`` to ``(block_index, col_in_block)``.

    Returns ``None`` when ``merged_col`` is out of range or no blocks are enabled (placeholder column).
    """
    if merged_col < 0:
        return None
    col_off = 0
    for bi, b in enumerate(doc.blocks):
        if not b.enabled:
            continue
        if merged_col < col_off + b.cols:
            return (bi, merged_col - col_off)
        col_off += b.cols
    return None


def document_from_single_model(model: SequenceModel, block_name: str = "Block 1") -> SequenceDocument:
    block = SequenceBlock(
        name=block_name,
        enabled=True,
        cols=model.cols,
        channels=dict(model.channels),
        delays_us=dict(model.delays_us),
        analog=dict(model.analog),
        col_labels=model.col_labels,
    )
    return SequenceDocument(
        rows=model.rows,
        row_labels=model.row_labels,
        row_software=model.row_software,
        blocks=(block,),
    )


def default_document(row_labels: Tuple[str, ...]) -> SequenceDocument:
    """One block with the same default timeline shape as a standalone SequenceModel."""
    base = SequenceModel(row_labels=row_labels)
    return document_from_single_model(base, block_name="Block 1")


def complete_timeline_duration_us(doc: SequenceDocument) -> float:
    """Sum of per-step delays for the merged enabled-blocks timeline (runtime shape)."""
    model = merge_blocks(doc, enabled_only=True)
    return sum(model.delay_us(c, 0.0) for c in range(model.cols))


def complete_cycle_rate_hz(doc: SequenceDocument) -> float | None:
    """Experiment repetition rate (Hz) for one full enabled-blocks cycle; ``None`` if duration is zero."""
    us = complete_timeline_duration_us(doc)
    if us <= 0.0:
        return None
    return 1e6 / us
