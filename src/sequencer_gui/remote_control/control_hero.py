"""``SequencerControl_HERO``: remote API for scripts and AI agents (reads + proposals).

Separate from :class:`sequencer_gui.sequencer_hero.Sequencer_HERO`, which is the data path read by
ARTIQ. Every public method returns a JSON string::

    {"ok": true, "result": {...}}     or     {"ok": false, "error": "readable message"}

so a client never has to interpret a remote traceback. Descriptions are built by
:mod:`sequencer_gui.remote_control.describe`; see there for addressing and cell conventions.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from heros import LocalHERO

from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.remote_control.describe import (
    ScanConfig,
    describe_block,
    describe_complete,
    describe_devices,
    describe_overview,
)
from sequencer_gui.remote_control.gui_invoker import GuiThreadInvoker
from sequencer_gui.remote_control.proposal_controller import ProposalController


class _Snapshot:
    """Consistent copy of the GUI state taken in one GUI-thread call (document is immutable)."""

    def __init__(self, state: SequenceAppState) -> None:
        self.document: SequenceDocument = state.document
        self.sequence_name: str = state.sequence_name
        self.run_sequence: bool = state.run_sequence
        self.scan = ScanConfig(
            running=state.scan_running,
            label=state.scan_label,
            repetitions=state.scan_repetitions,
            parameters=tuple(dict(p._asdict()) for p in state.scan_parameters),
        )


def _ok(result: Any) -> str:
    return json.dumps({"ok": True, "result": result})


def _error(message: str) -> str:
    return json.dumps({"ok": False, "error": message})


class SequencerControl_HERO(LocalHERO):
    """Read the sequence open in the GUI and submit proposals for the operator to approve.

    Create on the GUI thread, after the main window. Nothing here changes the sequence directly:
    proposals only open the approval window (see ``proposal_controller.py``).
    """

    def __init__(self, name: str, state: SequenceAppState, invoker: GuiThreadInvoker,
                 controller: ProposalController | None = None, **kwargs: Any):
        # Private attributes are not exposed by heros (names starting with "_").
        self._state = state
        self._invoker = invoker
        self._controller = controller
        super().__init__(name, **kwargs)

    def _respond(self, build: Callable[[_Snapshot], Any]) -> str:
        """Snapshot on the GUI thread, describe off it; any failure becomes an error envelope."""
        try:
            snap = self._invoker.call(lambda: _Snapshot(self._state))
            return _ok(build(snap))
        except ValueError as e:
            return _error(str(e))
        except Exception as e:
            return _error(f"{type(e).__name__}: {e}")

    def get_overview(self) -> str:
        """Sequence name, revision, blocks (name, enabled, cols, duration_us), run and scan state."""
        return self._respond(
            lambda s: describe_overview(
                s.document, s.sequence_name, run_sequence=s.run_sequence, scan=s.scan
            )
        )

    def get_devices(self) -> str:
        """Timeline rows and static devices: label, device type, parameters with ranges."""
        return self._respond(lambda s: describe_devices(s.document))

    def get_block(self, block: str) -> str:
        """One block's timeline; ``block`` is its name or its 0-based index as a string."""
        return self._respond(lambda s: describe_block(s.document, s.sequence_name, block))

    def get_complete_timeline(self) -> str:
        """Enabled blocks concatenated as played, with stored and resolved analog values."""
        return self._respond(lambda s: describe_complete(s.document, s.sequence_name))

    def _on_gui(self, work: Callable[[ProposalController], Any]) -> str:
        if self._controller is None:
            return _error("proposals are not available in this GUI")
        try:
            return _ok(self._invoker.call(lambda: work(self._controller)))
        except ValueError as e:
            return _error(str(e))
        except Exception as e:
            return _error(f"{type(e).__name__}: {e}")

    def submit_proposal(self, proposal_json: str) -> str:
        """Open the approval window for a proposal (format: ``proposals.PROPOSAL_FORMAT_HELP``).

        Returns the proposal id; nothing is applied until the operator accepts in the window.
        """
        try:
            data = json.loads(proposal_json)
        except (TypeError, ValueError) as e:
            return _error(f"proposal is not valid JSON ({e})")
        return self._on_gui(lambda ctl: ctl.submit(data))

    def get_proposal_status(self, proposal_id: str) -> str:
        """Operator decisions so far: changes / scan each pending, accepted, rejected, undone or dismissed."""
        return self._on_gui(lambda ctl: ctl.status(proposal_id))
