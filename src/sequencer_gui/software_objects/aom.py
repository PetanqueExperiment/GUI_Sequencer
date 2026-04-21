from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

AOM_ID = "aom"


@dataclass(frozen=True)
class AomObject:
    id: str = AOM_ID
    display_name: str = "AOM"

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="amplitude",
                label="Amplitude",
                default=0.0,
                minimum=0.0,
                maximum=1.0,
                decimals=1,
                single_step=0.0001,
            ),
            AnalogParameterSpec(
                param_id="frequency",
                label="Frequency (MHz)",
                default=80.0,
                minimum=0.0,
                maximum=500.0,
                decimals=1,
                single_step=0.001,
            ),
        )
