"""Digital Voice — DMR / dPMR / YSF / TETRA presence detection (4FSK sync).

Identifies digital-voice transmissions by their sync patterns and shows the
type/colour-code.  It does not run the proprietary AMBE/ACELP vocoders, so it
detects and classifies but does not play the voice audio (that needs an
external vocoder such as DSD/mbelib).
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import wave

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import DigitalVoiceDetector
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DSD_BIN = os.path.join(_ROOT, "tools", "dsd", "dsd-fme")
DSD_LIB = os.path.join(_ROOT, "tools", "dsd")


class DigitalVoice(AppView):
    title = "Digital Voice"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(446_100_000, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=100)
        left.addWidget(self.spectrum, 1)
        self.log = QListWidget()
        left.addWidget(self.log, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Mode")
        gl = QVBoxLayout(gb)
        self.proto = widgets.combo(["DMR (4FSK 4800)", "dPMR/NXDN (2400)",
                                    "YSF (4800)", "TETRA (detect)"])
        gl.addWidget(self.proto)
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        gbv = QGroupBox("Voice (dsd-fme)")
        gvl = QVBoxLayout(gbv)
        self.voice_btn = QPushButton("● Decode 8 s of voice")
        self.voice_btn.clicked.connect(self._decode_voice)
        gvl.addWidget(self.voice_btn)
        self.voice_stat = QLabel("AMBE vocoder via dsd-fme")
        self.voice_stat.setWordWrap(True)
        self.voice_stat.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        gvl.addWidget(self.voice_stat)
        if not os.path.exists(DSD_BIN):
            self.voice_btn.setEnabled(False)
            self.voice_stat.setText("dsd-fme not built")
        pl.addWidget(gbv)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        self.stat = QLabel("scanning for digital voice…")
        self.stat.setWordWrap(True)
        self.stat.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        pl.addWidget(self.stat)
        note = QLabel("Detects DMR sync (and flags 4FSK activity). Voice audio "
                      "needs an AMBE vocoder (DSD) — not bundled.")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        pl.addWidget(note)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 48_000)
        self.if_rate = fs / self.dec1
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.06)
        self.fm = dsp.FMDemod(2_400, self.if_rate, deemph_us=0)
        baud = 2400 if self.proto.currentIndex() == 1 else 4800
        self.dv = DigitalVoiceDetector(self.if_rate, baud)
        self._activity = 0.0
        self.vresamp = dsp.AudioResampler(self.if_rate, 48000)
        self._vbuf = np.zeros(0, dtype=np.float32)
        self._recording = False
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        if self._recording:
            a = self.vresamp.process(demod.astype(np.float32))
            self._vbuf = np.concatenate([self._vbuf, a])
            if len(self._vbuf) >= 48000 * 8:
                self._recording = False
                buf = self._vbuf[:48000 * 8].copy()
                self._vbuf = np.zeros(0, dtype=np.float32)
                threading.Thread(target=self._run_dsd, args=(buf,),
                                 daemon=True).start()
        act = float(np.std(demod))
        hits = self.dv.process(demod)
        self.emit_ui((power, hits, act))

    def _decode_voice(self):
        if not os.path.exists(DSD_BIN):
            return
        self._vbuf = np.zeros(0, dtype=np.float32)
        self._recording = True
        self.voice_stat.setText("recording 8 s…")

    def _run_dsd(self, buf):
        try:
            inp, outp = "/tmp/ppc_dsd_in.wav", "/tmp/ppc_dsd_out.wav"
            x = np.clip(buf / (np.max(np.abs(buf)) + 1e-9) * 32767, -32768, 32767)
            with wave.open(inp, "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
                w.writeframes(x.astype("<i2").tobytes())
            mode = {0: "-fs", 1: "-fd", 2: "-fy", 3: "-ft"}[self.proto.currentIndex()]
            env = dict(os.environ, LD_LIBRARY_PATH=DSD_LIB)
            subprocess.run([DSD_BIN, mode, "-i", inp, "-w", outp],
                           capture_output=True, timeout=40, env=env)
            played = False
            if os.path.exists(outp) and os.path.getsize(outp) > 100:
                from scipy.io import wavfile
                rate, data = wavfile.read(outp)
                if len(data) > 100:
                    audio = (data.astype(np.float32) /
                             (np.max(np.abs(data)) + 1e-9))
                    if rate != 48000:
                        audio = dsp.AudioResampler(rate, 48000).process(audio)
                    self.audio.push(audio)
                    played = True
            self.emit_ui(("voice", "decoded & playing voice" if played
                          else "no voice frames decoded"))
        except Exception as e:
            self.emit_ui(("voice", f"dsd error: {e}"))

    def _on_ui(self, payload):
        if len(payload) == 2 and payload[0] == "voice":
            self.voice_stat.setText(payload[1])
            return
        power, hits, act = payload
        self.spectrum.update_spectrum(power)
        for h in hits:
            self.log.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {h}")
        if hits:
            self.stat.setText(f"{self.log.count()} detections")
        elif act > 0.15:
            self.stat.setText("4FSK-like activity present (no DMR sync yet)")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="digital_voice", name="Digital Voice", category="Receive",
    factory=lambda hub, audio, ctx: DigitalVoice(hub, audio, ctx),
    description="DMR / dPMR / YSF / TETRA digital-voice detection"))
