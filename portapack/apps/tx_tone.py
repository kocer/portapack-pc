"""Tone / CW transmitter."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class TxTone(AppView):
    title = "Tone TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._phase = 0.0
        self._mphase = 0.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        gb = QGroupBox("Tone")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(["CW carrier", "FM tone", "AM tone"])
        gl.addWidget(widgets.Field("Mode", self.mode))
        self.tone = widgets.LabeledSlider("Tone", 100, 5000, 1000, suffix=" Hz")
        gl.addWidget(self.tone)
        self.dev = widgets.LabeledSlider("FM dev", 1, 100, 5, suffix=" kHz")
        gl.addWidget(self.dev)
        self.amp = widgets.LabeledSlider("Amplitude", 1, 100, 60, suffix="%")
        gl.addWidget(self.amp)
        lay.addWidget(gb)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47,
                                         int(self.hub.cfg.tx_vga_gain), suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub))
        from PySide6.QtWidgets import QCheckBox
        self.monitor_box = QCheckBox("🔊 Monitor (local sidetone)")
        g2.addWidget(self.monitor_box)
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button()
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            if self.hub.is_sim:
                self.warn.setText("Simulation mode — no RF emitted. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            return None
        fs = self.hub.cfg.sample_rate
        amp = self.amp.value() / 100.0
        tone = self.tone.value()
        t = (np.arange(n) + self._phase) / fs
        self._phase += n
        mode = self.mode.currentIndex()
        if mode == 0:  # CW
            iq = np.ones(n, dtype=np.complex64) * amp
        elif mode == 1:  # FM tone
            dev = self.dev.value() * 1000
            ph = self._mphase + np.cumsum(np.sin(2 * np.pi * tone * t)) / fs * 2 * np.pi * dev
            self._mphase = ph[-1] % (2 * np.pi)
            iq = (amp * np.exp(1j * ph)).astype(np.complex64)
        else:  # AM tone
            m = 0.5 * (1 + np.sin(2 * np.pi * tone * t))
            iq = (amp * m).astype(np.complex64)
        return self._monitor(iq)

    def _monitor(self, iq):
        if (iq is not None and self.monitor_box.isChecked()
                and self.audio is not None):
            from ._txbase import tx_monitor_audio
            m = tx_monitor_audio(iq, self.hub.cfg.sample_rate)
            if m is not None:
                self.audio.push(m)
        return iq


register(AppInfo(
    id="tx_tone", name="Tone TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: TxTone(hub, audio, ctx),
    description="CW / FM / AM test-tone transmitter"))
