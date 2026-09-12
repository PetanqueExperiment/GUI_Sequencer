from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import QApplication

from sequencer_gui.app.backend import NoOpBackend
from sequencer_gui.app.state import COMPLETE_TAB_INDEX, SequenceAppState
from sequencer_gui.domain.document import default_document
from sequencer_gui.domain.model import DEFAULT_DEVICE_ROWS
from sequencer_gui.main import _app_window_icon
from sequencer_gui.persistence import load_row_labels
from sequencer_gui.process_identity import set_windows_taskbar_app_id
from sequencer_gui.ui.visualizer_window import VisualizerWindow

_VIEWER_APP_NAME = "Petanque Sequence Viewer"
_VIEWER_APP_USER_MODEL_ID = "Petanque.Sequencer.Viewer.1"


def _empty_document():
    rows = DEFAULT_DEVICE_ROWS
    return default_document(load_row_labels(rows))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Browse saved sequencer GUI sequences (read-only).")
    parser.add_argument(
        "sequence",
        nargs="?",
        type=Path,
        help="Optional path to a .json sequence file",
    )
    args = parser.parse_args(argv)

    set_windows_taskbar_app_id(_VIEWER_APP_USER_MODEL_ID)
    QCoreApplication.setApplicationName(_VIEWER_APP_NAME)
    QGuiApplication.setApplicationDisplayName(_VIEWER_APP_NAME)

    app = QApplication(sys.argv)
    wicon = _app_window_icon()
    if not wicon.isNull():
        app.setWindowIcon(wicon)
    base = app.font()
    base.setPointSizeF(base.pointSizeF() + 1.0)
    app.setFont(base)

    state = SequenceAppState(
        NoOpBackend(),
        document=_empty_document(),
        sequence_name="Untitled",
        read_only=True,
    )
    state.set_active_tab(COMPLETE_TAB_INDEX)

    window = VisualizerWindow(state)
    if args.sequence is not None:
        if not window.load_path(args.sequence):
            sys.exit(1)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
