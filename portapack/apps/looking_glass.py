"""Looking Glass — wideband spectrum sweep by retuning the front end.

Steps the HackRF across a start/stop range one ``sample_rate`` slice at a time,
stitching the per-slice FFTs into a single wide spectrum + waterfall.  Mirrors
the Mayhem app's controls: scan type (fast/slow), view (spectrum/level/peak),
level integration, trigger, range presets, filter and markers.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView

# Range presets (label -> (start MHz, stop MHz)) — common scan bands
RANGE_PRESETS = {
    "Custom": None,
    "ISM 315/433": (300, 470),
    "PMR/LPD 433-446": (433, 446),
    "Airband 118-137": (118, 137),
    "VHF 130-170": (130, 170),
    "UHF 400-470": (400, 470),
    "GSM 900": (925, 960),
    "ISM 868/915": (860, 928),
    "Full 80-1000": (80, 1000),
    "Wide 1-6000": (1, 6000),
}


class LookingGlass(AppView):
    title = "Looking Glass"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.start_hz = 80e6
        self.stop_hz = 1000e6
        self.step_hz = 2.4e6
        self.nbins_total = 1200
        self._wide = np.full(self.nbins_total, -120.0, dtype=np.float32)
        self._peak = np.full(self.nbins_total, -150.0, dtype=np.float32)
        self._cur = self.start_hz
        self._settle = 0
        self.scan_fast = True
        self.view = 0          # 0 spectrum, 1 level, 2 peak
        self.integration = 1   # x0..x6 averaging
        self.trigger = -120.0
        self.marker_hz = 433.92e6
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.title_lbl = QLabel("Wideband sweep")
        self.title_lbl.setStyleSheet(f"color:{theme.ACCENT};")
        left.addWidget(self.title_lbl)
        self.spectrum = SpectrumWidget(history=160)
        self.spectrum.frequency_clicked.connect(self._click_marker)
        left.addWidget(self.spectrum, 1)
        lay.addLayout(left, 1)

        panel = QWidget()
        panel.setFixedWidth(248)
        pl = QVBoxLayout(panel)

        gbp = QGroupBox("Range preset")
        gpl = QVBoxLayout(gbp)
        self.preset = widgets.combo(list(RANGE_PRESETS.keys()))
        self.preset.setCurrentText("Full 80-1000")
        self.preset.currentTextChanged.connect(self._apply_preset)
        gpl.addWidget(self.preset)
        pl.addWidget(gbp)

        gb = QGroupBox("Sweep range")
        gl = QVBoxLayout(gb)
        self.start_disp = widgets.FrequencyDisplay(80_000_000, hub=self.hub,
                                                   font_pt=13)
        self.stop_disp = widgets.FrequencyDisplay(1_000_000_000, hub=self.hub,
                                                  font_pt=13)
        self.start_disp.frequency_changed.connect(self._range_changed)
        self.stop_disp.frequency_changed.connect(self._range_changed)
        gl.addWidget(QLabel("Start"))
        gl.addWidget(self.start_disp)
        gl.addWidget(QLabel("Stop"))
        gl.addWidget(self.stop_disp)
        pl.addWidget(gb)

        gbs = QGroupBox("Scan")
        gsl = QVBoxLayout(gbs)
        self.scan_box = widgets.combo(["F- Fast", "S- Slow"])
        self.scan_box.currentIndexChanged.connect(
            lambda i: setattr(self, "scan_fast", i == 0))
        gsl.addWidget(widgets.Field("Scan type", self.scan_box))
        self.view_box = widgets.combo(["SPCTR-V", "LEVEL-V", "PEAK-V"])
        self.view_box.currentIndexChanged.connect(self._set_view)
        gsl.addWidget(widgets.Field("View", self.view_box))
        self.integ_box = widgets.combo([f"x{i}" for i in range(7)])
        self.integ_box.setCurrentIndex(1)
        self.integ_box.currentIndexChanged.connect(self._set_integration)
        gsl.addWidget(widgets.Field("Integrate", self.integ_box))
        self.trig = widgets.LabeledSlider("Trigger", -120, -20, -120, suffix=" dB")
        self.trig.valueChanged.connect(lambda v: setattr(self, "trigger", float(v)))
        gsl.addWidget(self.trig)
        pl.addWidget(gbs)

        gb2 = QGroupBox("RF gain")
        g2 = QVBoxLayout(gb2)
        g2.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb2)

        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)

        gbm = QGroupBox("Marker")
        gml = QVBoxLayout(gbm)
        row = QHBoxLayout()
        bminus = QPushButton("◀")
        bplus = QPushButton("▶")
        bjump = QPushButton("Jump (tune)")
        bminus.clicked.connect(lambda: self._move_marker(-1))
        bplus.clicked.connect(lambda: self._move_marker(1))
        bjump.clicked.connect(self._jump)
        row.addWidget(bminus); row.addWidget(bplus); row.addWidget(bjump)
        gml.addLayout(row)
        self.marker_lbl = QLabel("")
        gml.addWidget(self.marker_lbl)
        pl.addWidget(gbm)

        self.info = QLabel("")
        pl.addWidget(self.info)
        pl.addStretch(1)
        lay.addWidget(panel)

    # ---- controls ---------------------------------------------------------
    def _apply_preset(self, name):
        rng = RANGE_PRESETS.get(name)
        if rng:
            self.start_disp.set_value(rng[0] * 1e6, emit=False)
            self.stop_disp.set_value(rng[1] * 1e6, emit=False)
            self._range_changed()

    def _range_changed(self, *_):
        self.start_hz = float(self.start_disp.value())
        self.stop_hz = float(self.stop_disp.value())
        if self.stop_hz <= self.start_hz:
            self.stop_hz = self.start_hz + self.step_hz
        self._wide[:] = -120.0
        self._peak[:] = -150.0
        self._cur = self.start_hz
        self.spectrum.configure((self.start_hz + self.stop_hz) / 2,
                                self.stop_hz - self.start_hz)

    def _set_view(self, i):
        self.view = i
        self.spectrum.set_peak_hold(i == 2)

    def _set_integration(self, i):
        self.integration = i
        # higher integration -> smoother (smaller alpha)
        self.spectrum.avg_alpha = 1.0 / (1 + i)

    def _move_marker(self, direction):
        span = self.stop_hz - self.start_hz
        self.marker_hz = float(np.clip(self.marker_hz + direction * span / 100,
                                       self.start_hz, self.stop_hz))
        self.spectrum.set_tune_marker(self.marker_hz)
        self._update_marker_lbl()

    def _click_marker(self, abs_hz):
        self.marker_hz = abs_hz
        self.spectrum.set_tune_marker(abs_hz)
        self._update_marker_lbl()

    def _update_marker_lbl(self):
        idx = int((self.marker_hz - self.start_hz) /
                  max(1, self.stop_hz - self.start_hz) * self.nbins_total)
        idx = int(np.clip(idx, 0, self.nbins_total - 1))
        self.marker_lbl.setText(f"⌖ {self.marker_hz/1e6:,.3f} MHz  "
                                f"{self._wide[idx]:.0f} dB")

    def _jump(self):
        self.hub.set_frequency(self.marker_hz)
        self.set_status(f"Tuned {self.marker_hz/1e6:,.3f} MHz — open Audio to listen")

    # ---- sweep ------------------------------------------------------------
    def on_start(self):
        self.step_hz = self.hub.cfg.sample_rate
        self._cur = self.start_hz
        self._settle = 0
        self.spectrum.configure((self.start_hz + self.stop_hz) / 2,
                                self.stop_hz - self.start_hz)
        self.spectrum.set_tune_marker(self.marker_hz)
        self.hub.set_frequency(self._cur)
        self.start_rx(self._rx, block_size=32768)

    def _rx(self, iq):
        if self._settle > 0:
            self._settle -= 1
            return
        # slow scan integrates more FFTs per slice for a cleaner trace
        nfft = 1024 if self.scan_fast else 2048
        power = dsp.psd(iq, nfft=nfft)
        span = self.stop_hz - self.start_hz
        lo = (self._cur - self.step_hz / 2 - self.start_hz) / span
        hi = (self._cur + self.step_hz / 2 - self.start_hz) / span
        i0 = int(np.clip(lo, 0, 1) * self.nbins_total)
        i1 = int(np.clip(hi, 0, 1) * self.nbins_total)
        if i1 > i0:
            x = np.linspace(0, len(power) - 1, i1 - i0)
            seg = np.interp(x, np.arange(len(power)), power)
            seg = np.maximum(seg, self.trigger)  # apply trigger floor
            self._wide[i0:i1] = seg
            self._peak[i0:i1] = np.maximum(self._peak[i0:i1], seg)
        self._cur += self.step_hz
        if self._cur > self.stop_hz:
            self._cur = self.start_hz
            disp = self._peak if self.view == 2 else self._wide
            self.emit_ui(disp.copy())
        self.hub.set_frequency(self._cur)
        self._settle = 1 if self.scan_fast else 2

    def _on_ui(self, wide):
        if self.view == 1:  # LEVEL view: quantise into coarse bars
            q = np.round(wide / 6) * 6
            self.spectrum.update_spectrum(q)
        else:
            self.spectrum.update_spectrum(wide)
        peak = int(np.argmax(wide))
        fpk = self.start_hz + peak / self.nbins_total * (self.stop_hz - self.start_hz)
        self.info.setText(f"Peak: {fpk/1e6:,.2f} MHz  {wide[peak]:.0f} dB")
        self._update_marker_lbl()


register(AppInfo(
    id="looking_glass", name="Looking Glass", category="Receive",
    factory=lambda hub, audio, ctx: LookingGlass(hub, audio, ctx),
    description="Wideband stepped spectrum sweep with scan/view/integration/markers"))
