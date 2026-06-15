"""Replay transmitter — stream a captured CS8 IQ file back out the HackRF."""

from __future__ import annotations

import os

import numpy as np
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from ..ui import theme, widgets
from .capture import CAPTURE_DIR
from . import AppInfo, register
from .base import AppView


class TxReplay(AppView):
    title = "Replay TX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._data = None
        self._pos = 0
        self.loop = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.hub.cfg.frequency)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        gb = QGroupBox("File (CS8 interleaved int8)")
        gl = QVBoxLayout(gb)
        row = QHBoxLayout()
        self.path_lbl = QLabel("no file loaded")
        self.path_lbl.setWordWrap(True)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_lbl, 1)
        row.addWidget(browse)
        gl.addLayout(row)
        self.sr_box = widgets.combo(["2.4", "5", "8", "10", "20"])
        self.sr_box.currentTextChanged.connect(
            lambda t: self.hub.set_sample_rate(float(t) * 1e6))
        gl.addWidget(widgets.Field("Samp MHz", self.sr_box))
        self.loop_box = widgets.combo(["Once", "Loop"])
        self.loop_box.currentIndexChanged.connect(
            lambda i: setattr(self, "loop", i == 1))
        gl.addWidget(widgets.Field("Mode", self.loop_box))
        lay.addWidget(gb)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 40, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub))
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button("REPLAY")
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        lay.addWidget(self.warn)
        lay.addStretch(1)

    def _browse(self):
        start = CAPTURE_DIR if os.path.isdir(CAPTURE_DIR) else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "Open IQ capture", start, "IQ files (*.cs8 *.c8 *.iq *.raw);;All (*)")
        if path:
            self._load(path)

    def _load(self, path):
        try:
            raw = np.fromfile(path, dtype=np.int8).astype(np.float32) / 127.0
            self._data = (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)
            self._pos = 0
            mb = os.path.getsize(path) / 1e6
            self.path_lbl.setText(f"{os.path.basename(path)}  ({mb:.1f} MB, "
                                  f"{len(self._data):,} samples)")
            # parse sample rate from filename if present
            for tok in os.path.basename(path).split("_"):
                if tok.endswith("sps"):
                    try:
                        self.hub.set_sample_rate(float(tok[:-3]))
                        self.sr_box.setCurrentText(f"{float(tok[:-3])/1e6:.1f}")
                    except Exception:
                        pass
        except Exception as e:
            self.path_lbl.setText(f"load error: {e}")

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            if self._data is None:
                self.warn.setText("Load a file first.")
                self.tx_btn.setChecked(False)
                return
            self._pos = 0
            if self.hub.is_sim:
                self.warn.setText("Simulation mode — no RF emitted. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked() or self._data is None:
            return None
        out = np.zeros(n, dtype=np.complex64)
        filled = 0
        while filled < n:
            remain = len(self._data) - self._pos
            if remain <= 0:
                if self.loop:
                    self._pos = 0
                    continue
                break
            take = min(remain, n - filled)
            out[filled:filled + take] = self._data[self._pos:self._pos + take]
            filled += take
            self._pos += take
        if filled == 0:
            self.emit_ui("done")
            return None
        return out

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False)
            self.warn.setText("replay complete")


register(AppInfo(
    id="tx_replay", name="Replay TX", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: TxReplay(hub, audio, ctx),
    description="Transmit a recorded CS8 IQ capture"))
