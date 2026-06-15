"""DSP building blocks: tuning, decimation, demodulators and audio resampling.

Everything is streaming-friendly: stateful blocks keep filter/PLL state across
calls so consecutive IQ blocks demodulate without clicks at the seams.
"""

from __future__ import annotations

import numpy as np
from scipy import signal


# ---------------------------------------------------------------------------
# Frequency translation (digital down conversion)
# ---------------------------------------------------------------------------
class Tuner:
    """Multiplies IQ by a complex NCO to shift ``offset`` Hz down to DC."""

    def __init__(self, sample_rate: float, offset: float = 0.0):
        self.sample_rate = sample_rate
        self.offset = offset
        self._phase = 0.0

    def set_offset(self, offset: float):
        self.offset = offset

    def process(self, iq: np.ndarray) -> np.ndarray:
        if self.offset == 0.0:
            return iq
        n = len(iq)
        k = -2 * np.pi * self.offset / self.sample_rate
        ph = self._phase + k * np.arange(n)
        self._phase = (self._phase + k * n) % (2 * np.pi)
        return (iq * np.exp(1j * ph)).astype(np.complex64)


# ---------------------------------------------------------------------------
# Decimation
# ---------------------------------------------------------------------------
class FirDecimator:
    """Low-pass FIR decimator that preserves state between blocks."""

    def __init__(self, factor: int, cutoff_ratio: float = 0.45, ntaps: int = 64):
        self.factor = int(factor)
        self.taps = signal.firwin(ntaps, cutoff_ratio / self.factor).astype(np.float32)
        self._zi = np.zeros(len(self.taps) - 1, dtype=np.complex64)

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = signal.lfilter(self.taps, 1.0, x, zi=self._zi)
        return y[:: self.factor].astype(np.complex64)


def best_decimation(in_rate: float, target: float) -> int:
    """Largest integer factor keeping output >= target."""
    factor = int(in_rate // target)
    return max(1, factor)


# ---------------------------------------------------------------------------
# Demodulators
# ---------------------------------------------------------------------------
class FMDemod:
    """Quadrature FM discriminator with optional de-emphasis."""

    def __init__(self, deviation: float = 75_000, sample_rate: float = 240_000,
                 deemph_us: float = 50.0):
        self.gain = sample_rate / (2 * np.pi * deviation)
        self._last = np.complex64(1 + 0j)
        self.sample_rate = sample_rate
        if deemph_us > 0:
            # one-pole de-emphasis
            dt = 1.0 / sample_rate
            alpha = dt / (deemph_us * 1e-6 + dt)
            self._deemph_b = np.array([alpha], dtype=np.float32)
            self._deemph_a = np.array([1.0, -(1 - alpha)], dtype=np.float32)
            self._deemph_zi = np.zeros(1, dtype=np.float32)
        else:
            self._deemph_a = None

    def process(self, iq: np.ndarray) -> np.ndarray:
        x = np.empty(len(iq) + 1, dtype=np.complex64)
        x[0] = self._last
        x[1:] = iq
        self._last = iq[-1] if len(iq) else self._last
        prod = x[1:] * np.conj(x[:-1])
        demod = np.angle(prod).astype(np.float32) * self.gain
        if self._deemph_a is not None:
            demod, self._deemph_zi = signal.lfilter(
                self._deemph_b, self._deemph_a, demod, zi=self._deemph_zi)
        return demod


class ComplexDCBlocker:
    """One-pole complex DC blocker for IQ — removes the HackRF DC offset / LO
    leakage on the signal path (``y[n] = x[n] - x[n-1] + R*y[n-1]``)."""

    def __init__(self, r: float = 0.9995):
        self.r = r
        self._x1 = np.complex64(0)
        self._y1 = np.complex64(0)

    def process(self, iq: np.ndarray) -> np.ndarray:
        b = np.array([1.0, -1.0], dtype=np.complex64)
        a = np.array([1.0, -self.r], dtype=np.complex64)
        zi = np.array([self.r * self._y1 - self._x1], dtype=np.complex64)
        y, zf = signal.lfilter(b, a, iq, zi=zi)
        self._x1 = iq[-1] if len(iq) else self._x1
        self._y1 = y[-1] if len(y) else self._y1
        return y.astype(np.complex64)


class AMDemod:
    """Envelope detector followed by a one-pole DC blocker.

    The DC blocker (``y[n] = x[n] - x[n-1] + R*y[n-1]``) removes the carrier
    DC term while preserving audio above a few Hz, keeping state across blocks.
    """

    def __init__(self, r: float = 0.999):
        self._b = np.array([1.0, -1.0], dtype=np.float32)
        self._a = np.array([1.0, -r], dtype=np.float32)
        self._zi = np.zeros(1, dtype=np.float32)

    def process(self, iq: np.ndarray) -> np.ndarray:
        env = np.abs(iq).astype(np.float32)
        out, self._zi = signal.lfilter(self._b, self._a, env, zi=self._zi)
        return out.astype(np.float32)


class SSBDemod:
    """Weaver/phasing-free SSB by real part of frequency-shifted signal.

    Assumes the IQ has already been tuned so the wanted sideband sits at DC;
    takes the real part for USB-like output. Adequate for voice intelligibility.
    """

    def __init__(self, lsb: bool = False):
        self.lsb = lsb

    def process(self, iq: np.ndarray) -> np.ndarray:
        return (iq.imag if self.lsb else iq.real).astype(np.float32)


# ---------------------------------------------------------------------------
# Audio resampling and AGC
# ---------------------------------------------------------------------------
class AudioResampler:
    """Rational resampler from ``in_rate`` to ``out_rate`` with state."""

    def __init__(self, in_rate: float, out_rate: float):
        from math import gcd
        in_rate = int(round(in_rate))
        out_rate = int(round(out_rate))
        g = gcd(in_rate, out_rate)
        self.up = out_rate // g
        self.down = in_rate // g
        # design a polyphase filter once
        self._buf = np.zeros(0, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        if self.up == 1 and self.down == 1:
            return x.astype(np.float32)
        return signal.resample_poly(x, self.up, self.down).astype(np.float32)


class AGC:
    """Simple automatic gain control for audio."""

    def __init__(self, target: float = 0.25, attack: float = 0.02,
                 decay: float = 0.0008):
        self.gain = 1.0
        self.target = target
        self.attack = attack
        self.decay = decay

    def process(self, x: np.ndarray) -> np.ndarray:
        peak = np.max(np.abs(x)) + 1e-9
        desired = self.target / peak
        rate = self.attack if desired < self.gain else self.decay
        self.gain += (desired - self.gain) * rate
        y = x * self.gain
        return np.clip(y, -1.0, 1.0).astype(np.float32)


def lowpass(x: np.ndarray, cutoff: float, fs: float, ntaps: int = 127) -> np.ndarray:
    taps = signal.firwin(ntaps, cutoff / (fs / 2))
    return signal.lfilter(taps, 1.0, x).astype(x.dtype)


# ---------------------------------------------------------------------------
# Spectrum helpers
# ---------------------------------------------------------------------------
def psd(iq: np.ndarray, nfft: int = 2048, window: str = "hann",
        max_segments: int = 16) -> np.ndarray:
    """Welch-averaged power spectrum (dB) of an IQ block.

    Averages up to ``max_segments`` overlapping FFTs across the block instead
    of a single noisy FFT, giving a stable, non-jittery trace and a flat noise
    floor from which real signals stand out clearly.
    """
    n = len(iq)
    if n < nfft:
        nfft = 1 << int(np.floor(np.log2(max(n, 2))))
    win = signal.get_window(window, nfft).astype(np.float32)
    wnorm = np.sum(win ** 2)
    # segment start positions with 50% overlap, capped at max_segments
    hop = nfft // 2
    starts = list(range(0, n - nfft + 1, hop))
    if not starts:
        starts = [0]
    if len(starts) > max_segments:
        idx = np.linspace(0, len(starts) - 1, max_segments).astype(int)
        starts = [starts[i] for i in idx]
    acc = np.zeros(nfft, dtype=np.float64)
    for s in starts:
        sp = np.fft.fftshift(np.fft.fft(iq[s:s + nfft] * win))
        acc += (np.abs(sp) ** 2)
    acc /= (len(starts) * wnorm)
    return (10 * np.log10(acc + 1e-12)).astype(np.float32)


def fm_stereo_mono(demod: np.ndarray, fs: float) -> np.ndarray:
    """Extract mono (L+R) audio from an FM-demodulated MPX signal."""
    return lowpass(demod, 15_000, fs)


class NotchFilter:
    """Stateful 2nd-order IIR notch at ``freq`` Hz (removes a tone/carrier)."""

    def __init__(self, freq: float, fs: float, q: float = 30.0):
        from scipy.signal import iirnotch
        self.b, self.a = iirnotch(freq / (fs / 2), q)
        self.b = self.b.astype(np.float32)
        self.a = self.a.astype(np.float32)
        self._zi = np.zeros(max(len(self.a), len(self.b)) - 1, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        y, self._zi = signal.lfilter(self.b, self.a, x, zi=self._zi)
        return y.astype(np.float32)


class NoiseReducer:
    """Simple spectral-gate noise reduction for audio (overlap-add)."""

    def __init__(self, nfft: int = 512, strength: float = 1.5):
        self.nfft = nfft
        self.strength = strength
        self._noise = None
        self._tail = np.zeros(0, dtype=np.float32)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.concatenate([self._tail, x.astype(np.float32)])
        n = (len(x) // self.nfft) * self.nfft
        self._tail = x[n:]
        if n == 0:
            return np.zeros(0, dtype=np.float32)
        out = np.empty(n, dtype=np.float32)
        for i in range(0, n, self.nfft):
            seg = x[i:i + self.nfft]
            sp = np.fft.rfft(seg * np.hanning(self.nfft))
            mag = np.abs(sp)
            if self._noise is None:
                self._noise = mag.copy()
            else:
                self._noise = 0.95 * self._noise + 0.05 * np.minimum(self._noise, mag)
            gain = np.maximum(0, mag - self.strength * self._noise) / (mag + 1e-9)
            out[i:i + self.nfft] = np.fft.irfft(sp * gain, self.nfft).astype(np.float32)
        return out
