"""The pending AI proposal and the operator's decisions on it (GUI thread only).

One proposal at a time. It has two parts decided separately: the sequence changes (the operator
may tick a subset) and the scan. Only this controller changes the live sequence for a proposal:

- Accept changes: refused while a scan runs or if the sequence changed since the proposal was made
  (revision check); applied in one ``replace_document``; kept for one Undo.
- Accept scan: re-checked on the current sequence, then written to the Scan panel (never started).

Every event is appended to ``~/.sequencer_gui/ai_proposals.jsonl``.
"""

from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QObject, pyqtSignal

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.remote_control.describe import document_revision
from sequencer_gui.remote_control.proposals import (
    Proposal,
    ResolvedChange,
    ScanCheck,
    apply_changes,
    check_scan,
    parse_proposal,
    resolve_changes,
    scan_parameters,
)

PENDING = "pending"
ACCEPTED = "accepted"
REJECTED = "rejected"
UNDONE = "undone"
DISMISSED = "dismissed"  # window closed without a decision


def proposal_log_path() -> Path:
    return Path.home() / ".sequencer_gui" / "ai_proposals.jsonl"


@dataclass
class ProposalSession:
    id: str
    proposal: Proposal
    base_document: SequenceDocument
    changes: list[ResolvedChange]
    scan_check: ScanCheck | None
    changes_status: str = PENDING
    accepted_indices: list[int] = field(default_factory=list)
    scan_status: str = PENDING
    undo_document: SequenceDocument | None = None
    applied_revision: str = ""

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    @property
    def has_scan(self) -> bool:
        return self.proposal.scan is not None

    @property
    def undecided(self) -> bool:
        return (self.has_changes and self.changes_status == PENDING) or (
            self.has_scan and self.scan_status == PENDING
        )


class ProposalController(QObject):
    """Create on the GUI thread; HERO calls reach it through ``GuiThreadInvoker``."""

    proposal_opened = pyqtSignal(object)  # ProposalSession
    session_changed = pyqtSignal(object)  # ProposalSession

    def __init__(self, state: SequenceAppState, parent: QObject | None = None, *,
                 log_path: Path | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self._session: ProposalSession | None = None
        self._ids = itertools.count(1)
        self._log_path = log_path if log_path is not None else proposal_log_path()

    # --- queries -----------------------------------------------------------------------------

    @property
    def session(self) -> ProposalSession | None:
        return self._session

    def current_revision(self) -> str:
        return document_revision(self._state.document, self._state.sequence_name)

    def is_up_to_date(self, session: ProposalSession) -> bool:
        return self.current_revision() == session.proposal.base_revision

    def status(self, proposal_id: str) -> dict[str, Any]:
        s = self._session
        if s is None or s.id != proposal_id:
            raise ValueError(f"unknown proposal {proposal_id!r} (only the latest one is kept)")
        out: dict[str, Any] = {"proposal_id": s.id, "waiting_for_operator": s.undecided}
        if s.has_changes:
            out["changes"] = {
                "status": s.changes_status,
                "accepted": [s.changes[i].what for i in s.accepted_indices],
                "not_accepted": [c.what for i, c in enumerate(s.changes) if i not in s.accepted_indices],
            }
        if s.has_scan:
            out["scan"] = {"status": s.scan_status, "label": s.proposal.scan.label}
            if s.scan_status == ACCEPTED:
                out["scan"]["note"] = "in the Scan panel; the operator starts it"
        return out

    # --- from the AI ---------------------------------------------------------------------------

    def submit(self, data: Any) -> dict[str, Any]:
        """Check a proposal and open the approval window; ``ValueError`` if it cannot be shown."""
        if self._session is not None and self._session.undecided:
            raise ValueError(
                f"proposal {self._session.id} is still waiting for the operator; "
                "check its status before sending another one"
            )
        proposal = parse_proposal(data)
        current = self.current_revision()
        if proposal.base_revision != current:
            raise ValueError(
                f"base_revision {proposal.base_revision!r} is not the current revision {current!r}; "
                "re-read the sequence and propose again"
            )
        document = self._state.document
        changes = resolve_changes(document, proposal.changes)
        scan_check = None
        if proposal.scan is not None:
            try:
                # Columns never move with these changes, so all-changes-applied is a fair check.
                scan_check = check_scan(apply_changes(document, changes), proposal.scan)
            except ValueError as e:
                raise ValueError(f"scan: {e}") from e
        session = ProposalSession(
            id=f"P{next(self._ids)}-{time.strftime('%H%M%S')}",
            proposal=proposal,
            base_document=document,
            changes=changes,
            scan_check=scan_check,
        )
        self._session = session
        self._log(session, "received", summary=proposal.summary,
                  changes=[f"{c.what}: {c.old} -> {c.new}{c.unit}" for c in changes],
                  scan=proposal.scan.label if proposal.scan else None)
        self.proposal_opened.emit(session)
        return {"proposal_id": session.id, "status": "waiting for the operator"}

    # --- from the window -----------------------------------------------------------------------

    def accept_changes(self, session: ProposalSession, indices: list[int]) -> None:
        """Apply the ticked changes; ``RuntimeError`` with a message for the operator if refused."""
        self._require_pending(session, "changes")
        if self._state.scan_running:
            raise RuntimeError("A scan is running. Accept the changes after the scan.")
        if not self.is_up_to_date(session):
            raise RuntimeError("The sequence changed since the AI made this proposal.\n"
                               "Reject it and ask the AI to propose again.")
        chosen = [session.changes[i] for i in sorted(set(indices))]
        if not chosen:
            raise RuntimeError("No change is ticked.")
        before = self._state.document
        after = apply_changes(before, chosen)
        self._state.replace_document(after)
        session.undo_document = before
        session.applied_revision = self.current_revision()
        session.accepted_indices = sorted(set(indices))
        session.changes_status = ACCEPTED
        self._log(session, "changes accepted", accepted=[c.what for c in chosen],
                  revision_before=session.proposal.base_revision, revision_after=session.applied_revision)
        self.session_changed.emit(session)

    def reject_changes(self, session: ProposalSession) -> None:
        self._require_pending(session, "changes")
        session.changes_status = REJECTED
        self._log(session, "changes rejected")
        self.session_changed.emit(session)

    def can_undo(self, session: ProposalSession) -> bool:
        return (session.changes_status == ACCEPTED and session.undo_document is not None
                and self.current_revision() == session.applied_revision)

    def undo_changes(self, session: ProposalSession) -> None:
        if session.changes_status != ACCEPTED or session.undo_document is None:
            raise RuntimeError("Nothing to undo.")
        if self.current_revision() != session.applied_revision:
            raise RuntimeError("The sequence changed after the changes were applied;\n"
                               "undo them by hand.")
        if self._state.scan_running:
            raise RuntimeError("A scan is running. Undo after the scan.")
        self._state.replace_document(session.undo_document)
        session.undo_document = None
        session.changes_status = UNDONE
        self._log(session, "changes undone", revision_after=self.current_revision())
        self.session_changed.emit(session)

    def accept_scan(self, session: ProposalSession) -> None:
        self._require_pending(session, "scan")
        if self._state.scan_running:
            raise RuntimeError("A scan is running. Accept this scan after it ends.")
        scan = session.proposal.scan
        try:
            check_scan(self._state.document, scan)
        except ValueError as e:
            raise RuntimeError(f"The scan does not fit the current sequence:\n{e}") from e
        self._state.set_scan_plan(scan.label, scan.repetitions, scan_parameters(scan))
        session.scan_status = ACCEPTED
        self._log(session, "scan accepted", label=scan.label)
        self.session_changed.emit(session)

    def reject_scan(self, session: ProposalSession) -> None:
        self._require_pending(session, "scan")
        session.scan_status = REJECTED
        self._log(session, "scan rejected")
        self.session_changed.emit(session)

    def dismiss(self, session: ProposalSession) -> None:
        """Window closed: undecided parts count as rejected (reported as 'dismissed')."""
        changed = False
        if session.has_changes and session.changes_status == PENDING:
            session.changes_status = DISMISSED
            changed = True
        if session.has_scan and session.scan_status == PENDING:
            session.scan_status = DISMISSED
            changed = True
        if changed:
            self._log(session, "dismissed (window closed)")
            self.session_changed.emit(session)

    # --- helpers -------------------------------------------------------------------------------

    def _require_pending(self, session: ProposalSession, part: str) -> None:
        if session is not self._session:
            raise RuntimeError("This proposal is no longer the current one.")
        status = session.changes_status if part == "changes" else session.scan_status
        if status != PENDING:
            raise RuntimeError(f"The {part} were already decided ({status}).")

    def _log(self, session: ProposalSession, event: str, **details: Any) -> None:
        record = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "proposal_id": session.id,
                  "event": event, "sequence": self._state.sequence_name, **details}
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except OSError:
            pass  # The log must never block a decision.
