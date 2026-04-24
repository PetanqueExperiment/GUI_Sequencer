from __future__ import annotations

import os
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

from sequencer_gui.app.backend import NoOpBackend
from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import default_document
from sequencer_gui.persistence import load_last_sequence_path, load_row_labels
from sequencer_gui.process_identity import HERO_INSTANCE_NAME, PROCESS_DISPLAY_NAME, SOFTWARE_PID
from sequencer_gui.sequence_io import SequenceFileError, load_sequence, validate_document_for_ui
from sequencer_gui.ui.main_window import MainWindow


def _load_initial_sequence() -> tuple[object, str]:
    """Return (document, sequence_name) for initial window."""
    rows = 4
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


def main() -> None:
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
