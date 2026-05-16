from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIntValidator
from PyQt5.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import ScanParameter, SequenceAppState


class ScanPanel(QGroupBox):
    """Scan configuration (repetitions per parameter step); execution wired later."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Scan", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 10, 12, 10)
        row.setSpacing(10)

        controls = QVBoxLayout()
        controls.setSpacing(6)

        label_row = QHBoxLayout()
        label_row.setSpacing(8)
        label_row.addWidget(QLabel("Label:"))
        self._label = QLineEdit(state.scan_label)
        self._label.setPlaceholderText("Experiment name")
        self._label.setMinimumWidth(140)
        self._label.setToolTip("Name of the scan experiment to perform")
        self._label.editingFinished.connect(self._on_label_edited)
        label_row.addWidget(self._label, 1)
        controls.addLayout(label_row)

        reps = QHBoxLayout()
        reps.setSpacing(8)
        reps.addWidget(QLabel("Repetitions:"))
        self._repetitions = QLineEdit(str(state.scan_repetitions))
        self._repetitions.setValidator(QIntValidator(1, 999_999, self))
        self._repetitions.setMaximumWidth(72)
        self._repetitions.setToolTip("Number of shots at each scan parameter value")
        self._repetitions.editingFinished.connect(self._on_repetitions_edited)
        reps.addWidget(self._repetitions, 0)
        controls.addLayout(reps)

        row.addLayout(controls, 0)

        self._cards_host = QWidget()
        self._cards_layout = QHBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(10)

        self._cards_scroll = QScrollArea()
        self._cards_scroll.setFrameShape(QFrame.NoFrame)
        self._cards_scroll.setWidgetResizable(True)
        self._cards_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._cards_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._cards_scroll.setWidget(self._cards_host)
        row.addWidget(self._cards_scroll, 1)

        self._btn_add_param = QPushButton("Add parameter")
        self._btn_add_param.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_add_param.setToolTip("Add a parameter axis to the scan (name and list of values)")
        self._btn_add_param.clicked.connect(self._state.add_scan_parameter)
        row.addWidget(self._btn_add_param, 0, Qt.AlignTop)

        state.scan_label_changed.connect(self._sync_label_from_state)
        state.scan_repetitions_changed.connect(self._sync_repetitions_from_state)
        state.scan_parameters_changed.connect(self._rebuild_param_cards)
        self._rebuild_param_cards()

    def _sync_label_from_state(self, value: str) -> None:
        self._label.blockSignals(True)
        self._label.setText(value)
        self._label.blockSignals(False)

    def _on_label_edited(self) -> None:
        self._state.set_scan_label(self._label.text().strip())

    def _sync_repetitions_from_state(self, value: int) -> None:
        self._repetitions.blockSignals(True)
        self._repetitions.setText(str(value))
        self._repetitions.blockSignals(False)

    def _on_repetitions_edited(self) -> None:
        text = self._repetitions.text().strip()
        if not text:
            self._sync_repetitions_from_state(self._state.scan_repetitions)
            return
        n = int(text)
        self._state.set_scan_repetitions(n)

    def _rebuild_param_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        for i, p in enumerate(self._state.scan_parameters):
            self._cards_layout.addWidget(self._make_param_card(i, p))

        self._cards_host.adjustSize()
        if self._state.scan_parameters:
            card_h = max(
                self._cards_layout.itemAt(i).widget().sizeHint().height()
                for i in range(self._cards_layout.count())
            )
            self._cards_scroll.setMinimumHeight(card_h)
        else:
            self._cards_scroll.setMinimumHeight(0)
        self.updateGeometry()

    def _make_param_card(self, index: int, p: ScanParameter) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setFixedWidth(152)
        frame.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(8, 6, 8, 6)
        outer.setSpacing(6)

        name_edit = QLineEdit(p.name)
        name_edit.setPlaceholderText("Parameter name")
        name_edit.editingFinished.connect(
            lambda idx=index, e=name_edit: self._state.set_scan_parameter_name(idx, e.text())
        )
        outer.addWidget(name_edit)

        values_edit = QLineEdit(p.values_text)
        values_edit.setPlaceholderText("e.g. 1, 2, 3")
        values_edit.setToolTip("Comma-separated values for this parameter")
        values_edit.editingFinished.connect(
            lambda idx=index, e=values_edit: self._state.set_scan_parameter_values_text(idx, e.text())
        )
        outer.addWidget(values_edit)

        btn_remove = QPushButton("Remove")
        btn_remove.clicked.connect(lambda checked=False, idx=index: self._state.remove_scan_parameter(idx))
        outer.addWidget(btn_remove, 0, Qt.AlignLeft)

        return frame
