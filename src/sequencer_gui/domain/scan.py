"""Scan configuration as shown in the Scan panel (no Qt)."""

from __future__ import annotations

from typing import NamedTuple


class ScanParameter(NamedTuple):
    """One scanned axis: device row label (or time/t for delay), param id, timestep label, values."""

    device_label: str
    param_id: str
    timestep_label: str
    values_text: str


class ScanPlan(NamedTuple):
    """Content of the Scan panel: label, shots per scan point, and the scanned axes."""

    label: str
    repetitions: int
    parameters: tuple[ScanParameter, ...]

    def is_empty(self) -> bool:
        """True when the panel holds nothing worth saving (no label and no axis)."""
        return not self.label.strip() and not self.parameters
