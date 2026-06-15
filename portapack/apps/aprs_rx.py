"""APRS receiver — 144.800 / 144.390 MHz AFSK1200 AX.25 packet decode."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import AFSK1200Decoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView


class APRSRx(AppView):
    title = "APRS"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(144_800_000)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=110)
        left.addWidget(self.spectrum, 1)
        self.log = QListWidget()
        left.addWidget(self.log, 2)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Region")
        gl = QVBoxLayout(gb)
        self.region = widgets.combo(["144.800 (EU)", "144.390 (US)",
                                     "145.575 (custom)"])
        self.region.currentIndexChanged.connect(self._region)
        gl.addWidget(self.region)
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        self.stat = QLabel("monitoring 1200 baud…")
        pl.addWidget(self.stat)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        pl.addStretch(1)
        lay.addWidget(panel)

    def _region(self, i):
        self.freq.set_value([144_800_000, 144_390_000, 145_575_000][i])

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 48_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.05)
        self.if_rate = fs / self.dec1
        self.fm = dsp.FMDemod(5_000, self.if_rate, deemph_us=0)
        self.afsk = AFSK1200Decoder(self.if_rate)
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        frames = self.afsk.process(demod)
        self.emit_ui((power, frames))

    def _on_ui(self, payload):
        power, frames = payload
        self.spectrum.update_spectrum(power)
        for f in frames:
            self.log.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {f}")
        if frames:
            self.stat.setText(f"{self.log.count()} packets decoded")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="aprs_rx", name="APRS", category="Receive",
    factory=lambda hub, audio, ctx: APRSRx(hub, audio, ctx),
    description="APRS / AX.25 AFSK1200 packet decoder"))
