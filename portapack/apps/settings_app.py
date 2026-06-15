"""Settings — device info, frequency correction, default front-end values."""

from __future__ import annotations

from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr.backend import enumerate_devices
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class Settings(AppView):
    title = "Settings"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)

        gb = QGroupBox("Device")
        gl = QVBoxLayout(gb)
        self.dev_lbl = QLabel()
        gl.addWidget(self.dev_lbl)
        rescan = QPushButton("Rescan / reconnect HackRF")
        rescan.clicked.connect(self._rescan)
        gl.addWidget(rescan)
        lay.addWidget(gb)

        gb2 = QGroupBox("Front-end defaults")
        g2 = QVBoxLayout(gb2)
        self.corr = widgets.LabeledSlider("Freq correction", -100, 100,
                                          int(self.hub.cfg.freq_corr_ppm),
                                          suffix=" ppm")
        self.corr.valueChanged.connect(lambda v: self.hub.set_freq_correction(v))
        g2.addWidget(self.corr)
        self.amp = widgets.LabeledSlider("Default LNA", 0, 40,
                                         int(self.hub.cfg.lna_gain),
                                         step=8, suffix=" dB")
        self.amp.valueChanged.connect(lambda v: self.hub.set_gains(lna=v))
        g2.addWidget(self.amp)
        self.bias = widgets.BiasTeeBox(self.hub)
        g2.addWidget(self.bias)
        lay.addWidget(gb2)

        gb3 = QGroupBox("Audio")
        g3 = QVBoxLayout(gb3)
        avail = "available" if self.audio.available else "UNAVAILABLE"
        g3.addWidget(QLabel(f"Output: {self.audio.sample_rate} Hz mono ({avail})"))
        lay.addWidget(gb3)

        lay.addStretch(1)
        self._refresh_dev()

    def _refresh_dev(self):
        devs = enumerate_devices()
        if self.hub.is_sim:
            txt = "Mode: SIMULATION (no HackRF)\n"
        else:
            txt = f"Mode: HARDWARE ({self.hub.driver})\n"
        if devs:
            txt += "\n".join(f"• {d.get('label', d)}" for d in devs)
        else:
            txt += "No SoapySDR devices enumerated."
        self.dev_lbl.setText(txt)

    def _rescan(self):
        self.hub.rescan()
        self._refresh_dev()


register(AppInfo(
    id="settings", name="Settings", category="System",
    factory=lambda hub, audio, ctx: Settings(hub, audio, ctx),
    description="Device, calibration and audio settings"))
