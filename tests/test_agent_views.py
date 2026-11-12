"""Compact text views for agents (``sequencer_gui.remote_control.agent_views``)."""

from __future__ import annotations

import pytest

from sample_documents import sample_document
from sequencer_gui.remote_control.agent_views import (
    _ranges,
    format_devices,
    format_overview,
    format_timeline,
)
from sequencer_gui.remote_control.describe import (
    ScanConfig,
    describe_block,
    describe_complete,
    describe_devices,
    describe_overview,
)


def test_ranges() -> None:
    assert _ranges([0, 1, 2, 5, 7, 8]) == "c0-2, c5, c7-8"
    assert _ranges([]) == ""


def test_complete_view_lists_changes_only() -> None:
    text = format_timeline(describe_complete(sample_document(), "x"))
    assert 'block "Load": c0 "load" 1000 us | c1 "ramp" 50 us' in text
    assert 'block "Image": c2 "img" 20 us | c3 "" 30 us' in text
    assert "    amplitude: c0=0.5, c1=ramp" in text
    # DDS: -12 MHz set at c0, then hold until the 0 MHz (ramp on a DDS plays the default) at c3.
    assert "    frequency: c0=-12, c3=0" in text
    assert '[2] "Camera" ttl\n    on: c1' in text
    assert "Unused rows" not in text


def test_block_view_flags_hold_at_start() -> None:
    text = format_timeline(describe_block(sample_document(), "x", "Image"))
    assert text.startswith('Block 2 "Image", enabled, block-local columns')
    assert "frequency: c1=0 (c0 holds the value from the previous block)" in text
    # MOT and Camera do nothing in this block.
    assert 'Unused rows (never ON, no value set): [0] "MOT", [2] "Camera"' in text


def test_row_filter() -> None:
    complete = describe_complete(sample_document(), "x")
    text = format_timeline(complete, rows=["Cooling", "2"])
    assert '"MOT"' not in text and '"Cooling"' in text and '"Camera"' in text
    with pytest.raises(ValueError, match="Unknown rows \\['Nope'\\]"):
        format_timeline(complete, rows=["Nope"])


def test_overview_and_devices_text() -> None:
    scan = ScanConfig(
        running=False,
        label="detuning_scan",
        repetitions=5,
        parameters=(
            {"device_label": "Cooling", "param_id": "frequency", "timestep_label": "load",
             "values_text": "-14, -12, -10"},
        ),
    )
    ov = format_overview(describe_overview(sample_document(), "x", run_sequence=False, scan=scan))
    assert '1  "Off"  DISABLED  1 cols  7 us  not played' in ov
    assert 'timestep "load", values [-14, -12, -10]' in ov
    dev = format_devices(describe_devices(sample_document()))
    assert '[0] "MOT" aom (ON/OFF, ramp allowed): amplitude "Amplitude" range 0..1' in dev
    assert '[2] "Camera" ttl (ON/OFF): no analog parameters' in dev
