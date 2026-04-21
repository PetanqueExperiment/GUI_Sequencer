from __future__ import annotations

from PyQt5.QtCore import QObject, pyqtSignal

from sequencer_gui.app.backend import NoOpBackend, SequenceBackendProtocol
from sequencer_gui.domain.model import SequenceModel


class SequenceAppState(QObject):
    """Owns the sequence model, emits Qt signals, forwards snapshots to a backend."""

    model_changed = pyqtSignal(SequenceModel)
    channels_changed = pyqtSignal()
    delays_changed = pyqtSignal()
    analog_changed = pyqtSignal()
    row_labels_changed = pyqtSignal()
    sequence_name_changed = pyqtSignal(str)

    def __init__(
        self,
        backend: SequenceBackendProtocol | None = None,
        model: SequenceModel | None = None,
        sequence_name: str = "Untitled",
    ) -> None:
        super().__init__()
        self._backend = backend if backend is not None else NoOpBackend()
        self._model = model if model is not None else SequenceModel()
        self._sequence_name = sequence_name

    @property
    def model(self) -> SequenceModel:
        return self._model

    @property
    def sequence_name(self) -> str:
        return self._sequence_name

    def set_sequence_name(self, name: str) -> None:
        self._sequence_name = name
        self.sequence_name_changed.emit(name)

    def replace_model(self, model: SequenceModel) -> None:
        self._set_model(model)

    def _set_model(self, model: SequenceModel) -> None:
        self._model = model
        self.model_changed.emit(model)
        self._backend.apply(model)

    def set_channel(self, row: int, col: int, on: bool) -> None:
        self._set_model(self._model.with_channel(row, col, on))
        self.channels_changed.emit()

    def set_row_software(self, row: int, object_name: str) -> None:
        if self._model.row_software_name(row) == object_name:
            return
        self._set_model(self._model.with_row_software(row, object_name))
        self.channels_changed.emit()

    def set_delay_us(self, col: int, value_us: float) -> None:
        self._set_model(self._model.with_delay_us(col, value_us))
        self.delays_changed.emit()

    def set_analog(self, row: int, param_id: str, col: int, value: float) -> None:
        self._set_model(self._model.with_analog(row, param_id, col, value))
        self.analog_changed.emit()

    def set_row_label(self, row: int, text: str) -> None:
        self._set_model(self._model.with_row_label(row, text))
        self.row_labels_changed.emit()
