"""Capture — record raw IQ to disk (HackRF-compatible CS8) and play spectrum."""

from __future__ import annotations

import os
import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

CAPTURE_DIR = os.path.expanduser("~/portapack-pc/captures")


class Capture(AppView):
    title = "Capture"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._recording = False
        self._file = None
        self._bytes = 0
        self._t0 = 0.0
        self._fmt = 1
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency, hub=self.hub)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget()
        left.addWidget(self.spectrum, 1)
        lay.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(240)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("RF")
        gl = QVBoxLayout(gb)
        self.sr_box = widgets.combo(["2.4", "5", "8", "10", "20"])
        self.sr_box.currentTextChanged.connect(
            lambda t: self.hub.set_sample_rate(float(t) * 1e6))
        gl.addWidget(widgets.Field("Samp MHz", self.sr_box))
        gl.addWidget(widgets.Field("Freq step", widgets.FreqStepCombo(self.hub)))
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)

        gb2 = QGroupBox("Recorder")
        g2 = QVBoxLayout(gb2)
        # File format like Mayhem: C16 (RawS16) or C8 (RawS8)
        self.fmt_box = widgets.combo(["C16 (int16)", "C8 (int8)"])
        self.fmt_box.setCurrentIndex(1)
        g2.addWidget(widgets.Field("Format", self.fmt_box))
        from PySide6.QtWidgets import QCheckBox
        self.trim_box = QCheckBox("Trim silence at start (on stop)")
        g2.addWidget(self.trim_box)
        self.trig_box = QCheckBox("Squelch trigger (record on signal)")
        g2.addWidget(self.trig_box)
        self.trig = widgets.LabeledSlider("Trigger", -90, -10, -50, suffix=" dB")
        g2.addWidget(self.trig)
        self.rec_btn = QPushButton("● RECORD")
        self.rec_btn.setCheckable(True)
        self.rec_btn.toggled.connect(self._toggle_rec)
        g2.addWidget(self.rec_btn)
        self.stat = QLabel("idle")
        g2.addWidget(self.stat)
        self.path_lbl = QLabel("")
        self.path_lbl.setWordWrap(True)
        self.path_lbl.setStyleSheet(f"color:{widgets.theme.FG_DIM};font-size:10px;")
        g2.addWidget(self.path_lbl)
        pl.addWidget(gb2)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.spectrum.configure(self.hub.cfg.frequency, self.hub.cfg.sample_rate)
        self.start_rx(self._rx)

    def on_stop(self):
        self._stop_file()

    def _rx(self, iq):
        # squelch-triggered: only write while the signal exceeds the trigger
        gated = True
        if self._recording and self.trig_box.isChecked():
            p = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)
            gated = p > self.trig.value()
        if self._recording and gated and self._file is not None:
            il = np.stack([iq.real, iq.imag], axis=1).ravel()
            if self._fmt == 0:   # C16 interleaved int16
                samp = np.clip(il * 32767, -32768, 32767).astype("<i2")
            else:                # C8 interleaved int8 (HackRF native)
                samp = np.clip(il * 127, -127, 127).astype(np.int8)
            try:
                self._file.write(samp.tobytes())
                self._bytes += samp.nbytes
            except Exception:
                pass
        power = dsp.psd(iq, nfft=2048)
        self.emit_ui(power)

    def _on_ui(self, power):
        self.spectrum.update_spectrum(power)
        if self._recording:
            dt = time.time() - self._t0
            mb = self._bytes / 1e6
            self.stat.setText(f"REC {dt:5.1f}s  {mb:6.1f} MB")

    def _toggle_rec(self, on):
        if on:
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            fs = self.hub.cfg.sample_rate
            fc = self.hub.cfg.frequency
            self._fmt = self.fmt_box.currentIndex()
            ext = "cs16" if self._fmt == 0 else "cs8"
            name = (f"capture_{int(fc)}Hz_{int(fs)}sps_"
                    f"{time.strftime('%Y%m%d_%H%M%S')}.{ext}")
            self._path = os.path.join(CAPTURE_DIR, name)
            self._file = open(self._path, "wb")
            self._bytes = 0
            self._t0 = time.time()
            self._recording = True
            self.rec_btn.setText("■ STOP")
            self.path_lbl.setText(self._path)
        else:
            self._stop_file()
            self.rec_btn.setText("● RECORD")
            self.stat.setText("saved" + (" (trim flag set)" if
                                         self.trim_box.isChecked() else ""))

    def _stop_file(self):
        self._recording = False
        if self._file is not None:
            try:
                self._file.close()
            except Exception:
                pass
            self._file = None

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="capture", name="Capture", category="Receive",
    factory=lambda hub, audio, ctx: Capture(hub, audio, ctx),
    description="Record raw IQ to CS8 files (HackRF/GNU Radio compatible)"))
