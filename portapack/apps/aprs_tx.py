"""APRS transmitter — beacon an AX.25 position/status packet (AFSK1200 FM)."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QLineEdit
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp, ax25_afsk, hdlc_frame


def _addr(call, ssid, last=False):
    call = (call.upper() + "      ")[:6]
    return bytes(((ord(c) << 1) & 0xFE) for c in call) + \
        bytes([0x60 | ((ssid & 0x0F) << 1) | (1 if last else 0)])


class APRSTx(TxWaveApp):
    title = "APRS TX"
    default_freq = 144_800_000
    tx_sample_rate = 2_400_000
    button_text = "BEACON"

    def build_extra(self, layout):
        self.src = QLineEdit("N0CALL-9")
        self.dst = QLineEdit("APRS")
        self.path = QLineEdit("WIDE1-1")
        self.info = QLineEdit("!4807.00N/01131.00E>PortaPack PC APRS")
        layout.addWidget(widgets.Field("Source", self.src))
        layout.addWidget(widgets.Field("Dest", self.dst))
        layout.addWidget(widgets.Field("Path", self.path))
        layout.addWidget(widgets.Field("Info", self.info))

    def build_waveform(self):
        def parse(c):
            if "-" in c:
                call, ssid = c.split("-"); return call, int(ssid)
            return c, 0
        sc, ss = parse(self.src.text())
        dc, ds = parse(self.dst.text())
        addr = _addr(dc, ds) + _addr(sc, ss)
        if self.path.text().strip():
            pc, ps = parse(self.path.text())
            addr += _addr(pc, ps, last=True)
        else:
            addr = _addr(dc, ds) + _addr(sc, ss, last=True)
        frame = addr + bytes([0x03, 0xF0]) + self.info.text().encode("ascii", "replace")
        bits = hdlc_frame(frame)
        return ax25_afsk(bits, self.tx_sample_rate)


register(AppInfo(id="aprs_tx", name="APRS TX", category="Transmit", needs_tx=True,
                 factory=lambda h, a, c: APRSTx(h, a, c),
                 description="Beacon AX.25/APRS position packets"))
