"""Scanner / Recon — sweep a range or channel list, stop on active signals."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QPushButton, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class Scanner(AppView):
    title = "Scanner"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.start_hz = 144_000_000
        self.stop_hz = 146_000_000
        self.step_hz = 25_000
        self.squelch = -45.0
        self._cur = self.start_hz
        self._settle = 0
        self._holding = False
        self._hold_left = 0
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        left = QVBoxLayout()
        self.cur_lbl = QLabel("--")
        f = self.cur_lbl.font(); f.setPointSize(30); f.setBold(True)
        self.cur_lbl.setFont(f)
        self.cur_lbl.setStyleSheet(f"color:{theme.ACCENT};")
        left.addWidget(self.cur_lbl)
        self.state_lbl = QLabel("idle")
        self.state_lbl.setStyleSheet(f"color:{theme.FG_DIM};")
        left.addWidget(self.state_lbl)
        left.addWidget(widgets.section("Activity log"))
        self.log = QListWidget()
        left.addWidget(self.log, 1)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(240)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Range")
        gl = QVBoxLayout(gb)
        self.start_disp = widgets.FrequencyDisplay(144_000_000, hub=self.hub,
                                                   font_pt=13)
        self.stop_disp = widgets.FrequencyDisplay(146_000_000, hub=self.hub,
                                                  font_pt=13)
        self.start_disp.frequency_changed.connect(self._reconf)
        self.stop_disp.frequency_changed.connect(self._reconf)
        gl.addWidget(QLabel("Start"))
        gl.addWidget(self.start_disp)
        gl.addWidget(QLabel("Stop"))
        gl.addWidget(self.stop_disp)
        self.step_box = widgets.combo(["6.25", "12.5", "25", "100", "200"])
        self.step_box.setCurrentText("25")
        self.step_box.currentTextChanged.connect(self._reconf)
        gl.addWidget(widgets.Field("Step kHz", self.step_box))
        pl.addWidget(gb)
        gbm = QGroupBox("Mode")
        gml = QVBoxLayout(gbm)
        self.scanmode_box = widgets.combo(["RECON (range)", "SCAN (presets)"])
        gml.addWidget(widgets.Field("Engine", self.scanmode_box))
        self.demod_box = widgets.combo(["NFM", "AM", "WFM", "Log only"])
        gml.addWidget(widgets.Field("Listen", self.demod_box))
        self.bw_box = widgets.combo(["8k5", "12k5", "16k", "wide"])
        self.bw_box.setCurrentText("12k5")
        gml.addWidget(widgets.Field("Bandwidth", self.bw_box))
        self.match_box = widgets.combo(["Continuous", "Sparse"])
        gml.addWidget(widgets.Field("Match", self.match_box))
        pl.addWidget(gbm)

        gb2 = QGroupBox("Detector")
        g2 = QVBoxLayout(gb2)
        self.sql = widgets.LabeledSlider("Squelch", -90, -10, int(self.squelch),
                                         suffix=" dB")
        self.sql.valueChanged.connect(lambda v: setattr(self, "squelch", float(v)))
        g2.addWidget(self.sql)
        self.wait_sl = widgets.LabeledSlider("Wait (hang)", 0, 80, 40,
                                             suffix=" blk")
        g2.addWidget(self.wait_sl)
        self.lock_sl = widgets.LabeledSlider("Lock confirm", 0, 20, 2,
                                             suffix=" blk")
        g2.addWidget(self.lock_sl)
        g2.addWidget(widgets.Field("Freq step", widgets.FreqStepCombo(self.hub)))
        g2.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb2)
        self.resume_btn = QPushButton("Resume scan")
        self.resume_btn.clicked.connect(self._resume)
        pl.addWidget(self.resume_btn)
        pl.addStretch(1)
        lay.addWidget(panel)
        self._lock_count = 0

    def _reconf(self, *_):
        self.start_hz = float(self.start_disp.value())
        self.stop_hz = float(self.stop_disp.value())
        self.step_hz = float(self.step_box.currentText()) * 1e3
        if self.stop_hz <= self.start_hz:
            self.stop_hz = self.start_hz + self.step_hz * 10
        self._cur = self.start_hz

    # SCAN-mode preset frequency list (loaded from freqman if present)
    SCAN_PRESETS = [446_006_250, 446_018_750, 446_031_250, 446_043_750,
                    145_500_000, 433_500_000, 27_185_000, 156_800_000]

    def on_start(self):
        self._reconf()
        self.hub.set_sample_rate(2_400_000)
        self._cur = self.start_hz
        self._scan_idx = 0
        self._holding = False
        self.audio.volume = 0.7
        fs = self.hub.cfg.sample_rate
        # channel filter bandwidth from selection
        bw = {"8k5": 8_500, "12k5": 12_500, "16k": 16_000, "wide": 180_000}[
            self.bw_box.currentText()]
        self.dec1 = dsp.best_decimation(fs, max(bw * 3, 48_000))
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=bw / fs * 2)
        self.if_rate = fs / self.dec1
        self.am = dsp.AMDemod()
        self.fm = dsp.FMDemod(5_000 if bw < 50_000 else 75_000, self.if_rate,
                              deemph_us=50 if bw > 50_000 else 0)
        self.resamp = dsp.AudioResampler(self.if_rate, 48000)
        self.agc = dsp.AGC()
        self.hub.set_frequency(self._cur)
        self.start_rx(self._rx, block_size=32768)

    def _demod_audio(self, iq):
        mode = self.demod_box.currentIndex()
        if mode == 3:   # Log only
            return None
        chan = self.decim.process(iq)
        if mode == 1:   # AM
            a = self.am.process(chan)
        else:           # NFM / WFM
            a = self.fm.process(chan)
        return self.resamp.process(a)

    def _rx(self, iq):
        p = 10 * np.log10(np.mean(np.abs(iq) ** 2) + 1e-12)
        if self._settle > 0:
            self._settle -= 1
            return
        if self._holding:
            a = self._demod_audio(iq)
            if a is not None:
                self.audio.push(self.agc.process(a))
            self._hold_left -= 1
            if p < self.squelch - 3 or self._hold_left <= 0:
                self._holding = False
                # in Continuous match mode keep scanning; Sparse pauses on resume
                if self.match_box.currentIndex() == 0:
                    self._advance()
            self.emit_ui(("hold", self._cur, p))
            return
        # scanning — confirm the signal stays up for 'lock confirm' blocks
        if p > self.squelch:
            self._lock_count += 1
            if self._lock_count >= self.lock_sl.value():
                self._holding = True
                self._hold_left = self.wait_sl.value()
                self._lock_count = 0
                self.emit_ui(("hit", self._cur, p))
            else:
                self.emit_ui(("scan", self._cur, p))
        else:
            self._lock_count = 0
            self._advance()
            self.emit_ui(("scan", self._cur, p))

    def _advance(self):
        if self.scanmode_box.currentIndex() == 1:  # SCAN presets
            self._scan_idx = (self._scan_idx + 1) % len(self.SCAN_PRESETS)
            self._cur = self.SCAN_PRESETS[self._scan_idx]
        else:                                       # RECON range sweep
            self._cur += self.step_hz
            if self._cur > self.stop_hz:
                self._cur = self.start_hz
        self.hub.set_frequency(self._cur)
        self._settle = 1

    def _resume(self):
        self._holding = False
        self._advance()

    def _on_ui(self, payload):
        kind, hz, p = payload
        self.cur_lbl.setText(f"{hz/1e6:,.4f} MHz")
        if kind == "hit":
            self.state_lbl.setText(f"● SIGNAL  {p:.1f} dB")
            self.state_lbl.setStyleSheet(f"color:{theme.GREEN};")
            import time
            self.log.insertItem(0, f"[{time.strftime('%H:%M:%S')}] "
                                   f"{hz/1e6:,.4f} MHz  {p:.1f} dB")
        elif kind == "hold":
            self.state_lbl.setText(f"listening  {p:.1f} dB")
        else:
            self.state_lbl.setText(f"scanning…  {p:.1f} dB")
            self.state_lbl.setStyleSheet(f"color:{theme.FG_DIM};")


register(AppInfo(
    id="scanner", name="Scanner", category="Receive",
    factory=lambda hub, audio, ctx: Scanner(hub, audio, ctx),
    description="Recon/search scanner — stop & listen on active channels"))
