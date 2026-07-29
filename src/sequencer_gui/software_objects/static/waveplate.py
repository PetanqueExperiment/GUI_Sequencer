from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

WAVEPLATE_ID = "waveplate"


# Default device / HERO instance name when adding a waveplate row (editable label).
DEFAULT_HERO_NAME = "Waveplate_HERO"


@dataclass(frozen=True)
class WaveplateObject:
    """Between-shot waveplate: one angle (°) for the full sequence (not per timeline step).

    Always remote: GUI applies values via ``RemoteHERO(...).sequencer_apply_static``.
    """

    id: str = WAVEPLATE_ID
    display_name: str = "Waveplate"
    default_hero_name: str | None = DEFAULT_HERO_NAME
    # Absolute tolerance when comparing echoed apply value to the sent value.
    apply_abs_tol: float = 0.02

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return (
            AnalogParameterSpec(
                param_id="angle",
                label="Angle (°)",
                default=0.00,
                minimum=0.00,
                maximum=359.99,
                decimals=2,
            ),
        )
