"""Sample sequence shared by the remote-control tests."""

from __future__ import annotations

from sequencer_gui.domain.document import SequenceBlock, SequenceDocument


def sample_document() -> SequenceDocument:
    """Rows: 0 = AOM 'MOT', 1 = DDS 'Cooling', 2 = TTL 'Camera'.

    Blocks: 'Load' (2 cols, enabled), 'Off' (1 col, disabled), 'Image' (2 cols, enabled).
    """
    load = SequenceBlock(
        name="Load",
        enabled=True,
        cols=2,
        channels={(0, 0): True, (2, 1): True},
        delays_us={0: 1000.0, 1: 50.0},
        analog={(0, "amplitude", 0): 0.5, (0, "amplitude", 1): "ramp", (1, "frequency", 0): -12.0},
        col_labels=("load", "ramp"),
    )
    off = SequenceBlock(name="Off", enabled=False, cols=1, delays_us={0: 7.0})
    image = SequenceBlock(
        name="Image",
        enabled=True,
        cols=2,
        delays_us={0: 20.0, 1: 30.0},
        # DDS col 0 left empty (= hold), col 1 is a ramp on a device without ramp support.
        analog={(1, "frequency", 1): "ramp"},
        col_labels=("img", ""),
    )
    return SequenceDocument(
        rows=3,
        row_labels=("MOT", "Cooling", "Camera"),
        row_software=("aom", "dds", "ttl"),
        blocks=(load, off, image),
        static_rows=0,
    )
