"""ERT receiver — utility (electric/gas/water) smart meters (~912 MHz OOK)."""
from __future__ import annotations
import numpy as np
from ..sdr import dsp
from ..sdr.decoders import ERTDecoder
from . import AppInfo, register
from ._rxlog import RxLogApp


class ERTRx(RxLogApp):
    title = "ERT Meters"
    default_freq = 912_600_000
    sample_rate = 2_400_000
    band_options = [("912.6", 912_600_000), ("915.0", 915_000_000)]
    extra_note = "OOK Manchester 32.768k — SCM consumption messages."

    def make_chain(self):
        fs = self.sample_rate
        self.dec1 = dsp.best_decimation(fs, 200_000)
        self.decim = dsp.FirDecimator(self.dec1, cutoff_ratio=0.3)
        self.ert = ERTDecoder(fs / self.dec1, chip_rate=32768)

    def decode(self, iq):
        chan = self.decim.process(iq)
        mag = np.abs(chan).astype(np.float32)
        return self.ert.process(mag)


register(AppInfo(id="ert_rx", name="ERT Meters", category="Receive",
                 factory=lambda h, a, c: ERTRx(h, a, c),
                 description="Utility smart-meter (ERT SCM) reader"))
