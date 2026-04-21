from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

TTL_ID = "ttl"


@dataclass(frozen=True)
class TtlObject:
    id: str = TTL_ID
    display_name: str = "TTL"

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return ()
