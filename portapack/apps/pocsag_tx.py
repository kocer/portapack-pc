"""POCSAG transmitter — send a pager message (FSK)."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QLineEdit
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp, fsk_modulate

SYNC = 0x7CD215D8
IDLE = 0x7A89C197


def _bch_parity(data21):
    # POCSAG (31,21) BCH + even parity — generate 10 parity bits + 1 parity
    cw = data21 << 11
    g = 0b11101101001
    for i in range(30, 10, -1):
        if cw & (1 << i):
            cw ^= g << (i - 10)
    full = (data21 << 11) | (cw & 0x7FF)
    # even parity bit
    p = bin(full).count("1") & 1
    return (full << 1) | p


def _addr_word(addr, func):
    data = ((addr >> 3) << 2) | (func & 3)
    return _bch_parity(data & 0x1FFFFF)


def _char_words(text):
    bits = []
    for ch in text:
        v = ord(ch) & 0x7F
        for i in range(7):
            bits.append((v >> i) & 1)  # LSB first
    out = []
    for i in range(0, len(bits), 20):
        chunk = bits[i:i + 20]
        chunk += [0] * (20 - len(chunk))   # pad final group
        data = 0
        for b in chunk:
            data = (data << 1) | b
        # message codeword: MSB flag = 1, then 20 data bits + BCH/parity
        w = (_bch_parity(data) | (1 << 31)) & 0xFFFFFFFF
        out.append(w)
    return out


class POCSAGTx(TxWaveApp):
    title = "POCSAG TX"
    default_freq = 153_350_000
    tx_sample_rate = 2_400_000
    button_text = "PAGE"

    def build_extra(self, layout):
        self.addr = QLineEdit("1234567")
        self.msg = QLineEdit("PORTAPACK PC TEST")
        self.baud = widgets.combo(["512", "1200", "2400"]); self.baud.setCurrentText("1200")
        layout.addWidget(widgets.Field("Address", self.addr))
        layout.addWidget(widgets.Field("Message", self.msg))
        layout.addWidget(widgets.Field("Baud", self.baud))

    def build_waveform(self):
        baud = int(self.baud.currentText())
        addr = int(self.addr.text() or "0")
        words = [_addr_word(addr, 0)] + _char_words(self.msg.text())
        # build one batch: preamble + (SYNC + 16 frames) padded with IDLE
        batch = words + [IDLE] * (16 - (len(words) % 16) if len(words) % 16 else 0)
        bits = [1, 0] * 288  # 576-bit preamble
        def wbits(w):
            return [(w >> i) & 1 for i in range(31, -1, -1)]
        bits += wbits(SYNC)
        for i, w in enumerate(batch):
            bits += wbits(w)
            if (i + 1) % 16 == 0 and i + 1 < len(batch):
                bits += wbits(SYNC)
        return fsk_modulate(bits, self.tx_sample_rate, baud, shift=9000)


register(AppInfo(id="pocsag_tx", name="POCSAG TX", category="Transmit", needs_tx=True,
                 factory=lambda h, a, c: POCSAGTx(h, a, c),
                 description="Transmit a POCSAG pager message"))
