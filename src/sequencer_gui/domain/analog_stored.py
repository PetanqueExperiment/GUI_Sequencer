"""Analog cell storage: explicit float or 'hold' (same resolved value as previous step)."""

from __future__ import annotations

from typing import Literal, Union

# JSON and domain sentinel for "keep same as previous step" (UI: "-").
ANALOG_HOLD = "hold"

# When a float is required (e.g. spec default, HERO API) with the same meaning as hold.
HOLD_SIGNAL = -9999.0

AnalogStored = Union[float, Literal["hold"]]


def is_hold(v: AnalogStored) -> bool:
    return v == ANALOG_HOLD


def is_hold_signal(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return float(v) == float(HOLD_SIGNAL)
    return False


def is_holdish(v: AnalogStored) -> bool:
    """String ``hold`` or the float :data:`HOLD_SIGNAL` (same on-screen and JSON ``hold`` after normalize)."""
    return is_hold(v) or is_hold_signal(v)
