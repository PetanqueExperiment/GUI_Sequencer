from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from sequencer_gui.scan_plan import ScanPoint

from PyQt5.QtCore import QObject, pyqtSignal

from sequencer_gui.app.backend import NoOpBackend, SequenceBackendProtocol
from sequencer_gui.process_identity import BURST_SHOTS_UNLIMITED
from sequencer_gui.domain.analog_stored import AnalogStored
from sequencer_gui.domain.document import (
    SequenceBlock,
    SequenceDocument,
    block_to_sequence_model,
    document_from_single_model,
    merge_blocks,
    merged_enabled_timeline_col_to_block,
)
from sequencer_gui.domain.model import DEFAULT_DELAY_US, SequenceModel
from sequencer_gui.software_objects import get_object

# Tab index -1 is the "Complete" view (enabled blocks concatenated); editable like per-block tabs.
COMPLETE_TAB_INDEX = -1


class ScanParameter(NamedTuple):
    """One scanned axis: device row label (or time/t for delay), param id, timestep label, values."""

    device_label: str
    param_id: str
    timestep_label: str
    values_text: str


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
    static_labels_changed = pyqtSignal()
    static_changed = pyqtSignal()
    sequence_name_changed = pyqtSignal(str)
    run_sequence_changed = pyqtSignal(bool)
    scan_running_changed = pyqtSignal(bool)
    scan_label_changed = pyqtSignal(str)
    scan_repetitions_changed = pyqtSignal(int)
    scan_parameters_changed = pyqtSignal()
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
        self._run_sequence = False
        self._scan_running = False
        self._scan_label = ""
        self._scan_repetitions = 1
        self._scan_parameters: tuple[ScanParameter, ...] = ()
        # Cells touched during a scan; restored when the scan ends or is interrupted.
        self._scan_restore: dict[tuple[int, int, str, int], AnalogStored] | None = None
        self._scan_restore_delays: dict[tuple[int, int], float] | None = None
        self._notify_backend()
        self._backend.sync_run_sequence(False)

    def _notify_backend(self) -> None:
        self._backend.sync_sequence_snapshot(self._document, self._sequence_name)
        self._backend.apply(merge_blocks(self._document, enabled_only=True))

    @property
    def document(self) -> SequenceDocument:
        return self._document

    @property
    def active_tab_index(self) -> int:
        """Block index 0..n-1, or COMPLETE_TAB_INDEX (-1) for the merged all-blocks view."""
        return self._active_tab

    @property
    def timeline_read_only(self) -> bool:
        if self._active_tab != COMPLETE_TAB_INDEX:
            return False
        return not any(b.enabled for b in self._document.blocks)

    @property
    def model(self) -> SequenceModel:
        """View model for the current tab: one block or merged preview (enabled blocks only)."""
        if self._active_tab == COMPLETE_TAB_INDEX:
            return merge_blocks(self._document, enabled_only=True)
        return block_to_sequence_model(self._document, self._active_tab)

    @property
    def sequence_name(self) -> str:
        return self._sequence_name

    @property
    def run_sequence(self) -> bool:
        """If False, the host should not run the sequence (pushed to the in-process HERO only; not saved in files)."""
        return self._run_sequence

    @property
    def scan_running(self) -> bool:
        return self._scan_running

    def set_scan_running(self, on: bool) -> None:
        if self._scan_running == on:
            return
        self._scan_running = on
        self.scan_running_changed.emit(on)

    @property
    def scan_label(self) -> str:
        """User-facing name for this scan experiment (UI only until scan execution exists)."""
        return self._scan_label

    def set_scan_label(self, label: str) -> None:
        if self._scan_label == label:
            return
        self._scan_label = label
        self.scan_label_changed.emit(label)

    @property
    def scan_repetitions(self) -> int:
        """Shots per scan step (UI only until scan execution exists)."""
        return self._scan_repetitions

    def set_scan_repetitions(self, n: int) -> None:
        if n < 1:
            n = 1
        if self._scan_repetitions == n:
            return
        self._scan_repetitions = n
        self.scan_repetitions_changed.emit(n)

    @property
    def scan_parameters(self) -> tuple[ScanParameter, ...]:
        return self._scan_parameters

    def add_scan_parameter(self) -> None:
        self._scan_parameters = self._scan_parameters + (ScanParameter("", "", "", ""),)
        self.scan_parameters_changed.emit()

    def remove_scan_parameter(self, index: int) -> None:
        n = len(self._scan_parameters)
        if not (0 <= index < n):
            return
        self._scan_parameters = tuple(p for i, p in enumerate(self._scan_parameters) if i != index)
        self.scan_parameters_changed.emit()

    def set_scan_parameter_device_label(self, index: int, device_label: str) -> None:
        if not (0 <= index < len(self._scan_parameters)):
            return
        p = self._scan_parameters[index]
        if p.device_label == device_label:
            return
        self._scan_parameters = tuple(
            q if i != index else q._replace(device_label=device_label)
            for i, q in enumerate(self._scan_parameters)
        )

    def set_scan_parameter_param_id(self, index: int, param_id: str) -> None:
        if not (0 <= index < len(self._scan_parameters)):
            return
        p = self._scan_parameters[index]
        if p.param_id == param_id:
            return
        self._scan_parameters = tuple(
            q if i != index else q._replace(param_id=param_id)
            for i, q in enumerate(self._scan_parameters)
        )

    def set_scan_parameter_timestep_label(self, index: int, timestep_label: str) -> None:
        if not (0 <= index < len(self._scan_parameters)):
            return
        p = self._scan_parameters[index]
        if p.timestep_label == timestep_label:
            return
        self._scan_parameters = tuple(
            q if i != index else q._replace(timestep_label=timestep_label)
            for i, q in enumerate(self._scan_parameters)
        )

    def set_scan_parameter_values_text(self, index: int, values_text: str) -> None:
        if not (0 <= index < len(self._scan_parameters)):
            return
        p = self._scan_parameters[index]
        if p.values_text == values_text:
            return
        self._scan_parameters = tuple(
            q if i != index else q._replace(values_text=values_text)
            for i, q in enumerate(self._scan_parameters)
        )

    def set_run_sequence(self, on: bool) -> None:
        if self._run_sequence == on:
            return
        self._run_sequence = on
        self.run_sequence_changed.emit(on)
        self._backend.sync_run_sequence(on)
        if not on:
            self._backend.sync_burst_shots(0)

    def poll_host_run_sequence(self) -> None:
        """Mirror run/pause from the in-process HERO when the host changes it (e.g. after a scan)."""
        if self._scan_running:
            return
        read = getattr(self._backend, "read_run_sequence", None)
        if read is None:
            return
        on = read()
        if on == self._run_sequence:
            return
        self._run_sequence = on
        self.run_sequence_changed.emit(on)

    def resume_sequence_for_scan_shots(self, shots: int | None = None) -> None:
        """Set burst shot budget on the host, then resume (Repetitions when ``shots`` is omitted)."""
        n = self._scan_repetitions if shots is None else shots
        if n < 1:
            n = 1
        self._backend.sync_burst_shots(n)
        self.set_run_sequence(True)

    def resume_live_sequence(self) -> None:
        """Live run/pause mode: no shot limit until the user pauses or a scan starts."""
        self._backend.sync_burst_shots(BURST_SHOTS_UNLIMITED)
        self.set_run_sequence(True)

    def prepare_scan_matrix_restore(self) -> None:
        """Remember analog cells that a scan will overwrite (call before applying scan points)."""
        from sequencer_gui.scan_plan import resolve_scan_bindings

        bindings = resolve_scan_bindings(self._document, self._scan_parameters)
        restore: dict[tuple[int, int, str, int], AnalogStored] = {}
        restore_delays: dict[tuple[int, int], float] = {}
        for b in bindings:
            resolved = merged_enabled_timeline_col_to_block(self._document, b.merged_col)
            if resolved is None:
                continue
            bi, local_col = resolved
            block = self._document.blocks[bi]
            if b.is_delay:
                key = (bi, local_col)
                if key not in restore_delays:
                    restore_delays[key] = block.delays_us.get(local_col, DEFAULT_DELAY_US)
                continue
            key = (b.row, bi, b.param_id, local_col)
            if key not in restore:
                restore[key] = block.analog.get((b.row, b.param_id, local_col), "hold")
        self._scan_restore = restore
        self._scan_restore_delays = restore_delays

    def restore_scan_matrix(self) -> None:
        """Put scan-touched analog cells and delays back to their pre-scan values."""
        analog_restore = self._scan_restore or {}
        delay_restore = self._scan_restore_delays or {}
        if not analog_restore and not delay_restore:
            self._scan_restore = None
            self._scan_restore_delays = None
            return
        doc = self._document
        for (row, bi, param_id, local_col), stored in analog_restore.items():
            block = doc.blocks[bi]
            doc = doc.with_block(
                bi,
                block.with_analog(doc.rows, row, param_id, local_col, stored),
            )
        for (bi, local_col), value_us in delay_restore.items():
            block = doc.blocks[bi]
            doc = doc.with_block(bi, block.with_delay_us(local_col, value_us))
        self._scan_restore = None
        self._scan_restore_delays = None
        if doc is not self._document:
            self._commit_document(doc)
            if analog_restore:
                self.analog_changed.emit()
            if delay_restore:
                self.delays_changed.emit()

    def apply_scan_point(self, point: ScanPoint) -> None:
        """Write one scan step into the sequence document (enabled-blocks timeline)."""
        doc = self._document
        analog_touched = False
        delays_touched = False
        for binding, value in zip(point.bindings, point.values):
            resolved = merged_enabled_timeline_col_to_block(doc, binding.merged_col)
            if resolved is None:
                continue
            bi, local_col = resolved
            block = doc.blocks[bi]
            if binding.is_delay:
                doc = doc.with_block(bi, block.with_delay_us(local_col, float(value)))
                delays_touched = True
            else:
                doc = doc.with_block(
                    bi,
                    block.with_analog(
                        doc.rows, binding.row, binding.param_id, local_col, float(value)
                    ),
                )
                analog_touched = True
        if doc is not self._document:
            self._commit_document(doc)
            if analog_touched:
                self.analog_changed.emit()
            if delays_touched:
                self.delays_changed.emit()

    def build_scan_points(self) -> list:
        from sequencer_gui.scan_plan import build_scan_points

        return build_scan_points(self._document, self._scan_parameters)

    def set_sequence_name(self, name: str) -> None:
        self._sequence_name = name
        self.sequence_name_changed.emit(name)
        self._notify_backend()

    def set_active_tab(self, index: int) -> None:
        if index == COMPLETE_TAB_INDEX:
            self._active_tab = COMPLETE_TAB_INDEX
        elif 0 <= index < len(self._document.blocks):
            self._active_tab = index
        else:
            raise IndexError("active tab index out of range")
        self.active_tab_changed.emit(self._active_tab)
        self.model_changed.emit(self.model)
        self._notify_backend()

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
        self._notify_backend()

    def replace_model(self, model: SequenceModel) -> None:
        """Backward compatibility: load a flat model as a single block."""
        self.replace_document(document_from_single_model(model, "Block 1"), active_tab=0)

    def _commit_document(self, document: SequenceDocument) -> None:
        self._document = document
        self.document_changed.emit(document)
        self.model_changed.emit(self.model)
        self._notify_backend()

    def _timeline_col_to_block(self, col: int) -> tuple[int, int] | None:
        """Map UI timeline column to (block_index, col_in_block); None if the edit does not apply."""
        if self._active_tab == COMPLETE_TAB_INDEX:
            return merged_enabled_timeline_col_to_block(self._document, col)
        return (self._active_tab, col)

    def set_channel(self, row: int, col: int, on: bool) -> None:
        if not get_object(self._document.row_software[row]).has_on_off:
            return
        resolved = self._timeline_col_to_block(col)
        if resolved is None:
            return
        bi, local_col = resolved
        block = self._document.blocks[bi]
        new_b = block.with_channel(self._document.rows, row, local_col, on)
        self._commit_document(self._document.with_block(bi, new_b))
        self.channels_changed.emit()

    def set_row_software(self, row: int, object_name: str) -> None:
        if self._document.row_software[row] == object_name:
            return
        self._commit_document(self._document.with_row_software(row, object_name))
        self.channels_changed.emit()

    def set_delay_us(self, col: int, value_us: float) -> None:
        resolved = self._timeline_col_to_block(col)
        if resolved is None:
            return
        bi, local_col = resolved
        block = self._document.blocks[bi]
        new_b = block.with_delay_us(local_col, value_us)
        self._commit_document(self._document.with_block(bi, new_b))
        self.delays_changed.emit()

    def set_col_label(self, col: int, text: str) -> None:
        resolved = self._timeline_col_to_block(col)
        if resolved is None:
            return
        bi, local_col = resolved
        block = self._document.blocks[bi]
        if block.col_label(local_col) == text:
            return
        new_b = block.with_col_label(local_col, text)
        self._commit_document(self._document.with_block(bi, new_b))

    def set_analog(self, row: int, param_id: str, col: int, value: AnalogStored) -> None:
        resolved = self._timeline_col_to_block(col)
        if resolved is None:
            return
        bi, local_col = resolved
        block = self._document.blocks[bi]
        new_b = block.with_analog(self._document.rows, row, param_id, local_col, value)
        self._commit_document(self._document.with_block(bi, new_b))
        self.analog_changed.emit()

    def set_row_label(self, row: int, text: str) -> None:
        self._commit_document(self._document.with_row_label(row, text))
        self.row_labels_changed.emit()

    def set_static_label(self, row: int, text: str) -> None:
        if self._document.static_label(row) == text:
            return
        self._commit_document(self._document.with_static_label(row, text))
        self.static_labels_changed.emit()

    def set_static_software(self, row: int, object_name: str) -> None:
        if self._document.static_software_name(row) == object_name:
            return
        self._commit_document(self._document.with_static_software(row, object_name))
        self.static_changed.emit()

    def set_static_value(self, row: int, param_id: str, value: float) -> None:
        self._commit_document(self._document.with_static_value(row, param_id, value))
        self.static_changed.emit()

    def set_block_name(self, block_index: int, name: str) -> None:
        b = self._document.blocks[block_index]
        self._commit_document(self._document.with_block(block_index, b.with_name(name)))

    def set_block_enabled(self, block_index: int, enabled: bool) -> None:
        b = self._document.blocks[block_index]
        if b.enabled == enabled:
            return
        self._commit_document(self._document.with_block(block_index, b.with_enabled(enabled)))

    def set_block_accent_color(self, block_index: int, accent_color: str | None) -> None:
        if not (0 <= block_index < len(self._document.blocks)):
            raise IndexError("block index out of range")
        b = self._document.blocks[block_index]
        if b.accent_color == accent_color:
            return
        self._commit_document(self._document.with_block(block_index, b.with_accent_color(accent_color)))

    def set_block_cols(self, block_index: int, cols: int) -> None:
        if cols < 1:
            cols = 1
        if not (0 <= block_index < len(self._document.blocks)):
            raise IndexError("block index out of range")
        b = self._document.blocks[block_index]
        if b.cols == cols:
            return
        self._commit_document(self._document.with_block(block_index, b.with_cols(cols)))
        self.channels_changed.emit()
        self.delays_changed.emit()
        self.analog_changed.emit()

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
        self._notify_backend()

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
        self._notify_backend()

    def add_block(self) -> None:
        n = len(self._document.blocks) + 1
        last = self._document.blocks[-1]
        new_b = SequenceBlock(
            name=f"Block {n}",
            enabled=False,
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
        self._notify_backend()
