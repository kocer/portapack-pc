"""SSTV receiver — slow-scan TV image decode (Martin / Scottie)."""

from __future__ import annotations

import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QGroupBox, QLabel, QPushButton, QVBoxLayout,
                               QHBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.sstv import SSTVDecoder, MODES
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView

SSTV_AUDIO = 12000
MAX_ROWS = 320


class SSTVRx(AppView):
    title = "SSTV"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._img = np.zeros((MAX_ROWS, 320, 3), dtype=np.uint8)
        self._row = 0
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(144_500_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.glw = pg.GraphicsLayoutWidget()
        vb = self.glw.addViewBox()
        vb.setAspectLocked(True)
        vb.invertY(True)
        self.img_item = pg.ImageItem()
        vb.addItem(self.img_item)
        left.addWidget(self.glw, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(230)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Mode / RF")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(list(MODES.keys()))
        self.mode.currentTextChanged.connect(self._set_mode)
        gl.addWidget(widgets.Field("Mode", self.mode))
        self.demod = widgets.combo(["FM (VHF)", "USB (HF)"])
        gl.addWidget(widgets.Field("Demod", self.demod))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        gb2 = QGroupBox("Image")
        g2 = QVBoxLayout(gb2)
        clr = QPushButton("Clear"); clr.clicked.connect(self._clear)
        save = QPushButton("Save PNG"); save.clicked.connect(self._save)
        g2.addWidget(clr); g2.addWidget(save)
        self.stat = QLabel("0 lines")
        g2.addWidget(self.stat)
        pl.addWidget(gb2)
        note = QLabel("VHF SSTV (144.5) FM or HF (14.230) USB. Common modes "
                      "Martin M1 / Scottie. Needs a live SSTV transmission.")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        pl.addWidget(note)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, SSTV_AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.5)
        self.fm = dsp.FMDemod(5_000, self.if_rate, deemph_us=0)
        self.ssb = dsp.SSBDemod(lsb=False)
        self.resamp = dsp.AudioResampler(self.if_rate, SSTV_AUDIO)
        self.sstv = SSTVDecoder(SSTV_AUDIO, self.mode.currentText())
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        chan = self.decim.process(iq)
        if self.demod.currentIndex() == 0:
            audio = self.fm.process(chan)
        else:
            audio = self.ssb.process(chan)
        audio = self.resamp.process(audio)
        rows = self.sstv.process(audio)
        if rows:
            self.emit_ui(rows)

    def _on_ui(self, rows):
        for r in rows:
            if self._row >= MAX_ROWS:
                self._img[:-1] = self._img[1:]
                self._row = MAX_ROWS - 1
            self._img[self._row] = r
            self._row += 1
        self.img_item.setImage(np.transpose(self._img[:self._row], (1, 0, 2)),
                               levels=(0, 255), autoLevels=False)
        self.stat.setText(f"{self._row} lines")

    def _set_mode(self, m):
        if hasattr(self, "sstv"):
            self.sstv.set_mode(m)

    def _clear(self):
        self._img[:] = 0
        self._row = 0
        self.img_item.clear()
        self.stat.setText("0 lines")

    def _save(self):
        if self._row < 2:
            self.stat.setText("nothing to save")
            return
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        path = os.path.join(CAPTURE_DIR, f"sstv_{time.strftime('%Y%m%d_%H%M%S')}.png")
        try:
            from PySide6.QtGui import QImage
            arr = np.ascontiguousarray(self._img[:self._row])
            h, w, _ = arr.shape
            qi = QImage(arr.data, w, h, w * 3, QImage.Format_RGB888)
            qi.save(path)
            self.stat.setText(f"saved {os.path.basename(path)}")
        except Exception as e:
            self.stat.setText(f"save error: {e}")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)


register(AppInfo(
    id="sstv_rx", name="SSTV", category="Receive",
    factory=lambda hub, audio, ctx: SSTVRx(hub, audio, ctx),
    description="Slow-scan TV image decoder (Martin / Scottie)"))
