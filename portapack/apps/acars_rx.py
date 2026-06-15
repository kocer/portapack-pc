"""ACARS receiver — 131 MHz aircraft text messages (AM, MSK 2400)."""
from __future__ import annotations
import numpy as np
from ..sdr import dsp
from ..sdr.decoders import ACARSDecoder
from . import AppInfo, register
from ._rxlog import RxLogApp


class ACARSRx(RxLogApp):
    title = "ACARS"
    default_freq = 131_550_000
    sample_rate = 2_400_000
    band_options = [("131.550 (common)", 131_550_000),
                    ("131.725 (EU)", 131_725_000),
                    ("130.025 (US)", 130_025_000),
                    ("136.900 (US)", 136_900_000)]
    extra_note = "AM MSK 2400 — aircraft/ground text (ACARS)."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 48_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.02)
        self.am = dsp.AMDemod()
        self.acars = ACARSDecoder(fs / self.dec1)

    def decode(self, iq):
        chan = self.decim.process(iq)
        env = self.am.process(chan)
        return self.acars.process(env)


register(AppInfo(id="acars_rx", name="ACARS", category="Receive",
                 factory=lambda h, a, c: ACARSRx(h, a, c),
                 description="Aircraft ACARS text message decoder"))
