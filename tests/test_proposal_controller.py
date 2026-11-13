"""ProposalController: what reaches the live sequence and when (no window)."""

from __future__ import annotations

import json

import pytest

from sample_documents import sample_document
from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import merge_blocks
from sequencer_gui.remote_control.describe import document_revision
from sequencer_gui.remote_control.proposal_controller import ProposalController


@pytest.fixture()
def setup(tmp_path, app):
    state = SequenceAppState(document=sample_document(), sequence_name="seq")
    ctl = ProposalController(state, log_path=tmp_path / "log.jsonl")
    opened = []
    ctl.proposal_opened.connect(opened.append)
    return state, ctl, opened, tmp_path / "log.jsonl"


def _data(state, *, changes=True, scan=True) -> dict:
    d = {"summary": "test", "base_revision": document_revision(state.document, state.sequence_name)}
    if changes:
        d["changes"] = [
            {"row": "Cooling", "param": "frequency", "column": "c2", "value": -15},
            {"column": "c1", "delay_us": 60},
        ]
    if scan:
        d["scan"] = {"label": "det", "repetitions": 5,
                     "axes": [{"device": "Cooling", "param": "frequency", "timestep": "c2",
                               "values": [-16, -15, -14]}]}
    return d


def _played(state, row, param, col):
    return merge_blocks(state.document, enabled_only=True).analog_value(row, param, col)


def test_submit_opens_window_and_changes_nothing(setup) -> None:
    state, ctl, opened, _ = setup
    before = state.document
    reply = ctl.submit(_data(state))
    assert reply["status"] == "waiting for the operator"
    assert len(opened) == 1 and state.document is before
    with pytest.raises(ValueError, match="still waiting for the operator"):
        ctl.submit(_data(state))


def test_stale_revision_refused_at_submit_and_accept(setup) -> None:
    state, ctl, _, _ = setup
    stale = _data(state)
    stale["base_revision"] = "000000000000"
    with pytest.raises(ValueError, match="re-read the sequence"):
        ctl.submit(stale)
    ctl.submit(_data(state))
    state.set_delay_us(0, 999.0)  # operator edits the sequence meanwhile (block 0, column 0)
    with pytest.raises(RuntimeError, match="changed since the AI made this proposal"):
        ctl.accept_changes(ctl.session, [0, 1])


def test_accept_subset_then_undo(setup) -> None:
    state, ctl, _, log = setup
    ctl.submit(_data(state, scan=False))
    s = ctl.session
    ctl.accept_changes(s, [1])  # only the delay
    model = merge_blocks(state.document, enabled_only=True)
    assert model.delay_us(1) == 60.0
    assert _played(state, 1, "frequency", 2) == -12.0  # change 0 not ticked
    status = ctl.status(s.id)
    assert status["changes"] == {"status": "accepted", "accepted": ["delay c1"],
                                 "not_accepted": ["Cooling c2"]}
    assert status["waiting_for_operator"] is False
    assert ctl.can_undo(s)
    ctl.undo_changes(s)
    assert merge_blocks(state.document, enabled_only=True).delay_us(1) == 50.0
    assert ctl.status(s.id)["changes"]["status"] == "undone"
    events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
    assert events == ["received", "changes accepted", "changes undone"]


def test_no_accept_during_scan(setup) -> None:
    state, ctl, _, _ = setup
    ctl.submit(_data(state))
    state.set_scan_running(True)
    with pytest.raises(RuntimeError, match="A scan is running"):
        ctl.accept_changes(ctl.session, [0])
    with pytest.raises(RuntimeError, match="A scan is running"):
        ctl.accept_scan(ctl.session)


def test_scan_accept_fills_plan_only(setup) -> None:
    state, ctl, _, _ = setup
    ctl.submit(_data(state, changes=False))
    ctl.accept_scan(ctl.session)
    assert state.scan_label == "det" and state.scan_repetitions == 5
    p = state.scan_parameters[0]
    assert (p.device_label, p.param_id, p.timestep_label, p.values_text) == (
        "Cooling", "frequency", "2", "-16, -15, -14")
    assert state.scan_running is False and state.run_sequence is False


def test_dismiss_marks_undecided_parts(setup) -> None:
    state, ctl, _, _ = setup
    ctl.submit(_data(state))
    s = ctl.session
    ctl.reject_scan(s)
    ctl.dismiss(s)
    st = ctl.status(s.id)
    assert (st["changes"]["status"], st["scan"]["status"]) == ("dismissed", "rejected")
    ctl.submit(_data(state))  # a new proposal is allowed once nothing is pending
