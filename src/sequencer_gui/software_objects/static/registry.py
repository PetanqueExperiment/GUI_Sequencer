from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.protocol import SoftwareObject
from sequencer_gui.software_objects.static.voa import VOA_ID, VoaObject
from sequencer_gui.software_objects.static.waveplate import WAVEPLATE_ID, WaveplateObject
from sequencer_gui.software_objects.types import AnalogParameterSpec

_OBJECTS: dict[str, SoftwareObject] = {}


def register(obj: SoftwareObject) -> None:
    oid = obj.id
    if oid in _OBJECTS:
        raise ValueError(f"Duplicate static software object id: {oid!r}")
    _OBJECTS[oid] = obj


def iter_objects() -> tuple[SoftwareObject, ...]:
    return tuple(_OBJECTS[o] for o in CATALOG_ORDER if o in _OBJECTS)


@dataclass(frozen=True)
class _UnknownObject:
    id: str
    display_name: str
    default_hero_name: str | None = None
    apply_abs_tol: float = 1e-6

    @property
    def has_on_off(self) -> bool:
        return False

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return ()


def get_object(object_id: str) -> SoftwareObject:
    if object_id in _OBJECTS:
        return _OBJECTS[object_id]
    return _UnknownObject(id=object_id, display_name=object_id)


def default_hero_name_for(object_id: str) -> str | None:
    """Default remote HERO instance name for a static type, or ``None`` if local-only."""
    raw = getattr(get_object(object_id), "default_hero_name", None)
    if raw is None:
        return None
    name = str(raw).strip()
    return name or None


def is_remote_static(object_id: str) -> bool:
    """True when this static type always talks to a remote HERO (e.g. waveplate)."""
    return default_hero_name_for(object_id) is not None


def apply_abs_tol_for(object_id: str) -> float:
    """Absolute echo tolerance for remote apply; falls back to ``1e-6``."""
    raw = getattr(get_object(object_id), "apply_abs_tol", None)
    try:
        tol = float(raw) if raw is not None else 1e-6
    except (TypeError, ValueError):
        return 1e-6
    return tol if tol >= 0.0 else 1e-6


CATALOG_ORDER: tuple[str, ...] = (VOA_ID, WAVEPLATE_ID)


def _build_registry() -> None:
    register(VoaObject())
    register(WaveplateObject())


_build_registry()
