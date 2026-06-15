"""WSPR receiver — weak-signal propagation reporter via bundled wsprd.

WSPR transmits in 2-minute UTC-aligned cycles (110.6 s of 4-FSK at 1.4648 baud).
We demodulate the HF audio (USB), downconvert the 1500 Hz WSPR window to a
375 Hz baseband I/Q, and run the canonical ``wsprd`` decoder, tabling the
callsign / locator / power / SNR / frequency / drift of every spot.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time

import numpy as np
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WSPRD = os.path.join(_ROOT, "tools", "wspr", "wsprd_file")
WSPR_AUDIO = 12000
BB_RATE = 375
RAW = "/tmp/portapack_wspr.raw"

# WSPR dial frequencies (USB); audio window is dial + ~1500 Hz
BANDS = {"160m 1.8366": 1_836_600, "80m 3.5686": 3_568_600, "40m 7.0386": 7_038_600,
         "30m 10.1387": 10_138_700, "20m 14.0956": 14_095_600,
         "17m 18.1046": 18_104_600, "15m 21.0946": 21_094_600,
         "10m 28.1246": 28_124_600, "2m 144.4890": 144_489_000}


class WSPRRx(AppView):
    title = "WSPR"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.channel_offset = 1500.0
        self._acc = np.zeros(0, dtype=np.float32)
        self._cycle = None
        self._mixph = 0.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        self.freq = widgets.FrequencyDisplay(14_095_600, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        head.addWidget(self.freq)
        self.band = widgets.combo(list(BANDS.keys()))
        self.band.setCurrentText("20m 14.0956")
        self.band.currentTextChanged.connect(lambda t: self.freq.set_value(BANDS[t]))
        head.addWidget(self.band)
        head.addStretch(1)
        self.stat = QLabel("waiting for 2-min cycle…")
        head.addWidget(self.stat)
        lay.addLayout(head)

        self.spectrum = SpectrumWidget(history=70)
        lay.addWidget(self.spectrum, 1)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["UTC", "SNR", "DT", "Freq MHz", "Drift", "Call", "Loc/Pwr"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 2)
        if not os.path.exists(WSPRD):
            self.stat.setText("wsprd not built")

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.tuner = dsp.Tuner(fs, self.channel_offset)
        self.dec1 = dsp.best_decimation(fs, WSPR_AUDIO)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.1)
        self.ssb = dsp.SSBDemod(lsb=False)
        self.resamp = dsp.AudioResampler(self.if_rate, WSPR_AUDIO)
        self._acc = np.zeros(0, dtype=np.float32)
        self._cycle = None
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(self.tuner.process(iq))
        audio = self.resamp.process(self.ssb.process(chan))
        self._acc = np.concatenate([self._acc, audio])
        if len(self._acc) > WSPR_AUDIO * 130:
            self._acc = self._acc[-WSPR_AUDIO * 130:]
        cyc = int(time.time() // 120)
        if self._cycle is None:
            self._cycle = cyc
        elif cyc != self._cycle:
            buf = self._acc[-WSPR_AUDIO * 116:].copy()
            self._acc = np.zeros(0, dtype=np.float32)
            self._cycle = cyc
            if len(buf) > WSPR_AUDIO * 110:
                threading.Thread(target=self._decode, args=(buf,),
                                 daemon=True).start()
        self.emit_ui(("spec", power))

    def _decode(self, audio):
        try:
            # downconvert the 1500 Hz WSPR window to baseband, decimate to 375 Hz
            t = np.arange(len(audio)) / WSPR_AUDIO
            bb = audio * np.exp(-1j * 2 * np.pi * 1500.0 * t)
            from scipy.signal import resample_poly
            i = resample_poly(bb.real, BB_RATE, WSPR_AUDIO)
            q = resample_poly(bb.imag, BB_RATE, WSPR_AUDIO)
            n = min(len(i), 120 * BB_RATE)
            iq = np.empty(n * 2, dtype=np.float32)
            iq[0::2] = i[:n]
            iq[1::2] = q[:n]
            iq.tofile(RAW)
            dial = int(self.hub.cfg.frequency)
            out = subprocess.run([WSPRD, RAW, str(dial)], capture_output=True,
                                 text=True, timeout=60).stdout
            spots = []
            for line in out.splitlines():
                p = line.split()
                if len(p) >= 8 and p[0] == "WSPR":
                    spots.append(p[1:])     # snr dt freq drift call loc pwr
            self.emit_ui(("wspr", spots))
        except Exception as e:
            self.emit_ui(("err", str(e)))

    def _on_ui(self, payload):
        kind = payload[0]
        if kind == "spec":
            self.spectrum.update_spectrum(payload[1])
        elif kind == "wspr":
            spots = payload[1]
            for s in spots:
                self.table.insertRow(0)
                vals = [time.strftime("%H:%M"), s[0], s[1], s[2], s[3], s[4],
                        f"{s[5]}/{s[6]}" if len(s) > 6 else s[5]]
                for c, v in enumerate(vals):
                    self.table.setItem(0, c, QTableWidgetItem(v))
            self.stat.setText(f"{time.strftime('%H:%M:%S')} — {len(spots)} spots "
                              f"(total {self.table.rowCount()})")
        elif kind == "err":
            self.stat.setText(f"decode error: {payload[1]}")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="wspr_rx", name="WSPR", category="Receive",
    factory=lambda hub, audio, ctx: WSPRRx(hub, audio, ctx),
    description="WSPR weak-signal propagation decoder (wsprd)"))
