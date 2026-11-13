"""Drag-to-reorder for a horizontal row of cards (block strip, scan parameter cards)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QCursor
from PyQt5.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget


class DragHandle(QLabel):
    """Starts a live reorder (☰): cards move in the row as you drag."""

    def __init__(
        self,
        slot: int,
        canvas: "LiveReorderCanvas",
        tooltip: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("☰", parent)
        self._slot = slot
        self._canvas = canvas
        self._press_pos = None
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip(tooltip)
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
        self._canvas.begin_live_drag(self._slot)
        self._press_pos = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._press_pos = None
        super().mouseReleaseEvent(event)


class LiveReorderCanvas(QWidget):
    """Horizontal row of cards; live-reorders the widgets while dragging.

    The owner fills ``row_layout`` and calls ``register_frames`` with the cards in
    order. Nothing is committed during the drag: ``drag_finished`` carries the
    permutation on release (``permutation[i]`` = original index of the card now at
    position ``i``; the identity when nothing moved).
    """

    drag_about_to_start = pyqtSignal()
    drag_finished = pyqtSignal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._frames: list[QWidget] = []
        self._row = QHBoxLayout(self)
        self._live_dragging = False
        self._perm: list[int] = []
        self._drag_slot = 0
        self.setMouseTracking(True)

    @property
    def row_layout(self) -> QHBoxLayout:
        return self._row

    @property
    def is_dragging(self) -> bool:
        return self._live_dragging

    def register_frames(self, frames: list[QWidget]) -> None:
        self._frames = frames

    def begin_live_drag(self, from_slot: int) -> None:
        if self._live_dragging or not (0 <= from_slot < len(self._frames)):
            return
        self.drag_about_to_start.emit()
        if not (0 <= from_slot < len(self._frames)):
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
        perm = self._perm
        self._perm = []
        self.drag_finished.emit(perm)

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
