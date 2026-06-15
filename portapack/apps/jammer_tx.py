"""Jammer TX — wideband noise / sweep generator for authorised RF testing.

For lab / shielded-enclosure interference testing and red-team engagements you
are authorised to perform.  Transmitting interference on live bands is illegal
in virtually every jurisdiction — the app emits nothing in simulation mode and
warns on real hardware.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class JammerTx(AppView):
    title = "Jammer TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._phase = 0.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        warn = QLabel("⚠ AUTHORISED TESTING ONLY — lab / shielded use. "
                      "Interfering with live services is illegal.")
        warn.setStyleSheet(f"color:{theme.RED};font-weight:bold;")
        warn.setWordWrap(True)
        lay.addWidget(warn)
        gb = QGroupBox("Waveform")
        gl = QVBoxLayout(gb)
        self.kind = widgets.combo(["Wideband noise", "Chirp sweep", "Multi-tone comb"])
        gl.addWidget(self.kind)
        self.bw = widgets.LabeledSlider("Bandwidth", 1, 20, 10, suffix=" MHz")
        gl.addWidget(self.bw)
        lay.addWidget(gb)
        gb2 = QGroupBox("TX gain"); g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 40, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub)); lay.addWidget(gb2)
        self.tx_btn = widgets.tx_button("JAM")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.status = QLabel(""); self.status.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.status)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            self.hub.set_sample_rate(self.bw.value() * 1e6)
            self._phase = 0.0
            if self.hub.is_sim:
                self.status.setText("Simulation — no RF emitted.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop(); self.status.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            return None
        k = self.kind.currentIndex()
        if k == 0:  # white gaussian noise
            iq = (np.random.randn(n) + 1j * np.random.randn(n)) * 0.5
        elif k == 1:  # chirp across the band
            fs = self.hub.cfg.sample_rate
            t = (np.arange(n) + self._phase) / fs
            self._phase += n
            sweep = 1e3  # Hz/s nominal; fast within block
            f = (self._phase % fs) - fs / 2
            ph = 2 * np.pi * (f * np.arange(n) / fs +
                              0.5 * (fs / n) * (np.arange(n) / fs) ** 2)
            iq = 0.9 * np.exp(1j * ph)
        else:  # multi-tone comb
            fs = self.hub.cfg.sample_rate
            t = (np.arange(n) + self._phase) / fs
            self._phase += n
            iq = np.zeros(n, dtype=np.complex128)
            for off in np.linspace(-fs / 2 * 0.8, fs / 2 * 0.8, 16):
                iq += np.exp(1j * 2 * np.pi * off * t)
            iq *= 0.06
        return iq.astype(np.complex64)


register(AppInfo(
    id="jammer_tx", name="Jammer TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: JammerTx(hub, audio, ctx),
    description="Noise/chirp/comb interference generator (authorised testing)"))
