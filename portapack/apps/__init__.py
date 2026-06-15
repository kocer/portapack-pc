"""Application registry — mirrors the PortaPack home-screen app tree."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Type


@dataclass
class AppInfo:
    id: str
    name: str
    category: str            # Receive / Transmit / Utilities / System
    factory: Callable        # callable(hub, audio, ctx) -> AppView
    needs_tx: bool = False
    description: str = ""


_REGISTRY: list[AppInfo] = []


def register(info: AppInfo):
    _REGISTRY.append(info)
    return info


def all_apps() -> list[AppInfo]:
    return list(_REGISTRY)


def by_category() -> dict[str, list[AppInfo]]:
    cats: dict[str, list[AppInfo]] = {}
    for a in _REGISTRY:
        cats.setdefault(a.category, []).append(a)
    return cats


def load_all():
    """Import the app modules so they self-register."""
    from . import (receiver_audio, looking_glass, capture, level,  # noqa: F401
                   adsb_rx, pocsag_rx, subghz_rx, analog_tv,
                   tpms_rx, aprs_rx, ais_rx, scanner,
                   acars_rx, radiosonde_rx, ert_rx, weather_rx, btle_rx, nrf_rx,
                   noaa_apt, sstv_rx, rtl433_rx, digital_modes, wefax_rx,
                   digital_voice, ft8_rx, meteor_lrpt, wspr_rx,
                   tx_tone, tx_ook, tx_replay, tx_microphone,
                   morse_tx, tones_tx, rds_tx, jammer_tx, spectrum_painter_tx,
                   aprs_tx, pocsag_tx, adsb_tx, gps_sim, soundboard_tx,
                   playlist_tx, gfsk_tx, bht_tx,
                   freqman, notepad, siggen, filemanager, calculator,
                   iq_analyzer,
                   scheduler, audio_monitor, settings_app, about_app)
