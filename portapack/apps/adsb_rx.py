"""ADS-B receiver — 1090 MHz Mode-S decoder with CPR position + live map."""

from __future__ import annotations

import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtWidgets import (QHBoxLayout, QHeaderView, QLabel, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)
from PySide6.QtCore import Qt

from ..sdr import dsp
from ..sdr.decoders import (ADSBDecoder, adsb_callsign, adsb_altitude,
                            adsb_cpr_latlon, adsb_global_position, adsb_typecode)
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

ADSB_FREQ = 1_090_000_000
ADSB_RATE = 2_000_000


class ADSBRx(AppView):
    title = "ADS-B RX"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._seen: dict[str, dict] = {}
        self._frames = 0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        head = QHBoxLayout()
        self.freq = widgets.FrequencyDisplay(ADSB_FREQ, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        head.addWidget(self.freq)
        head.addStretch(1)
        self.count = QLabel("frames: 0  aircraft: 0")
        head.addWidget(self.count)
        lay.addLayout(head)

        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["ICAO", "Callsign", "Alt ft", "Lat", "Lon", "Msgs", "Last"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        split.addWidget(self.table)

        # live map (lon = x, lat = y)
        self.plot = pg.PlotWidget()
        self.plot.setLabel("bottom", "Longitude")
        self.plot.setLabel("left", "Latitude")
        self.plot.showGrid(x=True, y=True, alpha=0.3)
        self.plot.setAspectLocked(False)
        self.scatter = pg.ScatterPlotItem(size=10, pen=pg.mkPen(theme.BG),
                                          brush=pg.mkBrush(theme.ACCENT2))
        self.plot.addItem(self.scatter)
        self._labels = []
        split.addWidget(self.plot)
        split.setSizes([640, 540])
        lay.addWidget(split, 1)

        note = QLabel("Needs a 1090 MHz antenna (+ external LNA recommended). "
                      "Position needs an even+odd frame pair from the same aircraft.")
        note.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        note.setWordWrap(True)
        lay.addWidget(note)

    def on_start(self):
        self.hub.set_sample_rate(ADSB_RATE)
        self.hub.set_frequency(self.freq.value())
        self.dec = ADSBDecoder(ADSB_RATE)
        self.start_rx(self._rx, block_size=131072)

    def _rx(self, iq):
        mag = np.abs(iq).astype(np.float32)
        frames = [f for f in self.dec.process(mag) if f.crc_ok]
        if frames:
            self.emit_ui(frames)

    def _on_ui(self, frames):
        now = time.strftime("%H:%M:%S")
        for f in frames:
            if len(f.hex) < 28:
                continue
            self._frames += 1
            rec = self._seen.setdefault(f.icao, {"n": 0})
            rec["n"] += 1
            rec["seen"] = now
            cs = adsb_callsign(f.hex)
            if cs:
                rec["callsign"] = cs
            alt = adsb_altitude(f.hex)
            if alt is not None:
                rec["alt"] = alt
            cpr = adsb_cpr_latlon(f.hex)
            if cpr:
                lat_cpr, lon_cpr, odd = cpr
                rec["odd" if odd else "even"] = (lat_cpr, lon_cpr, time.time())
                self._try_position(rec)
        self._refresh()

    def _try_position(self, rec):
        e, o = rec.get("even"), rec.get("odd")
        if e and o and abs(e[2] - o[2]) < 10:   # pair within 10 s
            pos = adsb_global_position((e[0], e[1]), (o[0], o[1]))
            if pos:
                rec["lat"], rec["lon"] = pos

    def _refresh(self):
        self.table.setRowCount(len(self._seen))
        pts = []
        for row, (icao, rec) in enumerate(sorted(self._seen.items())):
            def cell(v, fmt="{}"):
                return QTableWidgetItem(fmt.format(v) if v is not None else "—")
            self.table.setItem(row, 0, cell(icao))
            self.table.setItem(row, 1, cell(rec.get("callsign")))
            self.table.setItem(row, 2, cell(rec.get("alt")))
            self.table.setItem(row, 3, cell(rec.get("lat"), "{:.4f}"))
            self.table.setItem(row, 4, cell(rec.get("lon"), "{:.4f}"))
            self.table.setItem(row, 5, cell(rec.get("n")))
            self.table.setItem(row, 6, cell(rec.get("seen")))
            if rec.get("lat") is not None and rec.get("lon") is not None:
                pts.append({"pos": (rec["lon"], rec["lat"]),
                            "data": rec.get("callsign") or icao})
        self.scatter.setData(pts)
        self.count.setText(f"frames: {self._frames}  aircraft: {len(self._seen)}"
                           f"  positioned: {len(pts)}")


register(AppInfo(
    id="adsb_rx", name="ADS-B", category="Receive",
    factory=lambda hub, audio, ctx: ADSBRx(hub, audio, ctx),
    description="1090 MHz Mode-S decoder with CPR position + live map"))
