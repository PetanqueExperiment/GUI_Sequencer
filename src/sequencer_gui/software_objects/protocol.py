from __future__ import annotations

from typing import Protocol

from sequencer_gui.software_objects.types import AnalogParameterSpec


class SoftwareObject(Protocol):
    id: str
    display_name: str

    @property
    def has_on_off(self) -> bool:
        """Per time-step digital on/off (channel strip). False for devices that are analog-only."""
        ...

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        ...
