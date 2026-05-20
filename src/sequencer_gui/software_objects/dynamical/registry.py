from __future__ import annotations

from dataclasses import dataclass

from sequencer_gui.software_objects.dynamical.RF_source import RF_SOURCE_ID, RfSourceObject
from sequencer_gui.software_objects.dynamical.aom import AOM_ID, AomObject
from sequencer_gui.software_objects.dynamical.current_source import (
    CURRENT_SOURCE_ID,
    CurrentSourceObject,
)
from sequencer_gui.software_objects.dynamical.dds import DDS_ID, DdsObject
from sequencer_gui.software_objects.protocol import SoftwareObject
from sequencer_gui.software_objects.dynamical.shutter import SHUTTER_ID, ShutterObject
from sequencer_gui.software_objects.dynamical.ttl import TTL_ID, TtlObject
from sequencer_gui.software_objects.types import AnalogParameterSpec

_OBJECTS: dict[str, SoftwareObject] = {}


def register(obj: SoftwareObject) -> None:
    oid = obj.id
    if oid in _OBJECTS:
        raise ValueError(f"Duplicate dynamical software object id: {oid!r}")
    _OBJECTS[oid] = obj


def iter_objects() -> tuple[SoftwareObject, ...]:
    return tuple(_OBJECTS[o] for o in CATALOG_ORDER if o in _OBJECTS)


@dataclass(frozen=True)
class _UnknownObject:
    id: str
    display_name: str

    @property
    def has_on_off(self) -> bool:
        return True

    @property
    def analog_parameters(self) -> tuple[AnalogParameterSpec, ...]:
        return ()


def get_object(object_id: str) -> SoftwareObject:
    if object_id in _OBJECTS:
        return _OBJECTS[object_id]
    return _UnknownObject(id=object_id, display_name=object_id)


CATALOG_ORDER: tuple[str, ...] = (
    AOM_ID,
    RF_SOURCE_ID,
    SHUTTER_ID,
    TTL_ID,
    DDS_ID,
    CURRENT_SOURCE_ID,
)


def _build_registry() -> None:
    register(AomObject())
    register(RfSourceObject())
    register(ShutterObject())
    register(TtlObject())
    register(DdsObject())
    register(CurrentSourceObject())


_build_registry()
