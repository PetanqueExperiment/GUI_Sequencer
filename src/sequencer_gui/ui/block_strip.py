from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QCursor, QIntValidator
from PyQt5.QtWidgets import (
    QApplication,
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


class _DragHandle(QLabel):
    """Starts a live block reorder (☰): cards move in the strip as you drag."""

    def __init__(
        self,
        block_slot: int,
        canvas: "_BlockStripCanvas",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("☰", parent)
        self._block_slot = block_slot
        self._canvas = canvas
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip("Drag to reorder blocks")
        self.setFixedWidth(22)
        self.setAlignment(Qt.AlignCenter)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return super().mouseMoveEvent(event)
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return super().mouseMoveEvent(event)
        self._canvas.begin_live_drag(self._block_slot)
        self._press_pos = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)


class _BlockStripCanvas(QWidget):
    """Horizontal row of block cards; live-reorders widgets while dragging."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._frames: list[QFrame] = []
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(4, 4, 4, 4)
        self._row.setSpacing(10)
        self._live_dragging = False
        self._perm: list[int] = []
        self._drag_slot = 0
        self.setMouseTracking(True)

    def register_frames(self, frames: list[QFrame]) -> None:
        self._frames = frames

    def begin_live_drag(self, from_slot: int) -> None:
        if self._live_dragging or not (0 <= from_slot < len(self._frames)):
            return
        n = len(self._frames)
        self._live_dragging = True
        self._perm = list(range(n))
        self._drag_slot = from_slot
        self.grabMouse()
        self.setCursor(QCursor(Qt.ClosedHandCursor))
        lp = self.mapFromGlobal(QCursor.pos())
        self._sync_visual_to_target(self._target_index_from_pos(lp))

    def mouseMoveEvent(self, event) -> None:
        if self._live_dragging:
            target = self._target_index_from_pos(event.pos())
            self._sync_visual_to_target(target)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._live_dragging and event.button() == Qt.LeftButton:
            self._finish_live_drag()
        super().mouseReleaseEvent(event)

    def _finish_live_drag(self) -> None:
        self._live_dragging = False
        self.releaseMouse()
        self.unsetCursor()
        n = len(self._perm)
        identity = list(range(n))
        if self._perm != identity:
            self._state.apply_block_permutation(self._perm)
        self._perm = []

    def _sync_visual_to_target(self, target_slot: int) -> None:
        if not self._live_dragging or target_slot == self._drag_slot:
            return
        if not (0 <= target_slot < len(self._frames)):
            return
        self._move_visual(self._drag_slot, target_slot)
        self._drag_slot = target_slot

    def _move_visual(self, from_i: int, to_i: int) -> None:
        if from_i == to_i:
            return
        self._perm.insert(to_i, self._perm.pop(from_i))
        w = self._frames.pop(from_i)
        self._frames.insert(to_i, w)
        self._row.removeWidget(w)
        self._row.insertWidget(to_i, w)

    def _target_index_from_pos(self, pos) -> int:
        x = pos.x()
        n = len(self._frames)
        if n == 0:
            return 0
        for i, fr in enumerate(self._frames):
            g = fr.geometry()
            if x < g.center().x():
                return i
        return n - 1


class BlockStripWidget(QGroupBox):
    """Between toolbar and tabs: per-block name, ON/OFF, add block, drag to reorder."""

    def __init__(self, state: SequenceAppState, parent: QWidget | None = None) -> None:
        super().__init__("Block Timeline", parent)
        self._state = state
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self._canvas = _BlockStripCanvas(state)
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

        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(scroll, 1)
        outer.addWidget(self._btn_add, 0, Qt.AlignTop)

        state.document_changed.connect(self._rebuild_from_document)
        self._rebuild_from_document(state.document)

    def _on_add_block(self) -> None:
        self._state.add_block()

    def _rebuild_from_document(self, _document=None) -> None:
        if self._canvas._live_dragging:
            return

        row = self._canvas._row
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

            row_name = QHBoxLayout()
            row_name.setSpacing(6)

            handle = _DragHandle(i, self._canvas)
            row_name.addWidget(handle)

            btn_color = QPushButton()
            btn_color.setFixedSize(22, 22)
            btn_color.setToolTip("Choose block color (right-click to reset)")
            btn_color.setStyleSheet(block_swatch_stylesheet(accent))
            btn_color.setCursor(Qt.PointingHandCursor)

            def make_pick_color(ii: int, button: QPushButton, card: QFrame):
                def on_clicked() -> None:
                    current = QColor(
                        resolve_block_accent_color(ii, self._state.document.blocks[ii].accent_color)
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
            idx = i

            def make_finished(ii: int, e: QLineEdit):
                def on_finished() -> None:
                    self._state.set_block_name(ii, e.text())

                return on_finished

            edit.editingFinished.connect(make_finished(idx, edit))
            row_name.addWidget(edit)
            row_name.addStretch(1)

            btn_remove = QPushButton("\u00d7")
            btn_remove.setFixedSize(22, 22)
            btn_remove.setFlat(True)
            btn_remove.setToolTip("Remove block")
            btn_remove.setEnabled(len(doc.blocks) > 1)
            btn_remove.clicked.connect(lambda checked=False, ii=idx: self._state.remove_block(ii))
            row_name.addWidget(btn_remove, 0, Qt.AlignRight | Qt.AlignVCenter)
            outer.addLayout(row_name)

            row_actions = QHBoxLayout()
            row_actions.setSpacing(6)

            on_btn = QPushButton("On")
            on_btn.setCheckable(True)
            on_btn.setMinimumWidth(32)

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
