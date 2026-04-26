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
    HERO_INSTANCE_NAME,
    PROCESS_DISPLAY_NAME,
    SOFTWARE_PID,
    set_windows_taskbar_app_id,
)
from sequencer_gui.sequence_io import SequenceFileError, load_sequence, validate_document_for_ui
from sequencer_gui.ui.main_window import MainWindow


def _load_initial_sequence() -> tuple[object, str]:
    """Return (document, sequence_name) for initial window."""
    rows = DEFAULT_DEVICE_ROWS
    labels = load_row_labels(rows)
    document = default_document(labels)
    sequence_name = "Untitled"
    last = load_last_sequence_path()
    if last:
        p = Path(last)
        if p.is_file():
            try:
                _, loaded = load_sequence(p)
            except (OSError, SequenceFileError):
                pass
            else:
                if validate_document_for_ui(loaded) is None:
                    document = loaded
                    sequence_name = p.name
    return document, sequence_name


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

    document, sequence_name = _load_initial_sequence()

    try:
        from sequencer_gui.app.hero_dict_backend import HeroDictBackend
        from sequencer_gui.sequencer_hero import Sequencer_HERO
    except ImportError as e:
        print(
            f"Sequencer HERO not available ({e!r}); running without live dict sync.",
            file=sys.stderr,
        )
        state = SequenceAppState(NoOpBackend(), document=document, sequence_name=sequence_name)
        window = MainWindow(state)
        window.show()
        sys.exit(app.exec_())

    with Sequencer_HERO(HERO_INSTANCE_NAME) as hero:
        state = SequenceAppState(
            HeroDictBackend(hero), document=document, sequence_name=sequence_name
        )
        window = MainWindow(state)
        window.show()
        sys.exit(app.exec_())


if __name__ == "__main__":
    main()
