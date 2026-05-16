from __future__ import annotations

from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import QComboBox, QSizePolicy, QVBoxLayout, QWidget

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.software_objects import get_object, iter_objects

# Shared with ChannelMatrix column 0 and device_row header; fixed width aligns all rows.
LABEL_COL_MIN_WIDTH_PX = 230

_COMBO_H = 25


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event: QWheelEvent) -> None:
        event.ignore()


class RowSoftwareSelector(QWidget):
    """Dropdown: one software object id per row (display names in list)."""

    def __init__(self, row: int, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._row = row
        self._state = state

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._combo = _NoWheelComboBox()
        self._combo.setMinimumHeight(_COMBO_H)
        self._combo.setMaximumHeight(_COMBO_H)
        for obj in iter_objects():
            self._combo.addItem(obj.display_name, obj.id)
        self._combo.setStyleSheet("QComboBox { font-size: 11px; padding: 2px 6px; }")
        self._combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self._combo.currentIndexChanged.connect(self._on_index_changed)

        layout.addWidget(self._combo)

        self.setMinimumWidth(50)
        self.setMaximumWidth(80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.apply_from_model(state.model)

    def _on_index_changed(self, idx: int) -> None:
        if idx < 0:
            return
        oid = self._combo.itemData(idx)
        if oid is None:
            oid = self._combo.itemText(idx)
        self._state.set_row_software(self._row, str(oid))

    def apply_from_model(self, model: SequenceModel) -> None:
        oid = model.row_software_name(self._row)
        self._ensure_item(oid)
        self._combo.blockSignals(True)
        idx = self._combo.findData(oid)
        if idx < 0:
            idx = self._combo.findText(oid)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)
        self._combo.blockSignals(False)

    def _ensure_item(self, object_id: str) -> None:
        if self._combo.findData(object_id) >= 0:
            return
        obj = get_object(object_id)
        self._combo.addItem(obj.display_name, obj.id)
