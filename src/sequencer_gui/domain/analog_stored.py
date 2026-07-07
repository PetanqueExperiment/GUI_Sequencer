"""Analog cell storage: explicit float, 'hold' (previous step), or 'ramp' (ramp signal)."""

from __future__ import annotations

from typing import Literal, Union

# JSON and domain sentinel for "keep same as previous step" (UI: "-").
ANALOG_HOLD = "hold"

# When a float is required (e.g. spec default, HERO API) with the same meaning as hold.
HOLD_SIGNAL = -9999.0

# JSON and domain sentinel for ramp (UI: "ramp").
ANALOG_RAMP = "ramp"

# When a float is required (e.g. spec minimum, HERO API) with the same meaning as ramp.
RAMP_SIGNAL = -9998.0

# Device software ids that accept the ramp sentinel in the GUI (see ``ramp_applies_to_software``).
RAMP_DEVICE_IDS = frozenset({"aom", "piezo"})

AnalogStored = Union[float, Literal["hold", "ramp"]]


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


def is_ramp(v: AnalogStored) -> bool:
    return v == ANALOG_RAMP


def is_ramp_signal(v: object) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return float(v) == float(RAMP_SIGNAL)
    return False


def is_rampish(v: AnalogStored) -> bool:
    """String ``ramp`` or the float :data:`RAMP_SIGNAL` (same on-screen and JSON ``ramp`` after normalize)."""
    return is_ramp(v) or is_ramp_signal(v)


def ramp_applies_to_software(software_id: str) -> bool:
    return software_id in RAMP_DEVICE_IDS


def normalize_analog_stored(value: AnalogStored) -> AnalogStored:
    if is_holdish(value):
        return ANALOG_HOLD
    if is_ramp(value):
        return ANALOG_RAMP
    return float(value)  # type: ignore[arg-type]
