"""
Stable identity for this program.

The operating system still assigns a real process id; use :func:`os.getpid` for that. ``SOFTWARE_PID`` is
a fixed product identifier for logs, IPC, and integration.
"""

# Fixed product id (not the OS pid — change here if you need a different value).
SOFTWARE_PID = 2026_04_24

# Shown in the window title, Qt (taskbar / about), and Windows console when available.
PROCESS_DISPLAY_NAME = "Petanque Sequencer"

# :class:`heros.heros.LocalHERO` instance name (exposed to ARTIQ / HERO).
HERO_INSTANCE_NAME = "Sequencer_HERO"
