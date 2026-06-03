from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.domain.analog_stored import HOLD_SIGNAL
from sequencer_gui.software_objects.types import AnalogParameterSpec

VOA_ID = "voa"


@dataclass(frozen=True)
class VoaObject:
    id: str = VOA_ID
    display_name: str = "VOA"

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="attenuation",
                label="Attenuation (V)",
                default=HOLD_SIGNAL,
                minimum=0.0,
                maximum=5.0,
                decimals=1,
                single_step=0.0001,
            ),
        )
