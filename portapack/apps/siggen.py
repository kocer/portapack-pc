"""Signal Generator — calibrated CW / sweep source plus a whip-antenna calc."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class SigGen(AppView):
    title = "Signal Gen"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._phase = 0.0
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        left.addWidget(self.freq)
        gb = QGroupBox("Output")
        gl = QVBoxLayout(gb)
        self.kind = widgets.combo(["CW carrier", "Linear sweep", "Two-tone"])
        gl.addWidget(self.kind)
        self.span = widgets.LabeledSlider("Sweep span", 1, 20, 4, suffix=" MHz")
        gl.addWidget(self.span)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 20, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        gl.addWidget(self.txg)
        gl.addWidget(widgets.BiasTeeBox(self.hub))
        left.addWidget(gb)
        self.tx_btn = widgets.tx_button("OUTPUT ON")
        self.tx_btn.toggled.connect(self._toggle)
        left.addWidget(self.tx_btn)
        self.warn = QLabel(""); self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        left.addWidget(self.warn)
        left.addStretch(1)
        lay.addLayout(left, 1)

        # whip antenna length calculator
        panel = QWidget(); panel.setFixedWidth(240)
        pr = QVBoxLayout(panel)
        gbc = QGroupBox("Whip antenna calculator")
        gc = QVBoxLayout(gbc)
        self.calc = QLabel("")
        self.calc.setStyleSheet(f"color:{theme.ACCENT};")
        gc.addWidget(self.calc)
        pr.addWidget(gbc)
        pr.addStretch(1)
        lay.addWidget(panel)
        self.freq.frequency_changed.connect(self._update_calc)
        self._update_calc(self.hub.cfg.frequency)

    def _update_calc(self, hz):
        c = 299_792_458.0
        wl = c / hz
        self.calc.setText(
            f"λ      = {wl*100:8.2f} cm\n"
            f"λ/2    = {wl*50:8.2f} cm\n"
            f"λ/4    = {wl*25:8.2f} cm\n"
            f"5/8 λ  = {wl*62.5:8.2f} cm\n"
            f"(×0.95 velocity factor:\n"
            f" λ/4 ≈ {wl*25*0.95:7.2f} cm)")

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            self.hub.set_sample_rate(max(2_400_000, self.span.value() * 1e6))
            self._phase = 0.0
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop(); self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            return None
        fs = self.hub.cfg.sample_rate
        k = self.kind.currentIndex()
        if k == 0:
            iq = np.ones(n, dtype=np.complex64) * 0.7
        elif k == 1:
            span = self.span.value() * 1e6
            ph = self._phase + np.cumsum(
                np.linspace(-span / 2, span / 2, n)) / fs * 2 * np.pi
            self._phase = ph[-1] % (2 * np.pi)
            iq = (0.7 * np.exp(1j * ph)).astype(np.complex64)
        else:
            t = (np.arange(n) + self._phase) / fs
            self._phase += n
            iq = (0.4 * (np.exp(1j * 2 * np.pi * 100e3 * t) +
                         np.exp(1j * 2 * np.pi * -100e3 * t))).astype(np.complex64)
        return iq


register(AppInfo(
    id="siggen", name="Signal Gen", category="Utilities",
    factory=lambda hub, audio, ctx: SigGen(hub, audio, ctx),
    description="CW/sweep/two-tone source + antenna length calculator"))
