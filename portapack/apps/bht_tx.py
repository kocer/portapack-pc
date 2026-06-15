"""BHT TX — EU building/elevator tone signalling (Bowatone XY / FP, CCIR tones)."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QLineEdit
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp, fm_modulate

# CCIR tone set (Hz) for digits 0-9
CCIR = {0: 1981, 1: 1124, 2: 1197, 3: 1275, 4: 1358, 5: 1446,
        6: 1540, 7: 1640, 8: 1747, 9: 1860}


class BHTTx(TxWaveApp):
    title = "BHT TX"
    default_freq = 27_120_000
    tx_sample_rate = 2_400_000
    button_text = "SEND CODE"

    def build_extra(self, layout):
        self.system = widgets.combo(["Bowatone XY", "FP-5000", "CCIR raw"])
        self.code = QLineEdit("12345")
        self.tone_ms = widgets.LabeledSlider("Tone len", 40, 200, 100, suffix=" ms")
        layout.addWidget(widgets.Field("System", self.system))
        layout.addWidget(widgets.Field("Code", self.code))
        layout.addWidget(self.tone_ms)

    def build_waveform(self):
        fs = self.tx_sample_rate
        tlen = int(fs * self.tone_ms.value() / 1000)
        audio = []
        last = None
        for ch in self.code.text():
            if not ch.isdigit():
                continue
            d = int(ch)
            f = CCIR[d]
            if d == last:  # repeat tone (1981 Hz) for same consecutive digit
                f = CCIR[0]
            last = d
            t = np.arange(tlen) / fs
            audio.append(0.7 * np.sin(2 * np.pi * f * t))
        if not audio:
            return np.zeros(0, dtype=np.complex64)
        a = np.concatenate(audio).astype(np.float32)
        return fm_modulate(a, fs, 3000)


register(AppInfo(id="bht_tx", name="BHT TX", category="Transmit", needs_tx=True,
                 factory=lambda h, a, c: BHTTx(h, a, c),
                 description="EU building/elevator CCIR tone signalling"))
