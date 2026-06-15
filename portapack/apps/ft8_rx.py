"""FT8 / FT4 receiver — weak-signal digital decode via bundled ft8_lib.

FT8 runs in 15-second UTC-aligned cycles (FT4 in 7.5 s).  We demodulate the
HF audio (USB), record each cycle to a 12 kHz WAV and run the ``decode_ft8``
tool, then table the decoded callsigns / grids / SNR.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import wave

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHeaderView, QHBoxLayout, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FT8_BIN = os.path.join(_ROOT, "tools", "ft8", "decode_ft8")
FT8_AUDIO = 12000
TMP_WAV = "/tmp/portapack_ft8.wav"

# common FT8 dial frequencies (USB), audio passband 0–3 kHz
BANDS = {"40m 7.074": 7_074_000, "30m 10.136": 10_136_000, "20m 14.074": 14_074_000,
         "17m 18.100": 18_100_000, "15m 21.074": 21_074_000, "10m 28.074": 28_074_000,
         "2m 144.174": 144_174_000}


class FT8Rx(AppView):
    title = "FT8"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.channel_offset = 1500.0      # park USB so the 0–3 kHz audio is centred
        self._acc = np.zeros(0, dtype=np.float32)
        self._cycle = None
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        self.freq = widgets.FrequencyDisplay(14_074_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        head.addWidget(self.freq)
        self.band = widgets.combo(list(BANDS.keys()))
        self.band.setCurrentText("20m 14.074")
        self.band.currentTextChanged.connect(lambda t: self.freq.set_value(BANDS[t]))
        head.addWidget(self.band)
        self.modesel = widgets.combo(["FT8 (15s)", "FT4 (7.5s)"])
        head.addWidget(self.modesel)
        head.addStretch(1)
        self.stat = QLabel("waiting for cycle…")
        head.addWidget(self.stat)
        lay.addLayout(head)

        self.spectrum = SpectrumWidget(history=80)
        lay.addWidget(self.spectrum, 1)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["UTC", "dB", "DT", "Freq", "Message"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 2)

        if not os.path.exists(FT8_BIN):
            self.stat.setText("ft8 decoder missing")

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.tuner = dsp.Tuner(fs, self.channel_offset)
        self.dec1 = dsp.best_decimation(fs, FT8_AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.13)
        self.ssb = dsp.SSBDemod(lsb=False)
        self.resamp = dsp.AudioResampler(self.if_rate, FT8_AUDIO)
        self._acc = np.zeros(0, dtype=np.float32)
        self._cycle = None
        self.start_rx(self._rx, block_size=131072)

    def _period(self):
        return 7.5 if self.modesel.currentIndex() == 1 else 15.0

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(self.tuner.process(iq))
        audio = self.resamp.process(self.ssb.process(chan))
        self._acc = np.concatenate([self._acc, audio])
        per = self._period()
        cyc = int(time.time() // per)
        if self._cycle is None:
            self._cycle = cyc
        elif cyc != self._cycle:
            # a cycle boundary passed — decode the accumulated audio
            buf = self._acc[-int(FT8_AUDIO * per):]
            self._acc = np.zeros(0, dtype=np.float32)
            self._cycle = cyc
            if len(buf) > FT8_AUDIO * (per - 1):
                threading.Thread(target=self._decode,
                                 args=(buf.copy(),), daemon=True).start()
        self.emit_ui(("spec", power))

    def _decode(self, buf):
        try:
            buf = np.clip(buf / (np.max(np.abs(buf)) + 1e-9) * 32767, -32768, 32767)
            with wave.open(TMP_WAV, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(FT8_AUDIO)
                w.writeframes(buf.astype("<i2").tobytes())
            cmd = [FT8_BIN] + (["-ft4"] if self.modesel.currentIndex() == 1 else []) + [TMP_WAV]
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout
            msgs = []
            for line in out.splitlines():
                parts = line.split()
                # format: HHMMSS +SNR dt freq ~ message...
                if len(parts) >= 6 and parts[0].isdigit() and "~" in parts:
                    ti = parts.index("~")
                    msgs.append((parts[0], parts[1], parts[2], parts[3],
                                 " ".join(parts[ti + 1:])))
            self.emit_ui(("ft8", msgs))
        except Exception as e:
            self.emit_ui(("err", str(e)))

    def _on_ui(self, payload):
        kind = payload[0]
        if kind == "spec":
            self.spectrum.update_spectrum(payload[1])
        elif kind == "ft8":
            msgs = payload[1]
            t = time.strftime("%H:%M:%S")
            for m in msgs:
                r = self.table.rowCount()
                self.table.insertRow(0)
                for c, v in enumerate(m):
                    self.table.setItem(0, c, QTableWidgetItem(v))
            self.stat.setText(f"{time.strftime('%H:%M:%S')} — decoded {len(msgs)} "
                              f"(total {self.table.rowCount()})")
        elif kind == "err":
            self.stat.setText(f"decode error: {payload[1]}")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="ft8_rx", name="FT8/FT4", category="Receive",
    factory=lambda hub, audio, ctx: FT8Rx(hub, audio, ctx),
    description="FT8 / FT4 weak-signal decoder (ft8_lib)"))
