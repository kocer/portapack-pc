"""BTLE receiver — Bluetooth LE advertising packets (2.4 GHz GFSK 1 Mbps)."""
from __future__ import annotations
from ..sdr import dsp
from ..sdr.decoders import FSKFramer
from . import AppInfo, register
from ._rxlog import RxLogApp


def _lsb_bits(value: int, nbits: int) -> str:
    return "".join(str((value >> i) & 1) for i in range(nbits))


class BTLERx(RxLogApp):
    title = "BTLE"
    default_freq = 2_402_000_000          # advertising channel 37
    sample_rate = 4_000_000
    band_options = [("Ch37 2402", 2_402_000_000),
                    ("Ch38 2426", 2_426_000_000),
                    ("Ch39 2480", 2_480_000_000)]
    extra_note = "GFSK 1 Mbps — detects advertising access address 0x8E89BED6."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 2_000_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.5)
        self.fm = dsp.FMDemod(250_000, fs / self.dec1, deemph_us=0)
        # advertising access address, LSB-first, after 0xAA preamble
        aa = _lsb_bits(0x8E89BED6, 32)
        self.framer = FSKFramer(fs / self.dec1, 1_000_000, sync=aa,
                                payload_bits=320)

    def decode(self, iq):
        chan = self.decim.process(iq)
        demod = self.fm.process(chan)
        return [f"BLE adv pkt (whitened) {h[:40]}…"
                for h in self.framer.process(demod)]


register(AppInfo(id="btle_rx", name="BTLE", category="Receive",
                 factory=lambda h, a, c: BTLERx(h, a, c),
                 description="Bluetooth LE advertising packet sniffer"))
