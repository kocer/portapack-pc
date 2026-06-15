"""About — credits and feature list."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from ..ui import theme
from . import AppInfo, register, all_apps
from .base import AppView


class About(AppView):
    title = "About"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        t = QLabel("PortaPack PC")
        t.setStyleSheet(f"color:{theme.ACCENT};font-size:30px;font-weight:bold;")
        lay.addWidget(t)
        lay.addWidget(QLabel("A desktop reimagining of the PortaPack / Mayhem "
                             "firmware for HackRF One."))
        n = len(all_apps())
        lay.addWidget(QLabel(f"\n{n} applications registered.\n"))
        body = QLabel(
            "Inspired by:\n"
            "  • portapack-mayhem/mayhem-firmware\n"
            "  • furrtek/portapack-havoc\n\n"
            "Stack: PySide6 · SoapySDR (HackRF) · numpy/scipy · sounddevice\n\n"
            "Hardware: HackRF One — 1 MHz to 6 GHz, half-duplex, 20 Msps.\n"
            "Front-end gains: LNA 0-40 dB, VGA 0-62 dB, RF amp +14 dB.\n\n"
            "Transmit responsibly and legally — only on bands and power levels "
            "you are licensed/authorised to use.")
        body.setStyleSheet(f"color:{theme.FG};")
        lay.addWidget(body)
        lay.addStretch(1)


register(AppInfo(
    id="about", name="About", category="System",
    factory=lambda hub, audio, ctx: About(hub, audio, ctx),
    description="About PortaPack PC"))
