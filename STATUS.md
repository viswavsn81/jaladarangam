# Project status (as of 2026-09-06)

A running snapshot of where this project actually is, for picking work back
up cleanly later. Hardware/wiring specifics live in `README.md`; the network
control JSON contract lives in `PROTOCOL.md`. This file is the "what's done,
what's not, what's next" summary.

## Hardware

- **ADC1 (MCP3008, SPI CE0)**: all 8 note keys (Sa through upper Sa, CH0-CH7)
  physically wired with real FSR402 sensors and confirmed working.
- **ADC2 is gone.** The originally-planned second MCP3008 for the three
  control keys had an unresolved hardware fault (every channel - including
  one never wired to anything - read an identical fixed value regardless of
  wiring, grounding, or which physical chip/chip-select line was used). It
  has been **fully replaced** by an Arduino Nano 33 BLE over USB serial,
  reading its own three analog FSRs directly: `A0`=gamakam, `A1`=octave+,
  `A2`=octave- (firmware: `control_keys/control_keys.ino`). No ADC2/CE1
  code remains in `jaladarangam.py`.

## Software (`jaladarangam.py`)

- **Polyphony**: up to 8 notes ring independently (was strictly
  monophonic). A key's own re-pluck replaces only its own prior voice.
- **Octave-nearest note selection** on normal plucks: Ri/Ga/Ma/Pa/Da/Ni land
  in whichever octave (default, one up, or one down) is nearest the last
  note played. **Sa and upper Sa are deliberately excluded** from this -
  they already have two dedicated keys (key 1 / key 8), and applying
  nearest-pitch there too would flip the traditional Ni->Sa cadence to
  resolve upward instead of down (the leading-tone-to-tonic gap is always
  the largest "improvement" nearest-pitch could find, so no distance-based
  rule can fix the Sa-adjacent case without also breaking this one - this
  was worked through explicitly rather than guessed). The manual
  octave+/octave- keys remain the override for any other case.
- **Odukkal** (pressure-to-pitch-bend while a key is held and ringing):
  toggle with `o`+Enter (stdin) or `toggle_odukkal` (network), default OFF.
  One-euro-filtered per voice, additive on top of jaru/octave-shift state.
- **Attack velocity**: always active (not gated by the odukkal toggle) -
  press speed scales pluck loudness.
- **Per-instrument envelope**: mandolin/guitar are "plucked" (ring through
  natural decay regardless of release - unchanged, original behavior).
  Flute is "sustained" - release stops the note promptly with a short
  (50ms) click-free fade instead of playing out its full recorded length.
  True crossfaded sample looping for the sustain portion was considered
  and deliberately not implemented (see `jaladarangam.py`'s module
  docstring for why - the samples' natural sustain region has real
  vibrato/breath variation that makes a blind loop point risky).
- **Network control**: every toggle/config command (drone, instrument
  source, EQ, dual output, odukkal, volume) is a standalone function
  callable from anywhere, dispatched identically regardless of transport.
  Two transports, both running now, both documented in full in
  `PROTOCOL.md`:
  - **WiFi**: WebSocket server on port 8765.
  - **Bluetooth**: Classic SPP/RFCOMM, standard Serial Port Profile UUID,
    "Just Works" pairing (no PIN). Built on BlueZ's own D-Bus API
    (`dbus-python` + PyGObject's `GLib`), not PyBluez (confirmed
    unmaintained - see `PROTOCOL.md`'s implementation notes).
  - Both transports run persistently via a `systemd --user` service
    (`systemd/jaladarangam.service`, with lingering enabled) - survives
    reboots, no terminal session required. stdin control still works
    identically alongside both.
  - Validated end-to-end with a real Android phone: paired with no PIN,
    connected via a generic SPP terminal app ("Serial Bluetooth
    Terminal"), sent `{"cmd": "toggle_drone"}`, confirmed the drone
    turned on and a simultaneously-connected WebSocket client saw the
    same state change broadcast immediately.

## Explicitly NOT yet done

- **Tanpura drone**: scoped early on, never implemented. No CC0/permissive-
  license sample could be found that was also actually downloadable
  (a Freesound CC0 recording was gated behind account login; a Pixabay
  mirror of it was blocked by Cloudflare bot-protection from available
  tooling). No `toggle_tanpura` command exists anywhere - there's no
  feature behind it to expose.
- **The Android app itself**: not started. `PROTOCOL.md` is written as its
  complete spec (every command, exact fields, the state-push shape, both
  transports) - manual testing so far has used a generic SPP terminal app
  and a Python WebSocket script standing in for it, not a real app.
- **Jaru direction coverage**: only Sa->Ri has been extensively
  bench-tested against real hardware; other key-to-key jaru pairs and
  octave-down landings are implemented (and now exercised more, thanks to
  polyphony/octave-nearest testing) but not as thoroughly verified.
- **Attack-velocity calibration**: the counts/sec thresholds
  (`VELOCITY_MIN/MAX_COUNTS_PER_SEC`) were recalibrated once against real
  press data during testing but are still a rough fit, not a precisely
  tuned curve - worth revisiting by ear if velocity response feels off.
- **CPU headroom**: checked informally under active multi-key play
  (~20% of one core on the Pi 3, comfortable) - never stress-tested with
  literally all 8 keys held simultaneously plus drone plus dual output,
  since that requires more hands/hardware than one person has.

## Next session: start here

**Build the Android app against `PROTOCOL.md`.** This session's entire
WiFi+Bluetooth effort was specifically to enable that, both transports are
now validated end-to-end with real (if generic) clients, and the protocol
doc is written to be a complete, standalone spec for exactly this. This is
offered as a recommendation, not a decision made on the user's behalf - say
if tanpura sourcing (or something else) should actually come first.
