"""Audio output sink backed by sounddevice with a lock-free-ish ring buffer."""

from __future__ import annotations

import threading

import numpy as np

try:
    import sounddevice as sd
    _HAVE_SD = True
except Exception:  # pragma: no cover
    _HAVE_SD = False


class AudioSink:
    """Pushes mono float32 audio to the default output device.

    Audio is produced by the DSP thread via :meth:`push`; the sounddevice
    callback drains a ring buffer, underrunning to silence when starved.
    """

    def __init__(self, sample_rate: int = 48000, buffer_seconds: float = 0.5):
        self.sample_rate = sample_rate
        self.size = int(sample_rate * buffer_seconds)
        self._buf = np.zeros(self.size, dtype=np.float32)
        self._w = 0
        self._r = 0
        self._count = 0
        self._lock = threading.Lock()
        self._stream = None
        self.volume = 1.0
        self.muted = False
        self.available = _HAVE_SD

    def start(self):
        if not _HAVE_SD or self._stream is not None:
            return
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate, channels=1, dtype="float32",
                blocksize=1024, callback=self._callback)
            self._stream.start()
        except Exception:
            self._stream = None
            self.available = False

    def _callback(self, outdata, frames, time_info, status):
        with self._lock:
            avail = self._count
            n = min(frames, avail)
            if n > 0:
                end = self._r + n
                if end <= self.size:
                    chunk = self._buf[self._r:end]
                else:
                    chunk = np.concatenate(
                        [self._buf[self._r:], self._buf[:end - self.size]])
                self._r = end % self.size
                self._count -= n
            else:
                chunk = np.zeros(0, dtype=np.float32)
        out = np.zeros(frames, dtype=np.float32)
        if len(chunk):
            out[:len(chunk)] = chunk
        if self.muted:
            out[:] = 0.0
        outdata[:, 0] = out * self.volume

    def push(self, samples: np.ndarray):
        if not _HAVE_SD or self._stream is None:
            return
        samples = np.asarray(samples, dtype=np.float32).ravel()
        n = len(samples)
        with self._lock:
            if n > self.size:
                samples = samples[-self.size:]
                n = self.size
            # drop oldest on overflow
            if self._count + n > self.size:
                drop = self._count + n - self.size
                self._r = (self._r + drop) % self.size
                self._count -= drop
            end = self._w + n
            if end <= self.size:
                self._buf[self._w:end] = samples
            else:
                first = self.size - self._w
                self._buf[self._w:] = samples[:first]
                self._buf[:end - self.size] = samples[first:]
            self._w = end % self.size
            self._count += n

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        with self._lock:
            self._w = self._r = self._count = 0
