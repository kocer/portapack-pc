"""Digital modes — RTTY (Baudot) and PSK31 text decoder."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import RTTYDecoder, PSK31Decoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

AUDIO = 8000


class DigitalModes(AppView):
    title = "Digital Modes"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.channel_offset = 0.0
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(14_070_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=90)
        self.spectrum.frequency_clicked.connect(self._click)
        left.addWidget(self.spectrum, 1)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setStyleSheet(f"background:{theme.BG_RAISED};color:{theme.GREEN};")
        left.addWidget(self.text, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Mode")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(["RTTY 45.45", "RTTY 50", "RTTY 75", "PSK31"])
        self.mode.currentTextChanged.connect(self._set_mode)
        gl.addWidget(self.mode)
        self.demod_box = widgets.combo(["FM/FSK", "USB", "LSB"])
        self.demod_box.setCurrentText("USB")
        gl.addWidget(widgets.Field("Demod", self.demod_box))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        gb2 = QGroupBox("Display")
        g2 = QVBoxLayout(gb2)
        g2.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gb2)
        self.stat = QLabel("click signal in spectrum to tune")
        self.stat.setWordWrap(True)
        self.stat.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        pl.addWidget(self.stat)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.tuner = dsp.Tuner(fs, self.channel_offset)
        self.dec1 = dsp.best_decimation(fs, AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.02)
        self.fm = dsp.FMDemod(85, self.if_rate, deemph_us=0)
        self._make_decoder()
        self.start_rx(self._rx)

    def _make_decoder(self):
        m = self.mode.currentText()
        if m.startswith("RTTY"):
            baud = {"RTTY 45.45": 45.45, "RTTY 50": 50.0, "RTTY 75": 75.0}[m]
            self.rtty = RTTYDecoder(self.if_rate, baud)
            self.psk = None
        else:
            self.psk = PSK31Decoder(self.if_rate)
            self.rtty = None

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(self.tuner.process(iq))
        txt = ""
        if self.rtty is not None:
            if self.demod_box.currentIndex() == 0:
                demod = self.fm.process(chan)
            else:
                demod = chan.real if self.demod_box.currentIndex() == 1 else chan.imag
            txt = self.rtty.process(demod.astype(np.float32))
        elif self.psk is not None:
            txt = self.psk.process(chan)
        self.emit_ui((power, txt))

    def _on_ui(self, payload):
        power, txt = payload
        self.spectrum.update_spectrum(power)
        if txt:
            self.text.insertPlainText(txt)

    def _set_mode(self, _):
        if hasattr(self, "if_rate"):
            self._make_decoder()

    def _click(self, abs_hz):
        off = abs_hz - self.hub.cfg.frequency
        if abs(off) < self.hub.cfg.sample_rate / 2:
            self.channel_offset = off
            if hasattr(self, "tuner"):
                self.tuner.set_offset(off)
            self.spectrum.set_tune_marker(abs_hz)
            self.stat.setText(f"tuned {abs_hz/1e6:.4f} MHz")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)
        self.channel_offset = 0.0
        if hasattr(self, "tuner"):
            self.tuner.set_offset(0.0)


register(AppInfo(
    id="digital_modes", name="Digital Modes", category="Receive",
    factory=lambda hub, audio, ctx: DigitalModes(hub, audio, ctx),
    description="RTTY (Baudot) and PSK31 text decoder"))
