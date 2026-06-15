"""Level — single-frequency signal strength meter with peak/hold and dBm-ish scale."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..sdr import dsp
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class Level(AppView):
    title = "Level"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._peak = -120.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        self.big = QLabel("-- dB")
        f = QFont(theme.MONO_FONT, 64)
        f.setBold(True)
        self.big.setFont(f)
        self.big.setStyleSheet(f"color:{theme.GREEN};")
        self.big.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.big)

        self.bar = QLabel("")
        bf = QFont(theme.MONO_FONT, 20)
        self.bar.setFont(bf)
        self.bar.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.bar)

        self.peak_lbl = QLabel("peak: --")
        self.peak_lbl.setAlignment(Qt.AlignCenter)
        self.peak_lbl.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.peak_lbl)

        gb = QGroupBox("RF")
        gl = QHBoxLayout(gb)
        gl.addWidget(widgets.GainPanel(self.hub))
        lay.addWidget(gb)
        lay.addStretch(1)

    def on_start(self):
        self._peak = -120.0
        self.start_rx(self._rx, block_size=16384)

    def _rx(self, iq):
        p = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)
        self._peak = max(self._peak, p)
        self.emit_ui(p)

    def _on_ui(self, p):
        self.big.setText(f"{p:5.1f} dB")
        color = theme.GREEN if p < -40 else (theme.ACCENT2 if p < -15 else theme.RED)
        self.big.setStyleSheet(f"color:{color};")
        bars = max(0, min(40, int((p + 90) / 2)))
        self.bar.setText("▮" * bars)
        self.peak_lbl.setText(f"peak: {self._peak:5.1f} dB")


register(AppInfo(
    id="level", name="Level", category="Receive",
    factory=lambda hub, audio, ctx: Level(hub, audio, ctx),
    description="Wideband signal strength meter with peak hold"))
