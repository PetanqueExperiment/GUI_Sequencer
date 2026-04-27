from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass


@dataclass(frozen=True)
class InstanceLock:
    """Holds resources that keep the process as the single instance."""

    path: str
    file: object


def _lock_path(app_id: str) -> str:
    safe = "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in app_id)
    return os.path.join(tempfile.gettempdir(), f"{safe}.lock")


def acquire_single_instance(app_id: str) -> InstanceLock | None:
    """
    Return a lock handle if this is the only running instance, else None.

    Uses an OS-level file lock so it also works across virtualenvs and different python.exe.
    """
    path = _lock_path(app_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    f = open(path, "a+b")
    try:
        if sys.platform == "win32":
            import msvcrt

            f.seek(0)
            # Lock 1 byte; will raise OSError if another process holds it.
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        try:
            f.close()
        except Exception:
            pass
        return None
    return InstanceLock(path=path, file=f)

