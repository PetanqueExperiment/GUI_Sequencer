from __future__ import annotations

from sequencer_gui.software_objects.aom import AOM_ID
from sequencer_gui.software_objects.registry import (
    CATALOG_ORDER,
    get_object,
    iter_objects,
    register,
)
from sequencer_gui.software_objects.types import AnalogParameterSpec

CATALOG: tuple[str, ...] = CATALOG_ORDER
DEFAULT_ON_OBJECT = AOM_ID

__all__ = [
    "AnalogParameterSpec",
    "CATALOG",
    "CATALOG_ORDER",
    "DEFAULT_ON_OBJECT",
    "get_object",
    "iter_objects",
    "register",
]
