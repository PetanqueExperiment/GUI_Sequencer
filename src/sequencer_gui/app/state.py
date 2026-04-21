from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from sequencer_gui.app.backend import NoOpBackend, SequenceBackendProtocol
from sequencer_gui.domain.document import (
    SequenceBlock,
    SequenceDocument,
    block_to_sequence_model,
    document_from_single_model,
    merge_blocks,
)
from sequencer_gui.domain.model import SequenceModel

# Tab index -1 is the read-only "Complete" view (all blocks concatenated).
COMPLETE_TAB_INDEX = -1


def _remap_tab_after_block_move(active: int, from_i: int, to_i: int) -> int:
    """Keep the same logical block selected after reordering (by old index tracking)."""
    if active == COMPLETE_TAB_INDEX:
        return COMPLETE_TAB_INDEX
    if active == from_i:
        return to_i
    if from_i < to_i:
        if from_i < active <= to_i:
            return active - 1
    elif from_i > to_i:
        if to_i <= active < from_i:
            return active + 1
    return active


class SequenceAppState(QObject):
    """Owns a sequence document, active tab, emits Qt signals, forwards merged snapshot to backend."""

    model_changed = pyqtSignal(SequenceModel)
    channels_changed = pyqtSignal()
    delays_changed = pyqtSignal()
    analog_changed = pyqtSignal()
    row_labels_changed = pyqtSignal()
    sequence_name_changed = pyqtSignal(str)
    document_changed = pyqtSignal(SequenceDocument)
    active_tab_changed = pyqtSignal(int)

    def __init__(
        self,
        backend: SequenceBackendProtocol | None = None,
        document: SequenceDocument | None = None,
        model: SequenceModel | None = None,
        sequence_name: str = "Untitled",
    ) -> None:
        super().__init__()
        self._backend = backend if backend is not None else NoOpBackend()
        if document is not None:
            self._document = document
        elif model is not None:
            self._document = document_from_single_model(model, "Block 1")
        else:
            raise ValueError("document or model is required")
        self._active_tab = 0
        self._sequence_name = sequence_name

    @property
    def document(self) -> SequenceDocument:
        return self._document

    @property
    def active_tab_index(self) -> int:
        """Block index 0..n-1, or COMPLETE_TAB_INDEX (-1) for the merged all-blocks view."""
        return self._active_tab

    @property
    def timeline_read_only(self) -> bool:
        return self._active_tab == COMPLETE_TAB_INDEX

    @property
    def model(self) -> SequenceModel:
        """View model for the current tab: one block or merged preview."""
        if self._active_tab == COMPLETE_TAB_INDEX:
            return merge_blocks(self._document, enabled_only=False)
        return block_to_sequence_model(self._document, self._active_tab)

    @property
    def sequence_name(self) -> str:
        return self._sequence_name

    def set_sequence_name(self, name: str) -> None:
        self._sequence_name = name
        self.sequence_name_changed.emit(name)

    def set_active_tab(self, index: int) -> None:
        if index == COMPLETE_TAB_INDEX:
            self._active_tab = COMPLETE_TAB_INDEX
        elif 0 <= index < len(self._document.blocks):
            self._active_tab = index
        else:
            raise IndexError("active tab index out of range")
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(self._document, enabled_only=True))

    def replace_document(self, document: SequenceDocument, *, active_tab: int | None = None) -> None:
        self._document = document
        tab = self._active_tab if active_tab is None else active_tab
        if tab == COMPLETE_TAB_INDEX:
            self._active_tab = COMPLETE_TAB_INDEX
        else:
            self._active_tab = min(max(0, tab), len(document.blocks) - 1)
        self.document_changed.emit(document)
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(document, enabled_only=True))

    def replace_model(self, model: SequenceModel) -> None:
        """Backward compatibility: load a flat model as a single block."""
        self.replace_document(document_from_single_model(model, "Block 1"), active_tab=0)

    def _commit_document(self, document: SequenceDocument) -> None:
        self._document = document
        self.document_changed.emit(document)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(document, enabled_only=True))

    def set_channel(self, row: int, col: int, on: bool) -> None:
        if self._active_tab == COMPLETE_TAB_INDEX:
            return
        bi = self._active_tab
        block = self._document.blocks[bi]
        new_b = block.with_channel(self._document.rows, row, col, on)
        self._commit_document(self._document.with_block(bi, new_b))
        self.channels_changed.emit()

    def set_row_software(self, row: int, object_name: str) -> None:
        if self._document.row_software[row] == object_name:
            return
        self._commit_document(self._document.with_row_software(row, object_name))
        self.channels_changed.emit()

    def set_delay_us(self, col: int, value_us: float) -> None:
        if self._active_tab == COMPLETE_TAB_INDEX:
            return
        bi = self._active_tab
        block = self._document.blocks[bi]
        new_b = block.with_delay_us(col, value_us)
        self._commit_document(self._document.with_block(bi, new_b))
        self.delays_changed.emit()

    def set_analog(self, row: int, param_id: str, col: int, value: float) -> None:
        if self._active_tab == COMPLETE_TAB_INDEX:
            return
        bi = self._active_tab
        block = self._document.blocks[bi]
        new_b = block.with_analog(self._document.rows, row, param_id, col, value)
        self._commit_document(self._document.with_block(bi, new_b))
        self.analog_changed.emit()

    def set_row_label(self, row: int, text: str) -> None:
        self._commit_document(self._document.with_row_label(row, text))
        self.row_labels_changed.emit()

    def set_block_name(self, block_index: int, name: str) -> None:
        b = self._document.blocks[block_index]
        self._commit_document(self._document.with_block(block_index, b.with_name(name)))

    def set_block_enabled(self, block_index: int, enabled: bool) -> None:
        b = self._document.blocks[block_index]
        if b.enabled == enabled:
            return
        self._commit_document(self._document.with_block(block_index, b.with_enabled(enabled)))

    def move_block(self, from_index: int, to_index: int) -> None:
        if from_index == to_index:
            return
        n = len(self._document.blocks)
        if not (0 <= from_index < n and 0 <= to_index < n):
            raise IndexError("block index out of range")
        new_at = _remap_tab_after_block_move(self._active_tab, from_index, to_index)
        new_doc = self._document.with_move_block(from_index, to_index)
        self._document = new_doc
        self._active_tab = new_at
        self.document_changed.emit(new_doc)
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(new_doc, enabled_only=True))

    def apply_block_permutation(self, permutation: list[int]) -> None:
        """Reorder blocks in one step. permutation[i] is the original block index now at position i."""
        old = self._document.blocks
        n = len(old)
        if len(permutation) != n or set(permutation) != set(range(n)):
            raise ValueError("invalid block permutation")
        new_blocks = tuple(old[permutation[i]] for i in range(n))
        new_doc = self._document.with_blocks(new_blocks)
        if self._active_tab == COMPLETE_TAB_INDEX:
            new_at = COMPLETE_TAB_INDEX
        else:
            new_at = permutation.index(self._active_tab)
        self._document = new_doc
        self._active_tab = new_at
        self.document_changed.emit(new_doc)
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(new_doc, enabled_only=True))

    def add_block(self) -> None:
        n = len(self._document.blocks) + 1
        last = self._document.blocks[-1]
        new_b = SequenceBlock(
            name=f"Block {n}",
            enabled=True,
            cols=last.cols,
            channels={},
            delays_us={},
            analog={},
        )
        self._commit_document(self._document.with_blocks(self._document.blocks + (new_b,)))

    def remove_block(self, block_index: int) -> None:
        if len(self._document.blocks) <= 1:
            return
        if not (0 <= block_index < len(self._document.blocks)):
            raise IndexError("block index out of range")
        blocks = list(self._document.blocks)
        blocks.pop(block_index)
        new_doc = self._document.with_blocks(tuple(blocks))
        at = self._active_tab
        if at == COMPLETE_TAB_INDEX:
            new_at = COMPLETE_TAB_INDEX
        elif at == block_index:
            new_at = min(block_index, len(blocks) - 1)
        elif at > block_index:
            new_at = at - 1
        else:
            new_at = at
        self._document = new_doc
        self._active_tab = new_at
        self.document_changed.emit(new_doc)
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._backend.apply(merge_blocks(new_doc, enabled_only=True))
