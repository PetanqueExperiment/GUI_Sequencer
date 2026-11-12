"""Read-only remote descriptions (``sequencer_gui.remote_control.describe``); no Qt needed."""

from __future__ import annotations

import json

import pytest

from sample_documents import sample_document
from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.remote_control.describe import (
    ScanConfig,
    describe_block,
    describe_complete,
    describe_devices,
    describe_overview,
    document_revision,
)

_NO_SCAN = ScanConfig(running=False, label="", repetitions=1, parameters=())


def test_overview_blocks_durations_and_start_columns() -> None:
    doc = sample_document()
    ov = describe_overview(doc, "C:/seq/test.json", run_sequence=True, scan=_NO_SCAN)
    assert ov["sequence_name"] == "test"
    assert [b["name"] for b in ov["blocks"]] == ["Load", "Off", "Image"]
    assert [b["duration_us"] for b in ov["blocks"]] == [1050.0, 7.0, 50.0]
    # Disabled block has no place in the Complete timeline and does not count in its duration.
    assert [b["complete_start_col"] for b in ov["blocks"]] == [0, None, 2]
    assert ov["complete_duration_us"] == 1100.0
    assert ov["cycle_rate_Hz"] == pytest.approx(1e6 / 1100.0)
    assert ov["run_sequence"] is True
    json.dumps(ov)


def test_block_stored_cells() -> None:
    res = describe_block(sample_document(), "x", "Load")
    assert [c["label"] for c in res["columns"]] == ["load", "ramp"]
    mot, cooling, camera = res["rows"]
    assert mot["on"] == [True, False]
    assert mot["params"]["amplitude"]["stored"] == [0.5, "ramp"]
    assert cooling["params"]["frequency"]["stored"] == [-12.0, "hold"]
    assert camera["on"] == [False, True]
    assert camera["params"] == {}
    json.dumps(res)


def test_block_ramp_on_dds_plays_default() -> None:
    res = describe_block(sample_document(), "x", "Image")
    # Same rule as SequenceModel.analog_value: ramp on a non-ramp device plays the default (0 MHz).
    assert res["rows"][1]["params"]["frequency"]["stored"] == ["hold", 0.0]


def test_complete_resolves_hold_across_blocks() -> None:
    res = describe_complete(sample_document(), "x")
    assert [c["label"] for c in res["columns"]] == ["load", "ramp", "img", ""]
    assert [s["name"] for s in res["block_spans"]] == ["Load", "Image"]
    freq = res["rows"][1]["params"]["frequency"]
    assert freq["stored"] == [-12.0, "hold", "hold", 0.0]
    # Hold keeps -12 MHz through the 'Image' block's first column.
    assert freq["resolved"] == [-12.0, -12.0, -12.0, 0.0]
    assert res["rows"][0]["params"]["amplitude"]["resolved"] == [0.5, "ramp", "ramp", "ramp"]
    json.dumps(res)


def test_block_addressing_by_index_and_errors() -> None:
    doc = sample_document()
    assert describe_block(doc, "x", "2")["block"]["name"] == "Image"
    with pytest.raises(ValueError, match="Unknown block 'Nope'.*0: 'Load'"):
        describe_block(doc, "x", "Nope")
    twin = SequenceDocument(
        rows=doc.rows,
        row_labels=doc.row_labels,
        row_software=doc.row_software,
        blocks=(doc.blocks[0], doc.blocks[0]),
        static_rows=0,
    )
    with pytest.raises(ValueError, match="Several blocks"):
        describe_block(twin, "x", "Load")


def test_revision_tracks_content() -> None:
    doc = sample_document()
    assert document_revision(doc, "x") == document_revision(sample_document(), "x")
    edited = doc.with_block(0, doc.blocks[0].with_delay_us(0, 999.0))
    assert document_revision(edited, "x") != document_revision(doc, "x")


def test_devices_lists_ranges() -> None:
    dev = describe_devices(sample_document())
    mot = dev["rows"][0]
    assert mot["device"] == "aom" and mot["ramp_allowed"] is True
    assert mot["params"][0]["param_id"] == "amplitude"
    assert (mot["params"][0]["minimum"], mot["params"][0]["maximum"]) == (0.0, 1.0)
    assert mot["params"][0]["default"] == "hold"
    assert dev["rows"][2]["params"] == []
    assert dev["static_devices"] == []
    json.dumps(dev)
