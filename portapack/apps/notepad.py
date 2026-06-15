"""Notepad — simple persistent text scratchpad (PortaPack utility)."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QPlainTextEdit,
                               QVBoxLayout)

from ..ui import theme
from . import AppInfo, register
from .base import AppView

NOTES_PATH = os.path.expanduser("~/portapack-pc/notes.txt")


class Notepad(AppView):
    title = "Notepad"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.addWidget(QLabel("Notepad"))
        self.edit = QPlainTextEdit()
        self.edit.setStyleSheet(f"background:{theme.BG_RAISED};color:{theme.FG};")
        if os.path.exists(NOTES_PATH):
            try:
                self.edit.setPlainText(open(NOTES_PATH).read())
            except Exception:
                pass
        lay.addWidget(self.edit, 1)
        row = QHBoxLayout()
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.edit.clear)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.ACCENT};")
        row.addWidget(save); row.addWidget(clear); row.addStretch(1)
        row.addWidget(self.status)
        lay.addLayout(row)

    def _save(self):
        os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
        with open(NOTES_PATH, "w") as f:
            f.write(self.edit.toPlainText())
        self.status.setText(f"saved → {NOTES_PATH}")


register(AppInfo(
    id="notepad", name="Notepad", category="Utilities",
    factory=lambda hub, audio, ctx: Notepad(hub, audio, ctx),
    description="Persistent text scratchpad"))
