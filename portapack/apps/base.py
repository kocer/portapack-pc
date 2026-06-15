"""Base class for all PortaPack-PC applications."""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget


class AppView(QWidget):
    """Common lifecycle and threading plumbing for apps.

    Subclasses implement :meth:`on_start`/:meth:`on_stop` and, for RX apps,
    register an IQ callback via :meth:`start_rx`.  The callback runs in the
    SDR worker thread; use :data:`ui_signal` to marshal results to the GUI
    thread before touching widgets.
    """

    #: Emitted from the worker thread to deliver a payload onto the GUI thread.
    ui_signal = Signal(object)

    title = "App"

    def __init__(self, hub, audio, ctx):
        super().__init__()
        self.hub = hub
        self.audio = audio
        self.ctx = ctx            # MainWindow, for status/nav helpers
        self._active = False
        self.ui_signal.connect(self._on_ui)

    # ---- lifecycle (called by MainWindow) --------------------------------
    def activate(self):
        if self._active:
            return
        self._active = True
        self.on_start()

    def deactivate(self):
        if not self._active:
            return
        self._active = False
        try:
            self.on_stop()
        finally:
            self.hub.stop()

    # ---- hooks for subclasses --------------------------------------------
    def on_start(self):
        ...

    def on_stop(self):
        ...

    def _on_ui(self, payload):
        """Override to handle worker-thread payloads on the GUI thread."""
        ...

    # ---- helpers ----------------------------------------------------------
    def start_rx(self, callback, block_size: int = 65536):
        self.hub.start_rx(callback, block_size)

    def emit_ui(self, payload):
        self.ui_signal.emit(payload)

    def set_status(self, text: str):
        if self.ctx is not None:
            self.ctx.set_app_status(text)
