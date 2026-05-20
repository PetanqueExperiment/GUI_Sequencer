from __future__ import annotations

from sequencer_gui.software_objects.dynamical.registry import (
    AOM_ID,
    CATALOG_ORDER,
    get_object,
    iter_objects,
    register,
)
from sequencer_gui.software_objects.static.registry import (
    CATALOG_ORDER as STATIC_CATALOG_ORDER,
    get_object as get_static_object,
    iter_objects as iter_static_objects,
    register as register_static,
)
from sequencer_gui.software_objects.types import AnalogParameterSpec

CATALOG: tuple[str, ...] = CATALOG_ORDER
DEFAULT_ON_OBJECT = AOM_ID

__all__ = [
    "AnalogParameterSpec",
    "CATALOG",
    "CATALOG_ORDER",
    "DEFAULT_ON_OBJECT",
    "STATIC_CATALOG_ORDER",
    "get_object",
    "get_static_object",
    "iter_objects",
    "iter_static_objects",
    "register",
    "register_static",
]
