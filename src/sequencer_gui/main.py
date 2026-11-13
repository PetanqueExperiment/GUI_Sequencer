from __future__ import annotations

import os
import sys
from importlib import resources
from pathlib import Path

import sequencer_gui
from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QGuiApplication, QIcon
from PyQt5.QtWidgets import QApplication

from sequencer_gui.app.backend import NoOpBackend
from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import default_document
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS
from sequencer_gui.persistence import load_last_sequence_path, load_row_labels
from sequencer_gui.process_identity import (
    CONTROL_HERO_INSTANCE_NAME,
    HERO_INSTANCE_NAME,
    PROCESS_DISPLAY_NAME,
    SOFTWARE_PID,
    set_windows_taskbar_app_id,
)
from sequencer_gui.single_instance import acquire_single_instance
from sequencer_gui.domain.scan import ScanPlan
from sequencer_gui.sequence_io import SequenceFileError, load_sequence_file, validate_document_for_ui
from sequencer_gui.ui.main_window import MainWindow


def _load_initial_sequence() -> tuple[object, str, ScanPlan | None]:
    """Return (document, sequence_name, scan saved with it or None) for initial window."""
    rows = DEFAULT_DEVICE_ROWS
    labels = load_row_labels(rows)
    document = default_document(labels)
    sequence_name = "Untitled"
    scan = None
    last = load_last_sequence_path()
    if last:
        p = Path(last)
        if p.is_file():
            try:
                loaded = load_sequence_file(p)
            except (OSError, SequenceFileError):
                pass
            else:
                if validate_document_for_ui(loaded.document) is None:
                    document = loaded.document
                    sequence_name = str(p.resolve())
                    scan = loaded.scan
                    if loaded.scan_error is not None:
                        print(
                            f"Scan saved in {p} ignored: {loaded.scan_error}",
                            file=sys.stderr,
                        )
    return document, sequence_name, scan


def _apply_initial_scan(state: SequenceAppState, scan: ScanPlan | None) -> None:
    """Scan panel content saved with the last sequence (before the window is built)."""
    if scan is not None:
        state.set_scan_plan(scan.label, scan.repetitions, scan.parameters)


def _app_window_icon() -> QIcon:
    """
    Title bar and taskbar icon. Uses packaged :file:`resources/Petanque_sequencer.ico`
    (same file as the design copy under the repo :file:`Icon` folder at project root).
    """
    name = "Petanque_sequencer.ico"
    pkg = Path(sequencer_gui.__file__).resolve().parent
    p = pkg / "resources" / name
    if p.is_file():
        return QIcon(str(p))
    # Dev fallback if ``resources/`` is missing: ``src`` → project ``Icon/``
    repo_ico = pkg.parent.parent / "Icon" / name
    if repo_ico.is_file():
        return QIcon(str(repo_ico))
    try:
        ico = resources.files("sequencer_gui").joinpath("resources", name)
        with resources.as_file(ico) as fspath:
            return QIcon(str(fspath))
    except (FileNotFoundError, OSError, TypeError, ValueError, AttributeError):
        return QIcon()


def main() -> None:
    set_windows_taskbar_app_id()
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleTitleW(PROCESS_DISPLAY_NAME)
        except Exception:
            pass

    # Prevent multiple GUI instances (and therefore multiple HERO providers) from running.
    # Set SEQUENCER_ALLOW_MULTIPLE=1 to bypass for development.
    if os.environ.get("SEQUENCER_ALLOW_MULTIPLE", "").strip() not in {"1", "true", "True"}:
        lock = acquire_single_instance("Petanque.Sequencer.GUI")
        if lock is None:
            if sys.platform == "win32":
                try:
                    import ctypes

                    ctypes.windll.user32.MessageBoxW(
                        0,
                        "Sequencer GUI is already running.\n\n"
                        "Close the existing window (or end the python process) and try again.",
                        PROCESS_DISPLAY_NAME,
                        0x00000030,  # MB_ICONWARNING
                    )
                except Exception:
                    pass
            return

    QCoreApplication.setApplicationName(PROCESS_DISPLAY_NAME)
    QGuiApplication.setApplicationDisplayName(PROCESS_DISPLAY_NAME)

    if "SEQUENCER_SOFTWARE_PID" not in os.environ:
        os.environ["SEQUENCER_SOFTWARE_PID"] = str(SOFTWARE_PID)

    app = QApplication(sys.argv)
    wicon = _app_window_icon()
    if not wicon.isNull():
        app.setWindowIcon(wicon)
    base = app.font()
    base.setPointSizeF(base.pointSizeF() + 1.0)
    app.setFont(base)

    document, sequence_name, initial_scan = _load_initial_sequence()

    try:
        from sequencer_gui.app.hero_dict_backend import HeroDictBackend
        from sequencer_gui.sequencer_hero import Sequencer_HERO
    except ImportError as e:
        print(
            f"Sequencer HERO not available ({e!r}); running without live dict sync.",
            file=sys.stderr,
        )
        state = SequenceAppState(NoOpBackend(), document=document, sequence_name=sequence_name)
        _apply_initial_scan(state, initial_scan)
        window = MainWindow(state)
        window.show()
        sys.exit(app.exec_())

    with Sequencer_HERO(HERO_INSTANCE_NAME) as hero:
        state = SequenceAppState(
            HeroDictBackend(hero), document=document, sequence_name=sequence_name
        )
        _apply_initial_scan(state, initial_scan)
        window = MainWindow(state)
        window.show()
        control_hero = _start_control_hero(state)
        try:
            sys.exit(app.exec_())
        finally:
            if control_hero is not None:
                control_hero._destroy_hero()


def _start_control_hero(state: SequenceAppState) -> object | None:
    """Remote control API for scripts / agents; the GUI runs normally if it cannot start."""
    try:
        from sequencer_gui.remote_control.control_hero import SequencerControl_HERO
        from sequencer_gui.remote_control.gui_invoker import GuiThreadInvoker

        invoker = GuiThreadInvoker(state)
        return SequencerControl_HERO(CONTROL_HERO_INSTANCE_NAME, state, invoker)
    except Exception as e:
        print(
            f"{CONTROL_HERO_INSTANCE_NAME} not started ({e!r}); remote control unavailable.",
            file=sys.stderr,
        )
        return None


if __name__ == "__main__":
    main()
