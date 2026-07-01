from __future__ import annotations

DEFAULT_STATIC_ROWS: int = 0


def default_static_labels(num_rows: int = DEFAULT_STATIC_ROWS) -> tuple[str, ...]:
    return ()


def default_static_software(num_rows: int = DEFAULT_STATIC_ROWS) -> tuple[str, ...]:
    return ()


def default_static_analog(
    num_rows: int = DEFAULT_STATIC_ROWS,
) -> dict[tuple[int, str], float]:
    """Default ``(row, 'amplitude')`` values for new sequences."""
    return {}
