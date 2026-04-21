"""Analog cell storage: explicit float or 'hold' (same resolved value as previous step)."""

from __future__ import annotations

from typing import Literal, Union

# JSON and domain sentinel for "keep same as previous step" (UI: "-").
ANALOG_HOLD = "hold"

AnalogStored = Union[float, Literal["hold"]]


def is_hold(v: AnalogStored) -> bool:
    return v == ANALOG_HOLD
