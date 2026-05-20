from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

SHUTTER_ID = "shutter"


@dataclass(frozen=True)
class ShutterObject:
    id: str = SHUTTER_ID
    display_name: str = "Shutter"

    @property
    def has_on_off(self) -> bool:
        return True

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return ()
