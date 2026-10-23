from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.domain.analog_stored import HOLD_SIGNAL
from sequencer_gui.software_objects.types import AnalogParameterSpec

RF_SOURCE_ID = "rf_source"


@dataclass(frozen=True)
class RfSourceObject:
    id: str = RF_SOURCE_ID
    display_name: str = "RF Source"

    @property
    def has_on_off(self) -> bool:
        return True

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="amplitude",
                label="Amplitude",
                default=HOLD_SIGNAL,
                minimum=0.0,
                maximum=1.0,
                decimals=3,
            ),
            AnalogParameterSpec(
                param_id="frequency",
                label="Frequency (MHz)",
                default=HOLD_SIGNAL,
                minimum=1.0,
                maximum=400.0,
                decimals=4,
            ),
        )
