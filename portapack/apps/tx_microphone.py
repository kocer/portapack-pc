"""Microphone transmitter — live WFM/NFM voice from the PC mic (walkie-talkie)."""

from __future__ import annotations

import threading

import numpy as np
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ..sdr import dsp
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

try:
    import sounddevice as sd
    _HAVE_SD = True
except Exception:
    _HAVE_SD = False

MIC_RATE = 48000


class TxMicrophone(AppView):
    title = "Mic TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._mic_buf = np.zeros(0, dtype=np.float32)
        self._lock = threading.Lock()
        self._stream = None
        self._mphase = 0.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        gb = QGroupBox("Modulation")
        gl = QVBoxLayout(gb)
        self.mode = widgets.combo(["NFM", "WFM", "AM"])
        gl.addWidget(widgets.Field("Mode", self.mode))
        self.dev = widgets.LabeledSlider("FM dev", 1, 100, 5, suffix=" kHz")
        gl.addWidget(self.dev)
        self.micgain = widgets.LabeledSlider("Mic gain", 1, 100, 50, suffix="%")
        gl.addWidget(self.micgain)
        from .tones_tx import CTCSS
        self._ctcss = CTCSS
        self.ctcss_box = widgets.combo(["off"] + [f"{x:.1f} Hz" for x in CTCSS])
        gl.addWidget(widgets.Field("CTCSS", self.ctcss_box))
        lay.addWidget(gb)

        gb3 = QGroupBox("Options")
        g3 = QVBoxLayout(gb3)
        from PySide6.QtWidgets import QCheckBox
        self.roger = QCheckBox("Roger beep on release")
        g3.addWidget(self.roger)
        self.vox = QCheckBox("VOX (voice activated)")
        self.vox.toggled.connect(self._vox_toggled)
        g3.addWidget(self.vox)
        self.vox_th = widgets.LabeledSlider("VOX level", 1, 50, 8, suffix="%")
        g3.addWidget(self.vox_th)
        lay.addWidget(gb3)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 30, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        self.bias_box = widgets.BiasTeeBox(self.hub)
        g2.addWidget(self.bias_box)
        from PySide6.QtWidgets import QCheckBox
        self.monitor_box = QCheckBox("🔊 Monitor (hear your voice)")
        g2.addWidget(self.monitor_box)
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button("PTT (transmit)")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self._ctcss_phase = 0.0
        self._roger_left = 0
        self._mic_level = 0.0
        from PySide6.QtCore import QTimer
        self._vox_timer = QTimer(self)
        self._vox_timer.timeout.connect(self._vox_tick)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            if not _HAVE_SD:
                self.warn.setText("sounddevice unavailable")
                self.tx_btn.setChecked(False)
                return
            self.hub.set_sample_rate(2_400_000)
            self._resampler = dsp.AudioResampler(MIC_RATE, self.hub.cfg.sample_rate)
            try:
                self._stream = sd.InputStream(samplerate=MIC_RATE, channels=1,
                                              dtype="float32", blocksize=2048,
                                              callback=self._mic_cb)
                self._stream.start()
            except Exception as e:
                self.warn.setText(f"mic error: {e}")
                self.tx_btn.setChecked(False)
                return
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            if self._stream is not None:
                try:
                    self._stream.stop(); self._stream.close()
                except Exception:
                    pass
                self._stream = None
            self.warn.setText("")

    def _mic_cb(self, indata, frames, t, status):
        x = indata[:, 0] * (self.micgain.value() / 50.0)
        self._mic_level = float(np.sqrt(np.mean(indata[:, 0] ** 2)))
        with self._lock:
            self._mic_buf = np.concatenate([self._mic_buf, x.astype(np.float32)])
            if len(self._mic_buf) > MIC_RATE * 2:
                self._mic_buf = self._mic_buf[-MIC_RATE * 2:]

    # ---- VOX --------------------------------------------------------------
    def _vox_toggled(self, on):
        if on:
            self.hub.set_sample_rate(2_400_000)
            self._resampler = dsp.AudioResampler(MIC_RATE, self.hub.cfg.sample_rate)
            self._open_mic()
            self._vox_timer.start(100)
            self.warn.setText("VOX armed — speak to transmit")
        else:
            self._vox_timer.stop()
            if not self.tx_btn.isChecked():
                self._close_mic()
            self.warn.setText("")

    def _vox_tick(self):
        thr = self.vox_th.value() / 100.0
        if self._mic_level > thr and not self.tx_btn.isChecked():
            self.tx_btn.setChecked(True)
            self._vox_hang = 8
        elif self.tx_btn.isChecked():
            if self._mic_level < thr * 0.6:
                self._vox_hang = getattr(self, "_vox_hang", 8) - 1
                if self._vox_hang <= 0:
                    self.tx_btn.setChecked(False)
            else:
                self._vox_hang = 8

    def _open_mic(self):
        if self._stream is not None or not _HAVE_SD:
            return
        try:
            self._stream = sd.InputStream(samplerate=MIC_RATE, channels=1,
                                          dtype="float32", blocksize=2048,
                                          callback=self._mic_cb)
            self._stream.start()
        except Exception as e:
            self.warn.setText(f"mic error: {e}")

    def _close_mic(self):
        if self._stream is not None:
            try:
                self._stream.stop(); self._stream.close()
            except Exception:
                pass
            self._stream = None

    def _gen(self, n):
        if not self.tx_btn.isChecked():
            # roger beep: emit a short tone burst after release, then finish
            if self.roger.isChecked() and self._roger_left > 0:
                return self._roger_burst(n)
            return None
        fs = self.hub.cfg.sample_rate
        need_mic = int(n * MIC_RATE / fs) + 4
        with self._lock:
            if len(self._mic_buf) >= need_mic:
                chunk = self._mic_buf[:need_mic]
                self._mic_buf = self._mic_buf[need_mic:]
            else:
                chunk = np.zeros(need_mic, dtype=np.float32)
        audio = self._resampler.process(chunk)
        if len(audio) < n:
            audio = np.pad(audio, (0, n - len(audio)))
        audio = audio[:n]
        # mix CTCSS sub-audible tone
        ci = self.ctcss_box.currentIndex()
        if ci > 0:
            f = self._ctcss[ci - 1]
            t = (np.arange(n) + self._ctcss_phase) / fs
            self._ctcss_phase += n
            audio = audio * 0.85 + 0.15 * np.sin(2 * np.pi * f * t).astype(np.float32)
        self._roger_left = int(0.15 * fs)  # arm roger beep for next release
        return self._modulate(audio, fs, n)

    def _roger_burst(self, n):
        fs = self.hub.cfg.sample_rate
        take = min(n, self._roger_left)
        t = (np.arange(take)) / fs
        beep = 0.6 * np.sin(2 * np.pi * 1200 * t).astype(np.float32)
        self._roger_left -= take
        audio = np.pad(beep, (0, n - take))
        if self._roger_left <= 0:
            # final block
            return self._modulate(audio, fs, n)
        return self._modulate(audio, fs, n)

    def _modulate(self, audio, fs, n):
        # local monitor: play the mic audio itself (true sidetone)
        if self.monitor_box.isChecked() and self.audio is not None and len(audio):
            self.audio.push(np.clip(audio * 0.5, -1, 1).astype(np.float32))
        mode = self.mode.currentIndex()
        if mode == 2:  # AM
            return (0.5 * (1 + audio)).astype(np.complex64)
        dev = self.dev.value() * 1000 if mode == 0 else 75_000
        ph = self._mphase + np.cumsum(audio) / fs * 2 * np.pi * dev
        self._mphase = ph[-1] % (2 * np.pi)
        return (0.9 * np.exp(1j * ph)).astype(np.complex64)


register(AppInfo(
    id="tx_mic", name="Mic TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: TxMicrophone(hub, audio, ctx),
    description="Live FM/AM voice transmit from the PC microphone"))
