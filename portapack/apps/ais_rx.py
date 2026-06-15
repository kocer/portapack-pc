"""AIS receiver — marine 161.975 / 162.025 MHz GMSK 9600 (best-effort)."""

from __future__ import annotations

import time

import numpy as np
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..sdr import dsp
from ..sdr.decoders import AISDecoder
from ..ui import theme, widgets
from ..ui.spectrum import SpectrumWidget
from . import AppInfo, register
from .base import AppView


class AISRx(AppView):
    title = "AIS"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._build()

    def _build(self):
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        left = QVBoxLayout()
        self.freq = widgets.FrequencyDisplay(162_000_000)
        self.freq.frequency_changed.connect(self._set_freq)
        left.addWidget(self.freq)
        self.spectrum = SpectrumWidget(history=110)
        left.addWidget(self.spectrum, 1)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["MMSI", "Lat", "Lon", "SOG kn", "COG°", "Last"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        left.addWidget(self.table, 2)
        lay.addLayout(left, 1)
        self._ships = {}

        panel = QWidget(); panel.setFixedWidth(220)
        pl = QVBoxLayout(panel)
        gb = QGroupBox("Channel")
        gl = QVBoxLayout(gb)
        self.chan = widgets.combo(["A 161.975", "B 162.025", "center 162.000"])
        self.chan.setCurrentIndex(2)
        self.chan.currentIndexChanged.connect(
            lambda i: self.freq.set_value([161_975_000, 162_025_000,
                                           162_000_000][i]))
        gl.addWidget(self.chan)
        gl.addWidget(widgets.GainPanel(self.hub))
        pl.addWidget(gb)
        self.stat = QLabel("listening 9600 GMSK…")
        pl.addWidget(self.stat)
        gbd = QGroupBox("Display")
        gdl = QVBoxLayout(gbd)
        gdl.addWidget(widgets.SpectrumControls(self.spectrum))
        pl.addWidget(gbd)
        pl.addStretch(1)
        lay.addWidget(panel)

    def on_start(self):
        self.hub.set_sample_rate(2_400_000)
        self.spectrum.configure(self.hub.cfg.frequency, 2_400_000)
        fs = self.hub.cfg.sample_rate
        self.dec1 = dsp.best_decimation(fs, 96_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.12)
        self.if_rate = fs / self.dec1
        self.fm = dsp.FMDemod(4_800, self.if_rate, deemph_us=0)
        self.ais = AISDecoder(self.if_rate)
        self.start_rx(self._rx)

    def _rx(self, iq):
        power = dsp.psd(iq, 2048)
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        frames = self.ais.process(demod)
        self.emit_ui((power, frames))

    def _on_ui(self, payload):
        power, frames = payload
        self.spectrum.update_spectrum(power)
        now = time.strftime("%H:%M:%S")
        for f in frames:
            mmsi = f.get("mmsi")
            if not mmsi:
                continue
            s = self._ships.setdefault(mmsi, {})
            s.update({k: v for k, v in f.items() if v is not None})
            s["last"] = now
        if frames:
            self._refresh()

    def _refresh(self):
        self.table.setRowCount(len(self._ships))
        for r, (mmsi, s) in enumerate(sorted(self._ships.items())):
            def cell(v, fmt="{}"):
                return QTableWidgetItem(fmt.format(v) if v is not None else "—")
            self.table.setItem(r, 0, cell(mmsi))
            self.table.setItem(r, 1, cell(s.get("lat"), "{:.5f}"))
            self.table.setItem(r, 2, cell(s.get("lon"), "{:.5f}"))
            self.table.setItem(r, 3, cell(s.get("sog"), "{:.1f}"))
            self.table.setItem(r, 4, cell(s.get("cog"), "{:.0f}"))
            self.table.setItem(r, 5, cell(s.get("last")))
        self.stat.setText(f"{len(self._ships)} vessels")

    def _set_freq(self, hz):
        self.hub.set_frequency(hz)
        self.spectrum.configure(hz, self.hub.cfg.sample_rate)


register(AppInfo(
    id="ais_rx", name="AIS", category="Receive",
    factory=lambda hub, audio, ctx: AISRx(hub, audio, ctx),
    description="Marine AIS GMSK frame detector (161.975/162.025)"))
