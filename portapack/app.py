"""PortaPack-PC main window: status bar, navigation tree and app host."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QPushButton, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import apps
from .apps import AppInfo, by_category
from .sdr.audio import AudioSink
from .sdr.backend import RadioHub
from .ui import theme, widgets


CATEGORY_ORDER = ["Receive", "Transmit", "Utilities", "System"]
CATEGORY_ICON = {"Receive": "▼", "Transmit": "▲", "Utilities": "⚙", "System": "⊞"}


class StatusBar(QFrame):
    def __init__(self, hub: RadioHub):
        super().__init__()
        self.setObjectName("StatusBar")
        self.hub = hub
        self.setFixedHeight(34)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 2, 10, 2)

        self.dev = QLabel("●")
        self.dev.setStyleSheet(f"color: {theme.RED};")
        self.dev_txt = QLabel("no device")
        self.freq = QLabel("")
        self.rate = QLabel("")
        self.gain = QLabel("")
        self.mode = QLabel("IDLE")
        self.mode.setStyleSheet(f"color: {theme.FG_DIM}; font-weight:bold;")
        self.clock = QLabel("")

        for w in (self.dev, self.dev_txt):
            lay.addWidget(w)
        lay.addSpacing(16)
        lay.addWidget(self.freq)
        lay.addSpacing(12)
        lay.addWidget(self.rate)
        lay.addSpacing(12)
        lay.addWidget(self.gain)
        lay.addStretch(1)
        lay.addWidget(self.mode)
        lay.addSpacing(16)
        lay.addWidget(self.clock)

        hub.status_changed.connect(self._on_status)
        hub.rx_active.connect(lambda on: self._mode("RX", theme.GREEN) if on
                              else self._mode("IDLE", theme.FG_DIM))
        hub.tx_active.connect(lambda on: self._mode("TX", theme.ACCENT2) if on
                              else self._mode("IDLE", theme.FG_DIM))

        t = QTimer(self)
        t.timeout.connect(self._tick)
        t.start(250)
        self._tick()

    def _on_status(self, text):
        self.dev_txt.setText(text)
        color = theme.RED if self.hub.is_sim else theme.GREEN
        self.dev.setStyleSheet(f"color: {color};")

    def _mode(self, text, color):
        self.mode.setText(text)
        self.mode.setStyleSheet(f"color: {color}; font-weight:bold;")

    def _tick(self):
        c = self.hub.cfg
        self.freq.setText(f"⟳ {c.frequency/1e6:,.4f} MHz")
        self.rate.setText(f"SR {c.sample_rate/1e6:.2f}M")
        amp = "+AMP" if c.amp_enable else ""
        bias = " ⚡BIAS" if c.bias_tee else ""
        self.gain.setText(f"LNA{int(c.lna_gain)} VGA{int(c.vga_gain)} {amp}{bias}")
        self.clock.setText(time.strftime("%H:%M:%S"))


class HomeScreen(QWidget):
    """Grid of category app buttons, shown when no app is open."""

    def __init__(self, on_open):
        super().__init__()
        self.on_open = on_open
        outer = QVBoxLayout(self)
        title = QLabel("PORTAPACK · PC")
        f = QFont(theme.MONO_FONT, 28)
        f.setBold(True)
        title.setFont(f)
        title.setStyleSheet(f"color: {theme.ACCENT};")
        title.setAlignment(Qt.AlignCenter)
        outer.addWidget(title)
        sub = QLabel("HackRF software-defined transceiver console")
        sub.setStyleSheet(f"color: {theme.FG_DIM};")
        sub.setAlignment(Qt.AlignCenter)
        outer.addWidget(sub)
        outer.addSpacing(20)

        cats = by_category()
        for cat in CATEGORY_ORDER:
            if cat not in cats:
                continue
            outer.addWidget(widgets.section(f"{CATEGORY_ICON.get(cat,'')} {cat}"))
            row = QHBoxLayout()
            row.setSpacing(8)
            count = 0
            for info in cats[cat]:
                b = QPushButton(info.name)
                b.setMinimumHeight(46)
                b.setToolTip(info.description)
                b.clicked.connect(lambda _=False, i=info: self.on_open(i))
                row.addWidget(b)
                count += 1
                if count % 4 == 0:
                    outer.addLayout(row)
                    row = QHBoxLayout()
                    row.setSpacing(8)
            if row.count():
                row.addStretch(1)
                outer.addLayout(row)
        outer.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, force_sim: bool = False):
        super().__init__()
        self.setWindowTitle("PortaPack PC")
        self.resize(1180, 760)

        from .config import Config
        self.config = Config()
        self.hub = RadioHub(force_sim=force_sim)
        self.config.apply_frontend(self.hub)   # restore saved front-end
        self.audio = AudioSink()
        self.audio.start()

        apps.load_all()
        self._app_cache: dict[str, object] = {}
        self._current = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.status = StatusBar(self.hub)
        root.addWidget(self.status)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        root.addLayout(body, 1)

        # --- navigation panel ---
        nav = QFrame()
        nav.setObjectName("NavPanel")
        nav.setFixedWidth(240)
        navlay = QVBoxLayout(nav)
        navlay.setContentsMargins(6, 6, 6, 6)
        home_btn = QPushButton("⌂  Home")
        home_btn.clicked.connect(self.show_home)
        navlay.addWidget(home_btn)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_tree)
        navlay.addWidget(self.tree, 1)
        self.rescan_btn = QPushButton("⟲  Rescan HackRF")
        self.rescan_btn.clicked.connect(self._rescan)
        navlay.addWidget(self.rescan_btn)
        body.addWidget(nav)

        self._build_tree()

        # --- app host ---
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.home = HomeScreen(self.open_app)
        self.stack.addWidget(self.home)
        self.stack.setCurrentWidget(self.home)

        self.setStyleSheet(theme.stylesheet())

        # restore last-opened app
        last = self.config.get("last_app")
        if last:
            for info in apps.all_apps():
                if info.id == last:
                    QTimer.singleShot(200, lambda i=info: self.open_app(i))
                    break

    # ---- navigation -------------------------------------------------------
    def _build_tree(self):
        cats = by_category()
        for cat in CATEGORY_ORDER:
            if cat not in cats:
                continue
            top = QTreeWidgetItem([f"{CATEGORY_ICON.get(cat,'')} {cat}"])
            top.setFlags(top.flags() & ~Qt.ItemIsSelectable)
            self.tree.addTopLevelItem(top)
            for info in cats[cat]:
                child = QTreeWidgetItem([info.name])
                child.setData(0, Qt.UserRole, info)
                top.addChild(child)
            top.setExpanded(True)

    def _on_tree(self, item, _col):
        info = item.data(0, Qt.UserRole)
        if isinstance(info, AppInfo):
            self.open_app(info)

    def open_app(self, info: AppInfo):
        if info.needs_tx and self.hub.is_sim:
            self.set_app_status(f"{info.name}: TX requires a real HackRF "
                                "(running in simulation)")
        if self._current is not None:
            self._current.deactivate()
        view = self._app_cache.get(info.id)
        if view is None:
            view = info.factory(self.hub, self.audio, self)
            self._app_cache[info.id] = view
            self.stack.addWidget(view)
        self.stack.setCurrentWidget(view)
        view.activate()
        self._current = view
        self.setWindowTitle(f"PortaPack PC — {info.name}")
        self.config.set("last_app", info.id)

    def show_home(self):
        if self._current is not None:
            self._current.deactivate()
            self._current = None
        self.stack.setCurrentWidget(self.home)
        self.setWindowTitle("PortaPack PC")

    def _rescan(self):
        if self._current is not None:
            self._current.deactivate()
            self._current = None
            self.stack.setCurrentWidget(self.home)
        ok = self.hub.rescan()
        self.set_app_status("HackRF detected!" if ok else
                            ("HackRF active" if not self.hub.is_sim
                             else "No HackRF — still simulation"))

    # ---- status helper ----------------------------------------------------
    def set_app_status(self, text: str):
        self.status.dev_txt.setText(text)

    def closeEvent(self, ev):
        if self._current is not None:
            self._current.deactivate()
        self.config.capture_frontend(self.hub.cfg)
        self.config.save()
        self.hub.close()
        self.audio.stop()
        super().closeEvent(ev)
