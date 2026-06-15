"""GFSK/FSK generic TX — transmit an arbitrary hex payload (testing/dev)."""
from __future__ import annotations
import numpy as np
from scipy import signal as ssig
from PySide6.QtWidgets import QLineEdit
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp


class GFSKTx(TxWaveApp):
    title = "GFSK TX"
    default_freq = 433_920_000
    tx_sample_rate = 2_400_000
    button_text = "SEND"

    def build_extra(self, layout):
        self.preamble = widgets.combo(["0xAA×4", "0x55×4", "none"])
        self.payload = QLineEdit("DEADBEEF1234")
        self.baud = widgets.combo(["2400", "9600", "38400", "100000", "250000"])
        self.baud.setCurrentText("38400")
        self.dev = widgets.LabeledSlider("Deviation", 2, 250, 20, suffix=" kHz")
        self.shape = widgets.combo(["FSK (square)", "GFSK (gaussian)"])
        self.rep = widgets.LabeledSlider("Repeats", 1, 20, 3)
        layout.addWidget(widgets.Field("Preamble", self.preamble))
        layout.addWidget(widgets.Field("Payload hex", self.payload))
        layout.addWidget(widgets.Field("Baud", self.baud))
        layout.addWidget(self.dev)
        layout.addWidget(widgets.Field("Shaping", self.shape))
        layout.addWidget(self.rep)

    def build_waveform(self):
        fs = self.tx_sample_rate
        baud = int(self.baud.currentText())
        hexstr = "".join(c for c in self.payload.text() if c in "0123456789abcdefABCDEF")
        if len(hexstr) % 2:
            hexstr += "0"
        data = bytes.fromhex(hexstr) if hexstr else b""
        pre = {0: b"\xAA\xAA\xAA\xAA", 1: b"\x55\x55\x55\x55",
               2: b""}[self.preamble.currentIndex()]
        frame = pre + data
        bits = []
        for byte in frame:
            for i in range(7, -1, -1):
                bits.append((byte >> i) & 1)
        bits = bits * self.rep.value()
        sps = int(fs / baud)
        nrz = np.repeat(np.array([1.0 if b else -1.0 for b in bits]), sps)
        if self.shape.currentIndex() == 1:  # gaussian shaping
            bt = 0.5
            span = sps
            t = np.arange(-span, span + 1) / sps
            g = np.exp(-2 * (np.pi * bt) ** 2 * t ** 2 / np.log(2))
            g /= g.sum()
            nrz = ssig.fftconvolve(nrz, g, "same")
        dev = self.dev.value() * 1000
        ph = np.cumsum(2 * np.pi * dev * nrz / fs)
        gap = np.zeros(int(fs * 0.02), dtype=np.complex64)
        wave = (0.9 * np.exp(1j * ph)).astype(np.complex64)
        return np.concatenate([wave, gap])


register(AppInfo(id="gfsk_tx", name="GFSK TX", category="Transmit", needs_tx=True,
                 factory=lambda h, a, c: GFSKTx(h, a, c),
                 description="Generic FSK/GFSK payload transmitter"))
