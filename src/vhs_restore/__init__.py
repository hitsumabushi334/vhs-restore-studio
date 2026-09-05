"""VHS Restore Studio package entry point."""

from __future__ import annotations

import sys

__version__ = "0.1.0"


def main(argv: list[str] | None = None) -> int:
    """Launch the PySide6 GUI and return its event-loop exit code."""

    from PySide6.QtWidgets import QApplication

    from vhs_restore.gui.main_window import MainWindow

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv if argv is None else argv)
    window = MainWindow()
    window.show()
    return int(app.exec())
