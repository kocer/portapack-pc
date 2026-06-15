"""Audio Monitor — PC microphone level meter + spectrum (debug utility)."""
from __future__ import annotations
import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

try:
    import sounddevice as sd
    _HAVE_SD = True
except Exception:
    _HAVE_SD = False

RATE = 48000


class AudioMonitor(AppView):
    title = "Audio Monitor"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._stream = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        lay.addWidget(QLabel("PC microphone monitor"))
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Hz")
        self.plot.setYRange(-100, 0)
        self.curve = self.plot.plot(pen=pg.mkPen(theme.ACCENT))
        lay.addWidget(self.plot, 1)
        self.level = QLabel("level: —")
        f = self.level.font(); f.setPointSize(20); self.level.setFont(f)
        lay.addWidget(self.level)
        if not _HAVE_SD:
            self.level.setText("sounddevice unavailable")

    def on_start(self):
        if not _HAVE_SD:
            return
        try:
            self._stream = sd.InputStream(samplerate=RATE, channels=1,
                                          dtype="float32", blocksize=2048,
                                          callback=self._cb)
            self._stream.start()
        except Exception as e:
            self.level.setText(f"mic error: {e}")

    def _cb(self, indata, frames, t, status):
        x = indata[:, 0].copy()
        sp = np.abs(np.fft.rfft(x * np.hanning(len(x))))
        db = 20 * np.log10(sp / len(x) + 1e-9)
        rms = 20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-9)
        self.emit_ui((db, rms))

    def _on_ui(self, payload):
        db, rms = payload
        freqs = np.fft.rfftfreq(len(db) * 2 - 1, 1 / RATE)
        self.curve.setData(freqs[:len(db)], db)
        bars = max(0, min(30, int((rms + 60) / 2)))
        self.level.setText(f"level: {rms:6.1f} dBFS  " + "▮" * bars)

    def on_stop(self):
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None


register(AppInfo(id="audio_monitor", name="Audio Monitor", category="Utilities",
                 factory=lambda h, a, c: AudioMonitor(h, a, c),
                 description="PC microphone level + spectrum"))
