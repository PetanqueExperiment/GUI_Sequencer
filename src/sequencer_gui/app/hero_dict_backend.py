"""Backend that keeps a :class:`sequencer_gui.sequencer_hero.Sequencer_HERO` snapshot in sync with the GUI."""

from __future__ import annotations

from typing import Any, Protocol

from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.domain.model import SequenceModel
from sequencer_gui.sequence_io import live_sequence_file_dict


class _SequenceDataHost(Protocol):
    """:class:`sequencer_gui.sequencer_hero.Sequencer_HERO` and compatible hosts."""

    def set_sequence_data(self, data: dict[str, Any]) -> None: ...


class HeroDictBackend:
    """
    On each sequence change, calls ``host.set_sequence_data(...)`` with the same structure as
    :func:`sequencer_gui.sequence_io.live_sequence_file_dict` (format, version, name, document).
    The merged-model :meth:`apply` is a no-op; use this in the same process as the HERO.
    """

    def __init__(self, host: _SequenceDataHost) -> None:
        self._host = host

    def sync_sequence_snapshot(self, document: SequenceDocument, sequence_name: str) -> None:
        self._host.set_sequence_data(live_sequence_file_dict(sequence_name, document))

    def apply(self, model: SequenceModel) -> None:
        del model
