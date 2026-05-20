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

# PyCam for Petanque (:class:`PyCam_HERO.PyCam_HERO` in the camera GUI process).
PYCAM_HERO_INSTANCE_NAME = "PyCam_HERO"

# ARTIQ master scheduler (:class:`atomiq.frontend.atomiq_master.Scheduler` LocalHERO).
ATOMIQ_SCHEDULER_HERO_NAME = "atomiq-scheduler"

# ARTIQ experiment database (:class:`atomiq.frontend.atomiq_master.ExperimentDB` LocalHERO).
ATOMIQ_EXPERIMENTDB_HERO_NAME = "atomiq-experimentdb"

# ``list_experiments()`` key for the sequencer-mode experiment (``Sequencer_mode.py``).
ATOMIQ_SEQUENCER_MODE_EXPERIMENT_KEY = "Sequencer_mode.py"

# Default ARTIQ pipeline for :meth:`Scheduler.submit`.
ATOMIQ_DEFAULT_PIPELINE = "main"

# PyCam repo for live sequence run/pause (not a user scan).
PYCAM_LIVE_EXPERIMENT_NAME = "Running_without_scan"

# ``Sequencer_HERO.set_burst_shots``: run until paused (live mode).
BURST_SHOTS_UNLIMITED = -1


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
