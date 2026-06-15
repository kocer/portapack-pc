"""SSTV decoder — Martin and Scottie colour modes.

The received audio encodes pixel brightness as tone frequency (1500 Hz black …
2300 Hz white) with 1200 Hz horizontal-sync pulses.  We recover the audio's
instantaneous frequency, detect sync pulses, and slice each line's R/G/B scans
per the selected mode's timing.
"""

from __future__ import annotations

import numpy as np

# mode timing: (scan_ms_per_channel, order, sync_ms, porch_ms, width, height)
MODES = {
    "Martin M1":  dict(scan=146.432, sync=4.862, porch=0.572, order="GBR",
                       width=320, height=256),
    "Martin M2":  dict(scan=73.216, sync=4.862, porch=0.572, order="GBR",
                       width=320, height=256),
    "Scottie S1": dict(scan=138.240, sync=9.0, porch=1.5, order="GBR",
                       width=320, height=256, scottie=True),
    "Scottie S2": dict(scan=88.064, sync=9.0, porch=1.5, order="GBR",
                       width=320, height=256, scottie=True),
}


def inst_freq(audio: np.ndarray, fs: float) -> np.ndarray:
    """Instantaneous frequency (Hz) of a real audio signal via analytic phase."""
    from scipy.signal import hilbert
    a = hilbert(audio)
    phase = np.unwrap(np.angle(a))
    f = np.diff(phase) / (2 * np.pi) * fs
    return np.concatenate([f[:1], f])


class SSTVDecoder:
    def __init__(self, audio_rate: float, mode: str = "Martin M1"):
        self.fs = audio_rate
        self.set_mode(mode)
        self._buf = np.zeros(0, dtype=np.float32)

    def set_mode(self, mode: str):
        self.mode = mode
        self.spec = MODES[mode]
        sc = self.spec["scan"] / 1000.0
        self.line_s = self.spec["sync"] / 1000.0 + (
            sc * 3 + self.spec["porch"] * 3 / 1000.0)
        self.width = self.spec["width"]

    def process(self, audio: np.ndarray) -> list[np.ndarray]:
        self._buf = np.concatenate([self._buf, audio.astype(np.float32)])
        rows = []
        line_n = int(self.line_s * self.fs)
        while len(self._buf) >= line_n * 2:
            seg = self._buf[:line_n * 2]
            sync = self._find_sync(seg)
            if sync is None:
                self._buf = self._buf[line_n:]
                continue
            line = self._buf[sync:sync + line_n]
            if len(line) < line_n:
                break
            rows.append(self._decode_line(line))
            self._buf = self._buf[sync + line_n:]
        if len(self._buf) > line_n * 8:
            self._buf = self._buf[-line_n * 4:]
        return rows

    def _find_sync(self, seg):
        # 1200 Hz sync pulse → strong low-frequency region
        f = inst_freq(seg, self.fs)
        sync_len = int(self.spec["sync"] / 1000.0 * self.fs)
        low = (f < 1350).astype(np.float32)
        kern = np.ones(sync_len) / sync_len
        score = np.convolve(low, kern, "valid")
        i = int(np.argmax(score))
        return i if score[i] > 0.7 else None

    def _decode_line(self, line):
        f = inst_freq(line, self.fs)
        spec = self.spec
        sync_n = int(spec["sync"] / 1000.0 * self.fs)
        porch_n = int(spec["porch"] / 1000.0 * self.fs)
        scan_n = int(spec["scan"] / 1000.0 * self.fs)
        out = np.zeros((self.width, 3), dtype=np.uint8)
        pos = sync_n + porch_n
        order = spec["order"]
        chans = {}
        for ch in order:
            seg = f[pos:pos + scan_n]
            if len(seg) < scan_n:
                seg = np.pad(seg, (0, scan_n - len(seg)), constant_values=1900)
            # map 1500..2300 Hz -> 0..255
            px = np.clip((seg - 1500.0) / 800.0 * 255, 0, 255)
            idx = np.linspace(0, len(px) - 1, self.width).astype(int)
            chans[ch] = px[idx].astype(np.uint8)
            pos += scan_n + porch_n
        out[:, 0] = chans.get("R", 0)
        out[:, 1] = chans.get("G", 0)
        out[:, 2] = chans.get("B", 0)
        return out


def synth_sstv_line(rgb_row: np.ndarray, fs: float, mode="Martin M1") -> np.ndarray:
    """Synthesize one SSTV line (audio) from an (width×3) uint8 row, for tests."""
    spec = MODES[mode]
    sync_n = int(spec["sync"] / 1000.0 * fs)
    porch_n = int(spec["porch"] / 1000.0 * fs)
    scan_n = int(spec["scan"] / 1000.0 * fs)
    freqs = []
    freqs.append(np.full(sync_n, 1200.0))
    for ch in spec["order"]:
        idx = {"R": 0, "G": 1, "B": 2}[ch]
        vals = rgb_row[:, idx].astype(np.float32)
        tone = 1500.0 + vals / 255.0 * 800.0
        scan = np.repeat(tone, int(np.ceil(scan_n / len(tone))))[:scan_n]
        freqs.append(np.full(porch_n, 1500.0))
        freqs.append(scan)
    f = np.concatenate(freqs)
    ph = np.cumsum(2 * np.pi * f / fs)
    return np.sin(ph).astype(np.float32)
