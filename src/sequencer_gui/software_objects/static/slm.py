from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.types import AnalogParameterSpec

SLM_ID = "slm"


# Default device / HERO instance name when adding an SLM row (editable label).
DEFAULT_HERO_NAME = "SLM_Controller"

# ``param_id`` values must match the SLM Controller HERO (``sequencer_apply_static``):
# ``grating_x`` / ``grating_y`` or one of ``SLMGUI.aberration_label_list``.
GRATING_PARAMS: tuple[tuple[str, str], ...] = (
    ("grating_x", "Grating X (µm)"),
    ("grating_y", "Grating Y (µm)"),
)

ZERNIKE_PARAMS: tuple[tuple[str, str], ...] = (
    ("defocus", "Defocus"),
    ("asti 0", "Astigmatism 0°"),
    ("asti 45", "Astigmatism 45°"),
    ("coma 0", "Coma 0°"),
    ("coma 90", "Coma 90°"),
    ("primary spherical", "Primary spherical"),
    ("trefoil 0", "Trefoil 0°"),
    ("trefoil 90", "Trefoil 90°"),
    ("asti 2nd 0", "Astigmatism 2nd 0°"),
    ("asti 2nd 45", "Astigmatism 2nd 45°"),
    ("coma 2nd 0", "Coma 2nd 0°"),
    ("coma 2nd 90", "Coma 2nd 90°"),
    ("2nd spherical", "2nd spherical"),
    ("trefoil 2nd 0", "Trefoil 2nd 0°"),
    ("trefoil 2nd 90", "Trefoil 2nd 90°"),
)


@dataclass(frozen=True)
class SlmObject:
    """Between-shot SLM: grating shift and Zernike coefficients for the full sequence.

    Always remote: GUI applies values via ``RemoteHERO(...).sequencer_apply_static``.
    Zernike coefficients only reach the SLM while "Zernike correction" is checked
    in the SLM Controller GUI.
    """

    id: str = SLM_ID
    display_name: str = "SLM"
    default_hero_name: str | None = DEFAULT_HERO_NAME
    # The HERO echoes the stored float exactly.
    apply_abs_tol: float = 1e-6

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        grating = tuple(
            AnalogParameterSpec(
                param_id=pid,
                label=label,
                default=0.0,
                minimum=-1000.0,
                maximum=1000.0,
                decimals=3,
            )
            for pid, label in GRATING_PARAMS
        )
        zernike = tuple(
            AnalogParameterSpec(
                param_id=pid,
                label=label,
                default=0.0,
                minimum=-10.0,
                maximum=10.0,
                decimals=4,
            )
            for pid, label in ZERNIKE_PARAMS
        )
        return grating + zernike
