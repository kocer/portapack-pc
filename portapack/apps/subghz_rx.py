"""Sub-GHz OOK/ASK receiver — captures remote/sensor bursts (315/433/868 MHz)."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import OOKDecoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

BANDS = {"315 MHz": 315e6, "433.92 MHz": 433_920_000,
         "868 MHz": 868e6, "915 MHz": 915e6}


class SubGhzRx(AppView):
    title = "Sub-GHz"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(433_920_000)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=120)
        left.addWidget(self.spectrum, 1)
        self.log = QListWidget()
        left.addWidget(self.log, 1)
        lay.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Band")
        gl = QVBoxLayout(gb)
        self.band = widgets.combo(list(BANDS.keys()))
        self.band.setCurrentText("433.92 MHz")
        self.band.currentTextChanged.connect(
            lambda t: self.freq.set_value(BANDS[t]))
        gl.addWidget(self.band)
        pl.addWidget(gb)
        gb2 = QGroupBox("Decoder")
        g2 = QVBoxLayout(gb2)
        self.thr = widgets.LabeledSlider("Threshold", 3, 20, 6, suffix=" dB")
        self.thr.valueChanged.connect(self._set_thr)
        g2.addWidget(self.thr)
        g2.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb2)
        self.stat = QLabel("waiting for bursts…")
        pl.addWidget(self.stat)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 200_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.3)
        self.ook = OOKDecoder(fs / self.dec1, threshold_db=self.thr.value())
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        mag = np.abs(chan).astype(np.float32)
        bursts = self.ook.process(mag)
        self.emit_ui((power, bursts))

    def _on_ui(self, payload):
        power, bursts = payload
        self.spectrum.update_spectrum(power)
        for b in bursts:
            self.log.insertItem(
                0, f"[{time.strftime('%H:%M:%S')}] {len(b.pulses)} pulses "
                   f"{b.duration_us:.0f}µs  bits={b.raw_bits[:48]}")
        if bursts:
            self.stat.setText(f"captured {self.log.count()} bursts")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)

    def _set_thr(self, v):
        if hasattr(self, "ook"):
            self.ook.threshold_db = float(v)


register(AppInfo(
    id="subghz_rx", name="Sub-GHz", category="Receive",
    factory=lambda hub, audio, ctx: SubGhzRx(hub, audio, ctx),
    description="OOK/ASK capture for remotes & sensors (315/433/868/915)"))
