"""Morse / CW transmitter — keys text as on-off carrier."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QLabel, QLineEdit, QVBoxLayout)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..", "0": "-----", "1": ".----", "2": "..---",
    "3": "...--", "4": "....-", "5": ".....", "6": "-....", "7": "--...",
    "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..",
    "/": "-..-.", "=": "-...-", "-": "-....-", " ": " ",
}


class MorseTx(AppView):
    title = "Morse TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._wave = None
        self._pos = 0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        gb = QGroupBox("Message")
        gl = QVBoxLayout(gb)
        self.text = QLineEdit("CQ CQ DE PORTAPACK PC")
        gl.addWidget(self.text)
        self.wpm = widgets.LabeledSlider("Speed", 5, 40, 18, suffix=" WPM")
        gl.addWidget(self.wpm)
        self.tone = widgets.LabeledSlider("Side tone", 300, 1200, 700, suffix=" Hz")
        gl.addWidget(self.tone)
        self.preview = QLabel("")
        self.preview.setStyleSheet(f"color:{theme.FG_DIM};")
        self.preview.setWordWrap(True)
        gl.addWidget(self.preview)
        lay.addWidget(gb)
        gb2 = QGroupBox("TX gain"); g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 30, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub)); lay.addWidget(gb2)
        from PySide6.QtWidgets import QCheckBox
        self.monitor_box = QCheckBox("🔊 Monitor (local sidetone)")
        g2.addWidget(self.monitor_box)
        self.tx_btn = widgets.tx_button("KEY")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel(""); self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _build_wave(self):
        fs = self.hub.cfg.sample_rate
        unit = int(fs * (1.2 / self.wpm.value()))  # dot length in samples
        msg = self.text.text().upper()
        seq = []
        morse_str = []
        for ch in msg:
            code = MORSE.get(ch)
            if code is None:
                continue
            if code == " ":
                seq.append(("gap", unit * 4))
                morse_str.append("/")
                continue
            for sym in code:
                seq.append(("on", unit if sym == "." else unit * 3))
                seq.append(("gap", unit))
            seq.append(("gap", unit * 2))  # letter gap (total 3)
            morse_str.append(code)
        self.preview.setText(" ".join(morse_str))
        env = []
        for kind, n in seq:
            env.append(np.ones(n) if kind == "on" else np.zeros(n))
        if not env:
            self._wave = None
            return
        e = np.concatenate(env).astype(np.float32)
        # raised-cosine edges to avoid key clicks
        r = max(1, unit // 8)
        ramp = (1 - np.cos(np.linspace(0, np.pi, r))) / 2
        self._wave = (e * 0.9).astype(np.complex64)
        self._pos = 0

    def _toggle(self, on):
        if on:
            self._build_wave()
            if self._wave is None:
                self.tx_btn.setChecked(False); return
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop(); self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked() or self._wave is None:
            return None
        if self._pos >= len(self._wave):
            self.emit_ui("done"); return None
        out = np.zeros(n, dtype=np.complex64)
        take = min(n, len(self._wave) - self._pos)
        out[:take] = self._wave[self._pos:self._pos + take]
        self._pos += take
        return self._monitor(out)

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False)
            self.warn.setText("sent")


    def _monitor(self, iq):
        # CW has no audio tone (the carrier is just keyed on/off), so synthesise
        # a side-tone beep gated by the keying envelope — like a real CW rig.
        if (iq is not None and self.monitor_box.isChecked()
                and self.audio is not None and len(iq)):
            fs = self.hub.cfg.sample_rate
            q = max(1, int(fs // 48000))
            env = np.abs(iq[::q]).astype(np.float32)      # keying envelope @ ~48k
            env = (env > 0.3).astype(np.float32)
            f = self.tone.value()
            t = (np.arange(len(env)) + getattr(self, "_mon_ph", 0)) / 48000.0
            self._mon_ph = getattr(self, "_mon_ph", 0) + len(env)
            beep = 0.4 * np.sin(2 * np.pi * f * t).astype(np.float32) * env
            self.audio.push(beep)
        return iq


register(AppInfo(
    id="morse_tx", name="Morse TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: MorseTx(hub, audio, ctx),
    description="CW/Morse keyer from text"))
