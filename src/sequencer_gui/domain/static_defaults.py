from __future__ import annotations

from sequencer_gui.software_objects.static.voa import VOA_ID

DEFAULT_STATIC_ROWS: int = 10

# Labels match Sequences/repository/EXPERIMENT_PARAMETERS.py (VOA_MOT_*, VOA_IMG_*).
_DEFAULT_STATIC_LABELS: tuple[str, ...] = (
    "VOA MOT X1",
    "VOA MOT X2",
    "VOA MOT Y1",
    "VOA MOT Y2",
    "VOA MOT Z1",
    "VOA MOT Z2",
    "VOA IMG 1",
    "VOA IMG 2",
    "VOA IMG 3",
    "VOA IMG 4",
)

# Lab defaults (V); same order as labels — matches Sequences/EXPERIMENT_PARAMETERS.py.
_DEFAULT_STATIC_AMPLITUDES_V: tuple[float, ...] = (
    0.0,
    2.2,
    1.6,
    1.5,
    1.9,
    1.5,
    0.0,
    0.0,
    0.0,
    0.0,
)


def default_static_labels(num_rows: int = DEFAULT_STATIC_ROWS) -> tuple[str, ...]:
    if num_rows <= len(_DEFAULT_STATIC_LABELS):
        return _DEFAULT_STATIC_LABELS[:num_rows]
    extra = tuple(f"VOA {i + 1}" for i in range(len(_DEFAULT_STATIC_LABELS), num_rows))
    return _DEFAULT_STATIC_LABELS + extra


def default_static_software(num_rows: int = DEFAULT_STATIC_ROWS) -> tuple[str, ...]:
    return tuple(VOA_ID for _ in range(num_rows))


def default_static_analog(
    num_rows: int = DEFAULT_STATIC_ROWS,
) -> dict[tuple[int, str], float]:
    """Default ``(row, 'amplitude')`` values for new sequences."""
    n = min(num_rows, len(_DEFAULT_STATIC_AMPLITUDES_V))
    return {(row, "amplitude"): _DEFAULT_STATIC_AMPLITUDES_V[row] for row in range(n)}
