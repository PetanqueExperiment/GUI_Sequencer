from __future__ import annotations

import sys

from PyQt5.QtWidgets import QApplication

from sequencer_gui.app.backend import NoOpBackend
from sequencer_gui.app.state import SequenceAppState
from sequencer_gui.domain.document import default_document
from sequencer_gui.persistence import load_row_labels
from sequencer_gui.ui.main_window import MainWindow


def main() -> None:
    app = QApplication(sys.argv)
    base = app.font()
    base.setPointSizeF(base.pointSizeF() + 1.0)
    app.setFont(base)

    rows = 4
    labels = load_row_labels(rows)
    state = SequenceAppState(NoOpBackend(), document=default_document(labels))
    window = MainWindow(state)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
