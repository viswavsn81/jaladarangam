# Mindfulness Instrument

A Raspberry Pi 3 project that plays an instrument sample when a sensor is triggered.
Started as a keyboard-spacebar proof of concept (evdev + pygame); the wiring below is
for the real sensor hardware: two FSR402 force sensors and a SparkFun SoftPot ribbon,
read through an MCP3008 ADC over SPI.

## Hardware

- Raspberry Pi 3 Model B
- MCP3008 8-channel 10-bit ADC (16-pin DIP, SPI interface)
- 2x FSR402 round force sensor (18mm)
- 1x SparkFun SoftPot linear ribbon (100mm, male pin connector)
- Resistors: 2x 10kΩ, 1x 100kΩ
- Breadboard + jumper wires

## Wiring

All physical pin numbers below refer to the Raspberry Pi's 40-pin GPIO header, and were
verified against the official Raspberry Pi pinout and the Microchip MCP3008 datasheet
(DS20001295E) before wiring.

### Pi -> MCP3008

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

### Sensors (voltage dividers into the MCP3008)

| Component | Leg/end | Connects to |
|---|---|---|
| FSR #1 | leg A | 3.3V rail |
| FSR #1 | leg B | MCP3008 CH0 (pin 1) **and** 10kΩ resistor -> GND |
| FSR #2 | leg A | 3.3V rail |
| FSR #2 | leg B | MCP3008 CH1 (pin 2) **and** 10kΩ resistor -> GND |
| SoftPot | end (arrow-marked side) | GND rail |
| SoftPot | end (other side) | 3.3V rail |
| SoftPot | wiper (middle pin) | MCP3008 CH2 (pin 3) **and** 100kΩ resistor -> GND |

The 10kΩ/100kΩ resistors form voltage dividers: FSR resistance drops under pressure,
so the sense-node voltage *rises* with force. The SoftPot's wiper floats when untouched,
so the 100kΩ pulldown gives a clean, defined idle reading instead of a floating value.

## Step-by-step wiring order

1. Power off / unplug the Pi before wiring anything.
2. Seat the MCP3008 across the breadboard's center gap, pin 1 (notch end) toward CH0.
3. Run the 3.3V rail and GND rail down the breadboard from the Pi's pin 1 and pin 6.
4. Wire MCP3008 VDD (16) and VREF (15) to the 3.3V rail; AGND (14) and DGND (9) to the GND rail.
5. Wire the SPI lines: Pi pin 23 -> MCP3008 CLK (13), Pi pin 19 -> DIN (11),
   Pi pin 21 -> DOUT (12), Pi pin 24 -> CS/SHDN (10).
6. Place FSR #1: one leg to the 3.3V rail, the other leg to MCP3008 CH0 (1) and to one
   leg of a 10kΩ resistor whose other leg goes to the GND rail.
7. Repeat step 6 for FSR #2 into MCP3008 CH1 (2).
8. Wire the SoftPot: arrow-marked end to GND rail, other end to 3.3V rail, wiper (middle
   pin) to MCP3008 CH2 (3) and to one leg of a 100kΩ resistor whose other leg goes to GND.
9. Double-check every connection against the table above before powering the Pi back on.
10. Once wired, enable SPI on the Pi (`sudo raspi-config nonint do_spi 0`) if not already
    enabled, then reboot before trying to read the MCP3008.

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
