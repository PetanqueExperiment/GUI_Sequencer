from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Sequence

_SETTINGS_ROW_LABELS = "row_labels"
_SETTINGS_WINDOW_GEOMETRY_B64 = "window_geometry_b64"
_SETTINGS_LAST_SEQUENCE_PATH = "last_sequence_path"


def settings_path() -> Path:
    return Path.home() / ".sequencer_gui" / "settings.json"


def _load_settings_dict() -> dict[str, Any]:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def _save_settings_dict(data: dict[str, Any]) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def load_row_labels(num_rows: int) -> tuple[str, ...]:
    """Load saved row labels, or default \"1\"..\"N\"."""
    data = _load_settings_dict()
    raw = data.get(_SETTINGS_ROW_LABELS)
    if not isinstance(raw, list):
        return tuple(str(i + 1) for i in range(num_rows))
    return tuple(str(raw[i]) if i < len(raw) else str(i + 1) for i in range(num_rows))


def save_row_labels(labels: Sequence[str]) -> None:
    data = _load_settings_dict()
    data[_SETTINGS_ROW_LABELS] = list(labels)
    _save_settings_dict(data)


def load_window_geometry() -> bytes | None:
    """Return saved QWidget geometry bytes for restoreGeometry, or None if missing/invalid."""
    data = _load_settings_dict()
    b64 = data.get(_SETTINGS_WINDOW_GEOMETRY_B64)
    if not isinstance(b64, str) or not b64.strip():
        return None
    try:
        return base64.b64decode(b64.encode("ascii"))
    except (ValueError, OSError):
        return None


def save_window_geometry(geometry: bytes) -> None:
    data = _load_settings_dict()
    data[_SETTINGS_WINDOW_GEOMETRY_B64] = base64.b64encode(geometry).decode("ascii")
    _save_settings_dict(data)


def load_last_sequence_path() -> str | None:
    """Absolute path to the last successfully saved sequence file, or None."""
    data = _load_settings_dict()
    p = data.get(_SETTINGS_LAST_SEQUENCE_PATH)
    if isinstance(p, str) and p.strip():
        return p
    return None


def save_last_sequence_path(path: str | None) -> None:
    """Remember the path used for Save (canonical absolute path). Pass None to clear."""
    data = _load_settings_dict()
    if path and str(path).strip():
        data[_SETTINGS_LAST_SEQUENCE_PATH] = str(Path(path).resolve())
    else:
        data.pop(_SETTINGS_LAST_SEQUENCE_PATH, None)
    _save_settings_dict(data)
