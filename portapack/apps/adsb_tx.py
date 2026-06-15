"""ADS-B transmitter — build & send a Mode-S DF17 frame (PPM 2 Mbps OOK)."""
from __future__ import annotations
import numpy as np
from PySide6.QtWidgets import QLineEdit
from ..ui import widgets
from . import AppInfo, register
from ._txbase import TxWaveApp
from ..sdr.decoders import _modes_crc


def _modes_parity(data_bits):
    """Parity = CRC of the 88 data bits with 24 trailing zeros, matching the
    receiver's :func:`_modes_crc` so the transmitted frame validates (CRC==0)."""
    import numpy as np
    full = np.array(list(data_bits) + [0] * 24, dtype=np.int8)
    return _modes_crc(full)


class ADSBTx(TxWaveApp):
    title = "ADS-B TX"
    default_freq = 1_090_000_000
    tx_sample_rate = 4_000_000
    button_text = "SQUITTER"
    loop = True

    def build_extra(self, layout):
        self.icao = QLineEdit("AB1234")
        self.callsign = QLineEdit("PPC001")
        layout.addWidget(widgets.Field("ICAO (hex)", self.icao))
        layout.addWidget(widgets.Field("Callsign", self.callsign))

    def build_waveform(self):
        icao = int(self.icao.text(), 16) & 0xFFFFFF
        # Build the 88 data bits directly:
        #   DF(5)=17, CA(3)=5, ICAO(24), ME(56) = 88 bits, then CRC(24) = 112.
        def push(bits, value, nbits):
            for i in range(nbits - 1, -1, -1):
                bits.append((value >> i) & 1)

        bits = []
        push(bits, 17, 5)               # DF17
        push(bits, 5, 3)                # CA = 5
        push(bits, icao, 24)            # ICAO address
        # ME: aircraft identification — TC(5)=4, category(3)=0, 8×6-bit chars
        push(bits, 4, 5)                # type code 4
        push(bits, 0, 3)               # category
        cs = (self.callsign.text().upper() + "        ")[:8]
        charset = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"
        for ch in cs:
            push(bits, charset.index(ch) if ch in charset else 32, 6)
        assert len(bits) == 88, len(bits)
        crc = _modes_parity(bits)       # parity over 88 data + 24 zero bits
        push(bits, crc, 24)
        # PPM: bit 1 -> high then low; bit 0 -> low then high (1us/bit @2Mbps)
        fs = self.tx_sample_rate
        sph = int(fs / 2_000_000)  # samples per half-bit
        preamble = [1, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0]
        env = []
        for h in preamble:
            env += [0.9 if h else 0.0] * sph
        for b in bits:
            if b:
                env += [0.9] * sph + [0.0] * sph
            else:
                env += [0.0] * sph + [0.9] * sph
        env += [0.0] * (sph * 8)  # inter-frame gap
        return np.array(env, dtype=np.complex64)


register(AppInfo(id="adsb_tx", name="ADS-B TX", category="Transmit", needs_tx=True,
                 factory=lambda h, a, c: ADSBTx(h, a, c),
                 description="Transmit a Mode-S/ADS-B squitter (testing)"))
