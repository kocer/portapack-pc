"""rtl_433 bridge — decode 200+ sub-GHz devices via the bundled rtl_433.

rtl_433 drives the HackRF directly through SoapySDR and emits one JSON object
per decoded event; we parse those into a live device table.  While this app
runs it owns the radio (the internal streaming hub is released).
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import threading
import time

from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RTL433 = os.path.join(_ROOT, "tools", "rtl433", "rtl_433")

BANDS = {"433.92 MHz": 433_920_000, "315 MHz": 315_000_000,
         "868.3 MHz": 868_300_000, "915 MHz": 915_000_000}


class RTL433Rx(AppView):
    title = "rtl_433"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._proc = None
        self._reader = None
        self._devices = {}
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        head = QHBoxLayout()
        self.band = widgets.combo(list(BANDS.keys()))
        head.addWidget(QLabel("Band:"))
        head.addWidget(self.band)
        self.btn = QPushButton("▶ Start rtl_433")
        self.btn.setCheckable(True)
        self.btn.toggled.connect(self._toggle)
        head.addWidget(self.btn)
        head.addStretch(1)
        self.stat = QLabel("idle")
        head.addWidget(self.stat)
        lay.addLayout(head)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Model", "ID", "Channel", "Readings", "Count", "Last"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        lay.addWidget(self.table, 1)

        self.raw = QLabel("")
        self.raw.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        self.raw.setWordWrap(True)
        lay.addWidget(self.raw)

        if not os.path.exists(RTL433):
            self.stat.setText("rtl_433 binary missing")
            self.btn.setEnabled(False)

    def on_start(self):
        pass

    def on_stop(self):
        self._stop_proc()
        if self.btn.isChecked():
            self.btn.setChecked(False)

    def _toggle(self, on):
        if on:
            if self.hub.is_sim:
                self.stat.setText("needs a real HackRF (simulation active)")
                self.btn.setChecked(False)
                return
            # fully release the SoapySDR handle so rtl_433 can open the HackRF
            self.hub.release_device()
            freq = BANDS[self.band.currentText()]
            # HackRF minimum sample rate is 2 MHz — rtl_433's 250k default fails
            cmd = [RTL433, "-d", "driver=hackrf", "-f", str(freq),
                   "-s", "2000000", "-F", "json", "-M", "level"]
            try:
                self._proc = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, bufsize=1)
            except Exception as e:
                self.stat.setText(f"launch error: {e}")
                self.hub.reacquire()
                self.btn.setChecked(False)
                return
            self.btn.setText("■ Stop rtl_433")
            self.stat.setText(f"decoding @ {self.band.currentText()} — "
                              "HackRF RX LED should be on")
            self._reader = threading.Thread(target=self._read, daemon=True)
            self._reader.start()
            threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stderr(self):
        p = self._proc
        if not p:
            return
        for line in p.stderr:
            low = line.lower()
            if any(k in low for k in ("hackrf", "error", "tuned", "sample rate",
                                      "found", "fail", "usb")):
                self.emit_ui({"_status": line.strip()})
        else:
            self._stop_proc()
            self.hub.reacquire()      # give the radio back to the app
            self.btn.setText("▶ Start rtl_433")
            self.stat.setText("stopped")

    def _read(self):
        p = self._proc
        if not p:
            return
        for line in p.stdout:
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            self.emit_ui(obj)

    def _on_ui(self, obj):
        if "_status" in obj:
            self.raw.setText(obj["_status"])
            return
        model = obj.get("model", "?")
        ident = str(obj.get("id", obj.get("address", "")))
        key = f"{model}/{ident}"
        skip = {"time", "model", "id", "address", "mic", "mod", "freq",
                "rssi", "snr", "noise", "channel"}
        readings = ", ".join(f"{k}={v}" for k, v in obj.items() if k not in skip)
        rec = self._devices.setdefault(key, {"n": 0})
        rec.update(model=model, id=ident, channel=str(obj.get("channel", "")),
                   readings=readings, last=time.strftime("%H:%M:%S"))
        rec["n"] += 1
        self._refresh()

    def _refresh(self):
        self.table.setRowCount(len(self._devices))
        for r, (key, rec) in enumerate(sorted(self._devices.items())):
            vals = [rec.get("model", ""), rec.get("id", ""), rec.get("channel", ""),
                    rec.get("readings", ""), str(rec["n"]), rec.get("last", "")]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
        self.stat.setText(f"{len(self._devices)} devices")

    def _stop_proc(self):
        if self._proc:
            try:
                self._proc.send_signal(signal.SIGINT)
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None


register(AppInfo(
    id="rtl433_rx", name="rtl_433", category="Receive",
    factory=lambda hub, audio, ctx: RTL433Rx(hub, audio, ctx),
    description="Decode 200+ sub-GHz sensors/devices via rtl_433"))
