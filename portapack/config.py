"""Persistent application settings (front-end state, last app, per-app prefs)."""

from __future__ import annotations

import json
import os

CONFIG_PATH = os.path.expanduser("~/portapack-pc/config.json")

_DEFAULTS = {
    "frequency": 100_000_000,
    "sample_rate": 2_400_000,
    "lna_gain": 24.0,
    "vga_gain": 20.0,
    "amp_enable": False,
    "bias_tee": False,
    "freq_corr_ppm": 0.0,
    "freq_step": 25_000.0,
    "last_app": None,
    "apps": {},          # per-app preference dicts
}


class Config:
    def __init__(self, path: str = CONFIG_PATH):
        self.path = path
        self.data = dict(_DEFAULTS)
        self.load()

    def load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self.data.update(json.load(f))
            except Exception:
                pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception:
            pass

    # ---- convenience ------------------------------------------------------
    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        self.data[key] = value

    def app_prefs(self, app_id: str) -> dict:
        return self.data.setdefault("apps", {}).setdefault(app_id, {})

    # ---- front-end sync ---------------------------------------------------
    def capture_frontend(self, cfg):
        """Snapshot a RadioConfig into the store."""
        for k in ("frequency", "sample_rate", "lna_gain", "vga_gain",
                  "amp_enable", "bias_tee", "freq_corr_ppm", "freq_step"):
            self.data[k] = getattr(cfg, k)

    def apply_frontend(self, hub):
        """Restore stored front-end values onto a RadioHub."""
        c = hub.cfg
        c.frequency = self.data.get("frequency", c.frequency)
        c.sample_rate = self.data.get("sample_rate", c.sample_rate)
        c.lna_gain = self.data.get("lna_gain", c.lna_gain)
        c.vga_gain = self.data.get("vga_gain", c.vga_gain)
        c.amp_enable = self.data.get("amp_enable", c.amp_enable)
        c.bias_tee = self.data.get("bias_tee", c.bias_tee)
        c.freq_corr_ppm = self.data.get("freq_corr_ppm", c.freq_corr_ppm)
        c.freq_step = self.data.get("freq_step", c.freq_step)
