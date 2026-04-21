from __future__ import annotations

from typing import Protocol

from sequencer_gui.domain.model import SequenceModel


class SequenceBackendProtocol(Protocol):
    def apply(self, model: SequenceModel) -> None:
        """Receive the current sequence snapshot (channels, delays, row_software, sparse analog)."""
        ...


class NoOpBackend:
    def apply(self, model: SequenceModel) -> None:
        del model  # unused; placeholder for ArtiQ integration
