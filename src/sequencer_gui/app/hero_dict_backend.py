"""Backend that keeps a host object's ``dict`` in sync with the GUI (same shape as a saved .json file)."""

from __future__ import annotations

from typing import Any, Protocol

from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.sequence_io import live_sequence_file_dict


class _DictHost(Protocol):
    """Any object with a ``dict`` attribute (e.g. :class:`sequencer_gui.sequencer_hero.Sequencer_HERO`)."""

    dict: dict[str, Any]


class HeroDictBackend:
    """
    On each sequence change, sets ``host.dict`` to the same structure as
    :func:`sequencer_gui.sequence_io.live_sequence_file_dict` (format, version, name, document).
    The merged-model :meth:`apply` is a no-op; use this in the same process as the HERO.
    """

    def __init__(self, host: _DictHost) -> None:
        self._host = host

    def sync_sequence_snapshot(self, document: SequenceDocument, sequence_name: str) -> None:
        self._host.dict = live_sequence_file_dict(sequence_name, document)

    def apply(self, model: SequenceModel) -> None:
        del model
