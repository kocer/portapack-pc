"""Tones TX — DTMF dialer and CTCSS sub-audible tone generator (FM)."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QLabel, QLineEdit, QVBoxLayout)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

DTMF = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}
CTCSS = [67.0, 71.9, 77.0, 88.5, 100.0, 103.5, 110.9, 123.0, 131.8, 141.3,
         156.7, 173.8, 192.8, 203.5, 210.7, 233.6, 250.3]


class TonesTx(AppView):
    title = "Tones TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._wave = None
        self._pos = 0
        self._mphase = 0.0
        self._cont = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        gb = QGroupBox("Mode")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(["DTMF sequence", "CTCSS tone (FM)",
                                   "Single tone (FM)"])
        self.mode.currentIndexChanged.connect(self._mode_changed)
        gl.addWidget(self.mode)
        self.dtmf_in = QLineEdit("0123456789*#")
        gl.addWidget(widgets.Field("DTMF", self.dtmf_in))
        self.ctcss = widgets.combo([f"{x:.1f} Hz" for x in CTCSS])
        gl.addWidget(widgets.Field("CTCSS", self.ctcss))
        self.tone = widgets.LabeledSlider("Tone", 50, 3000, 1000, suffix=" Hz")
        gl.addWidget(self.tone)
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
        self.tx_btn = widgets.tx_button("SEND")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel(""); self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def _mode_changed(self, i):
        pass

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _build_dtmf(self):
        fs = self.hub.cfg.sample_rate
        tone_len = int(fs * 0.12)
        gap = int(fs * 0.06)
        parts = []
        for ch in self.dtmf_in.text().upper():
            if ch not in DTMF:
                continue
            f1, f2 = DTMF[ch]
            t = np.arange(tone_len) / fs
            audio = 0.5 * (np.sin(2 * np.pi * f1 * t) + np.sin(2 * np.pi * f2 * t))
            # AM-style baseband (directly as IQ magnitude)
            parts.append((0.5 + 0.4 * audio).astype(np.complex64))
            parts.append(np.zeros(gap, dtype=np.complex64))
        self._wave = np.concatenate(parts) if parts else None
        self._cont = False
        self._pos = 0

    def _toggle(self, on):
        if on:
            mode = self.mode.currentIndex()
            if mode == 0:
                self._build_dtmf()
                if self._wave is None:
                    self.tx_btn.setChecked(False); return
            else:
                self._cont = True
                self._mphase = 0.0
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop(); self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            return None
        if self._cont:
            fs = self.hub.cfg.sample_rate
            if self.mode.currentIndex() == 1:
                f = CTCSS[self.ctcss.currentIndex()]
            else:
                f = self.tone.value()
            t = np.arange(n) / fs
            audio = np.sin(2 * np.pi * f * t)
            dev = 2500
            ph = self._mphase + np.cumsum(audio) / fs * 2 * np.pi * dev
            self._mphase = ph[-1] % (2 * np.pi)
            return self._monitor((0.9 * np.exp(1j * ph)).astype(np.complex64))
        # DTMF one-shot
        if self._wave is None or self._pos >= len(self._wave):
            self.emit_ui("done"); return None
        out = np.zeros(n, dtype=np.complex64)
        take = min(n, len(self._wave) - self._pos)
        out[:take] = self._wave[self._pos:self._pos + take]
        self._pos += take
        return self._monitor(out)

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False); self.warn.setText("sent")


    def _monitor(self, iq):
        if (iq is not None and self.monitor_box.isChecked()
                and self.audio is not None):
            from ._txbase import tx_monitor_audio
            m = tx_monitor_audio(iq, self.hub.cfg.sample_rate)
            if m is not None:
                self.audio.push(m)
        return iq


register(AppInfo(
    id="tones_tx", name="Tones TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: TonesTx(hub, audio, ctx),
    description="DTMF dialer + CTCSS / single-tone FM generator"))
