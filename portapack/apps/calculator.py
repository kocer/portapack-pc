"""RF Calculator — frequency/wavelength, power dBm↔W, link & Doppler helpers."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import (QGroupBox, QLabel, QLineEdit, QVBoxLayout)
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

C = 299_792_458.0


class Calculator(AppView):
    title = "Calculator"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)

        gb = QGroupBox("Frequency ↔ wavelength")
        gl = QVBoxLayout(gb)
        self.f_in = QLineEdit("433.92")
        self.f_in.textChanged.connect(self._calc)
        gl.addWidget(widgets.Field("Freq (MHz)", self.f_in))
        self.wl = QLabel("")
        gl.addWidget(self.wl)
        lay.addWidget(gb)

        gb2 = QGroupBox("Power dBm ↔ W")
        g2 = QVBoxLayout(gb2)
        self.p_in = QLineEdit("10")
        self.p_in.textChanged.connect(self._calc)
        g2.addWidget(widgets.Field("Power (dBm)", self.p_in))
        self.pw = QLabel("")
        g2.addWidget(self.pw)
        lay.addWidget(gb2)

        gb3 = QGroupBox("Doppler shift")
        g3 = QVBoxLayout(gb3)
        self.v_in = QLineEdit("100")
        self.v_in.textChanged.connect(self._calc)
        g3.addWidget(widgets.Field("Speed (m/s)", self.v_in))
        self.dop = QLabel("")
        g3.addWidget(self.dop)
        lay.addWidget(gb3)

        for w in (self.wl, self.pw, self.dop):
            w.setStyleSheet(f"color:{theme.ACCENT};")
        lay.addStretch(1)
        self._calc()

    def _calc(self, *_):
        try:
            f = float(self.f_in.text()) * 1e6
            wl = C / f
            self.wl.setText(f"λ = {wl*100:.2f} cm    λ/4 = {wl*25:.2f} cm    "
                            f"λ/2 = {wl*50:.2f} cm")
        except Exception:
            self.wl.setText("—")
        try:
            dbm = float(self.p_in.text())
            w = 10 ** ((dbm - 30) / 10)
            self.pw.setText(f"{w*1000:.4f} mW   =   {w:.6f} W")
        except Exception:
            self.pw.setText("—")
        try:
            f = float(self.f_in.text()) * 1e6
            v = float(self.v_in.text())
            shift = f * v / C
            self.dop.setText(f"±{shift:.1f} Hz at {f/1e6:.3f} MHz")
        except Exception:
            self.dop.setText("—")


register(AppInfo(id="calculator", name="Calculator", category="Utilities",
                 factory=lambda h, a, c: Calculator(h, a, c),
                 description="RF / antenna / power calculator"))
