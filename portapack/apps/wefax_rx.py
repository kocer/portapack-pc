"""WEFAX — HF weather fax / radiofax image receiver (USB)."""

from __future__ import annotations

import os
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.fax import WEFAXDecoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView

FAX_AUDIO = 12000
WIDTH = 1200
MAX_ROWS = 1400

# common HF WEFAX broadcast frequencies (Hz) — tune to USB, then the audio fax
STATIONS = {"DWD 3855": 3_855_000, "DWD 7880": 7_880_000, "DWD 13882.5": 13_882_500,
            "Northwood 4610": 4_610_000, "US Pt Reyes 12786": 12_786_000}


class WEFAXRx(AppView):
    title = "WEFAX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._img = np.zeros((MAX_ROWS, WIDTH), dtype=np.uint8)
        self._row = 0
        self.channel_offset = 1900.0    # park USB so the 1.9 kHz fax lands right
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(7_880_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.glw = pg.GraphicsLayoutWidget()
        vb = self.glw.addViewBox()
        vb.setAspectLocked(False)
        vb.invertY(True)
        self.img_item = pg.ImageItem()
        lut = np.zeros((256, 3), dtype=np.uint8)
        lut[:, 0] = lut[:, 1] = lut[:, 2] = np.arange(256)
        self.img_item.setLookupTable(lut)
        vb.addItem(self.img_item)
        left.addWidget(self.glw, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(230)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Station / mode")
        gl = QVBoxLayout(gb)
        self.station = widgets.combo(list(STATIONS.keys()))
        self.station.setCurrentText("DWD 7880")
        self.station.currentTextChanged.connect(lambda t: self.freq.set_value(STATIONS[t]))
        gl.addWidget(self.station)
        self.lpm = widgets.combo(["60", "90", "120", "240"])
        self.lpm.setCurrentText("120")
        self.lpm.currentTextChanged.connect(self._set_lpm)
        gl.addWidget(widgets.Field("LPM", self.lpm))
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
        note = QLabel("HF USB radiofax. Tune the station; the 1.5–2.3 kHz fax "
                      "audio is decoded. 120 lpm is standard. Needs HF antenna.")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        pl.addWidget(note)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        fs = self.hub.cfg.sample_rate
        self.tuner = dsp.Tuner(fs, self.channel_offset)
        self.dec1 = dsp.best_decimation(fs, FAX_AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.1)
        self.ssb = dsp.SSBDemod(lsb=False)
        self.resamp = dsp.AudioResampler(self.if_rate, FAX_AUDIO)
        self.fax = WEFAXDecoder(FAX_AUDIO, float(self.lpm.currentText()), WIDTH)
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        chan = self.decim.process(self.tuner.process(iq))
        audio = self.ssb.process(chan)
        audio = self.resamp.process(audio)
        rows = self.fax.process(audio)
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

    def _set_lpm(self, t):
        if hasattr(self, "fax"):
            self.fax.set_lpm(float(t))

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
        path = os.path.join(CAPTURE_DIR, f"wefax_{time.strftime('%Y%m%d_%H%M%S')}.png")
        try:
            from PySide6.QtGui import QImage
            arr = np.ascontiguousarray(self._img[:self._row])
            h, w = arr.shape
            QImage(arr.data, w, h, w, QImage.Format_Grayscale8).save(path)
            self.stat.setText(f"saved {os.path.basename(path)}")
        except Exception as e:
            self.stat.setText(f"save error: {e}")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)


register(AppInfo(
    id="wefax_rx", name="WEFAX", category="Receive",
    factory=lambda hub, audio, ctx: WEFAXRx(hub, audio, ctx),
    description="HF weather fax / radiofax image decoder"))
