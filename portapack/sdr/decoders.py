"""Lightweight protocol decoders used by the receiver apps.

These operate on already-demodulated streams (magnitude for OOK/ADS-B, FM
discriminator output for FSK/POCSAG) and emit decoded events.  They are
deliberately self-contained and dependency-free beyond numpy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Optional

import numpy as np


# ---------------------------------------------------------------------------
# OOK / ASK (sub-GHz remotes, TPMS, weather stations)
# ---------------------------------------------------------------------------
@dataclass
class OOKBurst:
    pulses: list  # alternating (level, duration_us) starting with a high pulse
    duration_us: float
    raw_bits: str


class OOKDecoder:
    """Threshold an AM/magnitude stream into pulse/gap timings.

    Detects energy bursts, measures pulse widths and renders them to a bit
    string using a short/long heuristic — enough to fingerprint most remotes.
    """

    def __init__(self, sample_rate: float, threshold_db: float = 6.0,
                 min_gap_us: float = 3000, min_pulse_us: float = 80):
        self.fs = sample_rate
        self.threshold_db = threshold_db
        self.min_gap = min_gap_us * 1e-6 * sample_rate
        self.min_pulse = min_pulse_us * 1e-6 * sample_rate
        self._noise = 1e-3
        self._in_burst = False
        self._edges: list[int] = []
        self._level = 0
        self._count = 0
        self._sample_idx = 0
        self._gap_run = 0

    def process(self, mag: np.ndarray) -> list[OOKBurst]:
        bursts: list[OOKBurst] = []
        # adaptive noise floor
        self._noise = 0.999 * self._noise + 0.001 * float(np.median(mag) + 1e-9)
        thr = self._noise * (10 ** (self.threshold_db / 20))
        high = (mag > thr).astype(np.int8)

        # run-length encode transitions
        idx = 0
        n = len(high)
        while idx < n:
            v = high[idx]
            j = idx + 1
            while j < n and high[j] == v:
                j += 1
            run = j - idx
            if v == 1:
                self._edges.append(run)
                self._in_burst = True
                self._gap_run = 0
            else:
                if self._in_burst:
                    if run > self.min_gap:
                        # burst finished
                        b = self._finish_burst()
                        if b:
                            bursts.append(b)
                    else:
                        self._edges.append(-run)  # encode gap as negative
            idx = j
        return bursts

    def _finish_burst(self) -> Optional[OOKBurst]:
        edges = [e for e in self._edges if abs(e) >= self.min_pulse * 0.3]
        self._edges = []
        self._in_burst = False
        if len(edges) < 4:
            return None
        durs = [abs(e) / self.fs * 1e6 for e in edges]
        # classify by median pulse length
        med = np.median([d for d in durs])
        bits = "".join("1" if d > med else "0" for d in durs)
        pulses = [("H" if e > 0 else "L", abs(e) / self.fs * 1e6) for e in edges]
        return OOKBurst(pulses=pulses, duration_us=sum(durs), raw_bits=bits)


# ---------------------------------------------------------------------------
# ADS-B (1090 MHz Mode-S, PPM @ 2 Mbit/s)
# ---------------------------------------------------------------------------
_ADSB_PREAMBLE = np.array([1, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0],
                          dtype=np.float32)


def _modes_crc(bits: np.ndarray) -> int:
    """Compute the 24-bit Mode-S CRC over the message bits."""
    poly = 0xFFF409
    data = 0
    for b in bits:
        data = (data << 1) | int(b)
    msglen = len(bits)
    # process all but last 24 parity bits
    for i in range(msglen - 24):
        if (data >> (msglen - 1 - i)) & 1:
            data ^= poly << (msglen - 24 - i)
    return data & 0xFFFFFF


@dataclass
class ADSBFrame:
    df: int
    icao: str
    hex: str
    crc_ok: bool


class ADSBDecoder:
    """Detects Mode-S frames in a 2 Msps magnitude stream via PPM correlation."""

    def __init__(self, sample_rate: float = 2_000_000):
        self.fs = sample_rate
        self.sps = sample_rate / 2_000_000  # samples per ADS-B bit-half
        self._tail = np.zeros(0, dtype=np.float32)

    def process(self, mag: np.ndarray) -> list[ADSBFrame]:
        frames: list[ADSBFrame] = []
        sig = np.concatenate([self._tail, mag.astype(np.float32)])
        self._tail = sig[-240:].copy()
        sps = max(1, int(round(self.sps)))
        # decimate-ish to 2 Msps grid by simple striding if oversampled
        step = sps
        n = len(sig)
        i = 0
        limit = n - int(240 * step)
        while i < limit:
            window = sig[i:i + 16 * step:step][:16]
            if len(window) < 16:
                break
            if self._preamble_match(window):
                frame = self._decode_frame(sig, i + 16 * step, step)
                if frame:
                    frames.append(frame)
                    i += int(240 * step)
                    continue
            i += step
        return frames

    def _preamble_match(self, w: np.ndarray) -> bool:
        if w.max() <= 0:
            return False
        w = w / (w.max() + 1e-9)
        # high samples at preamble positions, low elsewhere
        highs = w[[0, 2, 7, 9]].mean()
        lows = w[[1, 3, 4, 5, 6, 8, 10, 11, 12, 13, 14, 15]].mean()
        return highs > 0.5 and lows < 0.35 and highs - lows > 0.3

    def _decode_frame(self, sig, start, step) -> Optional[ADSBFrame]:
        nbits = 112
        if start + int(nbits * 2 * step) > len(sig):
            nbits = 56
            if start + int(nbits * 2 * step) > len(sig):
                return None
        bits = np.zeros(nbits, dtype=np.int8)
        for k in range(nbits):
            a = sig[start + int(k * 2 * step)]
            b = sig[start + int((k * 2 + 1) * step)]
            bits[k] = 1 if a > b else 0
        crc = _modes_crc(bits)
        df = (bits[0] << 4) | (bits[1] << 3) | (bits[2] << 2) | (bits[3] << 1) | bits[4]
        hexstr = "".join(f"{int(''.join(map(str, bits[i:i+4])), 2):x}"
                         for i in range(0, nbits, 4))
        icao = hexstr[2:8] if nbits == 112 else "------"
        return ADSBFrame(df=int(df), icao=icao, hex=hexstr, crc_ok=(crc == 0))


# ---------------------------------------------------------------------------
# POCSAG (pager, FSK 512/1200/2400 bps)
# ---------------------------------------------------------------------------
_POCSAG_SYNC = 0x7CD215D8
_POCSAG_IDLE = 0x7A89C197


class POCSAGDecoder:
    """Decodes POCSAG batches from an FM-discriminator stream."""

    def __init__(self, sample_rate: float, baud: int = 1200):
        self.fs = sample_rate
        self.baud = baud
        self._bitbuf = ""
        self.address_filter = None     # set to an int RIC to show only that pager

    def set_baud(self, baud: int):
        self.baud = baud

    def process(self, demod: np.ndarray) -> list[str]:
        # slice to bits at the configured baud
        sps = self.fs / self.baud
        if sps < 2:
            return []
        # zero-crossing slicer
        sym = (demod > 0).astype(np.int8)
        idx = np.arange(0, len(sym), sps)
        bits = sym[idx.astype(int)]
        self._bitbuf += "".join("1" if b else "0" for b in bits)
        self._bitbuf = self._bitbuf[-20000:]
        return self._extract_messages()

    def _extract_messages(self) -> list[str]:
        out: list[str] = []
        s = self._bitbuf
        sync = f"{_POCSAG_SYNC:032b}"
        pos = s.find(sync)
        while pos != -1 and pos + 32 + 16 * 32 <= len(s):
            batch = s[pos + 32: pos + 32 + 16 * 32]
            out += self._decode_batch(batch)
            pos = s.find(sync, pos + 32)
        if pos > 0:
            self._bitbuf = s[pos:]
        return out

    def _decode_batch(self, batch: str):
        """Decode one 16-codeword batch into (RIC, function, alpha, numeric)."""
        results = []
        cur = None      # current (ric, func, msg_bits)

        def flush():
            if cur is None:
                return
            ric, func, mbits = cur
            if self.address_filter is not None and ric != self.address_filter:
                return
            alpha = self._alpha(mbits)
            numeric = self._numeric(mbits)
            tag = f"RIC {ric}  F{func}"
            if numeric:
                results.append(f"{tag}  NUM: {numeric}")
            if alpha.strip():
                results.append(f"{tag}  TXT: {alpha}")
            if not numeric and not alpha.strip():
                results.append(tag)

        for ci in range(16):
            word = batch[ci * 32:ci * 32 + 32]
            if len(word) < 32:
                break
            if int(word, 2) == _POCSAG_IDLE:
                continue
            if word[0] == "0":      # address codeword
                flush()
                addr18 = int(word[1:19], 2)
                func = int(word[19:21], 2)
                frame = ci // 2     # frame number gives the low 3 RIC bits
                ric = (addr18 << 3) | frame
                cur = (ric, func, "")
            elif cur is not None:   # message codeword
                ric, func, mbits = cur
                cur = (ric, func, mbits + word[1:21])
        flush()
        return results

    @staticmethod
    def _alpha(bits: str) -> str:
        chars = []
        for i in range(0, len(bits) - 6, 7):
            c = int(bits[i:i + 7][::-1], 2)   # 7-bit, LSB first
            if 32 <= c < 127:
                chars.append(chr(c))
        return "".join(chars)

    @staticmethod
    def _numeric(bits: str) -> str:
        table = "0123456789*U -)("
        out = []
        for i in range(0, len(bits) - 3, 4):
            v = int(bits[i:i + 4][::-1], 2)   # 4-bit BCD, LSB first
            out.append(table[v])
        return "".join(out)


# ---------------------------------------------------------------------------
# AFSK 1200 (Bell 202) + AX.25/HDLC  — used by APRS
# ---------------------------------------------------------------------------
class AFSK1200Decoder:
    """Demodulate Bell-202 AFSK from an FM-discriminator stream into AX.25 frames.

    Mark = 1200 Hz, Space = 2200 Hz.  Uses a correlation discriminator, NRZI
    decode and HDLC bit-destuffing with FCS (CRC-16/X.25) checking.
    """

    def __init__(self, sample_rate: float):
        self.fs = sample_rate
        self.baud = 1200
        self._bitbuf = ""
        self._prev = 0
        # correlator window = one bit period; quadrature tone detection
        n = int(sample_rate / 1200)
        self._n = max(2, n)
        self._t0 = 0.0                      # phase continuity across blocks
        self._samp_acc = (sample_rate / 1200) / 2  # start mid-symbol

    def process(self, demod: np.ndarray) -> list[str]:
        fs = self.fs
        n = len(demod)
        t = (np.arange(n) + self._t0) / fs
        self._t0 += n
        win = np.ones(self._n) / self._n

        def tone_mag(f):
            i = np.convolve(demod * np.cos(2 * np.pi * f * t), win, "same")
            q = np.convolve(demod * np.sin(2 * np.pi * f * t), win, "same")
            return i * i + q * q

        soft = tone_mag(1200) - tone_mag(2200)   # mark vs space energy
        sym = (soft > 0).astype(np.int8)
        # sample at baud centres, carrying fractional timing across blocks
        sps = fs / self.baud
        idx = []
        pos = self._samp_acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._samp_acc = pos - n
        bits = sym[idx] if idx else np.array([], dtype=np.int8)
        # NRZI: no transition = 1, transition = 0
        out = []
        prev = self._prev
        for b in bits:
            out.append(1 if b == prev else 0)
            prev = b
        self._prev = prev
        self._bitbuf += "".join(map(str, out))
        self._bitbuf = self._bitbuf[-40000:]
        return self._extract_frames()

    def _extract_frames(self) -> list[str]:
        frames = []
        flag = "01111110"
        s = self._bitbuf
        positions = []
        i = s.find(flag)
        while i != -1:
            positions.append(i)
            i = s.find(flag, i + 1)
        for a, b in zip(positions, positions[1:]):
            chunk = s[a + 8:b]
            if len(chunk) < 80:
                continue
            unstuffed = self._destuff(chunk)
            data = self._bits_to_bytes(unstuffed)
            if len(data) > 4 and self._fcs_ok(data):
                frames.append(self._format_ax25(data))
        if positions:
            self._bitbuf = s[positions[-1]:]
        return frames

    @staticmethod
    def _destuff(bits: str) -> str:
        out = []
        ones = 0
        for c in bits:
            if c == "1":
                ones += 1
                out.append(c)
            else:
                if ones == 5:
                    ones = 0
                    continue  # drop stuffed 0
                ones = 0
                out.append(c)
        return "".join(out)

    @staticmethod
    def _bits_to_bytes(bits: str) -> bytes:
        out = bytearray()
        for i in range(0, len(bits) - 7, 8):
            byte = bits[i:i + 8][::-1]  # LSB first
            out.append(int(byte, 2))
        return bytes(out)

    @staticmethod
    def _fcs_ok(data: bytes) -> bool:
        if len(data) < 3:
            return False
        crc = 0xFFFF
        for b in data[:-2]:
            crc ^= b
            for _ in range(8):
                crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
        crc ^= 0xFFFF
        rx = data[-2] | (data[-1] << 8)
        return crc == rx

    @staticmethod
    def _format_ax25(data: bytes) -> str:
        try:
            def addr(o):
                call = "".join(chr(b >> 1) for b in data[o:o + 6]).strip()
                ssid = (data[o + 6] >> 1) & 0x0F
                return f"{call}-{ssid}" if ssid else call
            dst = addr(0)
            src = addr(7)
            info = data[16:-2].decode("ascii", "replace")
            return f"{src} > {dst}: {info}"
        except Exception:
            return data.hex()


# ---------------------------------------------------------------------------
# AIS (161.975 / 162.025 MHz, GMSK 9600, HDLC) — best-effort bit framing
# ---------------------------------------------------------------------------
class AISDecoder:
    """NRZI/HDLC framer for AIS GMSK at 9600 baud from FM-discriminator input."""

    def __init__(self, sample_rate: float):
        self.fs = sample_rate
        self.baud = 9600
        self._bitbuf = ""
        self._prev = 0

    def process(self, demod: np.ndarray) -> list[str]:
        sps = self.fs / self.baud
        if sps < 2:
            return []
        sym = (demod > 0).astype(np.int8)
        idx = (np.arange(0, len(sym), sps)).astype(int)
        bits = sym[idx]
        out = []
        prev = self._prev
        for b in bits:
            out.append(1 if b == prev else 0)  # NRZI
            prev = b
        self._prev = prev
        self._bitbuf += "".join(map(str, out))
        self._bitbuf = self._bitbuf[-60000:]
        return self._frames()

    def _frames(self):
        flag = "01111110"
        s = self._bitbuf
        res = []
        pos = [i for i in range(len(s)) if s.startswith(flag, i)]
        for a, b in zip(pos, pos[1:]):
            chunk = s[a + 8:b]
            if 20 < len(chunk) < 500:
                payload = AFSK1200Decoder._destuff(chunk)
                rec = parse_ais_message(payload)
                if rec and rec.get("mmsi"):
                    rec["nmea"] = self._sixbit(payload)
                    res.append(rec)
        if pos:
            self._bitbuf = s[pos[-1]:]
        return res

    @staticmethod
    def _sixbit(bits: str) -> str:
        out = []
        for i in range(0, len(bits) - 5, 6):
            v = int(bits[i:i + 6], 2)
            v += 48
            if v > 87:
                v += 8
            out.append(chr(v))
        return "".join(out)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def manchester_decode(bits: str) -> str:
    """Decode Manchester (IEEE: 01->0, 10->1); skip malformed pairs."""
    out = []
    for i in range(0, len(bits) - 1, 2):
        pair = bits[i:i + 2]
        if pair == "01":
            out.append("0")
        elif pair == "10":
            out.append("1")
        else:
            break
    return "".join(out)


class FSKFramer:
    """Generic NRZ bit slicer + sync-word search over an FM-discriminator stream.

    Used by Radiosonde / BTLE / NRF detectors: slices at ``baud`` and reports
    payloads that follow a given ``sync`` bit pattern (best-effort detection).
    """

    def __init__(self, sample_rate: float, baud: float, sync: str,
                 payload_bits: int = 256):
        self.fs = sample_rate
        self.baud = baud
        self.sync = sync
        self.payload_bits = payload_bits
        self._buf = ""
        self._acc = (sample_rate / baud) / 2

    def process(self, demod: np.ndarray) -> list[str]:
        sps = self.fs / self.baud
        if sps < 1.5:
            return []
        sym = (demod > 0).astype(np.int8)
        n = len(sym)
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        if idx:
            self._buf += "".join(str(int(sym[i])) for i in idx)
        self._buf = self._buf[-20000:]
        out = []
        p = self._buf.find(self.sync)
        while p != -1 and p + len(self.sync) + self.payload_bits <= len(self._buf):
            payload = self._buf[p + len(self.sync):p + len(self.sync) + self.payload_bits]
            hexstr = "".join(f"{int(payload[i:i+4],2):x}"
                             for i in range(0, len(payload) - 3, 4))
            out.append(hexstr)
            p = self._buf.find(self.sync, p + len(self.sync))
        if p > 0:
            self._buf = self._buf[p:]
        return out


# ---------------------------------------------------------------------------
# ERT (utility meters, ~912 MHz, OOK Manchester) — SCM message
# ---------------------------------------------------------------------------
class ERTDecoder:
    """Decode ERT SCM consumption messages from an OOK magnitude stream."""

    SYNC = "111100010101001100000"  # 0x1F2A60-derived training+sync (approx)

    def __init__(self, sample_rate: float, chip_rate: float = 32768):
        self.fs = sample_rate
        self.chip = chip_rate
        self._buf = ""
        self._acc = (sample_rate / chip_rate) / 2
        self._noise = 1e-3

    def process(self, mag: np.ndarray) -> list[str]:
        self._noise = 0.999 * self._noise + 0.001 * float(np.median(mag) + 1e-9)
        thr = self._noise * 2.5
        sym = (mag > thr).astype(np.int8)
        sps = self.fs / self.chip
        n = len(sym)
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        if idx:
            self._buf += "".join(str(int(sym[i])) for i in idx)
        self._buf = self._buf[-16000:]
        out = []
        dec = manchester_decode(self._buf)
        p = dec.find("11110001010110")  # SCM sync pattern (after manchester)
        while p != -1 and p + 96 <= len(dec):
            frame = dec[p:p + 96]
            try:
                ert_id = int(frame[5 + 2 + 1:5 + 2 + 1 + 26], 2)
                consumption = int(frame[5 + 2 + 1 + 26 + 16:
                                        5 + 2 + 1 + 26 + 16 + 24], 2)
                out.append(f"meter ID={ert_id} consumption={consumption}")
            except Exception:
                pass
            p = dec.find("11110001010110", p + 1)
        return out


# ---------------------------------------------------------------------------
# ACARS (131 MHz AM, MSK 2400) — character framing, best-effort
# ---------------------------------------------------------------------------
class ACARSDecoder:
    """Decode ACARS text from an AM-envelope stream (MSK 2400, 7-bit ASCII)."""

    def __init__(self, sample_rate: float):
        self.fs = sample_rate
        self.baud = 2400
        self._buf = ""
        self._acc = (sample_rate / 2400) / 2
        self._t0 = 0.0

    def process(self, env: np.ndarray) -> list[str]:
        n = len(env)
        t = (np.arange(n) + self._t0) / self.fs
        self._t0 += n
        nwin = max(2, int(self.fs / self.baud))
        win = np.ones(nwin) / nwin

        def mag(f):
            i = np.convolve(env * np.cos(2 * np.pi * f * t), win, "same")
            q = np.convolve(env * np.sin(2 * np.pi * f * t), win, "same")
            return i * i + q * q

        soft = mag(2400) - mag(1200)
        sym = (soft > 0).astype(np.int8)
        sps = self.fs / self.baud
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        bits = [int(sym[i]) for i in idx]
        # differential decode (MSK): bit = XOR of consecutive samples
        prev = 0
        chars_bits = []
        for b in bits:
            chars_bits.append(b ^ prev)
            prev = b
        self._buf += "".join(map(str, chars_bits))
        self._buf = self._buf[-16000:]
        return self._extract()

    def _extract(self):
        out = []
        s = self._buf
        # ACARS pre-key/sync then characters; search SYN SYN SOH then text
        # 7-bit LSB-first chars; find printable runs delimited by SOH(0x01)/ETX(0x03)
        text = []
        for i in range(0, len(s) - 7, 7):
            c = int(s[i:i + 7][::-1], 2)
            if c in (0x01, 0x02):  # SOH/STX -> start
                text = []
            elif c in (0x03, 0x7F):  # ETX/DEL -> end
                if len(text) > 4:
                    out.append("".join(text))
                text = []
            elif 32 <= c < 127:
                text.append(chr(c))
        if len(text) > 8:
            out.append("".join(text))
            self._buf = ""
        return out


# ---------------------------------------------------------------------------
# TPMS (tyre pressure, 315/433 MHz, mostly FSK + Manchester/diff-Manchester)
# ---------------------------------------------------------------------------
def _crc8(data: bytes, poly=0x07, init=0x00) -> int:
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def diff_manchester_decode(bits: str) -> str:
    """Differential Manchester: bit value = whether the level changed at the
    start of the bit period (transition mid-bit is the clock)."""
    out = []
    for i in range(0, len(bits) - 1, 2):
        a, b = bits[i], bits[i + 1]
        out.append("1" if a == b else "0")  # simplified diff-manchester
    return "".join(out)


class TPMSDecoder:
    """Decode FSK TPMS frames from an FM-discriminator stream.

    Slices at the configured baud, Manchester-decodes, finds the preamble/sync,
    extracts the sensor ID and data bytes and checks CRC-8.  Pressure/temperature
    scaling is manufacturer-specific, so a common-format estimate is given and
    flagged as approximate.
    """

    # alternating preamble then a sync nibble — common across many sensors
    SYNC = "0101010101"

    def __init__(self, sample_rate: float, baud: float = 19200,
                 coding: str = "manchester"):
        self.fs = sample_rate
        self.baud = baud
        self.coding = coding
        self._buf = ""
        self._acc = (sample_rate / baud) / 2

    def process(self, demod: np.ndarray) -> list[dict]:
        sps = self.fs / self.baud
        if sps < 2:
            return []
        sym = (demod > 0).astype(np.int8)
        n = len(sym)
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        if idx:
            self._buf += "".join(str(int(sym[i])) for i in idx)
        self._buf = self._buf[-12000:]
        return self._extract()

    def _extract(self):
        out = []
        s = self._buf
        p = s.find(self.SYNC)
        while p != -1:
            # Manchester-decode the payload that follows the preamble/sync.
            payload = s[p + len(self.SYNC): p + len(self.SYNC) + 200]
            if len(payload) < 130:
                break
            decoded = (manchester_decode(payload) if self.coding == "manchester"
                       else diff_manchester_decode(payload))
            rec = self._parse(decoded)
            if rec:
                out.append(rec)
            p = s.find(self.SYNC, p + len(self.SYNC) + 120)
        if p > 0:
            self._buf = s[p:]
        return out

    def _parse(self, bits: str):
        # need at least 64 bits (8 bytes: ID4 + press + temp + flags + crc)
        if len(bits) < 64:
            return None
        data = bytearray()
        for i in range(0, 64, 8):
            data.append(int(bits[i:i + 8], 2))
        crc_ok = _crc8(bytes(data[:7])) == data[7]
        sid = (data[0] << 24) | (data[1] << 16) | (data[2] << 8) | data[3]
        # common scaling: pressure ~ kPa = raw * 2.5 ; temp = raw - 40 °C
        pressure_kpa = data[4] * 2.5
        temp_c = data[5] - 40
        return dict(id=f"{sid:08X}", pressure_kpa=round(pressure_kpa, 1),
                    temp_c=temp_c, flags=data[6], crc_ok=crc_ok,
                    raw=bytes(data).hex())


# ---------------------------------------------------------------------------
# AIS message field parser (ITU-R M.1371 position reports, types 1/2/3)
# ---------------------------------------------------------------------------
def parse_ais_message(bits: str):
    """Parse an AIS payload bit string (MSB-first fields) into a dict.

    Handles the common position report (types 1/2/3) and base-station (4) and
    static (5) name; returns None for too-short / unknown payloads.
    """
    if len(bits) < 38:
        return None

    def u(a, n):
        return int(bits[a:a + n], 2) if a + n <= len(bits) else 0

    def s(a, n):
        v = u(a, n)
        if v & (1 << (n - 1)):
            v -= (1 << n)
        return v

    mtype = u(0, 6)
    mmsi = u(8, 30)
    rec = {"type": mtype, "mmsi": mmsi}
    if mtype in (1, 2, 3) and len(bits) >= 138:
        rec["status"] = u(38, 4)
        sog = u(50, 10)
        rec["sog"] = sog / 10.0 if sog != 1023 else None        # knots
        lon = s(61, 28) / 600000.0
        lat = s(89, 27) / 600000.0
        rec["lon"] = round(lon, 6) if abs(lon) <= 180 else None
        rec["lat"] = round(lat, 6) if abs(lat) <= 90 else None
        cog = u(116, 12)
        rec["cog"] = cog / 10.0 if cog != 3600 else None        # degrees
        hdg = u(128, 9)
        rec["heading"] = hdg if hdg != 511 else None
    elif mtype == 5 and len(bits) >= 424:
        # static & voyage: ship name at bits 112..232 (20 six-bit chars)
        name = ""
        for i in range(112, 112 + 120, 6):
            c = u(i, 6)
            name += chr(c + 64) if 1 <= c <= 26 else (chr(c) if 32 <= c < 64 else "")
        rec["name"] = name.strip("@ ").strip()
    return rec


# ---------------------------------------------------------------------------
# ADS-B position (CPR), altitude and callsign decoding
# ---------------------------------------------------------------------------
_ADSB_CHARSET = "#ABCDEFGHIJKLMNOPQRSTUVWXYZ##### ###############0123456789######"


def _hex_to_bits(hexstr: str) -> str:
    return "".join(f"{int(c,16):04b}" for c in hexstr)


def adsb_typecode(hexstr: str) -> int:
    bits = _hex_to_bits(hexstr)
    return int(bits[32:37], 2) if len(bits) >= 37 else 0


def adsb_callsign(hexstr: str):
    bits = _hex_to_bits(hexstr)
    if len(bits) < 88:
        return None
    me = bits[32:88]
    tc = int(me[0:5], 2)
    if tc < 1 or tc > 4:
        return None
    cs = ""
    for i in range(8):
        c = int(me[8 + i * 6:8 + i * 6 + 6], 2)
        cs += _ADSB_CHARSET[c] if c < len(_ADSB_CHARSET) else "#"
    return cs.replace("#", "").strip()


def adsb_altitude(hexstr: str):
    bits = _hex_to_bits(hexstr)
    if len(bits) < 88:
        return None
    me = bits[32:88]
    tc = int(me[0:5], 2)
    if not (9 <= tc <= 18 or 20 <= tc <= 22):
        return None
    alt_bits = me[8:20]          # 12-bit altitude
    q = alt_bits[7]
    if q == "1":
        n = int(alt_bits[:7] + alt_bits[8:], 2)
        return n * 25 - 1000      # feet
    return None


def _cpr_nl(lat):
    import math
    if abs(lat) >= 87.0:
        return 1
    return int(2 * math.pi / math.acos(1 - (1 - math.cos(math.pi / 30)) /
                                       math.cos(math.pi / 180 * lat) ** 2))


def adsb_cpr_latlon(hexstr: str):
    """Return (cpr_lat, cpr_lon, odd_flag) from an airborne position message."""
    bits = _hex_to_bits(hexstr)
    if len(bits) < 88:
        return None
    me = bits[32:88]
    tc = int(me[0:5], 2)
    if not (9 <= tc <= 18):
        return None
    odd = int(me[21])
    lat_cpr = int(me[22:39], 2) / 131072.0
    lon_cpr = int(me[39:56], 2) / 131072.0
    return lat_cpr, lon_cpr, odd


def adsb_global_position(even, odd):
    """Decode global lat/lon from an even+odd CPR pair (each (latcpr,loncpr))."""
    import math
    lat_e, lon_e = even
    lat_o, lon_o = odd
    j = int(math.floor(59 * lat_e - 60 * lat_o + 0.5))
    dlat_e = 360.0 / 60
    dlat_o = 360.0 / 59
    lat_even = dlat_e * ((j % 60) + lat_e)
    lat_odd = dlat_o * ((j % 59) + lat_o)
    if lat_even >= 270:
        lat_even -= 360
    if lat_odd >= 270:
        lat_odd -= 360
    if _cpr_nl(lat_even) != _cpr_nl(lat_odd):
        return None
    lat = lat_even   # use even (most recent assumed even)
    nl = _cpr_nl(lat)
    ni = max(nl, 1)
    m = int(math.floor(lon_e * (nl - 1) - lon_o * nl + 0.5))
    lon = (360.0 / ni) * ((m % ni) + lon_e)
    if lon >= 180:
        lon -= 360
    return round(lat, 5), round(lon, 5)


# ---------------------------------------------------------------------------
# RTTY (Baudot, 45.45 baud, 170 Hz shift) from an FM/FSK discriminator stream
# ---------------------------------------------------------------------------
_BAUDOT_LTRS = {
    0b00000: "", 0b00100: " ", 0b10111: "Q", 0b10011: "W", 0b00001: "E",
    0b01010: "R", 0b10000: "T", 0b10101: "Y", 0b00111: "U", 0b00110: "I",
    0b11000: "O", 0b10110: "P", 0b00011: "A", 0b00101: "S", 0b01001: "D",
    0b01101: "F", 0b11010: "G", 0b10100: "H", 0b01011: "J", 0b01111: "K",
    0b10010: "L", 0b10001: "Z", 0b11101: "X", 0b01110: "C", 0b11110: "V",
    0b11001: "B", 0b01100: "N", 0b11100: "M", 0b01000: "\r", 0b00010: "\n",
}
_BAUDOT_FIGS = {
    0b10111: "1", 0b10011: "2", 0b00001: "3", 0b01010: "4", 0b10000: "5",
    0b10101: "6", 0b00111: "7", 0b00110: "8", 0b11000: "9", 0b10110: "0",
    0b00011: "-", 0b00101: "'", 0b01001: "$", 0b01101: "!", 0b11010: "&",
    0b10100: "#", 0b01011: "'", 0b01111: "(", 0b10010: ")", 0b10001: "\"",
    0b11101: "/", 0b01110: ":", 0b11110: ";", 0b11001: "?", 0b01100: ",",
    0b11100: ".", 0b00100: " ", 0b01000: "\r", 0b00010: "\n",
}
_LTRS, _FIGS = 0b11111, 0b11011


class RTTYDecoder:
    """Decode 5-bit Baudot RTTY from an FM-discriminator stream."""

    def __init__(self, sample_rate: float, baud: float = 45.45):
        self.fs = sample_rate
        self.baud = baud
        self._acc = (sample_rate / baud) / 2
        self._buf = ""
        self._figs = False

    def process(self, demod: np.ndarray) -> str:
        sps = self.fs / self.baud
        if sps < 2:
            return ""
        sym = (demod > 0).astype(np.int8)
        n = len(sym)
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        if idx:
            self._buf += "".join(str(int(sym[i])) for i in idx)
        self._buf = self._buf[-4000:]
        return self._extract()

    def _extract(self):
        out = []
        s = self._buf
        i = 0
        consumed = 0
        # frame: start(0) + 5 data + stop(1)
        while i + 7 <= len(s):
            if s[i] == "0" and s[i + 6] == "1":
                code = int(s[i + 1:i + 6][::-1], 2)  # LSB first
                if code == _FIGS:
                    self._figs = True
                elif code == _LTRS:
                    self._figs = False
                else:
                    table = _BAUDOT_FIGS if self._figs else _BAUDOT_LTRS
                    out.append(table.get(code, ""))
                i += 7
                consumed = i
            else:
                i += 1
        self._buf = s[consumed:]
        return "".join(out)


def encode_rtty(text: str, sample_rate: float, baud: float = 45.45) -> np.ndarray:
    """Build an FM-discriminator-style RTTY stream (+1 mark / -1 space) for tests."""
    inv = {}
    for code, ch in _BAUDOT_LTRS.items():
        inv.setdefault(ch.upper(), code)
    sps = int(sample_rate / baud)
    bits = []
    for ch in text.upper():
        code = inv.get(ch)
        if code is None:
            continue
        frame = [0] + [(code >> k) & 1 for k in range(5)] + [1, 1]  # start+5+stop
        bits += frame
    arr = np.repeat(np.array([1.0 if b else -1.0 for b in bits], dtype=np.float32), sps)
    return arr


# ---------------------------------------------------------------------------
# PSK31 (BPSK 31.25 baud, varicode) — differential BPSK from baseband IQ
# ---------------------------------------------------------------------------
_VARICODE = {
    "1010101011": " ", "1011011011": "!", "1011111011": '"', "1011101101": "$",
    "1010111011": "'", "1011000111": "(", "1011001011": ")", "1101101111": ",",
    "1011010100": "-", "1010110111": ".", "1010101101": "/", "1011011101": "0",
    "1011110111": "1", "1011110101": "2", "1110101101": "3", "1110101111": "4",
    "1101011011": "5", "1101101011": "6", "1101101101": "7", "1101010111": "8",
    "1101111011": "9", "1111101010": ":", "1101110101": ";", "1010010111": "?",
    "1111101": "A", "11101011": "B", "10101101": "C", "10110101": "D",
    "1110111": "E", "11011011": "F", "11111101": "G", "101010101": "H",
    "1111111": "I", "111111101": "J", "101111101": "K", "11010111": "L",
    "10111011": "M", "11011101": "N", "10101011": "O", "11010101": "P",
    "111011101": "Q", "10101111": "R", "1101111": "S", "1101101": "T",
    "101010111": "U", "110110101": "V", "101011101": "W", "101110101": "X",
    "101111011": "Y", "1010101111": "Z",
    "1011": "e", "1011111": "a", "101111": "n", "111101": "i", "1101": "t",
    "111": "o", "101": "s", "11111": "r", "110111": "h", "101011": "l",
    "11011": "d", "110101": "c", "111011": "u", "1111011": "m", "1010111": "f",
    "1010101": "g", "1110101": "p", "11111011": "w", "1011101": "y",
    "1110111": "b", "1011011": "v", "11101101": "k", "1011110111": "x",
    "1011100111": "j", "11110111": "q", "1010111101": "z", "10": "",
}


class PSK31Decoder:
    """Decode BPSK31 from a tuned-to-DC baseband IQ stream (differential)."""

    def __init__(self, sample_rate: float, baud: float = 31.25):
        self.fs = sample_rate
        self.baud = baud
        self.sps = sample_rate / baud
        self._prev = 1.0 + 0j
        self._acc = self.sps / 2
        self._bits = ""

    def process(self, iq: np.ndarray) -> str:
        n = len(iq)
        idx = []
        pos = self._acc
        while pos < n:
            idx.append(int(pos))
            pos += self.sps
        self._acc = pos - n
        out = []
        for i in idx:
            s = iq[i]
            # phase reversal vs previous symbol = 0, same = 1
            d = (s * np.conj(self._prev)).real
            self._bits += "0" if d < 0 else "1"
            self._prev = s
        return self._decode()

    def _decode(self):
        out = []
        # varicode chars are separated by "00"
        while "00" in self._bits:
            j = self._bits.index("00")
            code = self._bits[:j]
            self._bits = self._bits[j + 2:]
            if code:
                ch = _VARICODE.get(code)
                if ch:
                    out.append(ch)
        if len(self._bits) > 200:
            self._bits = self._bits[-100:]
        return "".join(out)


# ---------------------------------------------------------------------------
# CTCSS sub-audible tone detection (Goertzel)
# ---------------------------------------------------------------------------
CTCSS_TONES = [67.0, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5, 94.8,
               97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
               131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 162.2, 167.9, 173.8,
               179.9, 186.2, 192.8, 203.5, 210.7, 218.1, 225.7, 233.6, 241.8,
               250.3]


def detect_ctcss(audio: np.ndarray, fs: float):
    """Return the strongest CTCSS tone present (Hz) or None.

    Decimates to ~1 kHz (CTCSS < 254 Hz), then a vectorised single-bin DFT per
    tone — fast enough to run on every audio block in real time.
    """
    if len(audio) < int(fs * 0.25):
        return None
    from scipy.signal import decimate
    q = max(1, int(fs // 1000))
    x = decimate(audio - np.mean(audio), q, ftype="fir") if q > 1 else \
        (audio - np.mean(audio))
    fsr = fs / q
    n = len(x)
    if n < 64:
        return None
    k = np.arange(n)
    total = np.sum(x * x) + 1e-9
    best, best_mag = None, 0.0
    for f in CTCSS_TONES:
        c = np.sum(x * np.cos(2 * np.pi * f * k / fsr))
        s = np.sum(x * np.sin(2 * np.pi * f * k / fsr))
        mag = (c * c + s * s) / n
        if mag > best_mag:
            best_mag, best = mag, f
    return best if best_mag / total > 0.15 else None


# ---------------------------------------------------------------------------
# DCS (Digital Coded Squelch) — 134.4 bps, 23-bit Golay code, repeated
# ---------------------------------------------------------------------------
def detect_dcs(audio: np.ndarray, fs: float):
    """Best-effort DCS detection: slice the sub-audible stream at 134.4 bps and
    report the repeating 23-bit code as an octal DCS number, or None."""
    if len(audio) < int(fs * 0.5):
        return None
    from scipy.signal import decimate
    q = max(1, int(fs // 1200))
    x = decimate(audio - np.mean(audio), q, ftype="fir") if q > 1 else audio
    fsr = fs / q
    # low-pass < 300 Hz already (sub-audible); slice at 134.4 bps
    baud = 134.4
    sps = fsr / baud
    if sps < 2:
        return None
    sym = (x > 0).astype(np.int8)
    idx = (np.arange(0, len(sym), sps)).astype(int)
    bits = "".join(str(int(sym[i])) for i in idx if i < len(sym))
    # look for a 23-bit pattern repeating
    for period in (23,):
        if len(bits) >= period * 3:
            cand = bits[:period]
            reps = sum(bits[k * period:(k + 1) * period] == cand
                       for k in range(len(bits) // period))
            if reps >= max(2, (len(bits) // period) // 2):
                code = int(cand[::-1], 2) & 0o777
                return f"D{code:03o}"
    return None


# ---------------------------------------------------------------------------
# Digital voice (DMR / dPMR / YSF / TETRA) — 4FSK sync-pattern detection
# ---------------------------------------------------------------------------
# DMR 48-bit sync words (as transmitted dibit patterns → bit strings)
DMR_SYNCS = {
    "0111010101011111110101111101011111110101": "DMR BS voice",
    "1101111111110101011111010111010111011101": "DMR BS data",
    "0111111101111101010111010101011101111101": "DMR MS voice",
    "1101010111010101011111111101011101010111": "DMR MS data",
}
# TETRA / dPMR are π/4-DQPSK / 4FSK with their own training; we flag activity.


class DigitalVoiceDetector:
    """Detect DMR (and flag generic 4FSK digital voice) from an FM stream.

    4FSK → dibit symbols → search for the 48-bit DMR sync words.  This reports
    presence/type (and is the basis for a full decoder); it does not run the
    AMBE vocoder, so it identifies but does not play digital voice.
    """

    def __init__(self, sample_rate: float, baud: float = 4800):
        self.fs = sample_rate
        self.baud = baud
        self._acc = (sample_rate / baud) / 2
        self._bits = ""

    def process(self, demod: np.ndarray) -> list[str]:
        sps = self.fs / self.baud
        if sps < 2:
            return []
        # 4-level slice → 2 bits per symbol (Gray-ish): thresholds at -t,0,+t
        idx = []
        pos = self._acc
        n = len(demod)
        while pos < n:
            idx.append(int(pos))
            pos += sps
        self._acc = pos - n
        if not idx:
            return []
        s = demod[idx]
        t = np.percentile(np.abs(s), 75) * 0.5 + 1e-9
        out = []
        for v in s:
            if v > t:
                out.append("01")     # +3
            elif v > 0:
                out.append("00")     # +1
            elif v > -t:
                out.append("10")     # -1
            else:
                out.append("11")     # -3
        self._bits += "".join(out)
        self._bits = self._bits[-6000:]
        found = []
        for sync, name in DMR_SYNCS.items():
            if sync in self._bits:
                found.append(name)
        if found:
            self._bits = ""
        return found
