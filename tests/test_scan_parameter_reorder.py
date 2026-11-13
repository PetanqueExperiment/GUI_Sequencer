"""Reordering scan axes (drag of the Scan panel cards): state logic."""

from __future__ import annotations

import pytest

from sample_documents import sample_document
from sequencer_gui.app.state import ScanParameter, SequenceAppState
from sequencer_gui.scan_plan import build_scan_tags


@pytest.fixture()
def state(app):
    s = SequenceAppState(document=sample_document(), sequence_name="seq")
    s.set_scan_plan(
        "lbl",
        1,
        (
            ScanParameter("Cooling", "frequency", "c1", "1, 2"),
            ScanParameter("Cooling", "frequency", "c2", "10, 20, 30"),
            ScanParameter("time", "time", "c1", "5"),
        ),
    )
    return s


def test_permutation_reorders_axes_and_notifies(state) -> None:
    a, b, c = state.scan_parameters
    seen = []
    state.scan_parameters_changed.connect(lambda: seen.append(True))
    state.apply_scan_parameter_permutation([2, 0, 1])
    assert state.scan_parameters == (c, a, b)
    assert seen == [True]


def test_first_axis_is_the_outer_loop(state) -> None:
    before = build_scan_tags(state.scan_parameters[:2], 1)
    state.apply_scan_parameter_permutation([1, 0, 2])
    after = build_scan_tags(state.scan_parameters[:2], 1)
    assert len(before) == len(after) == 6
    assert before != after and sorted(len(t) for t in before) == sorted(len(t) for t in after)


@pytest.mark.parametrize("bad", [[0, 1], [0, 0, 1], [0, 1, 3]])
def test_invalid_permutation_refused(state, bad) -> None:
    before = state.scan_parameters
    with pytest.raises(ValueError):
        state.apply_scan_parameter_permutation(bad)
    assert state.scan_parameters == before


def test_refused_while_scan_running(state) -> None:
    before = state.scan_parameters
    state.set_scan_running(True)
    with pytest.raises(RuntimeError):
        state.apply_scan_parameter_permutation([1, 0, 2])
    assert state.scan_parameters == before

