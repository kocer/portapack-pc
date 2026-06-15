"""Reusable PortaPack-flavoured controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal, QRectF
from PySide6.QtGui import QFont, QFontMetrics, QPainter, QColor, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSlider, QVBoxLayout, QWidget)

from . import theme


def fmt_freq(hz: float) -> str:
    return f"{hz/1e6:,.4f} MHz"


class FrequencyDisplay(QWidget):
    """SDRangel-style segmented-digit frequency dial, themed for PortaPack PC.

    Renders the frequency as a fixed-width odometer of individual digits with
    thousands separators and a unit suffix.  The digit under the cursor is
    highlighted; mouse wheel (or click on the upper/lower half) increments or
    decrements that decade.  Leading zeros are dimmed.  Drop-in replacement for
    the old single-label readout: same ``value`` / ``set_value`` /
    ``frequency_changed`` API.
    """

    frequency_changed = Signal(float)

    N_DIGITS = 10            # up to 9,999,999,999 Hz (covers HackRF 6 GHz)
    MAX_HZ = 7_300_000_000

    def __init__(self, hz: float = 100_000_000, parent=None, hub=None,
                 unit: str = "Hz", font_pt: int = 24):
        super().__init__(parent)
        self._hz = int(hz)
        self._hub = hub
        self._unit = unit
        self._hover = -1         # decade under the cursor (-1 none)
        self._sel = 6            # keyboard-selected decade
        self._font = QFont(theme.MONO_FONT, font_pt)
        self._font.setBold(True)
        self.setMinimumHeight(int(font_pt * 1.9))
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self._relayout()

    # ---- public API -------------------------------------------------------
    def value(self) -> int:
        return self._hz

    def set_value(self, hz: float, emit: bool = True):
        self._hz = int(max(0, min(self.MAX_HZ, hz)))
        self.update()
        if emit:
            self.frequency_changed.emit(float(self._hz))

    # ---- layout -----------------------------------------------------------
    def _relayout(self):
        fm = QFontMetrics(self._font)
        self._cw = fm.horizontalAdvance("0")
        # token list: ('d', decade) for digits, (',', None) for separators
        toks = []
        for i in range(self.N_DIGITS):
            decade = self.N_DIGITS - 1 - i
            rem = self.N_DIGITS - i
            if i > 0 and rem % 3 == 0:
                toks.append((",", None))
            toks.append(("d", decade))
        self._tokens = toks
        self._n_cells = len(toks)
        # widget width: cells + space + unit
        w = (self._n_cells + 1 + len(self._unit)) * self._cw + 24
        self.setMinimumWidth(int(w))

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(self.minimumWidth(), 50)

    def _x0(self) -> float:
        """Left x of the first cell (content right-aligned with padding)."""
        content = (self._n_cells + 1 + len(self._unit)) * self._cw
        return (self.width() - content) / 2 + 6

    def _decade_at(self, x: float) -> int:
        x0 = self._x0()
        idx = int((x - x0) // self._cw)
        if 0 <= idx < self._n_cells:
            kind, dec = self._tokens[idx]
            if kind == "d":
                return dec
        return -1

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QColor(theme.BG_RAISED))
        p.setPen(QColor(theme.GREY))
        p.drawRoundedRect(r, 6, 6)

        p.setFont(self._font)
        fm = QFontMetrics(self._font)
        cw = self._cw
        cell_h = self.height()
        baseline = (cell_h + fm.capHeight()) / 2
        digits = f"{self._hz:0{self.N_DIGITS}d}"
        first_sig = next((k for k, c in enumerate(digits) if c != "0"),
                         self.N_DIGITS - 1)
        x = self._x0()
        for kind, dec in self._tokens:
            if kind == ",":
                p.setPen(QColor(theme.FG_DIM))
                p.drawText(QRectF(x, 0, cw, cell_h),
                           Qt.AlignCenter, ",")
                x += cw
                continue
            pos = self.N_DIGITS - 1 - dec     # index into digits string
            ch = digits[pos]
            dim = pos < first_sig
            hovered = (dec == self._hover)
            selected = (dec == self._sel and self.hasFocus() and not hovered)
            if hovered:
                p.setBrush(QColor(theme.SELECT_BG))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(x + 1, 4, cw - 2, cell_h - 8), 3, 3)
                self._draw_arrows(p, x, cw, cell_h)
            elif selected:
                p.setPen(QPen(QColor(theme.ACCENT), 2))
                p.drawLine(QPointF(x + 2, cell_h - 5),
                           QPointF(x + cw - 2, cell_h - 5))
            color = theme.FG_DIM if dim else (
                "#ffffff" if hovered else theme.ACCENT)
            p.setPen(QColor(color))
            p.drawText(QRectF(x, 0, cw, cell_h), Qt.AlignCenter, ch)
            x += cw
        # unit suffix
        p.setPen(QColor(theme.FG_DIM))
        p.drawText(QRectF(x + cw * 0.4, 0, cw * (len(self._unit) + 1), cell_h),
                   Qt.AlignVCenter | Qt.AlignLeft, self._unit)

    def _draw_arrows(self, p, x, cw, h):
        p.setBrush(QColor(theme.ACCENT))
        p.setPen(Qt.NoPen)
        cx = x + cw / 2
        up = QPolygonF([QPointF(cx - 4, 7), QPointF(cx + 4, 7),
                        QPointF(cx, 2)])
        dn = QPolygonF([QPointF(cx - 4, h - 7), QPointF(cx + 4, h - 7),
                        QPointF(cx, h - 2)])
        p.drawPolygon(up)
        p.drawPolygon(dn)

    # ---- interaction ------------------------------------------------------
    def mouseMoveEvent(self, ev):
        dec = self._decade_at(ev.position().x())
        if dec != self._hover:
            self._hover = dec
            self.update()

    def leaveEvent(self, ev):
        self._hover = -1
        self.update()

    def wheelEvent(self, ev):
        dec = self._decade_at(ev.position().x())
        if dec < 0:
            dec = self._hover if self._hover >= 0 else (
                self._hub and _decade_of(int(self._hub.cfg.freq_step)) or 4)
        step = 10 ** dec
        self.set_value(self._hz + (step if ev.angleDelta().y() > 0 else -step))
        ev.accept()

    def mousePressEvent(self, ev):
        self.setFocus()
        dec = self._decade_at(ev.position().x())
        if dec < 0:
            return
        self._sel = dec
        step = 10 ** dec
        up = ev.position().y() < self.height() / 2
        self.set_value(self._hz + (step if up else -step))
        ev.accept()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Left:
            self._sel = min(self.N_DIGITS - 1, self._sel + 1); self.update()
        elif k == Qt.Key_Right:
            self._sel = max(0, self._sel - 1); self.update()
        elif k == Qt.Key_Up:
            self.set_value(self._hz + 10 ** self._sel)
        elif k == Qt.Key_Down:
            self.set_value(self._hz - 10 ** self._sel)
        elif k == Qt.Key_PageUp:
            self.set_value(self._hz + 10 ** min(self._sel + 1, 9))
        elif k == Qt.Key_PageDown:
            self.set_value(self._hz - 10 ** min(self._sel + 1, 9))
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()


def _decade_of(step: int) -> int:
    d = 0
    while step >= 10:
        step //= 10
        d += 1
    return d


class LabeledSlider(QWidget):
    """Slider with a caption and live value label."""

    valueChanged = Signal(int)

    def __init__(self, label: str, lo: int, hi: int, value: int, step: int = 1,
                 suffix: str = "", parent=None):
        super().__init__(parent)
        self.suffix = suffix
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(1)
        top = QHBoxLayout()
        self._cap = QLabel(label)
        self._val = QLabel()
        self._val.setStyleSheet(f"color: {theme.ACCENT};")
        self._val.setAlignment(Qt.AlignRight)
        top.addWidget(self._cap)
        top.addWidget(self._val)
        lay.addLayout(top)
        self._s = QSlider(Qt.Horizontal)
        self._s.setRange(lo, hi)
        self._s.setSingleStep(step)
        self._s.setPageStep(step)
        self._s.setValue(value)
        self._s.valueChanged.connect(self._on)
        lay.addWidget(self._s)
        self._on(value)

    def _on(self, v):
        self._val.setText(f"{v}{self.suffix}")
        self.valueChanged.emit(v)

    def value(self):
        return self._s.value()

    def set_value(self, v):
        self._s.setValue(v)


class GainPanel(QFrame):
    """RX front-end: LNA / VGA / RF-Amp / Bias-T, bound to the RadioHub.

    Mirrors the PortaPack receiver front-end row (P.Amp, LNA, VGA) plus the
    antenna-port Bias-T (DC power) toggle.
    """

    def __init__(self, hub, parent=None, show_bias=True):
        super().__init__(parent)
        self.hub = hub
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.lna = LabeledSlider("LNA (IF)", 0, 40, int(hub.cfg.lna_gain),
                                 step=8, suffix=" dB")
        self.vga = LabeledSlider("VGA (BB)", 0, 62, int(hub.cfg.vga_gain),
                                 step=2, suffix=" dB")
        self.amp = QCheckBox("RF Amp (+14 dB)")
        self.amp.setChecked(hub.cfg.amp_enable)
        self.lna.valueChanged.connect(lambda v: hub.set_gains(lna=v))
        self.vga.valueChanged.connect(lambda v: hub.set_gains(vga=v))
        self.amp.toggled.connect(lambda b: hub.set_gains(amp=b))
        lay.addWidget(self.lna)
        lay.addWidget(self.vga)
        lay.addWidget(self.amp)
        if show_bias:
            self.bias = QCheckBox("Bias-T (antenna DC power)")
            self.bias.setChecked(hub.cfg.bias_tee)
            self.bias.setToolTip("Supplies ~3.3 V / 50 mA on the antenna port "
                                 "for active antennas / LNAs. Do not enable into "
                                 "a DC-shorted antenna.")
            self.bias.toggled.connect(hub.set_bias_tee)
            lay.addWidget(self.bias)


class BiasTeeBox(QCheckBox):
    """Standalone Bias-T toggle for TX apps / panels without a full GainPanel."""

    def __init__(self, hub, parent=None):
        super().__init__("Bias-T (antenna DC power)", parent)
        self.setChecked(hub.cfg.bias_tee)
        self.setToolTip("Antenna-port DC power for active antennas. "
                        "Never enable into a DC-shorted load.")
        self.toggled.connect(hub.set_bias_tee)


class FreqStepCombo(QComboBox):
    """Selects the tuning step used by FrequencyDisplay wheel/keys."""

    def __init__(self, hub, parent=None):
        super().__init__(parent)
        from ..sdr.backend import FREQ_STEPS
        self.hub = hub
        self._steps = FREQ_STEPS
        for label, _hz in FREQ_STEPS:
            self.addItem(label)
        # default to current cfg step
        for i, (_l, hz) in enumerate(FREQ_STEPS):
            if hz == int(hub.cfg.freq_step):
                self.setCurrentIndex(i)
                break
        self.currentIndexChanged.connect(self._on)

    def _on(self, i):
        self.hub.cfg.freq_step = float(self._steps[i][1])


class SpectrumControls(QFrame):
    """HDSDR-style manual spectrum/waterfall adjustment, bound to a SpectrumWidget.

    Reference = top of the colour/dB scale, Range = dB span (contrast),
    Smooth = trace averaging, Speed = waterfall refresh rate, plus Auto.
    """

    def __init__(self, spectrum, parent=None):
        super().__init__(parent)
        self.spec = spectrum
        ref, rng = spectrum.reference()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)

        self.ref = LabeledSlider("Reference", -120, 20, int(ref), suffix=" dB")
        self.ref.valueChanged.connect(self._apply)
        lay.addWidget(self.ref)

        self.rng = LabeledSlider("Range", 20, 140, int(rng), suffix=" dB")
        self.rng.valueChanged.connect(self._apply)
        lay.addWidget(self.rng)

        self.smooth = LabeledSlider("Smoothing", 0, 95,
                                    int((1 - spectrum.avg_alpha) * 100),
                                    suffix=" %")
        self.smooth.valueChanged.connect(
            lambda v: setattr(self.spec, "avg_alpha", max(0.02, 1 - v / 100)))
        lay.addWidget(self.smooth)

        self.speed = LabeledSlider("WF speed", 2, 40,
                                   int(getattr(spectrum, "refresh_fps", 20)),
                                   suffix=" fps")
        self.speed.valueChanged.connect(
            lambda v: setattr(self.spec, "refresh_fps", float(v)))
        lay.addWidget(self.speed)

        row = QHBoxLayout()
        auto = QPushButton("Auto")
        auto.clicked.connect(self._auto)
        savewf = QPushButton("Save WF")
        savewf.clicked.connect(self._save_wf)
        self.fill = QCheckBox("Fill")
        self.fill.toggled.connect(self._set_fill)
        row.addWidget(auto)
        row.addWidget(savewf)
        row.addWidget(self.fill)
        lay.addLayout(row)

    def _apply(self, *_):
        self.spec.set_reference(self.ref.value(), self.rng.value())

    def _auto(self):
        res = self.spec.auto_range()
        if res:
            r, g = res
            self.ref.set_value(int(r))
            self.rng.set_value(int(g))

    def _save_wf(self):
        import os
        import time
        d = os.path.expanduser("~/portapack-pc/captures")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"waterfall_{time.strftime('%Y%m%d_%H%M%S')}.png")
        self.spec.save_waterfall(path)

    def _set_fill(self, on):
        try:
            import pyqtgraph as pg
            from . import theme
            self.spec.curve.setFillLevel(self.spec._ref - self.spec._range
                                         if on else None)
            self.spec.curve.setBrush(pg.mkBrush(0, 192, 192, 60) if on else None)
        except Exception:
            pass


class Field(QWidget):
    """Caption + arbitrary control on one row."""

    def __init__(self, caption: str, widget: QWidget, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 1, 0, 1)
        cap = QLabel(caption)
        cap.setMinimumWidth(90)
        cap.setStyleSheet(f"color: {theme.FG_DIM};")
        lay.addWidget(cap)
        lay.addWidget(widget, 1)
        self.widget = widget


def section(title: str) -> QLabel:
    lbl = QLabel(title.upper())
    lbl.setStyleSheet(f"color: {theme.FG_DIM}; font-size: 11px; "
                      f"border-bottom: 1px solid {theme.GREY}; padding-top:6px;")
    return lbl


def combo(items, current=0) -> QComboBox:
    c = QComboBox()
    for it in items:
        c.addItem(it)
    if isinstance(current, int):
        c.setCurrentIndex(current)
    else:
        c.setCurrentText(str(current))
    return c


def tx_button(text: str = "TRANSMIT") -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("TxButton")
    b.setCheckable(True)
    return b
