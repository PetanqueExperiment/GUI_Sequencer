from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.domain.analog_stored import HOLD_SIGNAL
from sequencer_gui.software_objects.types import AnalogParameterSpec

CURRENT_SOURCE_ID = "current_source"


@dataclass(frozen=True)
class CurrentSourceObject:
    id: str = CURRENT_SOURCE_ID
    display_name: str = "Current Source"

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="current",
                label="Current (A)",
                default=HOLD_SIGNAL,
                minimum=0.0,
                maximum=9.99,
                decimals=3,
                single_step=0.1,
            ),
        )
