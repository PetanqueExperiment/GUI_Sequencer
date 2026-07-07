"""Float line edits: commit on Enter, gray while editing, Up/Down local step."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Literal

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFocusEvent, QKeyEvent
from PyQt5.QtWidgets import QLineEdit, QWidget

from sequencer_gui.software_objects.types import AnalogParameterSpec

_FLOAT_HEAD = re.compile(r"^\s*([+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?)")

_STYLE_COMMITTED = "color: #212121;"
_STYLE_EDITING = "color: #9e9e9e;"


def digit_step_left_of_cursor(numeric_text: str, cursor: int) -> float:
    """
    Step matching the decimal place of the digit immediately left of the cursor.
    cursor is a position in numeric_text (0..len); digit used is at index cursor - 1.
    """
    if cursor <= 0:
        i = 0
        while i < len(numeric_text) and numeric_text[i] not in "0123456789":
            i += 1
        if i >= len(numeric_text):
            return 1.0
        cursor = i + 1
    i = cursor - 1
    while i >= 0 and numeric_text[i] not in "0123456789":
        i -= 1
    if i < 0:
        return 1.0
    dot = numeric_text.find(".")
    if dot < 0:
        exp = (len(numeric_text) - 1) - i
    elif i < dot:
        exp = dot - 1 - i
    else:
        exp = -(i - dot)
    return 10.0**exp


def cursor_position_for_same_digit_step(numeric_text: str, step: float, fallback: int) -> int:
    """
    Rightmost cursor index in ``numeric_text`` where Up/Down would use the same ``step``
    as ``digit_step_left_of_cursor`` (same decimal place). Falls back if no position matches.
    """
    matches: list[int] = []
    for j in range(0, len(numeric_text) + 1):
        if math.isclose(digit_step_left_of_cursor(numeric_text, j), step, rel_tol=0.0, abs_tol=1e-12):
            matches.append(j)
    if not matches:
        return min(max(0, fallback), len(numeric_text))
    return max(matches)


def map_cursor_to_leading_float_text(full: str, cursor: int) -> tuple[str, int]:
    """Map cursor into the leading float token in the field."""
    s = full.strip()
    m = _FLOAT_HEAD.match(s)
    if not m:
        return s, max(0, min(cursor, len(s)))
    num = m.group(1)
    start = s.find(num)
    if start < 0:
        return num, min(cursor, len(num))
    end = start + len(num)
    rel = cursor - start
    if rel < 0:
        rel = 0
    elif rel > len(num) + 1:
        rel = len(num) + 1
    elif cursor > end:
        rel = len(num) + 1
    return num, rel


def parse_analog_value(raw: str) -> Literal["hold"] | float | None:
    """Parse analog text: '-' is hold; otherwise a single float (comma as decimal)."""
    s = raw.strip()
    if s in ("-", "\u2212"):
        return "hold"
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_float_field(raw: str) -> float | None:
    """Single float for delay/time; empty or invalid → None."""
    s = raw.strip()
    if not s:
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None


class CommitFloatLineEdit(QLineEdit):
    """
    Up/Down adjust the value locally without notifying the program.
    Commit when Return/Enter is pressed (returnPressed).
    Gray while editing; black after commit. Focus out reverts uncommitted text.
    """

    def __init__(
        self,
        minimum: float,
        maximum: float,
        decimals: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._decimals = decimals
        self._committed_text = ""
        self._style_guard = False
        self._on_return: Callable[[], None] | None = None
        self.setStyleSheet(_STYLE_COMMITTED)
        self.returnPressed.connect(self._emit_return)
        self.textChanged.connect(self._on_text_changed)

    def set_on_return(self, fn: Callable[[], None] | None) -> None:
        """Called only when the user presses Enter/Return (not on focus loss or arrows)."""
        self._on_return = fn

    def set_committed_display(self, text: str) -> None:
        """Set text from the model (or after commit); shows as committed (black)."""
        pos_before = self.cursorPosition()
        self._style_guard = True
        self._committed_text = text
        self.blockSignals(True)
        self.setText(text)
        self.blockSignals(False)
        self.setStyleSheet(_STYLE_COMMITTED)
        self._style_guard = False
        self.setCursorPosition(min(pos_before, len(text)))

    def _on_text_changed(self, _text: str) -> None:
        if self._style_guard:
            return
        self.setStyleSheet(_STYLE_EDITING)

    def _emit_return(self) -> None:
        if self._on_return is not None:
            self._on_return()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        if self.text() != self._committed_text:
            self.set_committed_display(self._committed_text)
        else:
            self.setStyleSheet(_STYLE_COMMITTED)
        super().focusOutEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            if event.modifiers() & (
                Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier | Qt.ShiftModifier
            ):
                super().keyPressEvent(event)
                return
            self._try_arrow_step(1 if event.key() == Qt.Key_Up else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _try_arrow_step(self, direction: int) -> bool:
        s = self.text().strip()
        if s in ("-", "\u2212", "ramp"):
            return False
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            return False
        num, rel = map_cursor_to_leading_float_text(s, self.cursorPosition())
        try:
            float(num.replace(",", "."))
        except ValueError:
            return False
        step = digit_step_left_of_cursor(num, rel)
        nv = max(self._minimum, min(self._maximum, v + direction * step))
        if nv == v:
            return True
        dec = self._decimals
        txt = format(nv, f".{dec}f")
        pos_before = self.cursorPosition()
        self._style_guard = True
        self.setText(txt)
        self._style_guard = False
        self.setCursorPosition(cursor_position_for_same_digit_step(txt, step, pos_before))
        self.setStyleSheet(_STYLE_EDITING)
        return True


class AnalogValueLineEdit(CommitFloatLineEdit):
    """Analog parameter cell: same as CommitFloatLineEdit with bounds from ``AnalogParameterSpec``."""

    def __init__(self, spec: AnalogParameterSpec, parent: QWidget | None = None) -> None:
        super().__init__(spec.minimum, spec.maximum, spec.decimals, parent)
