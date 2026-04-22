from __future__ import annotations

from typing import Protocol

from sequencer_gui.domain.document import SequenceDocument
from sequencer_gui.domain.model import SequenceModel


class SequenceBackendProtocol(Protocol):
    def apply(self, model: SequenceModel) -> None:
        """Receive the merged enabled-blocks snapshot (channels, delays, row_software, sparse analog)."""
        ...

    def sync_sequence_snapshot(self, document: SequenceDocument, sequence_name: str) -> None:
        """Full multi-block document + name (e.g. same shape as a saved JSON file, for HERO or IPC)."""
        ...


class NoOpBackend:
    def sync_sequence_snapshot(self, document: SequenceDocument, sequence_name: str) -> None:
        del document, sequence_name

    def apply(self, model: SequenceModel) -> None:
        del model  # unused; placeholder for ArtiQ integration
