"""Scan panel content saved in / loaded from the sequence JSON file."""

from __future__ import annotations

import json

import pytest

from sample_documents import sample_document
from sequencer_gui.domain.scan import ScanParameter, ScanPlan
from sequencer_gui.pycam_repository import save_scan_sequence_snapshot
from sequencer_gui.sequence_io import (
    SequenceFileError,
    document_to_payload,
    live_sequence_file_dict,
    load_sequence,
    load_sequence_file,
    save_sequence,
    scan_from_payload,
    scan_to_payload,
)

SCAN = ScanPlan(
    label="ramsey_detuning",
    repetitions=20,
    parameters=(
        ScanParameter("Tweezer AOM", "frequency", "Ramsey", "1, 2.5, 3"),
        ScanParameter("time", "time", "Wait", "10, 20"),
    ),
)


def _loaded_without_scan(tmp_path):
    """Payload of the sample document after a plain save / load (the loader may add default rows)."""
    path = tmp_path / "reference.json"
    save_sequence(path, "seq", sample_document())
    return document_to_payload(load_sequence_file(path).document)


def _rewrite_scan(path, scan_section) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["scan"] = scan_section
    path.write_text(json.dumps(data), encoding="utf-8")


def test_scan_round_trip(tmp_path):
    path = tmp_path / "seq.json"
    document = sample_document()
    save_sequence(path, "seq", document, SCAN)

    loaded = load_sequence_file(path)
    assert loaded.scan == SCAN
    assert loaded.scan_error is None
    assert loaded.name == "seq"
    assert document_to_payload(loaded.document) == _loaded_without_scan(tmp_path)


def test_file_without_scan_loads_with_no_scan(tmp_path):
    path = tmp_path / "seq.json"
    save_sequence(path, "seq", sample_document())

    assert "scan" not in json.loads(path.read_text(encoding="utf-8"))
    loaded = load_sequence_file(path)
    assert loaded.scan is None
    assert loaded.scan_error is None


def test_empty_scan_panel_is_not_written(tmp_path):
    path = tmp_path / "seq.json"
    save_sequence(path, "seq", sample_document(), ScanPlan("", 5, ()))
    assert "scan" not in json.loads(path.read_text(encoding="utf-8"))


def test_label_only_scan_is_written(tmp_path):
    path = tmp_path / "seq.json"
    plan = ScanPlan("lifetime", 3, ())
    save_sequence(path, "seq", sample_document(), plan)
    assert load_sequence_file(path).scan == plan


def test_load_sequence_keeps_its_signature(tmp_path):
    path = tmp_path / "seq.json"
    save_sequence(path, "seq", sample_document(), SCAN)
    name, document = load_sequence(path)
    assert name == "seq"
    assert document_to_payload(document) == _loaded_without_scan(tmp_path)


def test_host_dict_and_document_are_unchanged_by_the_scan(tmp_path):
    """The scan is only in the file: what goes to the host / the revision hash has no scan."""
    document = sample_document()
    path = tmp_path / "seq.json"
    save_sequence(path, "seq", document, SCAN)

    on_disk = json.loads(path.read_text(encoding="utf-8"))
    host = live_sequence_file_dict("seq", document)
    assert "scan" not in host
    assert {k: v for k, v in on_disk.items() if k != "scan"} == json.loads(json.dumps(host))


@pytest.mark.parametrize(
    "bad_scan",
    [
        "not an object",
        {"label": 3, "repetitions": 1, "axes": []},
        {"label": "x", "repetitions": 0, "axes": []},
        {"label": "x", "repetitions": "many", "axes": []},
        {"label": "x", "repetitions": True, "axes": []},
        {"label": "x", "repetitions": 1, "axes": "none"},
        {"label": "x", "repetitions": 1, "axes": ["axis"]},
        {"label": "x", "repetitions": 1, "axes": [{"device": 1}]},
    ],
)
def test_malformed_scan_still_loads_the_sequence(tmp_path, bad_scan):
    path = tmp_path / "seq.json"
    save_sequence(path, "seq", sample_document(), SCAN)
    _rewrite_scan(path, bad_scan)

    loaded = load_sequence_file(path)
    assert loaded.scan is None
    assert loaded.scan_error
    assert document_to_payload(loaded.document) == _loaded_without_scan(tmp_path)
    with pytest.raises(SequenceFileError):
        scan_from_payload(bad_scan)


def test_missing_scan_fields_use_defaults():
    plan = scan_from_payload({"axes": [{"device": "AOM"}]})
    assert plan == ScanPlan("", 1, (ScanParameter("AOM", "", "", ""),))


def test_payload_shape():
    assert scan_to_payload(SCAN) == {
        "label": "ramsey_detuning",
        "repetitions": 20,
        "axes": [
            {"device": "Tweezer AOM", "param": "frequency", "timestep": "Ramsey",
             "values": "1, 2.5, 3"},
            {"device": "time", "param": "time", "timestep": "Wait", "values": "10, 20"},
        ],
    }


def test_scan_snapshot_holds_the_scan(tmp_path):
    path = save_scan_sequence_snapshot(
        "ramsey_detuning", "seq", sample_document(), data_root=tmp_path, scan=SCAN
    )
    assert load_sequence_file(path).scan == SCAN


def test_state_scan_plan_round_trip(app):
    from sequencer_gui.app.state import SequenceAppState

    state = SequenceAppState(document=sample_document())
    assert state.scan_plan.is_empty()
    state.set_scan_plan(SCAN.label, SCAN.repetitions, SCAN.parameters)
    assert state.scan_plan == SCAN
