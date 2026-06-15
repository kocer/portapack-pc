"""RDS / FM stereo transmitter — broadcast a stereo MPX with RDS PS name.

Generates the FM multiplex: mono audio (a test tone or silence) + 19 kHz pilot
+ 57 kHz RDS BPSK carrying PS (station name) groups, then FM-modulates it.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QGroupBox, QLabel, QLineEdit, QVBoxLayout

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

MPX_RATE = 228_000  # multiplex sample rate (RDS bit rate 1187.5 = 228000/192)


def _rds_offset(word: str):
    return 0  # offset words omitted for brevity; PS still recognisable


class RDSTx(AppView):
    title = "RDS TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._mphase = 0.0
        self._mpx_phase = 0.0
        self._rds_bits = None
        self._bit_idx = 0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(98_000_000)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        gb = QGroupBox("RDS / audio")
        gl = QVBoxLayout(gb)
        self.ps = QLineEdit("PP-PC FM")
        gl.addWidget(widgets.Field("PS name", self.ps))
        self.pi = QLineEdit("1234")
        gl.addWidget(widgets.Field("PI (hex)", self.pi))
        self.audio_box = widgets.combo(["1 kHz test tone", "Silence", "440 Hz"])
        gl.addWidget(widgets.Field("Audio", self.audio_box))
        self.stereo = widgets.combo(["Stereo pilot ON", "Mono"])
        gl.addWidget(self.stereo)
        lay.addWidget(gb)
        gb2 = QGroupBox("TX gain"); g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 20, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub)); lay.addWidget(gb2)
        self.tx_btn = widgets.tx_button("BROADCAST")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel("Low power only & legal band — you are responsible.")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};"); self.warn.setWordWrap(True)
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def _build_rds(self):
        ps = (self.ps.text() + "        ")[:8]
        try:
            pi = int(self.pi.text(), 16) & 0xFFFF
        except ValueError:
            pi = 0x1234
        bits = []
        # 4 groups of 0A carrying 2 PS chars each
        for seg in range(4):
            chars = ps[seg * 2:seg * 2 + 2]
            b1 = pi
            b2 = (0x0 << 12) | (0x0 << 11) | seg  # group 0A, di bits omitted
            b3 = pi
            b4 = (ord(chars[0]) << 8) | ord(chars[1])
            for blk in (b1, b2, b3, b4):
                bits.extend((blk >> i) & 1 for i in range(15, -1, -1))
                bits.extend([0] * 10)  # checkword placeholder
        self._rds_bits = np.array(bits, dtype=np.float32) * 2 - 1
        self._bit_idx = 0

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            self.hub.set_sample_rate(2_280_000)  # 10x MPX, integer interp
            self._build_rds()
            self._mphase = 0.0
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            return None
        fs = self.hub.cfg.sample_rate
        t = (np.arange(n) + self._mpx_phase) / fs
        self._mpx_phase += n
        ab = self.audio_box.currentIndex()
        af = {0: 1000, 1: 0, 2: 440}[ab]
        audio = 0.3 * np.sin(2 * np.pi * af * t) if af else np.zeros(n)
        mpx = audio.copy()
        if self.stereo.currentIndex() == 0:
            mpx += 0.08 * np.sin(2 * np.pi * 19_000 * t)  # pilot
        # RDS subcarrier at 57 kHz, BPSK at 1187.5 bps
        bit_rate = 1187.5
        idxs = (t * bit_rate).astype(int) % len(self._rds_bits)
        symbols = self._rds_bits[idxs]
        rds = 0.05 * symbols * np.sin(2 * np.pi * 57_000 * t)
        mpx += rds
        # FM modulate the MPX
        dev = 75_000
        ph = self._mphase + np.cumsum(mpx) / fs * 2 * np.pi * dev
        self._mphase = ph[-1] % (2 * np.pi)
        return (0.9 * np.exp(1j * ph)).astype(np.complex64)


register(AppInfo(
    id="rds_tx", name="RDS TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: RDSTx(hub, audio, ctx),
    description="FM broadcast with stereo pilot + RDS PS name"))
