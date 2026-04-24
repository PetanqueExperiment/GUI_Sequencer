"""
Stable identity for this program.

The operating system still assigns a real process id; use :func:`os.getpid` for that. ``SOFTWARE_PID`` is
a fixed product identifier for logs, IPC, and integration.
"""

from __future__ import annotations

import sys

# Fixed product id (not the OS pid — change here if you need a different value).
SOFTWARE_PID = 2026_04_24

# Shown in the window title, Qt (taskbar / about), and Windows console when available.
PROCESS_DISPLAY_NAME = "Petanque Sequencer"

# Windows shell: unique AppUserModelID so this GUI is not grouped with other ``python*.exe`` apps
# in the same taskbar slot. Use a *different* string in each of your other programs.
WIN32_APP_USER_MODEL_ID = "Petanque.Sequencer.GUI.1"

# :class:`heros.heros.LocalHERO` instance name (exposed to ARTIQ / HERO).
HERO_INSTANCE_NAME = "Sequencer_HERO"


def set_windows_taskbar_app_id() -> None:
    """
    Set the app id the shell uses to group the taskbar / Start menu. Call
    *before* creating :class:`PyQt5.QtWidgets.QApplication` on Windows.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
    except ImportError:
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WIN32_APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass
