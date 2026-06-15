#!/usr/bin/env python3
"""PortaPack PC entry point.

Usage:
    python run.py            # auto-detect HackRF, fall back to simulation
    python run.py --sim      # force simulation mode
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from portapack.app import MainWindow


def main():
    force_sim = "--sim" in sys.argv
    app = QApplication(sys.argv)
    app.setApplicationName("PortaPack PC")
    win = MainWindow(force_sim=force_sim)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
