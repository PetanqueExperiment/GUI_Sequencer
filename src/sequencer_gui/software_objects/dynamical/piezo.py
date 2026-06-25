from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.domain.analog_stored import HOLD_SIGNAL
from sequencer_gui.software_objects.types import AnalogParameterSpec

PIEZO_ID = "piezo"


@dataclass(frozen=True)
class PiezoObject:
    id: str = PIEZO_ID
    display_name: str = "Piezo"

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="voltage",
                label="Voltage (V)",
                default=HOLD_SIGNAL,
                minimum=0.0,
                maximum=9.9,
                decimals=2,
                single_step=0.0001,
            ),
        )
