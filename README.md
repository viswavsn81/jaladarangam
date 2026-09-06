# Mindfulness Instrument

A Raspberry Pi 3 project that plays an instrument sample when a sensor is triggered.
Started as a keyboard-spacebar proof of concept (evdev + pygame); the wiring below is
for the real sensor hardware: 8 FSR402 force sensors, one per note key (Sa through
upper Sa), read through an MCP3008 ADC over SPI. An earlier hardware iteration used
2 FSRs plus a SparkFun SoftPot ribbon for continuous glide; that layout was replaced
by the 8 discrete note keys below, and the SoftPot has since been removed entirely.

The project's original design calls for two MCP3008 chips sharing one SPI0 bus
(distinguished by chip-select line): **ADC1** for the 8 note-key FSRs, and **ADC2**
for the gamakam/octave-up/octave-down control keys. ADC1 is documented and wired
below. ADC2's wiring is documented in [ADC2 (control keys)](#adc2--control-keys)
below; as of this writing it is still being physically wired and has no software
support yet (see that section for exact status).

## Hardware

- Raspberry Pi 3 Model B
- 2x MCP3008 8-channel 10-bit ADC (16-pin DIP, SPI interface) — ADC1 (note keys,
  wired) and ADC2 (control keys, being wired)
- 8x FSR402 round force sensor (18mm) — ADC1's discrete note keys, CH0-CH7 =
  Sa, Ri, Ga, Ma, Pa, Da, Ni, Sa' (upper Sa)
- Resistors: 8x 10kΩ (ADC1, one per note-key FSR) — plus 1x 10kΩ per ADC2
  control-key FSR as those get populated
- Breadboard + jumper wires

## Wiring

All physical pin numbers below refer to the Raspberry Pi's 40-pin GPIO header, and were
verified against the official Raspberry Pi pinout and the Microchip MCP3008 datasheet
(DS20001295E) before wiring.

### Pi -> MCP3008 (ADC1)

| Pi physical pin | Signal | MCP3008 pin |
|---|---|---|
| 1 | 3.3V | 16 (VDD) |
| 1 | 3.3V | 15 (VREF) |
| 6 | GND | 14 (AGND) |
| 6 | GND | 9 (DGND) |
| 23 | GPIO11 / SPI0 SCLK | 13 (CLK) |
| 19 | GPIO10 / SPI0 MOSI | 11 (DIN) |
| 21 | GPIO9 / SPI0 MISO | 12 (DOUT) |
| 24 | GPIO8 / SPI0 CE0 | 10 (CS/SHDN) |

MCP3008 pin 1 (CH0) is at the end of the chip marked with a notch/dot — make sure that
end is oriented correctly on the breadboard before inserting.

### Note-key channel assignment (ADC1)

| MCP3008 pin (channel) | Note key |
|---|---|
| 1 (CH0) | Sa |
| 2 (CH1) | Ri |
| 3 (CH2) | Ga |
| 4 (CH3) | Ma |
| 5 (CH4) | Pa |
| 6 (CH5) | Da |
| 7 (CH6) | Ni |
| 8 (CH7) | Sa' (upper Sa) |

All 8 are discrete FSR keys, matching `jaladarangam.py`'s `LIVE_POSITIONS =
set(range(8))`. There is no SoftPot or continuous-glide sensor in the current
hardware — an earlier prototype iteration used a SoftPot ribbon on CH2 for
continuous pitch glide, but that approach was replaced by these 8 discrete FSR
keys and the SoftPot has been physically removed.

### Sensors (voltage dividers into ADC1)

Identical divider pattern for all 8 note-key FSRs:

| Component | Leg/end | Connects to |
|---|---|---|
| Note-key FSR | leg A | 3.3V rail |
| Note-key FSR | leg B | ADC1 channel pin (per the table above) **and** 10kΩ resistor -> GND |

The 10kΩ resistor forms a voltage divider: FSR resistance drops under pressure,
so the sense-node voltage *rises* with force.

## Step-by-step wiring order (ADC1)

1. Power off / unplug the Pi before wiring anything.
2. Seat the MCP3008 across the breadboard's center gap, pin 1 (notch end) toward CH0.
3. Run the 3.3V rail and GND rail down the breadboard from the Pi's pin 1 and pin 6.
4. Wire MCP3008 VDD (16) and VREF (15) to the 3.3V rail; AGND (14) and DGND (9) to the GND rail.
5. Wire the SPI lines: Pi pin 23 -> MCP3008 CLK (13), Pi pin 19 -> DIN (11),
   Pi pin 21 -> DOUT (12), Pi pin 24 -> CS/SHDN (10).
6. Wire each of the 8 note-key FSRs (Sa through Sa', MCP3008 channels CH0-CH7 per
   the channel-assignment table above): one leg to the 3.3V rail, the other leg to
   its assigned MCP3008 channel pin and to one leg of a 10kΩ resistor whose other
   leg goes to the GND rail. Repeat for all 8 keys.
7. Double-check every connection against the tables above before powering the Pi back on.
8. Once wired, enable SPI on the Pi (`sudo raspi-config nonint do_spi 0`) if not already
   enabled, then reboot before trying to read the MCP3008.

## ADC2 (control keys)

**Status as of this writing:** ADC2 is not yet on the bus at all — no chip, no CE1,
no channels. This section is the build spec to wire it, not a record of something
already done. Update this status line once the chip is seated and again as
individual control-key FSRs get populated, so it always reflects "wired to Pi,
channels unpopulated" vs. specific live channels rather than assuming all three
control keys are connected just because the chip is on the bus.

ADC2 is a second MCP3008 sharing the same SPI0 bus as ADC1 (same CLK/DIN/DOUT,
same power/ground rails), distinguished by its own hardware chip-select line
(CE1 instead of ADC1's CE0). It carries the three control keys — gamakam,
octave+, octave- — reserved from the original two-chip instrument design.
**No software reads ADC2 yet** — see [Software](#software) below.

### Shared bus (Pi -> ADC2)

Identical to ADC1's bus wiring above — these four signals are shared by both
chips; do not re-run separate jumpers from the Pi for these, just tie ADC2's
matching pins onto the same rails/lines ADC1 already uses.

| Pi physical pin | Signal | MCP3008 pin |
|---|---|---|
| 1 | 3.3V | 16 (VDD) |
| 1 | 3.3V | 15 (VREF) |
| 6 | GND | 14 (AGND) |
| 6 | GND | 9 (DGND) |
| 23 | GPIO11 / SPI0 SCLK | 13 (CLK) |
| 19 | GPIO10 / SPI0 MOSI | 11 (DIN) |
| 21 | GPIO9 / SPI0 MISO | 12 (DOUT) |

### ADC2-specific: chip select

| Pi physical pin | Signal | MCP3008 pin |
|---|---|---|
| 26 | GPIO7 / SPI0 CE1 | 10 (CS/SHDN) |

This is distinct from ADC1's chip-select (Pi physical pin 24, GPIO8 / SPI0 CE0)
— CE0 and CE1 are separate hardware-controlled pins, so make sure ADC2's
CS/SHDN goes to physical pin 26 (GPIO7/CE1), not physical pin 24 (GPIO8/CE0),
which is already committed to ADC1.

### Channel assignment (reserved from the original design)

| MCP3008 pin (channel) | Control key | Status |
|---|---|---|
| 1 (CH0) | gamakam | unpopulated — currently a keyboard-spacebar stand-in in software |
| 2 (CH1) | octave+ | unpopulated |
| 3 (CH2) | octave- | unpopulated |
| 4-8 (CH3-CH7) | spare/unused | reserved for future use, not currently assigned |

### Sensors (voltage dividers into ADC2) — apply per channel as each FSR is added

Same pattern as ADC1's note-key FSRs: for whichever of the three control
channels above has an FSR physically attached, wire it as follows. Do **not**
wire a channel this way until an FSR is actually being installed on it —
until then, leave that channel's row in the table above as "unpopulated."

| Component | Leg/end | Connects to |
|---|---|---|
| Control-key FSR | leg A | 3.3V rail |
| Control-key FSR | leg B | ADC2 channel pin (CH0/CH1/CH2 per the table above) **and** 10kΩ resistor -> GND |

### Step-by-step wiring order (ADC2)

1. Power off / unplug the Pi before wiring anything.
2. Seat the second MCP3008 on the breadboard, pin 1 (notch end) toward CH0, same
   orientation convention as ADC1.
3. Tie ADC2's VDD (16) and VREF (15) onto the existing 3.3V rail; AGND (14) and
   DGND (9) onto the existing GND rail (the same rails ADC1 already uses).
4. Tie ADC2's CLK (13), DIN (11), and DOUT (12) onto the same SPI0 SCLK/MOSI/MISO
   lines ADC1 already uses (Pi physical pins 23/19/21) — these lines are shared,
   not duplicated.
5. Wire ADC2's CS/SHDN (10) to Pi physical pin 26 (GPIO7 / SPI0 CE1) — a new,
   ADC2-only line, separate from ADC1's CE0 on physical pin 24.
6. For each control-key FSR you are physically installing now, wire it per the
   voltage-divider table above into its assigned channel; leave any channel with
   no FSR yet unpopulated rather than wiring a dangling divider.
7. Double-check every connection against the tables above before powering the Pi
   back on, and update the status line at the top of this section to reflect
   exactly which channels are now populated.
8. SPI0 is already enabled from the ADC1 setup; no additional `raspi-config`
   step is needed for a second chip on the same bus.

## Software

- `spacebar_instrument.py` — the keyboard-spacebar proof of concept (evdev + pygame),
  kept as a reference/fallback trigger while the sensor wiring above is being built out.
- `samples/guitar_note.wav` — CC0 guitar sample from OpenGameArt.org
  (https://opengameart.org/content/guitar-0), used by the spacebar PoC.
- `read_fsr_raw.py` — prints raw MCP3008 readings for a channel; used to verify a
  sensor's wiring/divider orientation before building anything on top of it.
- `fsr_oscillator.py` — maps FSR1 (CH0) and FSR2 (CH1) each to a persistent sine
  oscillator (pygame.mixer, 48000Hz/1024-sample buffer) whose pitch tracks pressure;
  an interface-level proof of concept, not the final instrument sound.
- `gamaka.py` — the pressure-controlled pitch-bend (gamaka) proof of concept. FSR1
  triggers/bends a D3 guitar pluck, FSR2 triggers/bends a G3 pluck. Samples are
  streamed through a `sounddevice` callback with a variable-rate linear-interpolation
  reader per voice (pygame.mixer can't vary playback speed live, hence the different
  library here vs. the oscillator above). Raw ADC is EMA-smoothed before driving the
  bend; a fresh pluck triggers on the raw touch-threshold crossing, and the bend
  (0 to +40 cents, `rate = 2^(cents/1200)`) tracks the smoothed value continuously,
  including after release, so pitch settles back down instead of snapping.
- `prepare_samples.py` — one-time preprocessing script that derived `d3_pluck.wav`
  and `g3_pluck.wav` from the source samples below.
- `samples/d3_pluck.wav`, `samples/g3_pluck.wav` — derived from
  [`karoryfer.shinyguitar`](https://github.com/sfzinstruments/karoryfer.shinyguitar)
  (CC0 1.0, verified directly against the repo's `LICENSE` file). That library samples
  in whole tones rather than every semitone, so D3 and G3 aren't recorded directly —
  they're derived from the nearest neighbors (Eb3 and Gb3) via a 1-semitone pitch
  shift, resampled to 48000Hz to match this Pi's PipeWire audio graph quantum.
- `jaladarangam.py` — the current real hardware-driven instrument. Reads all 8
  physical note-key FSRs on ADC1 (CH0-CH7 = Sa..Sa'), with raga-selectable
  positional layout (`--raga`), polyphony (up to 8 notes ringing
  independently), mandolin/guitar/flute instrument switching with
  per-instrument envelopes (flute stops promptly on release; mandolin/guitar
  ring through their natural decay), octave-aware jaru (glide) and octave-
  nearest note selection, gamakam/octave+/octave- read from an Arduino Nano
  33 BLE over USB serial (see `control_keys/control_keys.ino`), odukkal
  (pressure-to-pitch-bend, toggleable), attack velocity, the double bass
  drone, a live 3-band EQ, master volume, and dual I2S+headphone output. All
  of the above is controllable both via typed stdin commands and remotely
  over a WebSocket network control interface — see **[PROTOCOL.md](PROTOCOL.md)**
  for the full JSON command/state protocol (the contract for building a
  remote-control app against). Known limitation: a tanpura drone was scoped
  but is **not implemented** (no CC0/permissive-license sample could be
  sourced that was also actually downloadable — a Freesound recording was
  gated behind account login, and a Pixabay mirror of it was blocked by
  Cloudflare bot-protection from this environment's tools). Usage:
  `python3 jaladarangam.py --raga Shankarabharanam`.

### ADC2 / control-key software support (not yet implemented)

`jaladarangam.py` reads only ADC1 (CE0) — it does not open or read ADC2 (CE1)
at all. The gamakam key is stood in by the keyboard spacebar (see
`poll_gamakam_input`); there is no octave+/octave- control-key handling in the
file at all yet. ADC2 is wired at the hardware level (see the ADC2 section
above) but not yet integrated into any script's code — wiring the chip is a
prerequisite for that future software work, not a sign it's under way.

`gamaka.py`, `read_fsr_raw.py`, and `fsr_oscillator.py` also each open a single
spidev bus (ADC1/CE0 only) with no CE1/ADC2 handling. The keyboard-based
prototypes (`sliding_window_raga.py`, `gamaka_keyboard.py`,
`gamaka_keyboard_mixer.py`) stand in for control keys with keyboard input
(e.g. spacebar for gamakam, bracket keys for octave up/down) and don't touch
spidev at all.
