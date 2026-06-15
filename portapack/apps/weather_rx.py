"""Weather receiver — 433/868/915 MHz OOK temperature/humidity sensors."""
from __future__ import annotations
import numpy as np
from ..sdr import dsp
from ..sdr.decoders import OOKDecoder
from . import AppInfo, register
from ._rxlog import RxLogApp


class WeatherRx(RxLogApp):
    title = "Weather"
    default_freq = 433_920_000
    sample_rate = 2_400_000
    band_options = [("433.92", 433_920_000), ("868.3", 868_300_000),
                    ("915.0", 915_000_000)]
    extra_note = "OOK sensors (Acurite/LaCrosse/Oregon) — raw burst fingerprint."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 250_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.3)
        self.ook = OOKDecoder(fs / self.dec1, threshold_db=7,
                              min_gap_us=2500, min_pulse_us=80)

    def decode(self, iq):
        chan = self.decim.process(iq)
        mag = np.abs(chan).astype(np.float32)
        out = []
        for b in self.ook.process(mag):
            bits = b.raw_bits[:48]
            hid = hex(int(bits, 2))[2:] if bits else "?"
            out.append(f"sensor {hid} ({len(b.pulses)}p, {b.duration_us:.0f}us)")
        return out


register(AppInfo(id="weather_rx", name="Weather", category="Receive",
                 factory=lambda h, a, c: WeatherRx(h, a, c),
                 description="433/868/915 OOK weather sensor capture"))
