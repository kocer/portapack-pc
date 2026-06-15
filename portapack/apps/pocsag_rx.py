"""POCSAG receiver — pager message decoder (FSK)."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import POCSAGDecoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView


class POCSAGRx(AppView):
    title = "POCSAG"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.baud = 1200
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(153_350_000)
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
        gb = QGroupBox("POCSAG")
        gl = QVBoxLayout(gb)
        self.baud_box = widgets.combo(["512", "1200", "2400"])
        self.baud_box.setCurrentText("1200")
        self.baud_box.currentTextChanged.connect(self._set_baud)
        gl.addWidget(widgets.Field("Baud", self.baud_box))
        from PySide6.QtWidgets import QLineEdit
        self.addr_filter = QLineEdit()
        self.addr_filter.setPlaceholderText("RIC (blank = all)")
        self.addr_filter.textChanged.connect(self._set_filter)
        gl.addWidget(widgets.Field("Address", self.addr_filter))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        self.stat = QLabel("listening…")
        pl.addWidget(self.stat)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        pl.addStretch(1)
        lay.addWidget(panel)

    def _set_filter(self, txt):
        if hasattr(self, "dec"):
            try:
                self.dec.address_filter = int(txt) if txt.strip() else None
            except ValueError:
                self.dec.address_filter = None

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        self.dec = POCSAGDecoder(48000, self.baud)
        self._set_filter(self.addr_filter.text())
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 48000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.02)
        self.fm = dsp.FMDemod(4500, fs / self.dec1, deemph_us=0)
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        msgs = self.dec.process(demod)
        self.emit_ui((power, msgs))

    def _on_ui(self, payload):
        power, msgs = payload
        self.spectrum.update_spectrum(power)
        for m in msgs:
            self.log.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {m}")
        if msgs:
            self.stat.setText(f"decoded {self.log.count()} msgs")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)

    def _set_baud(self, t):
        self.baud = int(t)
        if hasattr(self, "dec"):
            self.dec.set_baud(self.baud)


register(AppInfo(
    id="pocsag_rx", name="POCSAG", category="Receive",
    factory=lambda hub, audio, ctx: POCSAGRx(hub, audio, ctx),
    description="Pager (POCSAG 512/1200/2400) message decoder"))
