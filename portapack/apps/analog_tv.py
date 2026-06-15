"""Analog TV / video scope — renders demodulated amplitude as a raster image.

Not a full PAL/NTSC decoder; it shows an intensity raster of the demodulated
signal (like PortaPack's video preview) useful for spotting ATV/NTSC carriers
and sync structure.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class AnalogTV(AppView):
    title = "Analog TV"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.lines = 320
        self.cols = 400
        self._frame = np.zeros((self.lines, self.cols), dtype=np.float32)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(489_250_000)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        left.addWidget(self.freq)
        self.glw = pg.GraphicsLayoutWidget()
        vb = self.glw.addViewBox()
        vb.setAspectLocked(True)
        self.img = pg.ImageItem()
        self.img.setLookupTable(self._gray_lut())
        vb.addItem(self.img)
        left.addWidget(self.glw, 1)
        lay.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Video")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(["AM (vestigial)", "FM"])
        gl.addWidget(widgets.Field("Detect", self.mode))
        self.lines_box = widgets.combo(["240", "320", "525", "625"])
        self.lines_box.setCurrentText("320")
        self.lines_box.currentTextChanged.connect(self._set_lines)
        gl.addWidget(widgets.Field("Lines", self.lines_box))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        pl.addStretch(1)
        lay.addWidget(panel)

    def _gray_lut(self):
        lut = np.zeros((256, 3), dtype=np.uint8)
        lut[:, 0] = lut[:, 1] = lut[:, 2] = np.arange(256)
        return lut

    def _set_lines(self, t):
        self.lines = int(t)
        self._frame = np.zeros((self.lines, self.cols), dtype=np.float32)

    def on_start(self):
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 6_000_000) or 1
        self.fm = dsp.FMDemod(2.5e6, fs, deemph_us=0)
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        if self.mode.currentIndex() == 0:
            vid = np.abs(iq).astype(np.float32)
        else:
            vid = self.fm.process(iq)
        vid = vid - vid.min()
        m = vid.max() + 1e-9
        vid = vid / m
        per_line = max(1, len(vid) // self.lines)
        n = per_line * self.lines
        frame = vid[:n].reshape(self.lines, per_line)
        # resample columns to display width
        x = np.linspace(0, per_line - 1, self.cols)
        out = np.empty((self.lines, self.cols), dtype=np.float32)
        for r in range(self.lines):
            out[r] = np.interp(x, np.arange(per_line), frame[r])
        self.emit_ui(out)

    def _on_ui(self, frame):
        self._frame = 0.5 * self._frame + 0.5 * frame
        self.img.setImage((self._frame.T * 255), levels=(0, 255), autoLevels=False)


register(AppInfo(
    id="analog_tv", name="Analog TV", category="Receive",
    factory=lambda hub, audio, ctx: AnalogTV(hub, audio, ctx),
    description="Video raster preview of ATV/broadcast carriers"))
