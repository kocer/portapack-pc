"""File Manager — browse PortaPack-PC data (captures, notes, freqman)."""
from __future__ import annotations
import os
import numpy as np
from PySide6.QtCore import QDir
from PySide6.QtWidgets import (QFileSystemModel, QHBoxLayout, QLabel, QPushButton,
                               QTreeView, QVBoxLayout)
from ..ui import theme
from . import AppInfo, register
from .base import AppView

ROOT = os.path.expanduser("~/portapack-pc")


class FileManager(AppView):
    title = "File Manager"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        os.makedirs(ROOT, exist_ok=True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(QLabel(f"Root: {ROOT}"))
        self.model = QFileSystemModel()
        self.model.setRootPath(ROOT)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIndex(self.model.index(ROOT))
        self.tree.setColumnWidth(0, 360)
        self.tree.clicked.connect(self._sel)
        lay.addWidget(self.tree, 1)
        self.info = QLabel("")
        self.info.setStyleSheet(f"color:{theme.ACCENT};")
        lay.addWidget(self.info)
        row = QHBoxLayout()
        d = QPushButton("Delete"); d.clicked.connect(self._delete)
        r = QPushButton("Refresh"); r.clicked.connect(
            lambda: self.model.setRootPath(ROOT))
        o = QPushButton("Open folder"); o.clicked.connect(self._open)
        row.addWidget(d); row.addWidget(r); row.addWidget(o); row.addStretch(1)
        lay.addLayout(row)
        self._path = None

    def _sel(self, idx):
        self._path = self.model.filePath(idx)
        try:
            sz = os.path.getsize(self._path)
            extra = ""
            if self._path.endswith(".cs8"):
                samples = sz // 2
                extra = f"  ·  {samples:,} IQ samples"
            self.info.setText(f"{os.path.basename(self._path)}  ·  {sz/1e6:.2f} MB{extra}")
        except Exception:
            self.info.setText(self._path or "")

    def _delete(self):
        if self._path and os.path.isfile(self._path):
            try:
                os.remove(self._path)
                self.info.setText(f"deleted {os.path.basename(self._path)}")
                self._path = None
            except Exception as e:
                self.info.setText(f"error: {e}")

    def _open(self):
        import subprocess
        try:
            subprocess.Popen(["xdg-open", ROOT])
        except Exception:
            pass


register(AppInfo(id="filemanager", name="File Manager", category="Utilities",
                 factory=lambda h, a, c: FileManager(h, a, c),
                 description="Browse captures, notes and data files"))
