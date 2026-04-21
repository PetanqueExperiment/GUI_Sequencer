from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.aom import AOM_ID, AomObject
from sequencer_gui.software_objects.dds import DDS_ID, DdsObject
from sequencer_gui.software_objects.protocol import SoftwareObject
from sequencer_gui.software_objects.shutter import SHUTTER_ID, ShutterObject
from sequencer_gui.software_objects.types import AnalogParameterSpec

_OBJECTS: dict[str, SoftwareObject] = {}


def register(obj: SoftwareObject) -> None:
    oid = obj.id
    if oid in _OBJECTS:
        raise ValueError(f"Duplicate software object id: {oid!r}")
    _OBJECTS[oid] = obj


def iter_objects() -> tuple[SoftwareObject, ...]:
    return tuple(_OBJECTS[o] for o in CATALOG_ORDER if o in _OBJECTS)


@dataclass(frozen=True)
class _UnknownObject:
    id: str
    display_name: str

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return ()


def get_object(object_id: str) -> SoftwareObject:
    if object_id in _OBJECTS:
        return _OBJECTS[object_id]
    return _UnknownObject(id=object_id, display_name=object_id)


CATALOG_ORDER: tuple[str, ...] = (
    AOM_ID,
    SHUTTER_ID,
    DDS_ID,
)


def _build_registry() -> None:
    register(AomObject())
    register(ShutterObject())
    register(DdsObject())


_build_registry()
