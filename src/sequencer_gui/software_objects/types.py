from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnalogParameterSpec:
    param_id: str
    label: str
    default: float = 0.0
    minimum: float = -1000.0
    maximum: float = 1000.0
    decimals: int = 4
    single_step: float = 0.0001
