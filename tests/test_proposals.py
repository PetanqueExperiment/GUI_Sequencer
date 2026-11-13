"""AI proposals: parsing, checking against the sequence, applying a subset, scan check."""

from __future__ import annotations

import pytest

from sample_documents import sample_document
from sequencer_gui.domain.document import merge_blocks
from sequencer_gui.remote_control.proposals import (
    apply_changes,
    check_scan,
    parse_proposal,
    resolve_changes,
    scan_parameters,
)

# Complete timeline of the sample: c0 "load", c1 "ramp" (block Load), c2 "img", c3 "" (block Image).


def _proposal(changes=None, scan=None) -> dict:
    data = {"summary": "test", "base_revision": "abc"}
    if changes is not None:
        data["changes"] = changes
    if scan is not None:
        data["scan"] = scan
    return data


def test_parse_kinds_and_shape_errors() -> None:
    p = parse_proposal(_proposal([
        {"row": "Cooling", "param": "frequency", "column": "c2", "value": -15},
        {"row": "Camera", "column": "img", "on": True},
        {"column": "1", "delay_us": 60},
        {"row": "MOT", "param": "amplitude", "column": "c2", "value": "Ramp"},
    ]))
    assert [c.kind for c in p.changes] == ["value", "on", "delay", "value"]
    assert p.changes[3].value == "ramp"
    with pytest.raises(ValueError, match="exactly one of"):
        parse_proposal(_proposal([{"row": "MOT", "column": "c0", "on": True, "value": 1}]))
    with pytest.raises(ValueError, match="'on' must be true or false"):
        parse_proposal(_proposal([{"row": "MOT", "column": "c0", "on": 1}]))
    with pytest.raises(ValueError, match="needs 'changes', 'scan', or both"):
        parse_proposal(_proposal())
    with pytest.raises(ValueError, match="'repetitions' must be a positive integer"):
        parse_proposal(_proposal(scan={"label": "x", "repetitions": 0, "axes": [{}]}))


def test_resolve_shows_played_old_values() -> None:
    doc = sample_document()
    p = parse_proposal(_proposal([
        {"row": "Cooling", "param": "frequency", "column": "img", "value": -15},
        {"row": "Camera", "column": "c2", "on": True},
        {"column": "c1", "delay_us": 60},
    ]))
    r = resolve_changes(doc, p.changes)
    # c2 is a hold in the sample, so the old value is the -12 MHz carried over from block Load.
    assert [(x.what, x.old, x.new, x.unit) for x in r] == [
        ("Cooling c2", "-12", "-15", " MHz"),
        ("Camera c2", "off", "ON", ""),
        ("delay c1", "50", "60", " us"),
    ]
    assert (r[0].block_index, r[0].local_col) == (2, 0)  # block Image, its first column


def test_resolve_collects_all_errors() -> None:
    doc = sample_document()
    p = parse_proposal(_proposal([
        {"row": "Nope", "param": "frequency", "column": "c0", "value": 1},
        {"row": "MOT", "param": "amplitude", "column": "c0", "value": 1.5},
        {"row": "Cooling", "param": "frequency", "column": "c0", "value": "ramp"},
        {"row": "Cooling", "column": "c0", "on": True},
        {"column": "c9", "delay_us": 10},
        {"column": "c0", "delay_us": 0},
    ]))
    with pytest.raises(ValueError) as e:
        resolve_changes(doc, p.changes)
    msg = str(e.value)
    for expected in ("changes[0]: unknown row 'Nope'",
                     "changes[1]: MOT amplitude = 1.5 outside 0..1",
                     "changes[2]: row 'Cooling' (DDS) does not support ramp",
                     "changes[3]: row 'Cooling' (DDS) has no ON/OFF",
                     "changes[4]: unknown column 'c9'",
                     "changes[5]: delay 0 us outside"):
        assert expected in msg


def test_duplicate_cell_rejected() -> None:
    p = parse_proposal(_proposal([
        {"column": "c1", "delay_us": 60}, {"column": "ramp", "delay_us": 70},
    ]))
    with pytest.raises(ValueError, match=r"changes\[1\]: same cell as changes\[0\]"):
        resolve_changes(sample_document(), p.changes)


def test_apply_subset_only() -> None:
    doc = sample_document()
    p = parse_proposal(_proposal([
        {"row": "Cooling", "param": "frequency", "column": "c2", "value": -15},
        {"row": "Camera", "column": "c2", "on": True},
        {"column": "c1", "delay_us": 60},
    ]))
    r = resolve_changes(doc, p.changes)
    new = merge_blocks(apply_changes(doc, [r[0], r[2]]), enabled_only=True)
    assert new.analog_value(1, "frequency", 2) == -15.0
    assert new.channel(2, 2) is False  # change 2 not ticked
    assert new.delay_us(1) == 60.0
    # The disabled block is untouched and the original document unchanged.
    assert merge_blocks(doc, enabled_only=True).delay_us(1) == 50.0


def test_scan_check_and_index_form() -> None:
    doc = sample_document()
    p = parse_proposal(_proposal(scan={
        "label": "det_scan", "repetitions": 10, "reason": "find resonance",
        "axes": [{"device": "Cooling", "param": "frequency", "timestep": "c2", "values": [-14, -12, -10]},
                 {"device": "time", "param": "time", "timestep": "img", "values": [20, 40]}],
    }))
    assert scan_parameters(p.scan)[0].timestep_label == "2"
    sc = check_scan(doc, p.scan)
    assert (sc.points, sc.shots) == (6, 60)
    assert sc.axes[0] == ("Cooling c2", "-14, -12, -10", " MHz", "-12")
    assert sc.axes[1] == ("delay c2", "20, 40", " us", "20")
    # Each shot is 1100 us except the delay axis changes c2 (20 -> 40 us): 3 x 10 x (1100 + 1120) us.
    assert sc.duration_s == pytest.approx(3 * 10 * (1100 + 1120) * 1e-6)
    bad = parse_proposal(_proposal(scan={"label": "x", "repetitions": 1,
                                         "axes": [{"device": "Nope", "param": "frequency",
                                                   "timestep": "c0", "values": [1]}]}))
    with pytest.raises(ValueError, match="Unknown device row label 'Nope'"):
        check_scan(doc, bad.scan)
