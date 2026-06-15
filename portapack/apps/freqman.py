"""Frequency Manager — store/recall named frequencies (PortaPack freqman)."""

from __future__ import annotations

import json
import os

from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

FREQMAN_PATH = os.path.expanduser("~/portapack-pc/freqman.json")

DEFAULTS = [
    # Broadcast / utility
    {"name": "FM broadcast", "freq": 100_000_000, "mode": "WFM", "cat": "Broadcast"},
    {"name": "NOAA WX (US)", "freq": 162_550_000, "mode": "NFM", "cat": "Weather"},
    {"name": "NOAA-19 APT", "freq": 137_100_000, "mode": "WFM", "cat": "Satellite"},
    {"name": "NOAA-15 APT", "freq": 137_620_000, "mode": "WFM", "cat": "Satellite"},
    {"name": "ISS voice", "freq": 145_800_000, "mode": "NFM", "cat": "Satellite"},
    {"name": "Meteor M2", "freq": 137_100_000, "mode": "WFM", "cat": "Satellite"},
    # Aviation
    {"name": "Airband ATIS", "freq": 119_000_000, "mode": "AM", "cat": "Aviation"},
    {"name": "Airband twr", "freq": 118_100_000, "mode": "AM", "cat": "Aviation"},
    {"name": "ADS-B", "freq": 1_090_000_000, "mode": "RAW", "cat": "Aviation"},
    {"name": "ACARS", "freq": 131_550_000, "mode": "AM", "cat": "Aviation"},
    # Marine / amateur
    {"name": "AIS A", "freq": 161_975_000, "mode": "RAW", "cat": "Marine"},
    {"name": "AIS B", "freq": 162_025_000, "mode": "RAW", "cat": "Marine"},
    {"name": "PMR446 ch1", "freq": 446_006_250, "mode": "NFM", "cat": "PMR/Ham"},
    {"name": "2m calling", "freq": 145_500_000, "mode": "NFM", "cat": "PMR/Ham"},
    {"name": "APRS EU", "freq": 144_800_000, "mode": "NFM", "cat": "PMR/Ham"},
    {"name": "70cm calling", "freq": 433_500_000, "mode": "NFM", "cat": "PMR/Ham"},
    {"name": "SSTV 20m", "freq": 14_230_000, "mode": "USB", "cat": "PMR/Ham"},
    {"name": "PSK31 20m", "freq": 14_070_000, "mode": "USB", "cat": "PMR/Ham"},
    {"name": "FT8 20m", "freq": 14_074_000, "mode": "USB", "cat": "PMR/Ham"},
    {"name": "WEFAX DWD", "freq": 7_880_000, "mode": "USB", "cat": "Marine"},
    # ISM / devices
    {"name": "315 ISM", "freq": 315_000_000, "mode": "OOK", "cat": "ISM"},
    {"name": "433 ISM", "freq": 433_920_000, "mode": "OOK", "cat": "ISM"},
    {"name": "868 ISM", "freq": 868_300_000, "mode": "OOK", "cat": "ISM"},
    {"name": "915 ISM", "freq": 915_000_000, "mode": "OOK", "cat": "ISM"},
    {"name": "TPMS 433", "freq": 433_920_000, "mode": "FSK", "cat": "ISM"},
    {"name": "BTLE adv37", "freq": 2_402_000_000, "mode": "RAW", "cat": "ISM"},
    {"name": "ERT meters", "freq": 912_600_000, "mode": "OOK", "cat": "ISM"},
    # Public service
    {"name": "POCSAG", "freq": 153_350_000, "mode": "NFM", "cat": "Pager"},
    {"name": "GPS L1", "freq": 1_575_420_000, "mode": "RAW", "cat": "Nav"},
]


class Freqman(AppView):
    title = "Freq Manager"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.entries = self._load()
        self._build()
        self._refresh()

    def _load(self):
        if os.path.exists(FREQMAN_PATH):
            try:
                with open(FREQMAN_PATH) as f:
                    return json.load(f)
            except Exception:
                pass
        return list(DEFAULTS)

    def _save(self):
        os.makedirs(os.path.dirname(FREQMAN_PATH), exist_ok=True)
        with open(FREQMAN_PATH, "w") as f:
            json.dump(self.entries, f, indent=2)

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addWidget(QLabel("Stored frequencies"))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Frequency (MHz)", "Mode"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._tune_row)
        lay.addWidget(self.table, 1)

        gb = QGroupBox("Add entry")
        gl = QHBoxLayout(gb)
        self.name_in = QLineEdit()
        self.name_in.setPlaceholderText("name")
        self.freq_in = QLineEdit()
        self.freq_in.setPlaceholderText("MHz e.g. 145.500")
        self.mode_in = widgets.combo(["WFM", "NFM", "AM", "USB", "LSB", "OOK", "RAW"])
        addb = QPushButton("Add")
        addb.clicked.connect(self._add)
        gl.addWidget(self.name_in, 2)
        gl.addWidget(self.freq_in, 1)
        gl.addWidget(self.mode_in)
        gl.addWidget(addb)
        lay.addWidget(gb)

        row = QHBoxLayout()
        tune = QPushButton("⟳ Tune selected")
        tune.clicked.connect(lambda: self._tune_row(self.table.currentRow(), 0))
        dele = QPushButton("🗑 Delete selected")
        dele.clicked.connect(self._delete)
        row.addWidget(tune)
        row.addWidget(dele)
        row.addStretch(1)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setStyleSheet(f"color:{theme.ACCENT};")
        lay.addWidget(self.status)

    def _refresh(self):
        self.table.setRowCount(len(self.entries))
        for r, e in enumerate(self.entries):
            self.table.setItem(r, 0, QTableWidgetItem(e["name"]))
            self.table.setItem(r, 1, QTableWidgetItem(f"{e['freq']/1e6:,.4f}"))
            self.table.setItem(r, 2, QTableWidgetItem(e["mode"]))

    def _add(self):
        try:
            mhz = float(self.freq_in.text())
        except ValueError:
            self.status.setText("invalid frequency")
            return
        self.entries.append({"name": self.name_in.text() or "unnamed",
                             "freq": int(mhz * 1e6),
                             "mode": self.mode_in.currentText()})
        self._save()
        self._refresh()
        self.name_in.clear()
        self.freq_in.clear()

    def _delete(self):
        r = self.table.currentRow()
        if 0 <= r < len(self.entries):
            del self.entries[r]
            self._save()
            self._refresh()

    def _tune_row(self, r, _c):
        if 0 <= r < len(self.entries):
            e = self.entries[r]
            self.hub.set_frequency(e["freq"])
            self.status.setText(f"Tuned {e['name']} → {e['freq']/1e6:,.4f} MHz "
                                f"({e['mode']}). Open a Receive app to listen.")


register(AppInfo(
    id="freqman", name="Freq Manager", category="Utilities",
    factory=lambda hub, audio, ctx: Freqman(hub, audio, ctx),
    description="Store and recall named frequencies"))
