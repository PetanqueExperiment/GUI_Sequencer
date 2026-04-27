from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

DDS_ID = "dds"


@dataclass(frozen=True)
class DdsObject:
    id: str = DDS_ID
    display_name: str = "DDS"

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="frequency",
                label="Detuning (MHz)",
                default=0.0,
                minimum=-1000.0,
                maximum=1000.0,
                decimals=1,
                single_step=0.001,
            ),
        )
