"""Scheduler — trigger tuning / reminders at set times (On/Off scheduler)."""
from __future__ import annotations
import time
import numpy as np
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPushButton, QVBoxLayout)
from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView


class Scheduler(AppView):
    title = "Scheduler"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self.jobs = []   # list of dict(at_epoch, freq, note, done)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 12, 12, 12)
        gb = QGroupBox("New schedule")
        gl = QHBoxLayout(gb)
        self.time_in = QLineEdit(time.strftime("%H:%M"))
        self.time_in.setMaximumWidth(80)
        self.freq_in = QLineEdit("100.0")
        self.note_in = QLineEdit("FM check")
        add = QPushButton("Add")
        add.clicked.connect(self._add)
        gl.addWidget(QLabel("Time")); gl.addWidget(self.time_in)
        gl.addWidget(QLabel("MHz")); gl.addWidget(self.freq_in)
        gl.addWidget(QLabel("Note")); gl.addWidget(self.note_in, 1)
        gl.addWidget(add)
        lay.addWidget(gb)
        self.listw = QListWidget()
        lay.addWidget(self.listw, 1)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self._remove)
        lay.addWidget(rm)
        self.status = QLabel("clock running…")
        self.status.setStyleSheet(f"color:{theme.ACCENT};")
        lay.addWidget(self.status)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _add(self):
        try:
            hh, mm = self.time_in.text().split(":")
            now = time.localtime()
            at = time.struct_time((now.tm_year, now.tm_mon, now.tm_mday,
                                   int(hh), int(mm), 0, 0, 0, -1))
            epoch = time.mktime(at)
            if epoch < time.time():
                epoch += 86400  # next day
            self.jobs.append(dict(at=epoch, freq=float(self.freq_in.text()) * 1e6,
                                  note=self.note_in.text(), done=False))
            self._refresh()
        except Exception as e:
            self.status.setText(f"error: {e}")

    def _remove(self):
        r = self.listw.currentRow()
        if 0 <= r < len(self.jobs):
            del self.jobs[r]
            self._refresh()

    def _refresh(self):
        self.listw.clear()
        for j in sorted(self.jobs, key=lambda x: x["at"]):
            t = time.strftime("%H:%M", time.localtime(j["at"]))
            mark = "✓" if j["done"] else "○"
            self.listw.addItem(f"{mark} {t}  {j['freq']/1e6:.3f} MHz  {j['note']}")

    def _tick(self):
        now = time.time()
        fired = False
        for j in self.jobs:
            if not j["done"] and now >= j["at"]:
                j["done"] = True
                self.hub.set_frequency(j["freq"])
                self.status.setText(f"▶ {time.strftime('%H:%M:%S')} tuned "
                                    f"{j['freq']/1e6:.3f} MHz — {j['note']}")
                fired = True
        if fired:
            self._refresh()

    def on_stop(self):
        pass


register(AppInfo(id="scheduler", name="Scheduler", category="Utilities",
                 factory=lambda h, a, c: Scheduler(h, a, c),
                 description="Time-triggered tuning / reminders"))
