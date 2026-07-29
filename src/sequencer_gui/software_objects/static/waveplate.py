from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

WAVEPLATE_ID = "waveplate"


@dataclass(frozen=True)
class WaveplateObject:
    """Between-shot waveplate: one angle (°) for the full sequence (not per timeline step)."""

    id: str = WAVEPLATE_ID
    display_name: str = "Waveplate"

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="angle",
                label="Angle (°)",
                default=0.0,
                minimum=0.0,
                maximum=360.0,
                decimals=1
            ),
        )
