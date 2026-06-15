"""NRF receiver — nRF24L01 / Shockburst sniffer (2.4 GHz GFSK 1/2 Mbps)."""
from __future__ import annotations
from ..sdr import dsp
from ..sdr.decoders import FSKFramer
from . import AppInfo, register
from ._rxlog import RxLogApp


class NRFRx(RxLogApp):
    title = "NRF24"
    default_freq = 2_400_000_000
    sample_rate = 4_000_000
    band_options = [("2400", 2_400_000_000), ("2440", 2_440_000_000),
                    ("2480", 2_480_000_000)]
    extra_note = "GFSK 1/2 Mbps — Shockburst preamble/address detector."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 2_000_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.5)
        self.fm = dsp.FMDemod(160_000, fs / self.dec1, deemph_us=0)
        # Shockburst preamble 0xAA/0x55 + common address byte run
        self.framer = FSKFramer(fs / self.dec1, 1_000_000,
                                sync="10101010" * 2, payload_bits=256)

    def decode(self, iq):
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        return [f"NRF burst {h[:40]}…" for h in self.framer.process(demod)]


register(AppInfo(id="nrf_rx", name="NRF24", category="Receive",
                 factory=lambda h, a, c: NRFRx(h, a, c),
                 description="nRF24L01 Shockburst sniffer"))
