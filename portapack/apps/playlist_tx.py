"""Playlist TX — transmit a sequence of .cs8 IQ captures from a folder."""
from __future__ import annotations
import os
import numpy as np
from PySide6.QtWidgets import (QFileDialog, QLabel, QListWidget, QPushButton,
                               QVBoxLayout)
from . import AppInfo, register
from ._txbase import TxWaveApp


class PlaylistTx(TxWaveApp):
    title = "Playlist"
    default_freq = 433_920_000
    tx_sample_rate = 2_400_000
    button_text = "PLAY LIST"
    loop = False

    def build_extra(self, layout):
        self.files = []
        self.listw = QListWidget()
        layout.addWidget(self.listw)
        b = QPushButton("Add .cs8 files…")
        b.clicked.connect(self._add)
        layout.addWidget(b)
        clr = QPushButton("Clear")
        clr.clicked.connect(self._clear)
        layout.addWidget(clr)

    def _add(self):
        from .capture import CAPTURE_DIR
        start = CAPTURE_DIR if os.path.isdir(CAPTURE_DIR) else os.path.expanduser("~")
        ps, _ = QFileDialog.getOpenFileNames(self, "IQ files", start,
                                             "IQ (*.cs8 *.c8 *.iq *.raw)")
        for p in ps:
            self.files.append(p)
            self.listw.addItem(os.path.basename(p))

    def _clear(self):
        self.files = []
        self.listw.clear()

    def build_waveform(self):
        parts = []
        gap = np.zeros(int(self.tx_sample_rate * 0.2), dtype=np.complex64)
        for p in self.files:
            try:
                raw = np.fromfile(p, dtype=np.int8).astype(np.float32) / 127.0
                parts.append((raw[0::2] + 1j * raw[1::2]).astype(np.complex64))
                parts.append(gap)
            except Exception:
                pass
        return np.concatenate(parts) if parts else np.zeros(0, dtype=np.complex64)


register(AppInfo(id="playlist_tx", name="Playlist", category="Transmit",
                 needs_tx=True, factory=lambda h, a, c: PlaylistTx(h, a, c),
                 description="Transmit a sequence of IQ captures"))
