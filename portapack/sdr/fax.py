"""HF weather fax (WEFAX / radiofax) decoder.

Marine/aviation weather charts are sent on HF (USB) as frequency-modulated
images: 1500 Hz = black, 2300 Hz = white, at a selectable line rate (commonly
120 lpm).  We recover the audio's instantaneous frequency and slice it into
image lines.  IOC 576 gives ~1809 pixels/line; we resample to a display width.
"""

from __future__ import annotations

import numpy as np


def inst_freq(audio: np.ndarray, fs: float) -> np.ndarray:
    from scipy.signal import hilbert
    a = hilbert(audio)
    f = np.diff(np.unwrap(np.angle(a))) / (2 * np.pi) * fs
    return np.concatenate([f[:1], f])


class WEFAXDecoder:
    def __init__(self, audio_rate: float, lpm: float = 120.0, width: int = 1200):
        self.fs = audio_rate
        self.width = width
        self.set_lpm(lpm)
        self._buf = np.zeros(0, dtype=np.float32)

    def set_lpm(self, lpm: float):
        self.lpm = lpm
        self.line_samples = int(self.fs * 60.0 / lpm)

    def process(self, audio: np.ndarray) -> list[np.ndarray]:
        self._buf = np.concatenate([self._buf, audio.astype(np.float32)])
        rows = []
        while len(self._buf) >= self.line_samples:
            seg = self._buf[:self.line_samples]
            self._buf = self._buf[self.line_samples:]
            f = inst_freq(seg, self.fs)
            # smooth out transition spikes (a few-sample moving average)
            k = max(3, int(self.fs / 4000))
            f = np.convolve(f, np.ones(k) / k, "same")
            # 1500 Hz black .. 2300 Hz white
            px = np.clip((f - 1500.0) / 800.0 * 255, 0, 255)
            # average the samples that fall in each output pixel
            edges = np.linspace(0, len(px), self.width + 1).astype(int)
            row = np.array([px[edges[i]:edges[i + 1]].mean()
                            if edges[i + 1] > edges[i] else px[edges[i]]
                            for i in range(self.width)])
            rows.append(row.astype(np.uint8))
        if len(self._buf) > self.line_samples * 8:
            self._buf = self._buf[-self.line_samples * 2:]
        return rows


def synth_wefax_line(row: np.ndarray, fs: float, lpm: float = 120.0) -> np.ndarray:
    """Synthesize one WEFAX audio line from a width-N uint8 brightness row."""
    line_n = int(fs * 60.0 / lpm)
    tone = 1500.0 + row.astype(np.float32) / 255.0 * 800.0
    f = np.repeat(tone, int(np.ceil(line_n / len(tone))))[:line_n]
    ph = np.cumsum(2 * np.pi * f / fs)
    return np.sin(ph).astype(np.float32)
