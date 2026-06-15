"""NOAA APT weather-satellite image decoder.

APT (Automatic Picture Transmission) on ~137 MHz is WFM; the recovered audio
carries a 2400 Hz AM subcarrier whose envelope is the image brightness.  Lines
run at 2 per second, 2080 words per line (sync + space + channel-A 909 px +
telemetry + sync + channel-B …).  This decoder rectifies the subcarrier, resamples
to the 4160 word/s pixel grid and emits image rows.
"""

from __future__ import annotations

import numpy as np
from scipy import signal

APT_CARRIER = 2400.0
APT_WORD_RATE = 4160      # pixels per second (2 lines × 2080)
APT_LINE = 2080           # words per line


class APTDecoder:
    def __init__(self, audio_rate: float):
        self.fs = audio_rate
        # envelope low-pass (below the 2400 Hz subcarrier)
        self._lp = signal.firwin(65, 1200.0 / (audio_rate / 2)).astype(np.float32)
        self._zi = np.zeros(len(self._lp) - 1, dtype=np.float32)
        self._resid = np.zeros(0, dtype=np.float32)
        self._linebuf = np.zeros(0, dtype=np.float32)
        self.up = APT_WORD_RATE
        self.down = int(round(audio_rate))
        from math import gcd
        g = gcd(self.up, self.down)
        self.up //= g
        self.down //= g

    def process(self, audio: np.ndarray) -> list[np.ndarray]:
        # rectify the AM subcarrier and low-pass to get the envelope
        env = np.abs(audio).astype(np.float32)
        env, self._zi = signal.lfilter(self._lp, 1.0, env, zi=self._zi)
        # resample envelope to the 4160 word/s pixel grid
        px = signal.resample_poly(env, self.up, self.down).astype(np.float32)
        self._linebuf = np.concatenate([self._linebuf, px])
        rows = []
        while len(self._linebuf) >= APT_LINE:
            line = self._linebuf[:APT_LINE]
            self._linebuf = self._linebuf[APT_LINE:]
            # normalise to 0..255 using a robust span
            lo = np.percentile(line, 1)
            hi = np.percentile(line, 99)
            row = np.clip((line - lo) / (hi - lo + 1e-9) * 255, 0, 255)
            rows.append(row.astype(np.uint8))
        return rows


def synth_apt(image: np.ndarray, audio_rate: float) -> np.ndarray:
    """Build a test APT audio stream from a (rows×2080) uint8 image."""
    rows, width = image.shape
    assert width == APT_LINE
    spp = audio_rate / APT_WORD_RATE             # audio samples per pixel
    bright = image.astype(np.float32).ravel() / 255.0
    amp = np.repeat(bright, int(round(spp)))
    t = np.arange(len(amp)) / audio_rate
    return ((0.3 + 0.7 * amp) * np.sin(2 * np.pi * APT_CARRIER * t)).astype(np.float32)
