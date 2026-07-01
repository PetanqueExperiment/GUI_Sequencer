from __future__ import annotations

import subprocess
from pathlib import Path


def _git_toplevel(start: Path) -> Path | None:
    for parent in [start, *start.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def current_git_branch() -> str | None:
    """Return the checked-out branch name, or None if unavailable."""
    root = _git_toplevel(Path(__file__).resolve().parent)
    if root is None:
        return None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2,
            cwd=root,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.strip()
    if not branch or branch == "HEAD":
        return None
    return branch
