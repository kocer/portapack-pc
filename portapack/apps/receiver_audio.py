"""Audio receiver — the PortaPack 'Audio' app, AM/NFM/WFM/SSB/SPEC.

Mirrors the Mayhem analog_audio app: modulation with per-mode bandwidth
configuration presets, frequency step, squelch, volume, AGC, antenna Bias-T,
RF front-end gains, spectrum/waterfall and demodulated-audio recording.
"""

from __future__ import annotations

import time
import wave

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import widgets
from ..ui.spectrum import SpectrumWidget
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView
import os

AUDIO_RATE = 48000

# Per-modulation bandwidth configuration presets (label, channel_bw, extra).
# Matches Mayhem: AM {DSB 9k, DSB 6k, USB+3k, LSB-3k, CW}, NFM {8k5,11k,12k5,16k},
# WFM {180k, 200k}.  ``extra`` is the FM deviation or the SSB sideband.
MODES = {
    "AM": {
        "kind": "am",
        "configs": [("DSB 9k", 9_000, "dsb"), ("DSB 6k", 6_000, "dsb"),
                    ("USB +3k", 3_000, "usb"), ("LSB -3k", 3_000, "lsb"),
                    ("CW", 1_500, "cw")],
    },
    "NFM": {
        "kind": "fm",
        "configs": [("8k5", 8_500, 2_500), ("11k", 11_000, 3_500),
                    ("12k5", 12_500, 4_000), ("16k", 16_000, 5_000)],
    },
    "WFM": {
        "kind": "fm",
        "configs": [("200k", 200_000, 75_000), ("180k", 180_000, 75_000)],
    },
    "SPEC": {"kind": "spec", "configs": [("Wide", 0, 0)]},
}


class AudioRX(AppView):
    title = "Audio RX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.mode = "WFM"
        self.cfg_index = 0
        self.channel_offset = 0.0
        self.squelch_db = -80.0
        self.use_agc = True
        self._recording = False
        self._wav = None
        self._build()
        self._init_dsp()

    # ---- UI ---------------------------------------------------------------
    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency, hub=self.hub)
        self.freq.frequency_changed.connect(self._set_center)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget()
        self.spectrum.frequency_clicked.connect(self._on_click_tune)
        left.addWidget(self.spectrum, 1)
        lay.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(258)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(4, 4, 4, 4)

        gb_mode = QGroupBox("Modulation")
        ml = QVBoxLayout(gb_mode)
        self.mode_box = widgets.combo(list(MODES.keys()))
        self.mode_box.currentTextChanged.connect(self._set_mode)
        ml.addWidget(widgets.Field("Mode", self.mode_box))
        self.bw_box = QComboBox()
        self.bw_box.currentIndexChanged.connect(self._set_cfg)
        ml.addWidget(widgets.Field("Bandwidth", self.bw_box))
        self.step_box = widgets.FreqStepCombo(self.hub)
        ml.addWidget(widgets.Field("Freq step", self.step_box))
        pl.addWidget(gb_mode)

        gb_rf = QGroupBox("RF")
        rl = QVBoxLayout(gb_rf)
        self.sr_box = widgets.combo(["2.4", "3.2", "5", "8", "10", "20"])
        self.sr_box.setCurrentText("2.4")
        self.sr_box.currentTextChanged.connect(self._set_rate)
        rl.addWidget(widgets.Field("Samp MHz", self.sr_box))
        self.gains = widgets.GainPanel(self.hub)
        rl.addWidget(self.gains)
        pl.addWidget(gb_rf)

        gb_audio = QGroupBox("Audio")
        al = QVBoxLayout(gb_audio)
        self.vol = widgets.LabeledSlider("Volume", 0, 100, 70, suffix="%")
        self.vol.valueChanged.connect(lambda v: setattr(self.audio, "volume",
                                                        v / 100.0))
        self.audio.volume = 0.7
        al.addWidget(self.vol)
        self.sql = widgets.LabeledSlider("Squelch", -100, 0,
                                         int(self.squelch_db), suffix=" dB")
        self.sql.valueChanged.connect(lambda v: setattr(self, "squelch_db",
                                                        float(v)))
        al.addWidget(self.sql)
        self.agc_box = widgets.combo(["AGC on", "AGC off"])
        self.agc_box.currentIndexChanged.connect(
            lambda i: setattr(self, "use_agc", i == 0))
        al.addWidget(self.agc_box)
        self.filt_box = widgets.combo(["Filter: off", "Notch", "Noise reduce"])
        self.filt_box.currentIndexChanged.connect(self._set_filter)
        al.addWidget(self.filt_box)
        self.notch_sl = widgets.LabeledSlider("Notch Hz", 200, 5000, 1000)
        self.notch_sl.valueChanged.connect(self._set_filter)
        al.addWidget(self.notch_sl)
        self.rec_btn = QPushButton("● Record audio")
        self.rec_btn.setCheckable(True)
        self.rec_btn.toggled.connect(self._toggle_record)
        al.addWidget(self.rec_btn)
        self.sig = QLabel("Signal: —")
        al.addWidget(self.sig)
        pl.addWidget(gb_audio)

        gb_disp = QGroupBox("Display")
        dl = QVBoxLayout(gb_disp)
        self.peak_box = widgets.combo(["Peak hold off", "Peak hold on"])
        self.peak_box.currentIndexChanged.connect(
            lambda i: self.spectrum.set_peak_hold(i == 1))
        dl.addWidget(self.peak_box)
        self.dc_box = widgets.combo(["DC spike on", "DC spike removed"])
        self.dc_box.setCurrentIndex(1)
        self.dc_box.currentIndexChanged.connect(self._set_dc)
        self.remove_dc = True
        dl.addWidget(self.dc_box)
        dl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gb_disp)

        pl.addStretch(1)
        lay.addWidget(panel)
        # sync the modulation combo to the initial mode (emits → builds bw list)
        self.mode_box.setCurrentText(self.mode)
        self._refresh_bw_box()

    def _refresh_bw_box(self):
        self.bw_box.blockSignals(True)
        self.bw_box.clear()
        for label, _bw, _x in MODES[self.mode]["configs"]:
            self.bw_box.addItem(label)
        self.bw_box.setCurrentIndex(min(self.cfg_index, self.bw_box.count() - 1))
        self.bw_box.blockSignals(False)

    # ---- DSP setup --------------------------------------------------------
    def _init_dsp(self):
        fs = self.hub.cfg.sample_rate
        spec = MODES[self.mode]
        kind = spec["kind"]
        label, ch_bw, extra = spec["configs"][self.cfg_index]
        self.tuner = dsp.Tuner(fs, self.channel_offset)
        self.dcb = dsp.ComplexDCBlocker()

        if kind == "spec":
            self.demod = None
            self.spectrum.configure(self.hub.cfg.frequency, fs)
            return

        target_if = max(ch_bw * 2.5, AUDIO_RATE * 4)
        self.dec1 = dsp.best_decimation(fs, target_if)
        self.if_rate = fs / self.dec1
        self.decimator = dsp.FirDecimator(self.dec1,
                                          cutoff_ratio=ch_bw / fs * 2)
        if kind == "fm":
            self.demod = dsp.FMDemod(extra, self.if_rate,
                                     deemph_us=50 if self.mode == "WFM" else 0)
        elif kind == "am":
            if extra == "dsb":
                self.demod = dsp.AMDemod()
            elif extra == "usb" or extra == "cw":
                self.demod = dsp.SSBDemod(lsb=False)
            else:
                self.demod = dsp.SSBDemod(lsb=True)
        self.audio_bw = ch_bw
        self.resampler = dsp.AudioResampler(self.if_rate, AUDIO_RATE)
        self.agc = dsp.AGC()
        self._notch = None
        self._nr = None
        self._set_filter()
        # tell the radio the matching IF filter bandwidth
        self.hub.set_bandwidth(min(max(ch_bw * 4, 1_750_000), fs))
        self.spectrum.configure(self.hub.cfg.frequency, fs)
        self.spectrum.set_tune_marker(self.hub.cfg.frequency + self.channel_offset)

    # ---- lifecycle --------------------------------------------------------
    def on_start(self):
        self._init_dsp()
        self.start_rx(self._rx)

    def on_stop(self):
        if self._recording:
            self.rec_btn.setChecked(False)

    # ---- worker thread DSP ------------------------------------------------
    def _rx(self, iq):
        if self.remove_dc:
            iq = self.dcb.process(iq)   # strip DC offset on the signal path
        power = dsp.psd(iq, nfft=2048)
        if self.demod is None:  # SPEC mode
            self.emit_ui((power, -120.0, None))
            return
        baseband = self.tuner.process(iq)
        chan = self.decimator.process(baseband)
        p = 10 * np.log10(np.mean(np.abs(chan) ** 2) + 1e-12)
        audio = self.demod.process(chan)
        if isinstance(self.demod, dsp.FMDemod):
            audio = dsp.lowpass(audio, min(self.audio_bw, 15000), self.if_rate)
        audio = self.resampler.process(audio)
        fmode = self.filt_box.currentIndex()
        if fmode == 1 and self._notch is not None:
            audio = self._notch.process(audio)
        elif fmode == 2 and self._nr is not None:
            audio = self._nr.process(audio)
        if self.use_agc and len(audio):
            audio = self.agc.process(audio)
        if p < self.squelch_db:
            audio = np.zeros_like(audio)
        self.audio.push(audio)
        if self._recording and self._wav is not None:
            try:
                self._wav.writeframes(
                    np.clip(audio * 32767, -32768, 32767).astype("<i2").tobytes())
            except Exception:
                pass
        # CTCSS sub-audible tone detection (NFM, every ~0.4 s of audio)
        ctcss = None
        if self.mode == "NFM" and p > self.squelch_db:
            self._ctcss_buf = np.concatenate([self._ctcss_buf, audio]) \
                if hasattr(self, "_ctcss_buf") else audio
            if len(self._ctcss_buf) >= int(AUDIO_RATE * 0.5):
                from ..sdr.decoders import detect_ctcss, detect_dcs
                tone = detect_ctcss(self._ctcss_buf, AUDIO_RATE)
                dcs = detect_dcs(self._ctcss_buf, AUDIO_RATE) if tone is None else None
                ctcss = (tone, dcs)
                self._ctcss_buf = np.zeros(0, dtype=np.float32)
        self.emit_ui((power, p, ctcss))

    def _on_ui(self, payload):
        power, p, ctcss = payload
        self.spectrum.update_spectrum(power)
        if p > -119:
            bars = max(0, min(20, int((p + 90) / 4)))
            txt = f"Signal: {p:6.1f} dB  " + "▮" * bars
            if ctcss:
                tone, dcs = ctcss
                if tone:
                    txt += f"\nCTCSS {tone:.1f} Hz"
                elif dcs:
                    txt += f"\nDCS {dcs}"
            self.sig.setText(txt)

    # ---- recording --------------------------------------------------------
    def _toggle_record(self, on):
        if on:
            os.makedirs(CAPTURE_DIR, exist_ok=True)
            path = os.path.join(
                CAPTURE_DIR, f"audio_{self.mode}_{int(self.hub.cfg.frequency)}Hz_"
                             f"{time.strftime('%Y%m%d_%H%M%S')}.wav")
            self._wav = wave.open(path, "wb")
            self._wav.setnchannels(1)
            self._wav.setsampwidth(2)
            self._wav.setframerate(AUDIO_RATE)
            self._recording = True
            self.rec_btn.setText("■ Stop recording")
            self.set_status(f"recording → {os.path.basename(path)}")
        else:
            self._recording = False
            if self._wav is not None:
                try:
                    self._wav.close()
                except Exception:
                    pass
                self._wav = None
            self.rec_btn.setText("● Record audio")

    # ---- controls ---------------------------------------------------------
    def _set_center(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)
        self.channel_offset = 0.0
        self.tuner.set_offset(0.0)
        self.spectrum.set_tune_marker(hz)

    def _on_click_tune(self, abs_hz):
        off = abs_hz - self.hub.cfg.frequency
        if abs(off) < self.hub.cfg.sample_rate / 2:
            self.channel_offset = off
            self.tuner.set_offset(off)
            self.spectrum.set_tune_marker(abs_hz)

    def _set_dc(self, i):
        self.remove_dc = (i == 1)
        self.spectrum.set_dc_removal(self.remove_dc)

    def _set_filter(self, *_):
        mode = self.filt_box.currentIndex()
        if mode == 1:
            self._notch = dsp.NotchFilter(self.notch_sl.value(), AUDIO_RATE)
        elif mode == 2:
            self._nr = dsp.NoiseReducer()

    def _set_mode(self, mode):
        self.mode = mode
        self.cfg_index = 0
        self._refresh_bw_box()
        self._init_dsp()

    def _set_cfg(self, idx):
        if idx < 0:
            return
        self.cfg_index = idx
        self._init_dsp()

    def _set_rate(self, txt):
        self.hub.set_sample_rate(float(txt) * 1e6)
        self.freq.set_value(self.hub.cfg.frequency, emit=False)
        if self._active:
            self.hub.start_rx(self._rx)
        self._init_dsp()


register(AppInfo(
    id="audio_rx", name="Audio", category="Receive",
    factory=lambda hub, audio, ctx: AudioRX(hub, audio, ctx),
    description="AM/NFM/WFM/SSB/SPEC receiver with bandwidth presets, "
                "Bias-T, recording and waterfall"))
