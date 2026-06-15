"""SDR backend: owns the HackRF (via SoapySDR) and runs RX/TX streaming threads.

The :class:`RadioHub` is the single owner of the radio device, mirroring the
PortaPack model where only one application drives the radio at a time.  When no
HackRF is present it transparently falls back to a simulation source so the
whole UI remains usable for development/testing without hardware.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from PySide6.QtCore import QObject, Signal

try:
    import SoapySDR
    from SoapySDR import SOAPY_SDR_RX, SOAPY_SDR_TX, SOAPY_SDR_CF32
    _HAVE_SOAPY = True
except Exception:  # pragma: no cover - environment without SoapySDR
    _HAVE_SOAPY = False


# HackRF One hardware limits (Hz)
HACKRF_FREQ_MIN = 1_000_000
HACKRF_FREQ_MAX = 6_000_000_000
HACKRF_RATE_MIN = 2_000_000
HACKRF_RATE_MAX = 20_000_000

# Default front-end configuration
DEFAULT_FREQ = 100_000_000
DEFAULT_RATE = 2_400_000


@dataclass
class RadioConfig:
    """Mutable front-end state shared between UI and streaming threads."""

    frequency: float = DEFAULT_FREQ
    sample_rate: float = DEFAULT_RATE
    lna_gain: float = 24.0          # HackRF LNA (IF), 0..40 dB, 8 dB steps
    vga_gain: float = 20.0          # HackRF VGA (BB), 0..62 dB, 2 dB steps
    amp_enable: bool = False        # HackRF RF amp (+14 dB)
    tx_vga_gain: float = 30.0       # HackRF TX IF VGA, 0..47 dB
    bandwidth: float = 0.0          # baseband filter bandwidth, 0 = auto
    bias_tee: bool = False          # antenna port DC power (Bias-T, ~3.3V/50mA)
    freq_corr_ppm: float = 0.0      # frequency correction in ppm
    freq_step: float = 25_000.0     # tuning step for the frequency display


# HackRF baseband filter bandwidths (Hz) selectable on the MAX2837
HACKRF_BANDWIDTHS = [1_750_000, 2_500_000, 3_500_000, 5_000_000, 5_500_000,
                     6_000_000, 7_000_000, 8_000_000, 9_000_000, 10_000_000,
                     12_000_000, 14_000_000, 15_000_000, 20_000_000, 24_000_000,
                     28_000_000]

# Frequency tuning steps (Hz) — matches Mayhem's freqman step table
FREQ_STEPS = [
    ("1 Hz", 1), ("10 Hz", 10), ("100 Hz", 100), ("1 kHz", 1_000),
    ("5 kHz", 5_000), ("6.25 kHz", 6_250), ("9 kHz", 9_000), ("10 kHz", 10_000),
    ("12.5 kHz", 12_500), ("25 kHz", 25_000), ("100 kHz", 100_000),
    ("1 MHz", 1_000_000),
]


class DeviceError(RuntimeError):
    pass


def enumerate_devices() -> list[dict]:
    """Return a list of available SoapySDR devices (empty if none/unavailable)."""
    if not _HAVE_SOAPY:
        return []
    try:
        return [dict(r) for r in SoapySDR.Device.enumerate()]
    except Exception:
        return []


def find_hackrf() -> Optional[dict]:
    for dev in enumerate_devices():
        driver = (dev.get("driver") or "").lower()
        label = (dev.get("label") or "").lower()
        if "hackrf" in driver or "hackrf" in label:
            return dev
    return None


class _SimSource:
    """Generates synthetic IQ so the application works without hardware.

    Produces band-limited noise plus a few moving carriers and a wideband-FM
    looking signal near the tuned frequency, scaled to the configured rate.
    """

    def __init__(self, cfg: RadioConfig):
        self.cfg = cfg
        self._phase = 0.0
        self._t0 = time.time()

    def read(self, n: int) -> np.ndarray:
        fs = self.cfg.sample_rate
        t = (np.arange(n) + self._phase) / fs
        self._phase += n
        elapsed = time.time() - self._t0

        # Noise floor
        iq = (np.random.randn(n) + 1j * np.random.randn(n)).astype(np.complex64)
        iq *= 0.05

        # A WFM-ish carrier wandering +-150 kHz around DC (i.e. on-tune)
        fm_dev = 75_000 * np.sin(2 * np.pi * 0.7 * (t + elapsed)) \
            + 30_000 * np.sin(2 * np.pi * 3.0 * (t + elapsed))
        fc = 0.0
        inst = 2 * np.pi * (fc * t + np.cumsum(fm_dev) / fs)
        iq += (0.5 * np.exp(1j * inst)).astype(np.complex64)

        # A couple of static carriers at fixed offsets
        for off, amp in ((300_000, 0.25), (-450_000, 0.2), (700_000, 0.15)):
            if abs(off) < fs / 2:
                iq += (amp * np.exp(1j * 2 * np.pi * off * t)).astype(np.complex64)

        # Gentle real-time pacing so the stream rate is believable
        return iq


class RxWorker(threading.Thread):
    """Reads IQ from the device/sim and hands blocks to a callback."""

    def __init__(self, hub: "RadioHub", block_size: int = 65536):
        super().__init__(daemon=True)
        self.hub = hub
        self.block_size = block_size
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        hub = self.hub
        n = self.block_size
        if hub._sim:
            sim = _SimSource(hub.cfg)
            interval = n / hub.cfg.sample_rate
            next_t = time.time()
            while not self._stop.is_set():
                block = sim.read(n)
                hub._dispatch_rx(block)
                next_t += interval
                dt = next_t - time.time()
                if dt > 0:
                    time.sleep(min(dt, 0.2))
                else:
                    next_t = time.time()
            return

        # Real hardware path
        sr = hub._device
        stream = sr.setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
        sr.activateStream(stream)
        buff = np.empty(n, np.complex64)
        try:
            while not self._stop.is_set():
                got = 0
                while got < n and not self._stop.is_set():
                    res = sr.readStream(stream, [buff[got:]], n - got, timeoutUs=500000)
                    if res.ret > 0:
                        got += res.ret
                    elif res.ret in (-1, -4):  # timeout / overflow, keep going
                        if got == 0:
                            break
                    else:
                        break
                if got > 0:
                    hub._dispatch_rx(buff[:got].copy())
        finally:
            try:
                sr.deactivateStream(stream)
                sr.closeStream(stream)
            except Exception:
                pass


class TxWorker(threading.Thread):
    """Pulls IQ from a callback and writes it to the device."""

    def __init__(self, hub: "RadioHub", source, block_size: int = 65536):
        super().__init__(daemon=True)
        self.hub = hub
        self.source = source  # callable(n) -> np.complex64 array (or None to stop)
        self.block_size = block_size
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        hub = self.hub
        n = self.block_size
        if hub._sim:
            # No real TX in sim mode; just drain the source for timing/UI.
            interval = n / hub.cfg.sample_rate
            while not self._stop.is_set():
                block = self.source(n)
                if block is None:
                    break
                time.sleep(interval)
            hub._tx_finished()
            return

        sr = hub._device
        stream = sr.setupStream(SOAPY_SDR_TX, SOAPY_SDR_CF32)
        sr.activateStream(stream)
        try:
            while not self._stop.is_set():
                block = self.source(n)
                if block is None:
                    break
                block = np.ascontiguousarray(block, dtype=np.complex64)
                sent = 0
                while sent < len(block) and not self._stop.is_set():
                    res = sr.writeStream(stream, [block[sent:]], len(block) - sent,
                                         timeoutUs=500000)
                    if res.ret > 0:
                        sent += res.ret
                    else:
                        break
        finally:
            try:
                sr.deactivateStream(stream)
                sr.closeStream(stream)
            except Exception:
                pass
            hub._tx_finished()


class RadioHub(QObject):
    """Single owner of the radio device.

    Apps call :meth:`start_rx` with a callback to receive IQ blocks, and adjust
    the front end through :meth:`set_frequency`, :meth:`set_sample_rate`,
    :meth:`set_gains`.  Signals report device/stream state to the UI.
    """

    status_changed = Signal(str)      # human readable device status
    rx_active = Signal(bool)
    tx_active = Signal(bool)
    overflow = Signal()

    def __init__(self, force_sim: bool = False):
        super().__init__()
        self.cfg = RadioConfig()
        self._device = None
        self._sim = True
        self._driver = "simulation"
        self._rx_worker: Optional[RxWorker] = None
        self._tx_worker: Optional[TxWorker] = None
        self._rx_callback = None
        self._lock = threading.RLock()
        if not force_sim:
            self._try_open()

    # ---- device lifecycle -------------------------------------------------
    def _try_open(self):
        if not _HAVE_SOAPY:
            self._sim = True
            self._driver = "simulation"
            self.status_changed.emit("SoapySDR unavailable — simulation mode")
            return
        import gc
        import time as _t
        last_err = "no device"
        # Open by passing the raw enumerate kwargs straight back to make() —
        # passing a plain {"driver":"hackrf"} dict can yield "no match" on some
        # SoapyHackRF builds, and a previous leaked handle may need a moment.
        for attempt in range(3):
            try:
                results = SoapySDR.Device.enumerate()
            except Exception as e:
                last_err = f"enumerate: {e}"; results = []
            match = None
            for r in results:
                d = dict(r)
                if "hackrf" in (d.get("driver", "") + d.get("label", "")).lower():
                    match = r
                    break
            if match is None:
                self._sim = True
                self._driver = "simulation"
                self.status_changed.emit("No HackRF found — simulation mode")
                return
            try:
                self._device = SoapySDR.Device(match)
                self._sim = False
                self._driver = dict(match).get("driver", "hackrf")
                self._apply_all()
                serial = dict(match).get("serial", "")
                self.status_changed.emit(
                    f"HackRF connected ({serial[-8:]})" if serial
                    else "HackRF connected")
                return
            except Exception as e:  # pragma: no cover
                last_err = str(e)
                self._device = None
                gc.collect()           # release any leaked handle
                _t.sleep(0.6)
        self._sim = True
        self._driver = "simulation"
        self.status_changed.emit(f"HackRF open failed ({last_err}) — simulation")

    def rescan(self):
        """Re-probe for hardware (e.g. after user plugs in the HackRF)."""
        if self.is_streaming:
            return False
        was_sim = self._sim
        self._try_open()
        return was_sim and not self._sim

    @property
    def is_sim(self) -> bool:
        return self._sim

    @property
    def driver(self) -> str:
        return self._driver

    @property
    def is_streaming(self) -> bool:
        return (self._rx_worker is not None and self._rx_worker.is_alive()) or \
               (self._tx_worker is not None and self._tx_worker.is_alive())

    # ---- front-end control ------------------------------------------------
    def _apply_all(self):
        if self._sim or self._device is None:
            return
        d = self._device
        try:
            d.setSampleRate(SOAPY_SDR_RX, 0, self.cfg.sample_rate)
            d.setFrequency(SOAPY_SDR_RX, 0, self.cfg.frequency)
            d.setGain(SOAPY_SDR_RX, 0, "LNA", self.cfg.lna_gain)
            d.setGain(SOAPY_SDR_RX, 0, "VGA", self.cfg.vga_gain)
            d.setGain(SOAPY_SDR_RX, 0, "AMP", 14.0 if self.cfg.amp_enable else 0.0)
            bw = self.cfg.bandwidth or self.cfg.sample_rate * 0.75
            d.setBandwidth(SOAPY_SDR_RX, 0, bw)
            self._apply_bias()
            self._apply_corr()
        except Exception as e:
            self.status_changed.emit(f"config error: {e}")

    def _apply_bias(self):
        """Toggle the HackRF antenna-port Bias-T (DC power) via SoapyHackRF."""
        if self._sim or self._device is None:
            return
        try:
            self._device.writeSetting(
                "bias_tx", "true" if self.cfg.bias_tee else "false")
        except Exception:
            pass

    def _apply_corr(self):
        if self._sim or self._device is None:
            return
        try:
            self._device.setFrequencyCorrection(SOAPY_SDR_RX, 0,
                                                 self.cfg.freq_corr_ppm)
        except Exception:
            pass

    def set_frequency(self, hz: float):
        hz = float(max(HACKRF_FREQ_MIN, min(HACKRF_FREQ_MAX, hz)))
        self.cfg.frequency = hz
        if not self._sim and self._device is not None:
            try:
                self._device.setFrequency(SOAPY_SDR_RX, 0, hz)
            except Exception as e:
                self.status_changed.emit(f"freq error: {e}")

    def set_sample_rate(self, hz: float):
        hz = float(max(HACKRF_RATE_MIN, min(HACKRF_RATE_MAX, hz)))
        self.cfg.sample_rate = hz
        if not self._sim and self._device is not None:
            try:
                self._device.setSampleRate(SOAPY_SDR_RX, 0, hz)
                self._device.setBandwidth(SOAPY_SDR_RX, 0,
                                          self.cfg.bandwidth or hz * 0.75)
            except Exception as e:
                self.status_changed.emit(f"rate error: {e}")

    def set_gains(self, lna=None, vga=None, amp=None):
        if lna is not None:
            self.cfg.lna_gain = float(lna)
        if vga is not None:
            self.cfg.vga_gain = float(vga)
        if amp is not None:
            self.cfg.amp_enable = bool(amp)
        if not self._sim and self._device is not None:
            try:
                d = self._device
                d.setGain(SOAPY_SDR_RX, 0, "LNA", self.cfg.lna_gain)
                d.setGain(SOAPY_SDR_RX, 0, "VGA", self.cfg.vga_gain)
                d.setGain(SOAPY_SDR_RX, 0, "AMP",
                          14.0 if self.cfg.amp_enable else 0.0)
            except Exception as e:
                self.status_changed.emit(f"gain error: {e}")

    def set_bias_tee(self, on: bool):
        """Enable/disable antenna-port DC power (Bias-T) for active antennas."""
        self.cfg.bias_tee = bool(on)
        self._apply_bias()

    def set_bandwidth(self, hz: float):
        """Set the baseband (IF) filter bandwidth explicitly (0 = auto)."""
        self.cfg.bandwidth = float(hz)
        if not self._sim and self._device is not None:
            try:
                bw = hz or self.cfg.sample_rate * 0.75
                self._device.setBandwidth(SOAPY_SDR_RX, 0, bw)
            except Exception as e:
                self.status_changed.emit(f"bw error: {e}")

    def set_freq_correction(self, ppm: float):
        self.cfg.freq_corr_ppm = float(ppm)
        self._apply_corr()

    # ---- RX ---------------------------------------------------------------
    def start_rx(self, callback, block_size: int = 65536):
        """Begin streaming IQ; ``callback(np.complex64[])`` is called per block.

        The callback runs in the RX worker thread — apps must marshal to the GUI
        thread themselves (e.g. via a Qt signal) before touching widgets.
        """
        with self._lock:
            self.stop()
            self._rx_callback = callback
            if not self._sim:
                self._apply_all()
            self._rx_worker = RxWorker(self, block_size)
            self._rx_worker.start()
            self.rx_active.emit(True)

    def _dispatch_rx(self, block: np.ndarray):
        cb = self._rx_callback
        if cb is not None:
            try:
                cb(block)
            except Exception:
                pass

    # ---- TX ---------------------------------------------------------------
    def start_tx(self, source, block_size: int = 65536):
        """Begin transmitting; ``source(n)`` returns IQ or None to finish."""
        with self._lock:
            self.stop()
            if not self._sim:
                try:
                    d = self._device
                    d.setSampleRate(SOAPY_SDR_TX, 0, self.cfg.sample_rate)
                    d.setFrequency(SOAPY_SDR_TX, 0, self.cfg.frequency)
                    d.setGain(SOAPY_SDR_TX, 0, "VGA", self.cfg.tx_vga_gain)
                    d.setGain(SOAPY_SDR_TX, 0, "AMP",
                              14.0 if self.cfg.amp_enable else 0.0)
                    self._apply_bias()
                except Exception as e:
                    self.status_changed.emit(f"tx config error: {e}")
            self._tx_worker = TxWorker(self, source, block_size)
            self._tx_worker.start()
            self.tx_active.emit(True)

    def _tx_finished(self):
        self.tx_active.emit(False)

    # ---- stop -------------------------------------------------------------
    def stop(self):
        with self._lock:
            if self._rx_worker is not None:
                self._rx_worker.stop()
                self._rx_worker.join(timeout=1.0)
                self._rx_worker = None
                self.rx_active.emit(False)
            if self._tx_worker is not None:
                self._tx_worker.stop()
                self._tx_worker.join(timeout=1.0)
                self._tx_worker = None
                self.tx_active.emit(False)
            self._rx_callback = None

    def close(self):
        self.stop()
        if self._device is not None and not self._sim:
            try:
                self._device = None
            except Exception:
                pass

    # ---- temporary device hand-off (for external tools like rtl_433) ------
    def release_device(self) -> bool:
        """Fully release the SoapySDR handle so an external process can open the
        HackRF.  Returns True if a hardware device was released."""
        with self._lock:
            self.stop()
            if self._sim or self._device is None:
                return False
            try:
                self._device = None
            except Exception:
                pass
            import gc
            gc.collect()
            self.status_changed.emit("HackRF handed to external decoder")
            return True

    def reacquire(self):
        """Re-open the HackRF after an external tool has released it."""
        with self._lock:
            if not self._sim and self._device is not None:
                return
            self._try_open()
