"""Approval window for an AI proposal: sequence changes and scan, accepted separately.

The matrix is a read-only preview (its own ``SequenceAppState``); only the Accept buttons change the
live sequence, through :class:`~sequencer_gui.remote_control.proposal_controller.ProposalController`.
"""

from __future__ import annotations

from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QColor
from PyQt5.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sequencer_gui.app.backend import NoOpBackend
from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.domain.document import merged_enabled_timeline_col_to_block
from sequencer_gui.pycam_repository import ScanLabelAvailability, classify_scan_label
from sequencer_gui.remote_control.proposal_controller import (
    ACCEPTED,
    PENDING,
    ProposalController,
    ProposalSession,
)
from sequencer_gui.remote_control.proposals import apply_changes, scan_parameters
from sequencer_gui.scan_plan import format_duration_hms, resolve_scan_bindings
from sequencer_gui.ui.channel_matrix import ChannelMatrix

_CHANGE_EDIT_STYLE = "border: 2px solid #ef6c00; background-color: #ffe0b2;"
_CURRENT_EDIT_STYLE = "border: 2px dashed #1e88e5; background-color: #e3f2fd;"
_SCAN_EDIT_STYLE = "border: 2px dotted #6a1b9a; background-color: #f3e5f5;"
_BUTTON_BORDER = {
    _CHANGE_EDIT_STYLE: "#ef6c00",
    _CURRENT_EDIT_STYLE: "#1e88e5",
    _SCAN_EDIT_STYLE: "#6a1b9a",
}
_GREEN, _RED, _GREY = "#2e7d32", "#c62828", "#9e9e9e"


class ProposalWindow(QMainWindow):
    def __init__(self, live_state: SequenceAppState, controller: ProposalController,
                 session: ProposalSession, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.Window, True)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._live = live_state
        self._ctl = controller
        self._s = session
        self._highlighted: list[tuple[QWidget, str]] = []
        self._preview = SequenceAppState(
            NoOpBackend(), document=session.base_document,
            sequence_name=live_state.sequence_name, read_only=True,
        )
        self._preview.set_active_tab(COMPLETE_TAB_INDEX)
        name = Path(live_state.sequence_name).name or "sequence"
        self.setWindowTitle(f"AI proposal {session.id} — {name}")
        self.resize(1300, 900)

        central = QWidget()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.setSpacing(8)

        panel = QFrame()
        panel.setObjectName("proposal")
        panel.setStyleSheet("#proposal { border: 2px solid #ef6c00; border-radius: 4px; }")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)
        title = QLabel(f"<span style='color:#e65100'><b>AI:</b></span> {_esc(session.proposal.summary)}")
        title.setWordWrap(True)
        title.setToolTip(f"Proposal {session.id}, made on revision {session.proposal.base_revision}.")
        outer.addWidget(title)
        self._stale = QLabel()
        self._stale.setStyleSheet(f"color: {_RED};")
        self._stale.hide()
        outer.addWidget(self._stale)

        self._build_changes_part(outer)
        self._build_scan_part(outer)
        lay.addWidget(panel, 0)

        self._tabs = QTabBar()
        self._tabs.setExpanding(False)
        self._tabs.addTab("Complete")
        for blk in session.base_document.blocks:
            self._tabs.addTab(blk.name)
        self._tabs.currentChanged.connect(self._on_tab)
        lay.addWidget(self._tabs, 0)
        self._matrix = ChannelMatrix(self._preview)
        lay.addWidget(self._matrix, 1)

        self._preview.document_changed.connect(lambda _d: self._schedule_highlight())
        self._preview.active_tab_changed.connect(lambda _t: self._schedule_highlight())
        live_state.document_changed.connect(self._on_live_changed)
        live_state.scan_running_changed.connect(self._on_live_changed)
        controller.session_changed.connect(self._on_session_changed)
        self._refresh()

    # --- layout ----------------------------------------------------------------------------------

    def _build_changes_part(self, outer: QVBoxLayout) -> None:
        self._table = None
        if not self._s.has_changes:
            return
        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(4)
        self._changes_status = QLabel()
        self._changes_status.hide()
        left.addWidget(self._changes_status)
        t = QTableWidget(len(self._s.changes), 2)
        t.horizontalHeader().setVisible(False)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)
        t.setFrameShape(QFrame.NoFrame)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        self._change_labels: list[QLabel] = []
        for i, c in enumerate(self._s.changes):
            item = QTableWidgetItem(c.what)
            item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            item.setCheckState(Qt.Checked)
            item.setToolTip(c.tooltip)
            t.setItem(i, 0, item)
            lab = QLabel()
            lab.setToolTip(c.tooltip)
            lab.setContentsMargins(6, 0, 0, 0)
            t.setCellWidget(i, 1, lab)
            self._change_labels.append(lab)
        t.resizeColumnsToContents()
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.resizeRowsToContents()
        t.setFixedHeight(sum(t.rowHeight(i) for i in range(t.rowCount())) + 4)
        t.itemChanged.connect(lambda _it: self._refresh())
        self._table = t
        left.addWidget(t)
        row.addLayout(left, 1)

        buttons = QHBoxLayout()
        self._btn_current = QPushButton("Show current")
        self._btn_current.setCheckable(True)
        self._btn_current.setToolTip("Toggle to compare: matrix without the changes.\n"
                                     "Orange = change, purple = scanned cell.")
        self._btn_current.toggled.connect(lambda _on: self._refresh())
        buttons.addWidget(self._btn_current)
        self._btn_accept = QPushButton()
        self._btn_accept.setStyleSheet("font-weight: bold;")
        self._btn_accept.setMinimumWidth(130)
        self._btn_accept.setToolTip("Apply the ticked changes to the running sequence (one step, can be undone).")
        self._btn_accept.clicked.connect(self._accept_changes)
        buttons.addWidget(self._btn_accept)
        self._btn_reject = QPushButton("Reject")
        self._btn_reject.clicked.connect(lambda: self._call(self._ctl.reject_changes, self._s))
        buttons.addWidget(self._btn_reject)
        self._btn_undo = QPushButton("Undo")
        self._btn_undo.setToolTip("Restore the sequence as it was before these changes.")
        self._btn_undo.clicked.connect(lambda: self._call(self._ctl.undo_changes, self._s))
        buttons.addWidget(self._btn_undo)
        row.addLayout(buttons, 0)
        outer.addLayout(row)

    def _build_scan_part(self, outer: QVBoxLayout) -> None:
        self._scan_head = None
        if not self._s.has_scan:
            return
        if self._s.has_changes:
            sep = QFrame()
            sep.setFrameShape(QFrame.HLine)
            sep.setStyleSheet("color: #ffcc80;")
            outer.addWidget(sep)
        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(4)
        self._scan_head = QLabel()
        left.addWidget(self._scan_head)
        self._scan_axes = QLabel()
        self._scan_axes.setContentsMargins(18, 0, 0, 0)
        left.addWidget(self._scan_axes)
        row.addLayout(left, 1)
        buttons = QHBoxLayout()
        self._btn_scan_ok = QPushButton("Accept scan")
        self._btn_scan_ok.setStyleSheet("font-weight: bold;")
        self._btn_scan_ok.setMinimumWidth(130)
        self._btn_scan_ok.setToolTip("Fill the Scan panel with this scan; you press Start.")
        self._btn_scan_ok.clicked.connect(lambda: self._call(self._ctl.accept_scan, self._s))
        buttons.addWidget(self._btn_scan_ok)
        self._btn_scan_no = QPushButton("Reject scan")
        self._btn_scan_no.clicked.connect(lambda: self._call(self._ctl.reject_scan, self._s))
        buttons.addWidget(self._btn_scan_no)
        row.addLayout(buttons, 0)
        outer.addLayout(row)

    # --- state -----------------------------------------------------------------------------------

    def _ticked(self) -> list[int]:
        if self._table is None:
            return []
        return [i for i in range(self._table.rowCount())
                if self._table.item(i, 0).checkState() == Qt.Checked]

    def _shown_changes(self) -> list[int]:
        """Changes drawn in the preview: ticked while pending, accepted ones once applied."""
        if self._table is None:
            return []
        status = self._s.changes_status
        if status == PENDING:
            return [] if self._btn_current.isChecked() else self._ticked()
        return list(self._s.accepted_indices) if status == ACCEPTED else []

    def _refresh(self) -> None:
        self._refresh_changes()
        self._refresh_scan()
        shown = [self._s.changes[i] for i in self._shown_changes()]
        self._preview.replace_document(apply_changes(self._s.base_document, shown),
                                       active_tab=self._preview.active_tab_index)
        self._schedule_highlight()

    def _refresh_changes(self) -> None:
        if self._table is None:
            return
        s = self._s
        pending = s.changes_status == PENDING
        up_to_date = self._ctl.is_up_to_date(s)
        self._stale.setVisible(pending and not up_to_date)
        self._stale.setText("⚠ The sequence changed since this proposal was made: the changes "
                            "can no longer be accepted. Reject them and ask the AI again.")
        ticked = self._ticked()
        self._table.blockSignals(True)
        for i, c in enumerate(s.changes):
            on = i in ticked
            self._table.item(i, 0).setForeground(QColor("#000000" if on else _GREY))
            if on:
                html = (f"<span style='color:{_RED}'>{_esc(c.old)}</span> → "
                        f"<span style='color:{_GREEN}'><b>{_esc(c.new)}</b></span>{_esc(c.unit)}")
            else:
                html = f"<span style='color:{_GREY}'>{_esc(c.old)} → {_esc(c.new)}{_esc(c.unit)}</span>"
            self._change_labels[i].setText(html)
        self._table.blockSignals(False)
        self._table.setVisible(pending)
        for b in (self._btn_current, self._btn_accept, self._btn_reject):
            b.setVisible(pending)
        self._btn_accept.setText(f"Accept {len(ticked)} of {len(s.changes)}")
        self._btn_accept.setEnabled(bool(ticked) and up_to_date and not self._live.scan_running)
        if self._live.scan_running and pending:
            self._btn_accept.setToolTip("A scan is running: accept after it ends.")
        self._btn_undo.setVisible(s.changes_status == ACCEPTED)
        self._btn_undo.setEnabled(self._ctl.can_undo(s) and not self._live.scan_running)
        self._changes_status.setVisible(not pending)
        self._changes_status.setText(self._changes_status_text())

    def _changes_status_text(self) -> str:
        s = self._s
        if s.changes_status == ACCEPTED:
            names = ", ".join(_esc(s.changes[i].what) for i in s.accepted_indices)
            skipped = [_esc(c.what) for i, c in enumerate(s.changes) if i not in s.accepted_indices]
            text = f"<span style='color:{_GREEN}'>✓ Changes applied:</span> {names}"
            if skipped:
                text += f"<span style='color:{_GREY}'> · not applied: {', '.join(skipped)}</span>"
            if not self._ctl.can_undo(s):
                text += f"<span style='color:{_GREY}'> · sequence edited since (undo by hand)</span>"
            return text
        return f"<span style='color:{_GREY}'>✗ Sequence changes {s.changes_status}</span>"

    def _refresh_scan(self) -> None:
        if self._scan_head is None:
            return
        s = self._s
        scan = s.proposal.scan
        if s.scan_status != PENDING:
            if s.scan_status == ACCEPTED:
                text = (f"<span style='color:{_GREEN}'>✓ Scan \"{_esc(scan.label)}\" is in the Scan panel</span>"
                        f"<span style='color:{_GREY}'> · press Start when ready</span>")
            else:
                text = f"<span style='color:{_GREY}'>✗ Scan {s.scan_status}</span>"
            self._scan_head.setText(text)
            self._scan_head.setToolTip("")
            for w in (self._scan_axes, self._btn_scan_ok, self._btn_scan_no):
                w.hide()
            return
        chk = s.scan_check
        used = classify_scan_label(scan.label, scan_running=self._live.scan_running,
                                   active_scan_label=self._live.scan_label)
        name_note = "already used today" if used == ScanLabelAvailability.USED_TODAY else "new name today"
        self._scan_head.setText(
            f"<b>Scan \"{_esc(scan.label)}\"</b> ({name_note}): {chk.points} points × "
            f"{scan.repetitions} reps = {chk.shots} shots, ≈ {format_duration_hms(chk.duration_s)}")
        tip = "Accepting fills the Scan panel; you press Start.\nDuration = sequence time only (no dead time between shots)."
        if scan.reason:
            tip = f"{scan.reason}\n{tip}"
        self._scan_head.setToolTip(tip)
        lines = []
        for where, values, unit, now in chk.axes:
            now_text = f"&nbsp;&nbsp;<span style='color:#757575'>(now {_esc(now)})</span>" if now else ""
            lines.append(f"<span style='color:#6a1b9a'>{_esc(where)}:</span>&nbsp;&nbsp;"
                         f"{_esc(values)}{_esc(unit)}{now_text}")
        self._scan_axes.setText("<br>".join(lines))
        self._btn_scan_ok.setEnabled(not self._live.scan_running)
        self._btn_scan_ok.setToolTip("A scan is running: accept after it ends." if self._live.scan_running
                                     else "Fill the Scan panel with this scan; you press Start.")

    # --- highlighting ----------------------------------------------------------------------------

    def _schedule_highlight(self) -> None:
        QTimer.singleShot(0, self._highlight)

    def _visible_col(self, merged_col: int) -> int | None:
        tab = self._preview.active_tab_index
        if tab == COMPLETE_TAB_INDEX:
            return merged_col
        located = merged_enabled_timeline_col_to_block(self._s.base_document, merged_col)
        return located[1] if located is not None and located[0] == tab else None

    def _mark(self, row: int, param_id: str, merged_col: int, style: str) -> None:
        col = self._visible_col(merged_col)
        if col is None:
            return
        w = self._matrix.timelineCellWidget(row, param_id, col)
        if w is None:
            return
        base = w.styleSheet()
        self._highlighted.append((w, base))
        if isinstance(w, QPushButton):
            w.setStyleSheet(f"{base} QPushButton {{ border: 3px solid {_BUTTON_BORDER[style]}; }}")
        else:
            w.setStyleSheet(style)

    def _clear_marks(self) -> None:
        for w, base in reversed(self._highlighted):
            if not sip.isdeleted(w):
                w.setStyleSheet(base)
        self._highlighted.clear()

    def _highlight(self) -> None:
        if sip.isdeleted(self._matrix):
            return
        self._clear_marks()
        s = self._s
        if s.has_scan and s.scan_status in (PENDING, ACCEPTED):
            try:
                bindings = resolve_scan_bindings(self._preview.document, scan_parameters(s.proposal.scan))
            except ValueError:
                bindings = ()
            for bd in bindings:
                if bd.is_static:
                    continue
                self._mark(-1 if bd.is_delay else bd.row, "" if bd.is_delay else bd.param_id,
                           bd.merged_col, _SCAN_EDIT_STYLE)
        if self._table is not None and s.changes_status == PENDING and self._btn_current.isChecked():
            indices, style = self._ticked(), _CURRENT_EDIT_STYLE
        else:
            indices, style = self._shown_changes(), _CHANGE_EDIT_STYLE
        for i in indices:
            c = s.changes[i]
            param = c.change.param if c.change.kind == "value" else ""
            self._mark(c.row, param, c.merged_col, style)

    # --- events ----------------------------------------------------------------------------------

    def _on_tab(self, index: int) -> None:
        self._preview.set_active_tab(COMPLETE_TAB_INDEX if index == 0 else index - 1)

    def _on_live_changed(self, *_args) -> None:
        self._refresh_changes()
        self._refresh_scan()

    def _on_session_changed(self, session: ProposalSession) -> None:
        if session is self._s:
            self._refresh()

    def _accept_changes(self) -> None:
        self._call(self._ctl.accept_changes, self._s, self._ticked())

    def _call(self, fn, *args) -> None:
        try:
            fn(*args)
        except RuntimeError as e:
            QMessageBox.warning(self, "AI proposal", str(e))
            self._refresh()

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self._ctl.dismiss(self._s)
        try:
            self._live.document_changed.disconnect(self._on_live_changed)
            self._live.scan_running_changed.disconnect(self._on_live_changed)
            self._ctl.session_changed.disconnect(self._on_session_changed)
        except TypeError:
            pass
        super().closeEvent(event)


def _esc(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
