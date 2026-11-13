from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QIntValidator
from PyQt5.QtWidgets import (
    QColorDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.ui.device_row import (
    block_strip_card_stylesheet,
    block_swatch_stylesheet,
    resolve_block_accent_color,
)
from sequencer_gui.ui.live_reorder import DragHandle, LiveReorderCanvas


class BlockStripWidget(QGroupBox):
    """Between toolbar and tabs: per-block name, ON/OFF, add block, drag to reorder."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Block Timeline", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._canvas = LiveReorderCanvas()
        self._canvas.row_layout.setContentsMargins(4, 4, 4, 4)
        self._canvas.row_layout.setSpacing(10)
        self._canvas.drag_finished.connect(self._on_blocks_reordered)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumHeight(80)
        scroll.setWidget(self._canvas)

        self._btn_add = QPushButton("Add block")
        self._btn_add.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._btn_add.clicked.connect(self._on_add_block)
        if state.is_read_only:
            self._btn_add.hide()

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._btn_add, 0, Qt.AlignTop)

        state.document_changed.connect(self._rebuild_from_document)
        self._rebuild_from_document(state.document)

    def _on_add_block(self) -> None:
        self._state.add_block()

    def _on_blocks_reordered(self, permutation: list) -> None:
        if permutation != list(range(len(permutation))):
            self._state.apply_block_permutation(permutation)

    def _rebuild_from_document(self, _document=None) -> None:
        if self._canvas.is_dragging:
            return

        row = self._canvas.row_layout
        while row.count():
            item = row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        doc = self._state.document
        frames: list[QFrame] = []
        for i in range(len(doc.blocks)):
            b = doc.blocks[i]
            accent = resolve_block_accent_color(i, b.accent_color)
            frame = QFrame()
            frame.setFrameShape(QFrame.StyledPanel)
            frame.setStyleSheet(block_strip_card_stylesheet(accent, enabled=b.enabled))
            frames.append(frame)
            outer = QVBoxLayout(frame)
            outer.setContentsMargins(8, 4, 8, 4)
            outer.setSpacing(4)

            view_only = self._state.is_read_only
            row_name = QHBoxLayout()
            row_name.setSpacing(6)

            if not view_only:
                handle = DragHandle(i, self._canvas, "Drag to reorder blocks")
                row_name.addWidget(handle)

            btn_color = QPushButton()
            btn_color.setFixedSize(22, 22)
            btn_color.setStyleSheet(block_swatch_stylesheet(accent))
            if view_only:
                btn_color.setEnabled(False)
                btn_color.setToolTip("Block color")
            else:
                btn_color.setToolTip("Choose block color (right-click to reset)")
                btn_color.setCursor(Qt.PointingHandCursor)

                def make_pick_color(ii: int, button: QPushButton, card: QFrame):
                    def on_clicked() -> None:
                        current = QColor(
                            resolve_block_accent_color(
                                ii, self._state.document.blocks[ii].accent_color
                            )
                        )
                        chosen = QColorDialog.getColor(current, card, "Block color")
                        if chosen.isValid():
                            self._state.set_block_accent_color(ii, chosen.name())

                    return on_clicked

                def make_color_menu(ii: int):
                    def show_menu(pos) -> None:
                        menu = QMenu()
                        reset = menu.addAction("Reset to default color")
                        picked = menu.exec_(btn_color.mapToGlobal(pos))
                        if picked is reset:
                            self._state.set_block_accent_color(ii, None)

                    return show_menu

                btn_color.clicked.connect(make_pick_color(i, btn_color, frame))
                btn_color.setContextMenuPolicy(Qt.CustomContextMenu)
                btn_color.customContextMenuRequested.connect(make_color_menu(i))

            edit = QLineEdit(b.name)
            edit.setMinimumWidth(120)
            edit.setReadOnly(view_only)
            idx = i

            if not view_only:

                def make_finished(ii: int, e: QLineEdit):
                    def on_finished() -> None:
                        self._state.set_block_name(ii, e.text())

                    return on_finished

                edit.editingFinished.connect(make_finished(idx, edit))
            row_name.addWidget(edit)
            row_name.addStretch(1)

            if not view_only:
                btn_remove = QPushButton("\u00d7")
                btn_remove.setFixedSize(22, 22)
                btn_remove.setFlat(True)
                btn_remove.setToolTip("Remove block")
                btn_remove.setEnabled(len(doc.blocks) > 1)
                btn_remove.clicked.connect(
                    lambda checked=False, ii=idx: self._state.remove_block(ii)
                )
                row_name.addWidget(btn_remove, 0, Qt.AlignRight | Qt.AlignVCenter)
            outer.addLayout(row_name)

            row_actions = QHBoxLayout()
            row_actions.setSpacing(6)

            on_btn = QPushButton("On")
            on_btn.setCheckable(True)
            on_btn.setMinimumWidth(32)
            on_btn.setEnabled(not view_only)

            if not view_only:

                def make_toggled(ii: int, btn: QPushButton):
                    def on_toggled(checked: bool) -> None:
                        self._state.set_block_enabled(ii, checked)
                        btn.setText("On" if checked else "Off")

                    return on_toggled

                on_btn.toggled.connect(make_toggled(idx, on_btn))
            on_btn.blockSignals(True)
            on_btn.setChecked(b.enabled)
            on_btn.blockSignals(False)
            on_btn.setText("On" if b.enabled else "Off")
            row_actions.addWidget(on_btn)

            row_actions.addWidget(QLabel("Steps:"))
            steps_edit = QLineEdit(str(b.cols))
            steps_edit.setValidator(QIntValidator(1, 9999, frame))
            steps_edit.setMinimumWidth(32)
            steps_edit.setMaximumWidth(32)
            steps_edit.setToolTip("Number of time steps in this block")
            steps_edit.setReadOnly(view_only)

            if not view_only:

                def make_steps_finished(ii: int, e: QLineEdit):
                    def on_finished() -> None:
                        text = e.text().strip()
                        if not text:
                            e.setText(str(self._state.document.blocks[ii].cols))
                            return
                        self._state.set_block_cols(ii, int(text))

                    return on_finished

                steps_edit.editingFinished.connect(make_steps_finished(idx, steps_edit))
            row_actions.addWidget(steps_edit)
            row_actions.addStretch(1)
            row_actions.addWidget(btn_color, 0, Qt.AlignRight | Qt.AlignVCenter)
            outer.addLayout(row_actions)

            row.addWidget(frame)

        self._canvas.register_frames(frames)
        row.addStretch(1)
