"""Spectrum + waterfall display, the centrepiece of most PortaPack apps."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from . import theme

pg.setConfigOptions(antialias=False, useOpenGL=False, background=theme.BG,
                    foreground=theme.FG_DIM)


def _build_lut() -> np.ndarray:
    """256-entry RGBA lookup table from the Mayhem waterfall colour stops."""
    stops = theme.WATERFALL_STOPS
    lut = np.zeros((256, 4), dtype=np.uint8)
    lut[:, 3] = 255
    for i in range(256):
        x = i / 255.0
        for j in range(len(stops) - 1):
            x0, c0 = stops[j]
            x1, c1 = stops[j + 1]
            if x0 <= x <= x1:
                t = (x - x0) / (x1 - x0 + 1e-9)
                lut[i, 0] = int(c0[0] + t * (c1[0] - c0[0]))
                lut[i, 1] = int(c0[1] + t * (c1[1] - c0[1]))
                lut[i, 2] = int(c0[2] + t * (c1[2] - c0[2]))
                break
    return lut


_WATERFALL_LUT = _build_lut()


class SpectrumWidget(QWidget):
    """Live FFT trace above a scrolling waterfall.

    Frequencies are labelled in absolute MHz using ``center_hz``/``span_hz``.
    Clicking the plot emits :data:`frequency_clicked` with the absolute Hz of
    the click — apps use it to tune by pointing at a signal.
    """

    frequency_clicked = Signal(float)

    def __init__(self, history: int = 200, parent=None):
        super().__init__(parent)
        self.center_hz = 100e6
        self.span_hz = 2.4e6
        self.nbins = 1024
        self._history = history
        self._wf = np.zeros((history, self.nbins), dtype=np.float32)
        self._ref = -10.0     # top of colour scale (dB)
        self._range = 70.0    # dynamic range (dB)
        self._avg = None
        self.avg_alpha = 0.5
        self.remove_dc = True      # notch the centre DC/LO-leakage spike
        self.dc_notch_bins = 2     # half-width of the notch (display bins)
        self.refresh_fps = 20      # cap redraw/waterfall-scroll rate
        self._last_draw = 0.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.win = pg.GraphicsLayoutWidget()
        layout.addWidget(self.win)

        # spectrum trace
        self.p_spec = self.win.addPlot(row=0, col=0)
        self.p_spec.showGrid(x=True, y=True, alpha=0.2)
        self.p_spec.setMouseEnabled(x=False, y=False)
        self.p_spec.setMenuEnabled(False)
        self.p_spec.setLabel("left", "dB")
        self.p_spec.setYRange(self._ref - self._range, self._ref)
        self.curve = self.p_spec.plot(pen=pg.mkPen(theme.ACCENT, width=1))
        self.peak_curve = self.p_spec.plot(pen=pg.mkPen(theme.ACCENT2, width=1,
                                                        style=Qt.DashLine))
        self._peak_hold = None
        self.peak_enabled = False
        self.tune_line = pg.InfiniteLine(angle=90, movable=False,
                                         pen=pg.mkPen(theme.RED, width=1))
        self.p_spec.addItem(self.tune_line)

        # waterfall image
        self.p_wf = self.win.addPlot(row=1, col=0)
        self.p_wf.setMouseEnabled(x=False, y=False)
        self.p_wf.setMenuEnabled(False)
        self.p_wf.hideAxis("left")
        self.p_wf.setLabel("bottom", "MHz")
        self.img = pg.ImageItem()
        self.img.setLookupTable(_WATERFALL_LUT)
        self.p_wf.addItem(self.img)
        self.win.ci.layout.setRowStretchFactor(0, 1)
        self.win.ci.layout.setRowStretchFactor(1, 2)

        self.p_spec.scene().sigMouseClicked.connect(self._on_click)
        self._update_axes()

    # ---- configuration ----------------------------------------------------
    def configure(self, center_hz: float, span_hz: float):
        self.center_hz = center_hz
        self.span_hz = span_hz
        self._update_axes()

    def set_reference(self, ref_db: float, range_db: float):
        self._ref = ref_db
        self._range = range_db
        self.p_spec.setYRange(ref_db - range_db, ref_db)

    def reference(self):
        return self._ref, self._range

    def save_waterfall(self, path: str) -> bool:
        """Save the current waterfall buffer to a PNG (Mayhem colormap)."""
        try:
            from PySide6.QtGui import QImage
            norm = (self._wf - (self._ref - self._range)) / self._range
            np.clip(norm, 0, 1, out=norm)
            idx = (norm * 255).astype(np.uint8)
            rgb = _WATERFALL_LUT[idx][:, :, :3]      # (rows, bins, 3)
            rgb = np.ascontiguousarray(rgb)
            h, w, _ = rgb.shape
            qi = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888)
            return qi.save(path)
        except Exception:
            return False

    def auto_range(self, margin: float = 8.0):
        """Pick reference/range from the current trace (like HDSDR auto)."""
        if self._avg is None:
            return
        floor = float(np.percentile(self._avg, 10))
        peak = float(np.percentile(self._avg, 99.5))
        ref = peak + margin
        rng = max(30.0, (peak - floor) + 2 * margin)
        self.set_reference(round(ref), round(rng))
        return self._ref, self._range

    def set_tune_marker(self, abs_hz: float):
        self.tune_line.setValue(abs_hz / 1e6)

    def set_peak_hold(self, on: bool):
        self.peak_enabled = on
        if not on:
            self._peak_hold = None
            self.peak_curve.clear()

    def set_dc_removal(self, on: bool):
        """Enable/disable the centre DC-spike notch on the display."""
        self.remove_dc = bool(on)

    def _update_axes(self):
        f0 = (self.center_hz - self.span_hz / 2) / 1e6
        f1 = (self.center_hz + self.span_hz / 2) / 1e6
        self._f0, self._f1 = f0, f1
        self.p_spec.setXRange(f0, f1, padding=0)
        self.p_wf.setXRange(f0, f1, padding=0)
        self.img.setRect(pg.QtCore.QRectF(f0, 0, f1 - f0, self._history))

    # ---- live update ------------------------------------------------------
    def update_spectrum(self, power_db: np.ndarray):
        if power_db is None or len(power_db) < 4:
            return
        if len(power_db) != self.nbins:
            # resample to display bin count
            x = np.linspace(0, len(power_db) - 1, self.nbins)
            power_db = np.interp(x, np.arange(len(power_db)), power_db)
        if self.remove_dc:
            # notch the DC spike (LO leakage) at band centre by interpolating
            # across the centre bins from their neighbours
            power_db = power_db.copy()
            c = self.nbins // 2
            w = self.dc_notch_bins
            lo, hi = power_db[c - w - 1], power_db[c + w + 1]
            power_db[c - w:c + w + 1] = np.linspace(lo, hi, 2 * w + 1)
        if self._avg is None:
            self._avg = power_db.copy()
        else:
            self._avg = (1 - self.avg_alpha) * self._avg + self.avg_alpha * power_db

        # Throttle the actual redraw to ~refresh_fps so fast full-rate streaming
        # doesn't make the trace flicker and the waterfall race past.
        import time as _t
        now = _t.monotonic()
        if now - self._last_draw < 1.0 / self.refresh_fps:
            return
        self._last_draw = now

        freqs = np.linspace(self._f0, self._f1, self.nbins)
        self.curve.setData(freqs, self._avg)

        if self.peak_enabled:
            if self._peak_hold is None:
                self._peak_hold = self._avg.copy()
            else:
                self._peak_hold = np.maximum(self._peak_hold, self._avg)
            self.peak_curve.setData(freqs, self._peak_hold)

        # scroll waterfall
        self._wf[1:] = self._wf[:-1]
        self._wf[0] = self._avg
        norm = (self._wf - (self._ref - self._range)) / self._range
        np.clip(norm, 0, 1, out=norm)
        self.img.setImage(norm.T[:, ::-1], levels=(0, 1), autoLevels=False)

    def _on_click(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        vb = self.p_spec.vb
        pt = vb.mapSceneToView(ev.scenePos())
        self.frequency_clicked.emit(pt.x() * 1e6)
