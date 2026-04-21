from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Tuple

from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import DEFAULT_ON_OBJECT, get_object


@dataclass(frozen=True)
class SequenceBlock:
    """One named timeline segment: channels, delays, analog (no row metadata)."""

    name: str
    enabled: bool
    cols: int
    channels: Dict[Tuple[int, int], bool] = field(default_factory=dict)
    delays_us: Dict[int, float] = field(default_factory=dict)
    analog: Dict[Tuple[int, str, int], float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.cols < 1:
            raise ValueError("block cols must be positive")

    def with_name(self, name: str) -> SequenceBlock:
        return SequenceBlock(
            name=name,
            enabled=self.enabled,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=dict(self.analog),
        )

    def with_enabled(self, enabled: bool) -> SequenceBlock:
        return SequenceBlock(
            name=self.name,
            enabled=enabled,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=dict(self.analog),
        )

    def with_channel(self, rows: int, row: int, col: int, on: bool) -> SequenceBlock:
        if not (0 <= row < rows and 0 <= col < self.cols):
            raise IndexError("channel index out of range")
        new = dict(self.channels)
        new[(row, col)] = on
        return SequenceBlock(
            name=self.name,
            enabled=self.enabled,
            cols=self.cols,
            channels=new,
            delays_us=dict(self.delays_us),
            analog=dict(self.analog),
        )

    def with_delay_us(self, col: int, value_us: float) -> SequenceBlock:
        if not (0 <= col < self.cols):
            raise IndexError("delay column out of range")
        d = dict(self.delays_us)
        d[col] = value_us
        return SequenceBlock(
            name=self.name,
            enabled=self.enabled,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=d,
            analog=dict(self.analog),
        )

    def with_analog(self, rows: int, row: int, param_id: str, col: int, value: float) -> SequenceBlock:
        if not (0 <= row < rows and 0 <= col < self.cols):
            raise IndexError("analog index out of range")
        a = dict(self.analog)
        a[(row, param_id, col)] = value
        return SequenceBlock(
            name=self.name,
            enabled=self.enabled,
            cols=self.cols,
            channels=dict(self.channels),
            delays_us=dict(self.delays_us),
            analog=a,
        )

    def with_timeline_from_model(self, model: SequenceModel) -> SequenceBlock:
        """Replace timeline fields from a full model (rows/software/labels ignored)."""
        return SequenceBlock(
            name=self.name,
            enabled=self.enabled,
            cols=model.cols,
            channels=dict(model.channels),
            delays_us=dict(model.delays_us),
            analog=dict(model.analog),
        )


@dataclass(frozen=True)
class SequenceDocument:
    """Shared row configuration and one or more ordered timeline blocks."""

    rows: int
    row_labels: Tuple[str, ...]
    row_software: Tuple[str, ...]
    blocks: Tuple[SequenceBlock, ...]

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
        if len(self.blocks) < 1:
            raise ValueError("at least one block is required")

    def with_block(self, index: int, block: SequenceBlock) -> SequenceDocument:
        if not (0 <= index < len(self.blocks)):
            raise IndexError("block index out of range")
        lst = list(self.blocks)
        lst[index] = block
        return SequenceDocument(
            rows=self.rows,
            row_labels=self.row_labels,
            row_software=self.row_software,
            blocks=tuple(lst),
        )

    def with_blocks(self, blocks: Tuple[SequenceBlock, ...]) -> SequenceDocument:
        if len(blocks) < 1:
            raise ValueError("at least one block is required")
        return SequenceDocument(
            rows=self.rows,
            row_labels=self.row_labels,
            row_software=self.row_software,
            blocks=blocks,
        )

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
        return SequenceDocument(
            rows=self.rows,
            row_labels=tuple(lst),
            row_software=self.row_software,
            blocks=self.blocks,
        )

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
            new_blocks.append(
                SequenceBlock(
                    name=b.name,
                    enabled=b.enabled,
                    cols=b.cols,
                    channels=dict(b.channels),
                    delays_us=dict(b.delays_us),
                    analog=a,
                )
            )
        return SequenceDocument(
            rows=self.rows,
            row_labels=self.row_labels,
            row_software=tuple(lst),
            blocks=tuple(new_blocks),
        )


def block_to_sequence_model(doc: SequenceDocument, block_index: int) -> SequenceModel:
    b = doc.blocks[block_index]
    return SequenceModel(
        rows=doc.rows,
        cols=b.cols,
        channels=dict(b.channels),
        delays_us=dict(b.delays_us),
        analog=dict(b.analog),
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
            row_labels=doc.row_labels,
            row_software=doc.row_software,
        )
    total_cols = sum(b.cols for b in use)
    channels: Dict[Tuple[int, int], bool] = {}
    delays_us: Dict[int, float] = {}
    analog: Dict[Tuple[int, str, int], float] = {}
    col_off = 0
    for b in use:
        for c in range(b.cols):
            delays_us[col_off + c] = b.delays_us.get(c, 0.0)
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
        row_labels=doc.row_labels,
        row_software=doc.row_software,
    )


def document_from_single_model(model: SequenceModel, block_name: str = "Block 1") -> SequenceDocument:
    block = SequenceBlock(
        name=block_name,
        enabled=True,
        cols=model.cols,
        channels=dict(model.channels),
        delays_us=dict(model.delays_us),
        analog=dict(model.analog),
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
