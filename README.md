# PortaPack PC

A desktop reimagining of the **PortaPack / Mayhem firmware** for the **HackRF One**.
Same spirit and workflow as the handheld — frequency-tuning, waterfall, a tree of
receive/transmit/utility apps — but running on the PC and driving a HackRF over USB
via SoapySDR, with PC-class DSP (numpy/scipy) and real audio output.

It runs **with or without hardware**: when no HackRF is found it drops into a
simulation source so the whole UI and signal chain are usable for development.

```
┌──────────────────────────────────────────────────────────────┐
│ ● HackRF connected   ⟳ 100.0000 MHz  SR 2.40M  LNA24 VGA20   RX │  status bar
├───────────────┬──────────────────────────────────────────────┤
│ ⌂ Home        │            100.0000 MHz                       │
│ ▼ Receive     │   ┌────────── spectrum ──────────┐            │
│   Audio       │   │                              │  Modulation │
│   Looking…    │   └──────────────────────────────┘  [WFM ▾]   │
│   Capture     │   ┌────────── waterfall ─────────┐  RF / gains │
│   ...         │   │                              │  Audio/Sql  │
│ ▲ Transmit    │   └──────────────────────────────┘            │
│ ⚙ Utilities   │                                               │
│ ⊞ System      │                                               │
└───────────────┴──────────────────────────────────────────────┘
```

## Run

```bash
cd ~/portapack-pc
./portapack-pc          # auto-detect HackRF, else simulation
./portapack-pc --sim    # force simulation
```

(or `./.venv/bin/python run.py`)

When you plug the HackRF in while the app is running, hit **Rescan HackRF**
(left panel) or Settings → Rescan to switch from simulation to hardware.

## Apps (44)

**Receive (18)**
- **Audio** — WFM / NFM / AM / USB / LSB voice receiver with waterfall, squelch,
  volume, click-to-tune within the span, peak hold.
- **Looking Glass** — wideband stepped spectrum sweep (start/stop up to 6 GHz) by
  retuning the front end and stitching FFT slices.
- **Capture** — record raw IQ to `captures/*.cs8` (interleaved int8, HackRF /
  GNU Radio / `hackrf_transfer` compatible).
- **Level** — big wideband signal-strength meter with peak hold.
- **ADS-B** — 1090 MHz Mode-S frame decoder with CRC check + aircraft table.
- **POCSAG** — pager decoder (512 / 1200 / 2400 baud, FSK).
- **Sub-GHz** — OOK/ASK burst capture for remotes & sensors (315/433/868/915 MHz).
- **Analog TV** — video raster preview of ATV / broadcast carriers.
- **TPMS** — tyre-pressure sensor receiver (315/433, OOK/FSK).
- **APRS** — AFSK1200 AX.25 packet decoder (full HDLC + FCS check).
- **AIS** — marine GMSK 9600 frame detector (161.975 / 162.025 MHz).
- **Scanner** — recon/search across a range; stops and listens on active channels.
- **ACARS** — aircraft 131 MHz AM/MSK text message decoder.
- **Radiosonde** — weather-balloon (RS41/M10) GFSK frame detector.
- **ERT Meters** — utility smart-meter SCM reader (~912 MHz OOK Manchester).
- **Weather** — 433/868/915 OOK temperature/humidity sensor capture.
- **BTLE** — Bluetooth LE advertising packet sniffer (2.4 GHz GFSK 1 Mbps).
- **NRF24** — nRF24L01 Shockburst sniffer.

**Transmit (17)** (needs a real HackRF — half-duplex)
- **Tone TX** — CW / FM / AM test tone.
- **OOK TX** — synthesize sub-GHz remote codes (NRZ / Manchester / PT2262 PWM).
- **Replay TX** — transmit a recorded `.cs8` IQ capture (once or looped).
- **Mic TX** — live FM/AM voice from the PC microphone (PTT walkie-talkie).
- **Morse TX** — CW keyer from text (5–40 WPM).
- **Tones TX** — DTMF dialer + CTCSS / single-tone FM generator.
- **RDS TX** — FM broadcast with stereo pilot + RDS PS station name.
- **Jammer TX** — noise / chirp / comb interference generator (**authorised testing only**).
- **Spectrum Painter** — draw text into the RF waterfall.
- **APRS TX** — beacon AX.25/APRS position packets (validated against the RX decoder).
- **POCSAG TX** — transmit a pager message.
- **ADS-B TX** — build & send a Mode-S DF17 squitter (CRC validated against the RX decoder).
- **GPS Sim** — L1 C/A single-SV signal generator (testing/education, not a position fix).
- **Soundboard** — FM-transmit WAV files or built-in sound effects.
- **Playlist** — transmit a sequence of IQ captures.
- **GFSK TX** — generic FSK/GFSK payload transmitter (configurable baud/deviation).
- **BHT TX** — EU building/elevator CCIR tone signalling.

**Utilities (7)**
- **Freq Manager** — store/recall named frequencies (persists to `freqman.json`).
- **Notepad** — persistent text scratchpad.
- **Signal Gen** — CW/sweep/two-tone source + whip-antenna length calculator.
- **File Manager** — browse captures / notes / data files, delete, inspect.
- **Calculator** — RF / antenna / power (dBm↔W) / Doppler calculator.
- **Scheduler** — time-triggered tuning / reminders.
- **Audio Monitor** — PC microphone level meter + spectrum.

**System (2)**
- **Settings** — device info, rescan, default gains, freq correction.
- **About**.

## Architecture

```
portapack/
  app.py              main window: status bar, nav tree, app host
  sdr/
    backend.py        RadioHub — single owner of the HackRF (SoapySDR),
                      RX/TX worker threads, simulation fallback
    dsp.py            Tuner, FIR decimators, FM/AM/SSB demods, resampler, AGC, PSD
    decoders.py       OOK, ADS-B (Mode-S PPM+CRC), POCSAG, AFSK1200/AX.25,
                      AIS, ERT/SCM, ACARS, generic FSK framer
    audio.py          sounddevice output sink with ring buffer
  ui/
    theme.py          Mayhem-style palette + Qt stylesheet
    spectrum.py       spectrum trace + scrolling waterfall (pyqtgraph)
    widgets.py        FrequencyDisplay (wheel-tune), gain panel, sliders, fields
  apps/
    base.py           AppView lifecycle + worker→GUI thread marshaling
    *.py              one module per app, self-registering into the registry
```

The radio is single-owner: one app streams at a time, exactly like the firmware.
RX runs in a worker thread that hands IQ blocks to the active app's callback;
apps do their DSP there (push audio, compute FFT) and marshal UI updates to the
GUI thread via a Qt signal.

## Requirements

System packages (Arch): `python-pyside6 python-numpy python-scipy
python-pyqtgraph soapysdr soapyhackrf hackrf portaudio`, plus pip
`sounddevice colorama` in the venv. See `requirements.txt`.

## Legal

Transmit only on frequencies and at power levels you are licensed/authorised to
use. Receiving may also be regulated in your jurisdiction. You are responsible
for legal compliance.
