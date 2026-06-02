from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

VOA_ID = "voa"


@dataclass(frozen=True)
class VoaObject:
    """Between-shot VOA: one amplitude (V) for the full sequence (not per timeline step)."""

    id: str = VOA_ID
    display_name: str = "VOA"

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="amplitude",
                label="Amplitude (V)",
                default=0.0,
                minimum=0.0,
                maximum=5.0,
                decimals=3,
                single_step=0.01,
            ),
        )
