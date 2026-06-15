"""Radiosonde receiver — weather balloons (RS41/M10, ~400 MHz GFSK 4800)."""
from __future__ import annotations
from ..sdr import dsp
from ..sdr.decoders import FSKFramer
from . import AppInfo, register
from ._rxlog import RxLogApp


class RadiosondeRx(RxLogApp):
    title = "Radiosonde"
    default_freq = 405_000_000
    sample_rate = 2_400_000
    band_options = [("403.0", 403_000_000), ("404.0", 404_000_000),
                    ("405.0", 405_000_000), ("406.0", 406_000_000)]
    extra_note = "GFSK 4800 — RS41/M10 sonde frame detector (best-effort)."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 48_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.06)
        self.fm = dsp.FMDemod(2_400, fs / self.dec1, deemph_us=0)
        # RS41 frame sync header (0x10B6CA11...) approximated as bit run
        self.framer = FSKFramer(fs / self.dec1, 4800,
                                sync="00010000101101101100101000010001",
                                payload_bits=320)

    def decode(self, iq):
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        return [f"sonde frame {h[:48]}…" for h in self.framer.process(demod)]


register(AppInfo(id="radiosonde_rx", name="Radiosonde", category="Receive",
                 factory=lambda h, a, c: RadiosondeRx(h, a, c),
                 description="Weather-balloon radiosonde frame detector"))
