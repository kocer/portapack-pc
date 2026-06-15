"""NOAA APT — 137 MHz weather-satellite image receiver (WFM)."""

from __future__ import annotations

import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.apt import APTDecoder, APT_LINE
from ..ui import theme, widgets
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView

APT_AUDIO = 20800            # 5 × 4160 word rate
MAX_ROWS = 1600

# NOAA APT downlink frequencies
SATS = {"NOAA-15 (137.620)": 137_620_000,
        "NOAA-18 (137.9125)": 137_912_500,
        "NOAA-19 (137.100)": 137_100_000,
        "Meteor M2 (137.100)": 137_100_000}


class NOAAAPT(AppView):
    title = "NOAA APT"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._img = np.zeros((MAX_ROWS, APT_LINE), dtype=np.uint8)
        self._row = 0
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(137_100_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.glw = pg.GraphicsLayoutWidget()
        vb = self.glw.addViewBox()
        vb.setAspectLocked(False)
        vb.invertY(True)
        self.img_item = pg.ImageItem()
        self.img_item.setLookupTable(self._gray())
        vb.addItem(self.img_item)
        left.addWidget(self.glw, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(230)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Satellite")
        gl = QVBoxLayout(gb)
        self.sat = widgets.combo(list(SATS.keys()))
        self.sat.setCurrentText("NOAA-19 (137.100)")
        self.sat.currentTextChanged.connect(lambda t: self.freq.set_value(SATS[t]))
        gl.addWidget(self.sat)
        gl.addWidget(widgets.Field("Freq step", widgets.FreqStepCombo(self.hub)))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        gb2 = QGroupBox("Image")
        g2 = QVBoxLayout(gb2)
        clr = QPushButton("Clear")
        clr.clicked.connect(self._clear)
        save = QPushButton("Save PNG")
        save.clicked.connect(self._save)
        g2.addWidget(clr); g2.addWidget(save)
        self.stat = QLabel("0 lines")
        g2.addWidget(self.stat)
        pl.addWidget(gb2)
        note = QLabel("WFM 137 MHz. Needs a V-dipole/QFH antenna and a live "
                      "satellite pass (use a tracker for pass times). 2 lines/s.")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        pl.addWidget(note)
        pl.addStretch(1)
        lay.addWidget(panel)

    def _gray(self):
        lut = np.zeros((256, 3), dtype=np.uint8)
        lut[:, 0] = lut[:, 1] = lut[:, 2] = np.arange(256)
        return lut

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, APT_AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.5)
        self.fm = dsp.FMDemod(17_000, self.if_rate, deemph_us=0)
        self.resamp = dsp.AudioResampler(self.if_rate, APT_AUDIO)
        self.apt = APTDecoder(APT_AUDIO)
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        chan = self.decim.process(iq)
        audio = self.fm.process(chan)
        audio = self.resamp.process(audio)
        rows = self.apt.process(audio)
        if rows:
            self.emit_ui(rows)

    def _on_ui(self, rows):
        for r in rows:
            if self._row >= MAX_ROWS:
                self._img[:-1] = self._img[1:]
                self._row = MAX_ROWS - 1
            self._img[self._row] = r
            self._row += 1
        self.img_item.setImage(self._img[:self._row].T, levels=(0, 255),
                               autoLevels=False)
        self.stat.setText(f"{self._row} lines")

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
        path = os.path.join(CAPTURE_DIR,
                            f"apt_{time.strftime('%Y%m%d_%H%M%S')}.png")
        try:
            from PySide6.QtGui import QImage
            arr = np.ascontiguousarray(self._img[:self._row])
            h, w = arr.shape
            qi = QImage(arr.data, w, h, w, QImage.Format_Grayscale8)
            qi.save(path)
            self.stat.setText(f"saved {os.path.basename(path)}")
        except Exception as e:
            self.stat.setText(f"save error: {e}")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)


register(AppInfo(
    id="noaa_apt", name="NOAA APT", category="Receive",
    factory=lambda hub, audio, ctx: NOAAAPT(hub, audio, ctx),
    description="137 MHz weather-satellite image decoder (WFM/APT)"))
