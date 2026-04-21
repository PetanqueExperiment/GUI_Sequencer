from __future__ import annotations

import json
from pathlib import Path
from typing import Sequence


def settings_path() -> Path:
    return Path.home() / ".sequencer_gui" / "settings.json"


def load_row_labels(num_rows: int) -> tuple[str, ...]:
    """Load saved row labels, or default \"1\"..\"N\"."""
    path = settings_path()
    if not path.exists():
        return tuple(str(i + 1) for i in range(num_rows))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        raw = data.get("row_labels")
        if not isinstance(raw, list):
            return tuple(str(i + 1) for i in range(num_rows))
        return tuple(
            str(raw[i]) if i < len(raw) else str(i + 1) for i in range(num_rows)
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return tuple(str(i + 1) for i in range(num_rows))


def save_row_labels(labels: Sequence[str]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"row_labels": list(labels)}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
