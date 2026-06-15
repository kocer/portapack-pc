"""IQ file analyzer — open a recorded capture and play it through the waterfall."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget)
from PySide6.QtCore import Qt

from ..sdr import dsp
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView


class IQAnalyzer(AppView):
    title = "IQ Analyzer"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._data = None
        self._pos = 0
        self.fs = 2_400_000
        self.center = 100_000_000
        self._block = 32768
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.title_lbl = QLabel("Load an IQ capture to analyze")
        self.title_lbl.setStyleSheet(f"color:{theme.ACCENT};")
        left.addWidget(self.title_lbl)
        self.spectrum = SpectrumWidget()
        left.addWidget(self.spectrum, 1)
        self.seek = QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.sliderMoved.connect(self._seek)
        left.addWidget(self.seek)
        lay.addLayout(left, 1)

        panel = QWidget(); panel.setFixedWidth(240)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("File")
        gl = QVBoxLayout(gb)
        browse = QPushButton("Open capture…")
        browse.clicked.connect(self._browse)
        gl.addWidget(browse)
        self.info = QLabel("no file")
        self.info.setWordWrap(True)
        self.info.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        gl.addWidget(self.info)
        self.fmt_box = widgets.combo(["int8 (cs8)", "int16 (cs16)", "float32"])
        gl.addWidget(widgets.Field("Format", self.fmt_box))
        self.sr_box = widgets.combo(["2.4", "2.6", "5", "8", "10", "20"])
        self.sr_box.currentTextChanged.connect(self._set_sr)
        gl.addWidget(widgets.Field("Samp MHz", self.sr_box))
        self.fc = widgets.FrequencyDisplay(100_000_000, hub=self.hub, font_pt=12)
        self.fc.frequency_changed.connect(self._set_fc)
        gl.addWidget(QLabel("Center"))
        gl.addWidget(self.fc)
        pl.addWidget(gb)

        gb2 = QGroupBox("Playback")
        g2 = QVBoxLayout(gb2)
        row = QHBoxLayout()
        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setCheckable(True)
        self.play_btn.toggled.connect(self._toggle_play)
        rst = QPushButton("⟲")
        rst.clicked.connect(lambda: self._seek(0))
        row.addWidget(self.play_btn); row.addWidget(rst)
        g2.addLayout(row)
        self.speed = widgets.LabeledSlider("Speed", 1, 50, 10, suffix=" blk/tick")
        g2.addWidget(self.speed)
        g2.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gb2)
        self.pos_lbl = QLabel("")
        pl.addWidget(self.pos_lbl)
        pl.addStretch(1)
        lay.addWidget(panel)

    def _browse(self):
        start = CAPTURE_DIR if os.path.isdir(CAPTURE_DIR) else os.path.expanduser("~")
        p, _ = QFileDialog.getOpenFileName(
            self, "Open IQ capture", start,
            "IQ files (*.cs8 *.cs16 *.c8 *.c16 *.iq *.raw *.bin);;All (*)")
        if p:
            self._load(p)

    def _load(self, path):
        name = os.path.basename(path)
        # guess format/rate/center from extension + filename tokens
        if path.endswith((".cs16", ".c16")):
            self.fmt_box.setCurrentIndex(1)
        elif path.endswith(".float") or path.endswith(".cf32"):
            self.fmt_box.setCurrentIndex(2)
        else:
            self.fmt_box.setCurrentIndex(0)
        for tok in name.replace(".", "_").split("_"):
            if tok.endswith("sps"):
                try:
                    self.sr_box.setCurrentText(f"{float(tok[:-3])/1e6:.1f}")
                except Exception:
                    pass
            if tok.endswith("Hz") and tok[:-2].isdigit():
                self.center = int(tok[:-2])
                self.fc.set_value(self.center, emit=False)
        self._path = path
        self._read_file()
        self.info.setText(f"{name}\n{len(self._data):,} samples, "
                          f"{os.path.getsize(path)/1e6:.1f} MB")
        self.title_lbl.setText(name)
        self._pos = 0
        self.spectrum.configure(self.center, self.fs)

    def _read_file(self):
        fmt = self.fmt_box.currentIndex()
        if fmt == 2:
            raw = np.fromfile(self._path, dtype=np.float32)
            self._data = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
        elif fmt == 1:
            raw = np.fromfile(self._path, dtype="<i2").astype(np.float32) / 32768.0
            self._data = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
        else:
            raw = np.fromfile(self._path, dtype=np.int8).astype(np.float32) / 127.0
            self._data = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)

    def on_stop(self):
        self.play_btn.setChecked(False)

    def _toggle_play(self, on):
        if on and self._data is not None:
            self.play_btn.setText("⏸ Pause")
            self._timer.start(40)
        else:
            self.play_btn.setText("▶ Play")
            self._timer.stop()

    def _tick(self):
        if self._data is None:
            return
        for _ in range(self.speed.value()):
            if self._pos + self._block > len(self._data):
                self._pos = 0
            blk = self._data[self._pos:self._pos + self._block]
            self._pos += self._block
        power = dsp.psd(blk, 2048)
        self.spectrum.update_spectrum(power)
        frac = self._pos / max(1, len(self._data))
        self.seek.setValue(int(frac * 1000))
        self.pos_lbl.setText(f"{self._pos/self.fs:.2f}s / "
                             f"{len(self._data)/self.fs:.2f}s")

    def _seek(self, v):
        if self._data is not None:
            self._pos = int(v / 1000 * len(self._data))

    def _set_sr(self, t):
        self.fs = float(t) * 1e6
        self.spectrum.configure(self.center, self.fs)

    def _set_fc(self, hz):
        self.center = int(hz)
        self.spectrum.configure(self.center, self.fs)


register(AppInfo(
    id="iq_analyzer", name="IQ Analyzer", category="Utilities",
    factory=lambda hub, audio, ctx: IQAnalyzer(hub, audio, ctx),
    description="Open & analyze recorded IQ captures offline"))
