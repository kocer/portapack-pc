"""Soundboard — FM-transmit a WAV file or built-in tones."""
from __future__ import annotations
import os
import numpy as np
from PySide6.QtWidgets import QFileDialog, QPushButton
from scipy.io import wavfile
from scipy import signal as ssig
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp, fm_modulate


class SoundboardTx(TxWaveApp):
    title = "Soundboard"
    default_freq = 145_500_000
    tx_sample_rate = 2_400_000
    button_text = "PLAY OUT"
    loop = False

    def build_extra(self, layout):
        self._wav = None
        self.mode = widgets.combo(["WAV file", "Beep 1 kHz", "Siren", "Chime"])
        layout.addWidget(widgets.Field("Source", self.mode))
        b = QPushButton("Load WAV…")
        b.clicked.connect(self._load)
        layout.addWidget(b)
        self.lbl = widgets.QLabel("no file") if hasattr(widgets, "QLabel") else None
        from PySide6.QtWidgets import QLabel
        self.lbl = QLabel("no file")
        layout.addWidget(self.lbl)
        self.dev = widgets.LabeledSlider("FM dev", 1, 100, 5, suffix=" kHz")
        layout.addWidget(self.dev)
        self.loop_box = widgets.combo(["Once", "Loop"])
        self.loop_box.currentIndexChanged.connect(
            lambda i: setattr(self, "loop", i == 1))
        layout.addWidget(self.loop_box)

    def _load(self):
        p, _ = QFileDialog.getOpenFileName(self, "WAV", os.path.expanduser("~"),
                                           "WAV (*.wav)")
        if p:
            try:
                rate, data = wavfile.read(p)
                if data.ndim > 1:
                    data = data.mean(axis=1)
                data = data.astype(np.float32)
                data /= (np.max(np.abs(data)) + 1e-9)
                self._wav = (rate, data)
                self.lbl.setText(f"{os.path.basename(p)} ({len(data)/rate:.1f}s)")
            except Exception as e:
                self.lbl.setText(f"error: {e}")

    def _audio(self):
        fs = self.tx_sample_rate
        m = self.mode.currentIndex()
        if m == 0 and self._wav:
            rate, data = self._wav
            n = int(len(data) * fs / rate)
            return ssig.resample(data, n).astype(np.float32)
        dur = 1.0
        t = np.arange(int(fs * dur)) / fs
        if m == 1:
            return 0.7 * np.sin(2 * np.pi * 1000 * t)
        if m == 2:  # siren
            f = 600 + 400 * np.sin(2 * np.pi * 2 * t)
            return 0.7 * np.sin(2 * np.pi * np.cumsum(f) / fs)
        return 0.7 * np.sin(2 * np.pi * 880 * t) * np.exp(-3 * t)  # chime

    def build_waveform(self):
        audio = self._audio()
        return fm_modulate(audio, self.tx_sample_rate, self.dev.value() * 1000)


register(AppInfo(id="soundboard_tx", name="Soundboard", category="Transmit",
                 needs_tx=True, factory=lambda h, a, c: SoundboardTx(h, a, c),
                 description="FM-transmit WAV files or sound effects"))
