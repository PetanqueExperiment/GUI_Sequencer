from __future__ import annotations

"""Backward-compatible re-exports for dynamical (timeline) software objects."""

from sequencer_gui.software_objects.dynamical.registry import (
    AOM_ID,
    CATALOG_ORDER,
    get_object,
    iter_objects,
    register,
)

__all__ = [
    "AOM_ID",
    "CATALOG_ORDER",
    "get_object",
    "iter_objects",
    "register",
]
