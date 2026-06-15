"""Meteor-M2 LRPT — 137 MHz QPSK weather-satellite colour image.

Records the satellite-pass IQ (137.1 MHz, ~150 kS/s), then runs the bundled
``meteor_demod`` (QPSK → soft symbols) and ``meteor_decode`` (LRPT →
deinterleave/Viterbi/Reed-Solomon/JPEG → composite image) to build the picture.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import wave

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMOD = os.path.join(_ROOT, "tools", "meteor", "meteor_demod")
DECODE = os.path.join(_ROOT, "tools", "meteor", "meteor_decode")
LRPT_RATE = 150_000


class MeteorLRPT(AppView):
    title = "Meteor LRPT"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._iq = []
        self._recording = False
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(137_100_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=70)
        left.addWidget(self.spectrum, 1)
        self.glw = pg.GraphicsLayoutWidget()
        vb = self.glw.addViewBox(); vb.setAspectLocked(False); vb.invertY(True)
        self.img_item = pg.ImageItem()
        vb.addItem(self.img_item)
        left.addWidget(self.glw, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(230)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Capture")
        gl = QVBoxLayout(gb)
        self.sat = widgets.combo(["Meteor-M2 137.100", "Meteor-M2-3 137.900"])
        self.sat.currentIndexChanged.connect(
            lambda i: self.freq.set_value([137_100_000, 137_900_000][i]))
        gl.addWidget(self.sat)
        gl.addWidget(widgets.GainPanel(self.hub))
        self.rec_btn = QPushButton("● Record pass")
        self.rec_btn.setCheckable(True)
        self.rec_btn.toggled.connect(self._toggle_rec)
        gl.addWidget(self.rec_btn)
        self.rec_stat = QLabel("idle")
        gl.addWidget(self.rec_stat)
        pl.addWidget(gb)
        gb2 = QGroupBox("Decode")
        g2 = QVBoxLayout(gb2)
        self.dec_btn = QPushButton("⚙ Decode LRPT → image")
        self.dec_btn.clicked.connect(self._decode)
        g2.addWidget(self.dec_btn)
        self.dec_stat = QLabel("")
        self.dec_stat.setWordWrap(True)
        g2.addWidget(self.dec_stat)
        pl.addWidget(gb2)
        note = QLabel("QPSK 72k. Record a full ~10-min pass (QFH/turnstile "
                      "antenna), then decode. Needs meteor_demod/decode (built).")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        pl.addWidget(note)
        pl.addStretch(1)
        lay.addWidget(panel)
        if not (os.path.exists(DEMOD) and os.path.exists(DECODE)):
            self.dec_btn.setEnabled(False)
            self.dec_stat.setText("meteor tools not built")
        self._wavpath = os.path.join(CAPTURE_DIR, "meteor_iq.wav")

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, LRPT_RATE)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.7)
        self.start_rx(self._rx, block_size=262144)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        if self._recording:
            chan = self.decim.process(iq)
            self._iq.append(chan.copy())
            self._bytes = sum(len(c) for c in self._iq)
        self.emit_ui(power)

    def _on_ui(self, payload):
        if isinstance(payload, tuple) and payload and payload[0] in ("err", "stat", "img"):
            kind, val = payload
            if kind == "img":
                from PySide6.QtGui import QImage
                qi = QImage(val)
                if not qi.isNull():
                    arr = _qimage_to_np(qi)
                    self.img_item.setImage(np.transpose(arr, (1, 0, 2)),
                                           levels=(0, 255), autoLevels=False)
                    self.dec_stat.setText(f"✓ {os.path.basename(val)}")
                else:
                    self.dec_stat.setText("image load failed")
            else:
                self.dec_stat.setText(val)
            return
        power = payload
        self.spectrum.update_spectrum(power)
        if self._recording:
            n = sum(len(c) for c in self._iq)
            self.rec_stat.setText(f"REC {n/self.if_rate:5.0f}s  "
                                  f"{n*4/1e6:5.0f} MB")

    def _toggle_rec(self, on):
        if on:
            self._iq = []
            self._recording = True
            self.rec_btn.setText("■ Stop")
        else:
            self._recording = False
            self.rec_btn.setText("● Record pass")
            self._save_wav()

    def _save_wav(self):
        if not self._iq:
            return
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        iq = np.concatenate(self._iq)
        i16 = np.clip(np.stack([iq.real, iq.imag], axis=1) * 32767,
                      -32768, 32767).astype("<i2")
        with wave.open(self._wavpath, "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(int(self.if_rate))
            w.writeframes(i16.tobytes())
        self.rec_stat.setText(f"saved {os.path.getsize(self._wavpath)/1e6:.0f} MB")

    def _decode(self):
        if not os.path.exists(self._wavpath):
            self.dec_stat.setText("record a pass first")
            return
        self.dec_stat.setText("demodulating QPSK…")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            sym = "/tmp/ppc_meteor.s"
            png = os.path.join(CAPTURE_DIR,
                               f"meteor_{time.strftime('%Y%m%d_%H%M%S')}.png")
            r1 = subprocess.run([DEMOD, "-B", "-q", "-o", sym,
                                 "-s", str(int(self.if_rate)), "-r", "72000",
                                 self._wavpath], capture_output=True, text=True,
                                timeout=600)
            if not os.path.exists(sym) or os.path.getsize(sym) < 100:
                self.emit_ui(("err", f"demod produced no symbols ({r1.stderr[-100:]})"))
                return
            self.emit_ui(("stat", "decoding LRPT image…"))
            subprocess.run([DECODE, "-B", "-q", "-o", png, sym],
                           capture_output=True, text=True, timeout=300)
            if os.path.exists(png):
                self.emit_ui(("img", png))
            else:
                self.emit_ui(("err", "decode produced no image (weak/short pass?)"))
        except Exception as e:
            self.emit_ui(("err", str(e)))

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


def _qimage_to_np(qi):
    from PySide6.QtGui import QImage
    qi = qi.convertToFormat(QImage.Format_RGB888)
    w, h = qi.width(), qi.height()
    ptr = qi.constBits()
    arr = np.frombuffer(ptr, np.uint8).reshape(h, qi.bytesPerLine())
    return np.ascontiguousarray(arr[:, :w * 3].reshape(h, w, 3))


register(AppInfo(
    id="meteor_lrpt", name="Meteor LRPT", category="Receive",
    factory=lambda hub, audio, ctx: MeteorLRPT(hub, audio, ctx),
    description="Meteor-M2 LRPT colour weather image (QPSK)"))
