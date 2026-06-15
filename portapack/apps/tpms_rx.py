"""TPMS receiver — tyre-pressure sensors (315 / 433.92 MHz, OOK/FSK)."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import OOKDecoder, TPMSDecoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView


class TPMSRx(AppView):
    title = "TPMS"

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

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Band")
        gl = QVBoxLayout(gb)
        self.band = widgets.combo(["315 MHz (US)", "433.92 MHz (EU)"])
        self.band.setCurrentText("433.92 MHz (EU)")
        self.band.currentIndexChanged.connect(
            lambda i: self.freq.set_value(315e6 if i == 0 else 433_920_000))
        gl.addWidget(self.band)
        self.mod = widgets.combo(["FSK (most sensors)", "OOK/ASK"])
        gl.addWidget(widgets.Field("Modulation", self.mod))
        self.baud_box = widgets.combo(["9600", "19200", "8192"])
        self.baud_box.setCurrentText("19200")
        self.baud_box.currentTextChanged.connect(self._set_baud)
        gl.addWidget(widgets.Field("Baud", self.baud_box))
        self.code_box = widgets.combo(["Manchester", "Diff-Manchester"])
        self.code_box.currentIndexChanged.connect(self._set_code)
        gl.addWidget(widgets.Field("Coding", self.code_box))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        self.stat = QLabel("waiting for sensors…")
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
        self.dec1 = dsp.best_decimation(fs, 250_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.3)
        self.if_rate = fs / self.dec1
        # FSK path (most TPMS) via FM discriminator → TPMSDecoder
        self.fm = dsp.FMDemod(38_000, self.if_rate, deemph_us=0)
        coding = "manchester" if self.code_box.currentIndex() == 0 else "diff"
        self.tpms = TPMSDecoder(self.if_rate, baud=int(self.baud_box.currentText()),
                                coding=coding)
        # OOK fallback for the few ASK sensors
        self.ook = OOKDecoder(self.if_rate, threshold_db=8,
                              min_gap_us=1500, min_pulse_us=40)
        self.start_rx(self._rx)

    def _set_baud(self, t):
        if hasattr(self, "tpms"):
            self.tpms.baud = int(t)

    def _set_code(self, i):
        if hasattr(self, "tpms"):
            self.tpms.coding = "manchester" if i == 0 else "diff"

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        if self.mod.currentIndex() == 0:        # FSK
            demod = self.fm.process(chan)
            recs = self.tpms.process(demod)
            self.emit_ui((power, ("fsk", recs)))
        else:                                   # OOK/ASK fallback
            bursts = self.ook.process(np.abs(chan).astype(np.float32))
            self.emit_ui((power, ("ook", bursts)))

    def _on_ui(self, payload):
        power, (kind, items) = payload
        self.spectrum.update_spectrum(power)
        ts = time.strftime("%H:%M:%S")
        if kind == "fsk":
            for r in items:
                tag = "✓" if r["crc_ok"] else "?"
                self.log.insertItem(
                    0, f"[{ts}] {tag} ID {r['id']}  {r['pressure_kpa']:.0f} kPa "
                       f"({r['pressure_kpa']/6.895:.0f} psi)  {r['temp_c']}°C")
        else:
            for b in items:
                bits = b.raw_bits[:48]
                hid = hex(int(bits, 2))[2:] if bits else "?"
                self.log.insertItem(0, f"[{ts}] OOK burst id~{hid} "
                                       f"{len(b.pulses)}p")
        if items:
            self.stat.setText(f"{self.log.count()} frames")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="tpms_rx", name="TPMS", category="Receive",
    factory=lambda hub, audio, ctx: TPMSRx(hub, audio, ctx),
    description="Tyre-pressure sensor receiver (315/433, OOK/FSK)"))
