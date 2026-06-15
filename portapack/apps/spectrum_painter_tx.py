"""Spectrum Painter TX — draw text into the waterfall (iconic PortaPack app).

Rasterises a line of text to a bitmap, then synthesises IQ so that the image
appears in a receiver's waterfall: each column becomes an OFDM-like sum of
tones whose amplitudes follow that column's pixels.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QGroupBox, QLabel, QLineEdit, QVBoxLayout

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


def _text_bitmap(text: str, height: int = 64) -> np.ndarray:
    """Render text to a (height x W) float mask using Qt offscreen painting."""
    from PySide6.QtGui import QImage, QPainter, QFont, QColor
    from PySide6.QtCore import Qt
    f = QFont("DejaVu Sans Mono", int(height * 0.7))
    f.setBold(True)
    # measure
    probe = QImage(1, 1, QImage.Format_Grayscale8)
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(f)
    w = max(8, fm.horizontalAdvance(text) + 8)
    img = QImage(w, height, QImage.Format_Grayscale8)
    img.fill(0)
    p = QPainter(img)
    p.setFont(f)
    p.setPen(QColor(255, 255, 255))
    p.drawText(4, int(height * 0.78), text)
    p.end()
    buf = img.constBits()
    arr = np.frombuffer(buf, np.uint8).reshape(height, img.bytesPerLine())[:, :w]
    return (arr.astype(np.float32) / 255.0)[::-1]  # flip so it reads upright


class SpectrumPainterTx(AppView):
    title = "Spectrum Painter"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._cols = None
        self._col_idx = 0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        gb = QGroupBox("Paint")
        gl = QVBoxLayout(gb)
        self.text = QLineEdit("HACKRF")
        gl.addWidget(widgets.Field("Text", self.text))
        self.cps = widgets.LabeledSlider("Columns/s", 20, 400, 120)
        gl.addWidget(self.cps)
        self.loop = widgets.combo(["Loop", "Once"])
        gl.addWidget(self.loop)
        lay.addWidget(gb)
        gb2 = QGroupBox("TX gain"); g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 30, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub)); lay.addWidget(gb2)
        self.tx_btn = widgets.tx_button("PAINT")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel(""); self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            bmp = _text_bitmap(self.text.text() or " ")
            self._cols = bmp  # shape (height, width); columns over time
            self._col_idx = 0
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop(); self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked() or self._cols is None:
            return None
        fs = self.hub.cfg.sample_rate
        height, width = self._cols.shape
        samples_per_col = max(8, int(fs / self.cps.value()))
        out = np.zeros(n, dtype=np.complex64)
        filled = 0
        # frequency bins span the sample rate
        bins = np.linspace(-fs / 2 * 0.9, fs / 2 * 0.9, height)
        while filled < n:
            if self._col_idx >= width:
                if self.loop.currentIndex() == 0:
                    self._col_idx = 0
                else:
                    if filled == 0:
                        self.emit_ui("done"); return None
                    break
            col = self._cols[:, self._col_idx]
            take = min(samples_per_col, n - filled)
            t = np.arange(take) / fs
            seg = np.zeros(take, dtype=np.complex128)
            active = np.where(col > 0.2)[0]
            for r in active:
                seg += col[r] * np.exp(1j * 2 * np.pi * bins[r] * t)
            if len(active):
                seg *= 0.7 / (len(active) ** 0.5)
            out[filled:filled + take] = seg[:take]
            filled += take
            self._col_idx += 1
        return out

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False); self.warn.setText("done")


register(AppInfo(
    id="spectrum_painter", name="Spectrum Painter", category="Transmit",
    needs_tx=True,
    factory=lambda hub, audio, ctx: SpectrumPainterTx(hub, audio, ctx),
    description="Draw text into the RF waterfall"))
