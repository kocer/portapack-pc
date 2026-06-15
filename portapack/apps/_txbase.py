"""Shared base for one-shot / looped waveform transmitters."""

from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout

from ..ui import theme, widgets
from .base import AppView


class TxWaveApp(AppView):
    """Builds a complex64 burst once, streams it on TX.

    Subclasses set ``default_freq`` / ``tx_sample_rate``, implement
    :meth:`build_extra` (controls) and :meth:`build_waveform` (the IQ burst),
    and may set ``self.loop`` for continuous repeat.
    """

    default_freq = 433_920_000
    tx_sample_rate = 2_400_000
    button_text = "TRANSMIT"
    default_vga = 30

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._wave = None
        self._pos = 0
        self.loop = False
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(self.default_freq)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)
        self.body = QGroupBox(self.title)
        self.body_lay = QVBoxLayout(self.body)
        self.build_extra(self.body_lay)
        lay.addWidget(self.body)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, self.default_vga,
                                         suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        from PySide6.QtWidgets import QCheckBox
        self.amp_box = QCheckBox("RF Amp (+14 dB)")
        self.amp_box.setChecked(self.hub.cfg.amp_enable)
        self.amp_box.toggled.connect(lambda b: self.hub.set_gains(amp=b))
        g2.addWidget(self.amp_box)
        self.bias_box = widgets.BiasTeeBox(self.hub)
        g2.addWidget(self.bias_box)
        self.monitor_box = QCheckBox("🔊 Monitor (local sidetone)")
        g2.addWidget(self.monitor_box)
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button(self.button_text)
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        self.warn = QLabel("")
        self.warn.setStyleSheet(f"color:{theme.ACCENT2};")
        self.warn.setWordWrap(True)
        lay.addWidget(self.warn)
        lay.addStretch(1)

    # hooks
    def build_extra(self, layout):
        ...

    def build_waveform(self) -> np.ndarray:
        return np.zeros(0, dtype=np.complex64)

    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            self.hub.set_sample_rate(self.tx_sample_rate)
            try:
                self._wave = self.build_waveform()
            except Exception as e:
                self.warn.setText(f"build error: {e}")
                self.tx_btn.setChecked(False)
                return
            if self._wave is None or len(self._wave) == 0:
                self.warn.setText("nothing to transmit")
                self.tx_btn.setChecked(False)
                return
            self._pos = 0
            if self.hub.is_sim:
                self.warn.setText("Simulation — no RF emitted. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            self.warn.setText("")

    def _gen(self, n):
        if not self.tx_btn.isChecked() or self._wave is None:
            return None
        out = np.zeros(n, dtype=np.complex64)
        filled = 0
        while filled < n:
            remain = len(self._wave) - self._pos
            if remain <= 0:
                if self.loop:
                    self._pos = 0
                    continue
                break
            take = min(remain, n - filled)
            out[filled:filled + take] = self._wave[self._pos:self._pos + take]
            filled += take
            self._pos += take
        if filled == 0:
            self.emit_ui("done")
            return None
        if self.monitor_box.isChecked() and self.audio is not None:
            mon = tx_monitor_audio(out[:filled], self.hub.cfg.sample_rate)
            if mon is not None:
                self.audio.push(mon)
        return out

    def _on_ui(self, msg):
        if msg == "done":
            self.tx_btn.setChecked(False)
            self.warn.setText("sent")


# ---- local TX monitor (sidetone) ------------------------------------------
def tx_monitor_audio(iq: np.ndarray, fs: float, out_rate: int = 48000):
    """Derive a listenable ~48 kHz audio preview of a TX IQ block.

    HackRF is half-duplex, so this is a *local* monitor of what is being
    modulated (not off-air): FM discriminator (catches tone/FM/FSK) mixed with
    the AM envelope (catches OOK/AM).  Crude stride-decimation is fine here.
    """
    if iq is None or len(iq) < 4:
        return None
    q = max(1, int(fs // out_rate))
    x = iq[::q]
    if len(x) < 4:
        return None
    fm = np.angle(x[1:] * np.conj(x[:-1])).astype(np.float32)
    fm = np.concatenate([fm[:1], fm]) / np.pi          # FM/FSK/tone content
    env = np.abs(x).astype(np.float32)
    env = env - np.mean(env)                            # AM/OOK keying
    a = 0.6 * fm + 0.8 * env
    m = np.max(np.abs(a)) + 1e-9
    return (a / m * 0.5).astype(np.float32)


# ---- shared signal-building helpers ---------------------------------------
def fm_modulate(audio: np.ndarray, fs: float, deviation: float,
                amp: float = 0.9) -> np.ndarray:
    ph = np.cumsum(audio) / fs * 2 * np.pi * deviation
    return (amp * np.exp(1j * ph)).astype(np.complex64)


def fsk_modulate(bits, fs: float, baud: float, shift: float,
                 amp: float = 0.9) -> np.ndarray:
    """Continuous-phase 2-FSK: +shift/2 for 1, -shift/2 for 0."""
    sps = int(fs / baud)
    freqs = np.repeat([(shift / 2 if b else -shift / 2) for b in bits], sps)
    ph = np.cumsum(2 * np.pi * freqs / fs)
    return (amp * np.exp(1j * ph)).astype(np.complex64)


def ax25_afsk(frame_bits, fs: float, deviation: float = 3500.0) -> np.ndarray:
    """NRZI + Bell202 AFSK1200, then FM-modulate (for APRS TX)."""
    nrzi = []
    level = 0
    for b in frame_bits:
        if b == 0:
            level ^= 1
        nrzi.append(level)
    baud = 1200
    sps = int(fs / baud)
    audio = []
    phase = 0.0
    for bit in nrzi:
        f = 1200.0 if bit else 2200.0
        for _ in range(sps):
            phase += 2 * np.pi * f / fs
            audio.append(np.sin(phase))
    audio = np.array(audio, dtype=np.float32) * 0.5
    return fm_modulate(audio, fs, deviation)


def hdlc_frame(payload: bytes) -> list:
    """Wrap payload bytes (incl. FCS) with HDLC flags + bit stuffing → bit list."""
    crc = 0xFFFF
    for b in payload:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    crc ^= 0xFFFF
    data = payload + bytes([crc & 0xFF, (crc >> 8) & 0xFF])
    bits = []
    for byte in data:
        for i in range(8):
            bits.append((byte >> i) & 1)
    stuffed = []
    ones = 0
    for b in bits:
        stuffed.append(b)
        if b == 1:
            ones += 1
            if ones == 5:
                stuffed.append(0)
                ones = 0
        else:
            ones = 0
    flag = [0, 1, 1, 1, 1, 1, 1, 0]
    return flag * 8 + stuffed + flag * 4
