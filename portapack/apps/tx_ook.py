"""OOK transmitter — replay/synthesize sub-GHz remote codes."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QVBoxLayout, QWidget)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class TxOOK(AppView):
    title = "OOK TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._waveform = None
        self._pos = 0
        self._repeat = 0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(433_920_000)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        gb = QGroupBox("Payload")
        gl = QVBoxLayout(gb)
        self.bits = QLineEdit("101010110010110011001010")
        gl.addWidget(widgets.Field("Bits", self.bits))
        self.symrate = widgets.LabeledSlider("Symbol rate", 200, 10000, 2000,
                                             suffix=" sym/s")
        gl.addWidget(self.symrate)
        self.encoding = widgets.combo(["Raw NRZ", "Manchester", "PWM (PT2262)"])
        gl.addWidget(widgets.Field("Encoding", self.encoding))
        self.repeats = widgets.LabeledSlider("Repeats", 1, 50, 5)
        gl.addWidget(self.repeats)
        lay.addWidget(gb)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 40, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub))
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button("SEND")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _build_waveform(self):
        fs = self.hub.cfg.sample_rate
        bits = [int(c) for c in self.bits.text() if c in "01"]
        sps = int(fs / self.symrate.value())
        enc = self.encoding.currentIndex()
        levels = []
        for b in bits:
            if enc == 0:  # NRZ
                levels.append([b] * sps)
            elif enc == 1:  # Manchester: 1=10, 0=01
                half = sps // 2
                levels.append(([1] * half + [0] * (sps - half)) if b
                              else ([0] * half + [1] * (sps - half)))
            else:  # PWM PT2262: 1=long high, 0=short high
                hi = int(sps * (0.66 if b else 0.33))
                levels.append([1] * hi + [0] * (sps - hi))
        env = np.concatenate([np.array(l, dtype=np.float32) for l in levels]) \
            if levels else np.zeros(1, dtype=np.float32)
        gap = np.zeros(sps * 6, dtype=np.float32)
        one_packet = np.concatenate([env, gap])
        self._waveform = (one_packet * 0.9).astype(np.complex64)
        self._pos = 0
        self._repeat = self.repeats.value()

    def _toggle(self, on):
        if on:
            self._build_waveform()
            if self.hub.is_sim:
                self.warn.setText("Simulation mode — no RF emitted. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked() or self._waveform is None:
            return None
        out = np.zeros(n, dtype=np.complex64)
        filled = 0
        while filled < n and self._repeat > 0:
            remain = len(self._waveform) - self._pos
            take = min(remain, n - filled)
            out[filled:filled + take] = self._waveform[self._pos:self._pos + take]
            filled += take
            self._pos += take
            if self._pos >= len(self._waveform):
                self._pos = 0
                self._repeat -= 1
        if self._repeat <= 0 and filled == 0:
            # done — schedule button reset on GUI thread
            self.emit_ui("done")
            return None
        return out

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False)
            self.warn.setText("sent")


register(AppInfo(
    id="tx_ook", name="OOK TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: TxOOK(hub, audio, ctx),
    description="Transmit OOK/ASK remote codes (NRZ/Manchester/PWM)"))
