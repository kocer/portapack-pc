"""Shared base for simple 'tune + spectrum + decode log' receiver apps."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from .base import AppView


class RxLogApp(AppView):
    """Subclass fills in ``default_freq``, ``sample_rate`` and ``make_chain`` /
    ``decode`` (worker thread) returning a list of strings to log."""

    default_freq = 100_000_000
    sample_rate = 2_400_000
    band_options: list[tuple[str, float]] = []
    extra_note = ""

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build_common()
        self.make_chain()

    def _build_common(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(self.default_freq, hub=self.hub)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=110)
        left.addWidget(self.spectrum, 1)
        self.log = QListWidget()
        left.addWidget(self.log, 2)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        if self.band_options:
            gb = QGroupBox("Band")
            gl = QVBoxLayout(gb)
            self.band = widgets.combo([b[0] for b in self.band_options])
            self.band.currentIndexChanged.connect(
                lambda i: self.freq.set_value(self.band_options[i][1]))
            gl.addWidget(self.band)
            pl.addWidget(gb)
        gb2 = QGroupBox("RF gain")
        g2 = QVBoxLayout(gb2)
        g2.addWidget(widgets.Field("Freq step", widgets.FreqStepCombo(self.hub)))
        g2.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb2)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        self.stat = QLabel(self.extra_note or "listening…")
        self.stat.setWordWrap(True)
        self.stat.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        pl.addWidget(self.stat)
        pl.addStretch(1)
        lay.addWidget(panel)
        self._count = 0

    def make_chain(self):
        ...

    def decode(self, iq) -> list:
        return []

    def on_start(self):
        self.hub.set_sample_rate(self.sample_rate)
        self.hub.set_frequency(self.freq.value())
        self.spectrum.configure(self.hub.cfg.frequency, self.sample_rate)
        self.make_chain()
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        msgs = self.decode(iq)
        self.emit_ui((power, msgs))

    def _on_ui(self, payload):
        power, msgs = payload
        self.spectrum.update_spectrum(power)
        for m in msgs:
            self._count += 1
            self.log.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {m}")
        if msgs:
            self.stat.setText(f"{self._count} decoded")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)
