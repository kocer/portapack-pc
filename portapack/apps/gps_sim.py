"""GPS simulator — real multi-satellite L1 C/A using gps-sdr-sim.

Generates a genuine GPS baseband recording (all visible satellites, navigation
message, correct code phase / Doppler / timing) for a chosen location via the
bundled ``gps-sdr-sim`` tool, then transmits it on L1 (1575.42 MHz).  A GPS
receiver in a shielded setup will actually lock and report the simulated fix.
"""

from __future__ import annotations

import collections
import datetime
import gzip
import os
import subprocess
import threading
import urllib.request

import numpy as np
from PySide6.QtWidgets import (QFileDialog, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QProgressBar, QPushButton, QVBoxLayout,
                               QWidget)

from ..ui import theme, widgets
from . import AppInfo, register
from .base import AppView

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GPS_BIN = os.path.join(_ROOT, "tools", "gps", "gps-sdr-sim")
DEFAULT_EPH = os.path.join(_ROOT, "tools", "gps", "brdc0010.22n")
OUT_DIR = os.path.expanduser("~/portapack-pc/captures")
L1_FREQ = 1_575_420_000
GPS_RATE = 2_600_000


def rinex3_to_rinex2(src: str, dst: str):
    """Convert a RINEX-3 mixed nav file to single-day RINEX-2 GPS nav.

    Extracts GPS (G) records, keeps only the most common calendar day (the
    merged broadcast file carries stray old ephemerides), re-headers each epoch
    line and re-indents the orbit lines, and sorts epoch-major as gps-sdr-sim's
    RINEX-2 reader expects.  Returns the modal date (datetime.date).
    """
    lines = open(src, errors="replace").read().splitlines()
    i = 0
    while i < len(lines) and "END OF HEADER" not in lines[i]:
        i += 1
    i += 1
    n = len(lines)
    raw = []
    while i < n:
        line = lines[i]
        if not line or line[0] != "G":
            i += 1
            continue
        try:
            prn = int(line[1:3]); y4 = int(line[4:8]); mm = int(line[9:11])
            dd = int(line[12:14]); hh = int(line[15:17]); mi = int(line[18:20])
            ss = float(line[21:23])
        except (ValueError, IndexError):
            i += 1
            continue
        cont, ok = [], True
        for k in range(1, 8):
            if i + k < n and lines[i + k].startswith("    "):
                cont.append(lines[i + k][1:])
            else:
                ok = False
                break
        if ok:
            raw.append((y4, mm, dd, hh, mi, prn, ss, line, cont))
        i += 8
    if not raw:
        raise ValueError("no GPS records in ephemeris")
    modal = collections.Counter((r[0], r[1], r[2]) for r in raw).most_common(1)[0][0]
    md = datetime.date(*modal)
    blocks = []
    for (y4, mm, dd, hh, mi, prn, ss, line, cont) in raw:
        if datetime.date(y4, mm, dd) != md:
            continue
        clk = line[23:42] + line[42:61] + line[61:80]
        rec = ["%2d %02d %2d %2d %2d %2d %4.1f%s"
               % (prn, y4 % 100, mm, dd, hh, mi, ss, clk)] + cont
        blocks.append(((y4, mm, dd, hh, mi, prn), "\n".join(rec)))
    blocks.sort(key=lambda b: b[0])
    out = ["%9.2f%-11sN: GPS NAV DATA%26s%s" % (2.11, "", "", "RINEX VERSION / TYPE"),
           "%-60s%s" % ("portapack-pc", "PGM / RUN BY / DATE"),
           "%-60s%s" % ("", "END OF HEADER")]
    out += [b[1] for b in blocks]
    open(dst, "w").write("\n".join(out) + "\n")
    return md


def download_ephemeris(dest_dir: str):
    """Fetch a recent RINEX-3 broadcast file (BKG, open) and convert to RINEX-2.

    Returns ``(rinex2_path, date)``.  Tries the last few days (data latency).
    """
    os.makedirs(dest_dir, exist_ok=True)
    today = datetime.date.today()
    last_err = "no data"
    for back in range(1, 6):
        d = today - datetime.timedelta(days=back)
        doy = d.timetuple().tm_yday
        url = (f"https://igs.bkg.bund.de/root_ftp/IGS/BRDC/{d.year}/{doy:03d}/"
               f"BRDC00WRD_R_{d.year}{doy:03d}0000_01D_MN.rnx.gz")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "portapack-pc"})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
            rnx = os.path.join(dest_dir, "brdc_current.rnx")
            with open(rnx, "wb") as f:
                f.write(gzip.decompress(data))
            r2 = os.path.join(dest_dir, "brdc_current.nav")
            md = rinex3_to_rinex2(rnx, r2)
            return r2, md
        except Exception as e:
            last_err = f"{e}"
            continue
    raise RuntimeError(f"download failed ({last_err})")


class _GenWorker(threading.Thread):
    def __init__(self, cmd, on_done):
        super().__init__(daemon=True)
        self.cmd = cmd
        self.on_done = on_done

    def run(self):
        try:
            p = subprocess.run(self.cmd, capture_output=True, text=True,
                               timeout=900)
            self.on_done(p.returncode, p.stdout + p.stderr)
        except Exception as e:
            self.on_done(-1, str(e))


class GPSSim(AppView):
    title = "GPS Sim"

    def __init__(self, hub, audio, ctx):
        super().__init__(hub, audio, ctx)
        self._iqpath = None
        self._file = None
        self._eph = DEFAULT_EPH
        self._eph_date = None       # set when a dated ephemeris is loaded
        self.loop = True
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        self.freq = widgets.FrequencyDisplay(L1_FREQ, hub=self.hub, font_pt=15)
        self.freq.frequency_changed.connect(self.hub.set_frequency)
        lay.addWidget(self.freq)

        warn = QLabel("⚠ GPS spoofing is dangerous & illegal on the air. "
                      "Use only in a shielded enclosure with no antenna leakage.")
        warn.setStyleSheet(f"color:{theme.RED};font-weight:bold;")
        warn.setWordWrap(True)
        lay.addWidget(warn)

        gb = QGroupBox("Scenario")
        gl = QVBoxLayout(gb)
        self.lat = QLineEdit("41.015137")
        self.lon = QLineEdit("28.979530")
        self.alt = QLineEdit("100")
        gl.addWidget(widgets.Field("Latitude", self.lat))
        gl.addWidget(widgets.Field("Longitude", self.lon))
        gl.addWidget(widgets.Field("Altitude m", self.alt))
        self.dur = widgets.LabeledSlider("Duration", 10, 300, 30, suffix=" s")
        gl.addWidget(self.dur)
        row = QHBoxLayout()
        self.eph_lbl = QLabel(os.path.basename(self._eph) + " (2022, expired)")
        self.eph_lbl.setStyleSheet(f"color:{theme.FG_DIM};font-size:10px;")
        eph_btn = QPushButton("Browse…")
        eph_btn.clicked.connect(self._browse_eph)
        dl_btn = QPushButton("⤓ Download current")
        dl_btn.clicked.connect(self._download)
        row.addWidget(self.eph_lbl, 1)
        row.addWidget(eph_btn)
        row.addWidget(dl_btn)
        gl.addLayout(row)
        lay.addWidget(gb)

        self.gen_btn = QPushButton("⚙  Generate GPS signal")
        self.gen_btn.clicked.connect(self._generate)
        lay.addWidget(self.gen_btn)
        self.prog = QProgressBar()
        self.prog.setRange(0, 0)
        self.prog.hide()
        lay.addWidget(self.prog)
        self.status = QLabel("Set a location and Generate.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet(f"color:{theme.ACCENT};")
        lay.addWidget(self.status)

        gb2 = QGroupBox("TX gain")
        g2 = QVBoxLayout(gb2)
        self.txg = widgets.LabeledSlider("TX VGA", 0, 47, 30, suffix=" dB")
        self.txg.valueChanged.connect(
            lambda v: setattr(self.hub.cfg, "tx_vga_gain", float(v)))
        g2.addWidget(self.txg)
        g2.addWidget(widgets.BiasTeeBox(self.hub))
        lay.addWidget(gb2)

        self.tx_btn = widgets.tx_button("TRANSMIT (loop)")
        self.tx_btn.setEnabled(False)
        self.tx_btn.toggled.connect(self._toggle)
        lay.addWidget(self.tx_btn)
        lay.addStretch(1)

        if not os.path.exists(GPS_BIN):
            self.status.setText(f"gps-sdr-sim not found at {GPS_BIN}")
            self.gen_btn.setEnabled(False)

    def _browse_eph(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "RINEX navigation (ephemeris)",
            os.path.dirname(self._eph), "RINEX nav (*.*n *.rnx *.nav);;All (*)")
        if p:
            self._eph = p
            self._eph_date = None
            self.eph_lbl.setText(os.path.basename(p))

    def _download(self):
        self.status.setText("Downloading current ephemeris (BKG IGS)…")
        self.prog.show()

        def work():
            try:
                path, date = download_ephemeris(os.path.join(_ROOT, "tools", "gps"))
                self.emit_ui(("eph", path, date.isoformat()))
            except Exception as e:
                self.emit_ui(("eph", None, str(e)))
        threading.Thread(target=work, daemon=True).start()

    # ---- generation -------------------------------------------------------
    def _generate(self):
        os.makedirs(OUT_DIR, exist_ok=True)
        self._iqpath = os.path.join(OUT_DIR, "gpssim.bin")
        cmd = [GPS_BIN, "-e", self._eph,
               "-l", f"{self.lat.text()},{self.lon.text()},{self.alt.text()}",
               "-b", "8", "-s", str(GPS_RATE),
               "-d", str(self.dur.value()), "-o", self._iqpath]
        if self._eph_date:   # downloaded/dated ephemeris needs an explicit epoch
            cmd += ["-t", self._eph_date.replace("-", "/") + ",12:00:00"]
        self.gen_btn.setEnabled(False)
        self.tx_btn.setEnabled(False)
        self.prog.show()
        self.status.setText("Generating… (computing satellites; a few seconds "
                            "per simulated second)")
        _GenWorker(cmd, lambda rc, out: self.emit_ui(("gen", rc, out))).start()

    def _on_ui(self, payload):
        if not payload:
            return
        if payload[0] == "eph":
            self.prog.hide()
            _, path, info = payload
            if path:
                self._eph = path
                self._eph_date = info       # ISO date string YYYY-MM-DD
                self.eph_lbl.setText(f"current {info} ✓")
                self.status.setText(f"Current ephemeris ready ({info}). Generate now.")
            else:
                self.status.setText(f"Download failed: {info}. Using bundled "
                                    "(expired) file.")
            return
        if payload[0] != "gen":
            return
        _, rc, out = payload
        self.prog.hide()
        self.gen_btn.setEnabled(True)
        if rc == 0 and self._iqpath and os.path.exists(self._iqpath):
            sats = [l for l in out.splitlines()
                    if l.strip() and l.split()[0].isdigit()]
            mb = os.path.getsize(self._iqpath) / 1e6
            self.status.setText(
                f"✓ Generated {mb:.0f} MB — {len(sats)} satellites, "
                f"{self.dur.value()} s @ {GPS_RATE/1e6:.1f} Msps. Ready to TX.")
            self.tx_btn.setEnabled(True)
        else:
            self.status.setText(f"Generation failed (rc={rc}): {out[-200:]}")

    # ---- transmit ---------------------------------------------------------
    def on_stop(self):
        if self.tx_btn.isChecked():
            self.tx_btn.setChecked(False)

    def _toggle(self, on):
        if on:
            if not self._iqpath or not os.path.exists(self._iqpath):
                self.tx_btn.setChecked(False)
                return
            self.hub.set_sample_rate(GPS_RATE)
            self.hub.set_frequency(self.freq.value())
            try:
                self._file = open(self._iqpath, "rb")
            except Exception as e:
                self.status.setText(f"open error: {e}")
                self.tx_btn.setChecked(False)
                return
            if self.hub.is_sim:
                self.status.setText("Simulation — no RF emitted. Plug HackRF.")
            self.hub.start_tx(self._gen)
        else:
            self.hub.stop()
            if self._file:
                self._file.close()
                self._file = None

    def _gen(self, n):
        """Stream the int8 I/Q file from disk (loop), converting to complex64."""
        if not self.tx_btn.isChecked() or self._file is None:
            return None
        need = n * 2  # int8 I/Q pairs
        raw = self._file.read(need)
        if len(raw) < need:
            if self.loop:
                self._file.seek(0)
                raw += self._file.read(need - len(raw))
            if not raw:
                return None
        a = np.frombuffer(raw, dtype=np.int8).astype(np.float32) / 127.0
        if len(a) % 2:
            a = a[:-1]
        return (a[0::2] + 1j * a[1::2]).astype(np.complex64)


register(AppInfo(
    id="gps_sim", name="GPS Sim", category="Transmit", needs_tx=True,
    factory=lambda hub, audio, ctx: GPSSim(hub, audio, ctx),
    description="Real multi-SV GPS L1 simulation via gps-sdr-sim (shielded use)"))
