#!/usr/bin/env python3
"""jaladarangam.py - the real hardware-driven instrument: 8 physical FSR
note keys on one MCP3008 (ADC1, raga-selectable positional layout, ported
from sliding_window_raga.py/gamaka_keyboard_mixer.py) plus 3 physical FSR
control keys (gamakam, octave+, octave-) read by an Arduino Nano 33 BLE
over USB serial, mandolin/guitar/flute instrument switching, the double
bass drone, the live 3-band EQ, and dual I2S+headphone output.

All 8 ADC1 keys (CH0..CH7) and all 3 Nano control keys (A0/A1/A2) are
physically wired with real FSRs - no keyboard stand-ins remain. No
vibration motors in this build (see key_press.py for that, on its own
throwaway test rig - unrelated to this instrument's hardware).

The control keys were originally planned as a second MCP3008 (ADC2) on
the same SPI0 bus as ADC1 (CE1 instead of ADC1's CE0). That chip turned
out to have an unresolved hardware fault: every channel (including one
never wired to anything) read an identical fixed value regardless of the
FSR, the pulldown, a direct ground jumper, which physical MCP3008 unit
was in the socket, or which chip-select line addressed it - conclusive
enough to rule out wiring and point at the chip itself. It was replaced
entirely with an Arduino Nano 33 BLE reading its own three analog FSRs
(A0=gamakam, A1=octave+, A2=octave-; A4/A5 avoided since they default to
this board's I2C bus) and streaming them as CSV over USB serial - see
control_keys/control_keys.ino and poll_nano_values below. No ADC2/CE1/
spidev code remains in this file.

The gamakam (jaru-trigger) key is now a real FSR (Nano A0), read
edge-triggered exactly like the ADC1 note keys (see poll_gamakam).
Octave+ / octave- (Nano A1 / A2) are also edge-triggered (debounced -
see poll_octave_keys) and shift the module-level `octave_shift`, which
every key position's pitch resolution (see resolve_position) is offset
by, clamped to +-OCTAVE_SHIFT_LIMIT.

POLYPHONY: the instrument is no longer monophonic. `voices` is a pool
of up to MAX_VOICES independently-playing voice dicts (one per
currently-ringing key position), each with its own sample position,
playback rate, and decay - all summed in audio_callback. A key's own
re-pluck replaces that same key's own prior voice (matching a real
instrument re-plucking its own string) rather than layering a second
copy of itself; a DIFFERENT key's pluck never touches another key's
voice. MAX_VOICES=8 matches the physical key count, so voice-stealing
(oldest-first - see pluck) is defense-in-depth for a future change
that might exceed that, not something normal 8-key play can trigger.
gamakam+jaru always acts on `most_recent_voice` (whichever voice was
plucked or last jaru'd most recently), matching a player having one
hand doing the glide motion regardless of how many other notes are
independently ringing.

OCTAVE-NEAREST PLUCK SELECTION: a normal pluck (not jaru) of Ri/Ga/Ma/
Pa/Da/Ni (positions 1-6) now lands in whichever octave (its own
default/structural one, one up, or one down) is nearest in pitch to
`most_recent_voice`'s pitch, via the same principle as nearest_octave_
hz - so e.g. playing upper Sa (key 8) then Ri (key 2) continues in the
upper register instead of dropping over an octave to Ri's default mid
position. Sa itself (position 0) and upper Sa (UPPER_SA_POSITION) are
deliberately EXCLUDED from this - they already have two dedicated,
unambiguous keys for their two registers, and applying nearest-pitch
there too would flip the traditional Ni->Sa cadence to resolve upward
instead of down (the leading-tone-to-tonic gap is mathematically
always the largest "improvement" nearest-pitch could find, so no
threshold can fix the Ri case without also flipping this one - see
this file's PR discussion for the worked-through math). The manual
octave+/octave- keys remain the explicit override for any case where
the automatic choice isn't the one intended.

ODUKKAL (pressure->pitch bend) and ATTACK VELOCITY: while a note key
is held and its voice is ringing, sustained pressure depth on that
SAME key bends its pitch up by 0-ODUKKAL_MAX_CENTS, smoothed via a
one-euro filter (see one_euro_filter) - same filter design as gamaka.
py's softpot smoothing, ported here for the same reason (a fixed-alpha
EMA lags fast pressure changes badly). Toggled on/off via 'o'+Enter
(default OFF); when off, pressure has zero effect on pitch. This is
purely additive on top of whatever jaru/octave-shift state a voice
already has (see audio_callback's rate composition), never a
replacement, mirroring gamaka.py's kampita-is-additive-to-jaru
design. Independent per voice, since each voice has its own filter
state and its own key's pressure feeds only its own bend.

Separately (NOT gated by the odukkal toggle - always active), the
rate of pressure rise at a fresh pluck's press-edge (dF/dt, measured
in raw ADC counts/sec) maps to attack velocity via velocity_to_params,
currently scaling amplitude only, since only one mandolin stress-level
recording exists on disk today (see mandolin_audio.STRESS_LEVEL) -
that function returns a dict specifically so a future 'layer' key can
drive real low/high-stress sample selection without restructuring any
caller.

PER-INSTRUMENT ENVELOPE: mandolin/guitar are 'plucked' - attack on
press-edge, then ring through their own natural decay regardless of
release, exactly as this file has always behaved. flute is 'sustained'
- attack the same way, but release stops the note promptly (a 50ms
fade, FLUTE_RELEASE_SECONDS, to avoid a click) instead of letting it
play out. A voice's envelope is fixed at pluck time from the actual
resolved source_used (so a flute pluck that falls back to a guitar
sample - outside flute's recorded range - correctly gets plucked
behavior, since what's actually ringing is a guitar recording). Real
sustain/looping was considered (see ENVELOPE_MODES/FLUTE_RELEASE_
SECONDS section) and deliberately not implemented: the flute samples'
RMS envelope does show a genuine ~2-2.5s quasi-steady region, but with
real breath/vibrato variation rather than a flat plateau, so a loop
point picked without per-note listening/tuning risks an audible seam -
worse than just letting each note play its natural (already fairly
long) recorded length while held.

NETWORK CONTROL: every toggle/config command (drone, instrument
source, EQ, dual output, odukkal, volume) is a standalone function
(toggle_drone, set_source, adjust_band, etc.) with no stdin-specific
logic - control_listener (stdin), run_network_server (WiFi, a
WebSocket server on NETWORK_PORT), and run_bluetooth_server (a
Bluetooth SPP/RFCOMM server, "Just Works"/no-PIN pairing) are three
different ways a command can ARRIVE, each in its own thread so none of
control_loop's real-time SPI/serial polling, the WiFi asyncio loop, or
the Bluetooth D-Bus/GLib loop can block each other. All three funnel
through the same _dispatch_command/NETWORK_COMMANDS layer and every
one triggers the exact same broadcast_state() push of the full current
state to every connected client on BOTH network transports, regardless
of which transport (or stdin) triggered the change. Full JSON protocol
(every command, its fields, the state-push shape, both transports) is
documented in PROTOCOL.md - that's the contract to build a client
against, not this file.

NOTE: an earlier revision of this file used a FIXED Sa-Ri-Ga-Ma-Pa-Da-
Ni-Sa' diatonic layout (natural-major swara values) instead of raga
selection. This revision replaces that entirely per updated
requirements - the note map is now positional and raga-driven, matching
gamaka_keyboard_mixer.py's "Mode B" fingering, not a fixed scale.

A tanpura drone layer ('t'+Enter) was scoped for this revision but is
NOT implemented: no suitable sample could be sourced within this file's
license requirement (explicitly free for any use, no attribution-only/
personal-use-only restriction) that was also actually downloadable -
Freesound had a confirmed CC0 tanpura recording but gated the download
behind account login; a Pixabay mirror of the same recording had no
login wall but is blocked by Cloudflare bot-protection from this
environment's tools. Dropped per instruction rather than substituted
with a lower-quality or license-uncertain source. Because of this, 't'
as a stdin command is unused in this file - the collision concern
raised about physical note-key input doesn't apply anyway, since this
file's note keys are FSRs read over SPI (ADC1) and its control keys are
FSRs read via the Arduino Nano over USB serial; no code in this file
reads the keyboard for performance input at all.

Provenance of each piece (this file's own PR description/conversation
has the full detail; summarized here):
  - Sample loading, single-voice variable-rate playback, ramp/portamento
    math, and the bass-boost-capable output stage: mandolin_audio.py
    (shared engine, used unchanged by every script in this project).
  - Raga corpus loading, distinct-pitch-set derivation (arohanam UNION
    avarohanam, deduplicated, sorted ascending from Sa), and the
    position<->semitone/swara math with automatic next-octave
    continuation for positions past a short raga's pattern length:
    ported from sliding_window_raga.py (this file's note_to_index/
    index_to_note/load_raga_corpus/find_raga/strip_trailing_sa/
    distinct_pitch_set/position_to_semitones/position_to_swara are
    copies of that file's functions, not imports - matching this
    project's existing convention of each script being self-contained
    apart from mandolin_audio.py; gamaka_keyboard_mixer.py made the same
    choice for the same functions).
  - Key 8 (position 7) forced to always be upper Sa regardless of the
    raga's pattern length: NEW in this file. Neither
    sliding_window_raga.py nor gamaka_keyboard_mixer.py has an 8th key -
    both let positions past the pattern length continue wrapping via the
    generic position_to_semitones formula (which for a short/pentatonic
    raga would NOT land back on Sa at position 7). See
    UPPER_SA_POSITION's resolve_position handling.
  - Jaru-target nearest-octave selection: NEW in this file (see
    nearest_octave_hz) - no prior script has octave-aware jaru. Only
    the Sa->Ri direction has been tested against real hardware; every
    other key-to-key jaru, and any case where the nearest octave is
    "down" rather than "up," remains UNTESTED.
  - Instrument switching (mandolin/guitar/flute cycling, positional
    MandolinBank, ChromaticBank nearest-note lookup, missing-note
    fallback-to-guitar policy): ported from gamaka_keyboard_mixer.py's
    resolve_note/MandolinBank/ChromaticBank essentially unchanged, just
    renamed resolve_position and extended to 8 positions (5 recorded
    mandolin positions, 3 fallback positions: 5, 6, and the fixed
    upper-Sa position 7).
  - Double bass drone (C#1/C#2, 'b'/'c'): gamaka_keyboard.py, unchanged.
  - 3-band EQ (bass/mid/treble): gamaka_keyboard_mixer.py, unchanged.
  - Dual I2S+headphone output ('s'): gamaka_keyboard_mixer.py, unchanged.
  - Control-key integration (gamakam, octave+, octave-) and the
    `octave_shift` mechanism: NEW in this revision, replacing the
    keyboard-spacebar gamakam stand-in entirely. Octave shift concept
    (a signed integer that offsets every key's resolved pitch by whole
    octaves) ported from sliding_window_raga.py's manual-octave-key
    handling; here it's driven by real FSRs instead of keyboard keys,
    and applies uniformly to all 8 ADC1 positions via resolve_position
    rather than to a positional swara pattern. Originally built against
    a second MCP3008 (ADC2); rebuilt against an Arduino Nano 33 BLE over
    USB serial after ADC2 proved to have an unresolved chip-level fault
    (see the module docstring's opening section). octave_shift is
    clamped to +-OCTAVE_SHIFT_LIMIT on every increment/decrement, and
    resolve_position's dynamically-computed rate is separately clamped
    to [RATE_MIN, RATE_MAX] as defense-in-depth - both fixes were added
    after a runaway octave_shift (from then-undebounced, then-unbounded
    octave keys) was diagnosed as the cause of a "very low pitch /
    heavy speaker vibration" bug, and both are kept here even though the
    input source changed, since the failure mode they guard against
    (an extreme target_hz collapsing playback rate toward zero) doesn't
    depend on which hardware drives octave_shift.
  - Polyphony (the `voices` pool, voice-stealing, per-voice glide/
    odukkal state), octave-nearest pluck selection (Sa/upper-Sa
    excluded - see module docstring), odukkal pressure->bend, and
    attack velocity: NEW in this revision. The single global
    `active_voice`/`glide` model is gone entirely, replaced by a list
    of independent voice dicts; jaru's cents-ramp math (ramp_cents,
    cents_between, nearest_octave_hz) is unchanged, just now reads/
    writes `most_recent_voice` and a per-voice 'glide' field instead
    of module globals. odukkal reuses gamaka.py's one-euro filter
    design (ONE_EURO_* constants/tuning) verbatim, one filter instance
    per voice rather than one shared instance, since two held keys'
    pressure must never leak into each other's bend.
  - Per-instrument envelope (plucked vs sustained), flute's release
    fade: NEW in this revision. A voice's envelope mode and release
    state ('envelope', 'releasing', 'release_start') are new per-voice
    fields alongside the polyphony fields above; the fade itself
    (audio_callback) is a plain per-frame linear gain ramp, sample-
    accurate against real elapsed time rather than block-quantized, so
    the short (50ms) duration stays smooth regardless of BLOCKSIZE
    boundaries. True crossfaded sample looping for the sustain portion
    was considered and deliberately not implemented - see module
    docstring for the reasoning (real vibrato/breath variation in the
    samples' sustain region makes a blind loop point risky).
  - Network control (run_network_server, NETWORK_COMMANDS, broadcast_
    state, get_full_state) and master volume (master_volume, set_
    volume/adjust_volume - no volume control existed before this):
    NEW in this revision. Refactored set_source out of cycle_source
    (previously one function that always advanced; now cycle_source is
    a one-line wrapper over set_source, which the network layer's
    direct instrument-select command also calls) so every command has
    exactly one implementation regardless of which transport triggered
    it. No tanpura toggle exists in the network protocol, matching the
    module docstring above - there is no tanpura feature in this file
    to expose.
  - Bluetooth SPP transport (run_bluetooth_server, _BluetoothProfile,
    _BluetoothAgent, _handle_bt_client) and the _dispatch_command
    refactor it required: NEW in this revision. _dispatch_command was
    factored out of what used to be _handle_ws_message's body so both
    the WebSocket and Bluetooth handlers call one shared implementation
    instead of two copies of the same JSON-parsing/NETWORK_COMMANDS-
    lookup/error-formatting logic - this is also what "reuse
    NETWORK_COMMANDS directly" meant in practice, not just dispatching
    through the same table but sharing the code around it too. Uses
    dbus-python + PyGObject's GLib (both already on Raspberry Pi OS) to
    talk to BlueZ's own D-Bus API, not PyBluez - see run_bluetooth_
    server's docstring for why (PyBluez is unmaintained; the classic
    sdptool-based approach doesn't work on this system's BlueZ at all).
    broadcast_state was generalized from WebSocket-only to fan out to
    both transports (_broadcast_ws_async, _broadcast_bt) - a Bluetooth
    client sees a state change made from WiFi or stdin exactly as
    promptly as a WebSocket client would, and vice versa.

Usage:
    python3 jaladarangam.py --raga Shankarabharanam
"""
import argparse
import asyncio
import collections
import json
import os
import socket
import sys
import threading
import time
import numpy as np
import soundfile as sf
import sounddevice as sd
import serial
from serial.tools import list_ports
import spidev
import mandolin_audio as ma
from mandolin_audio import SAMPLE_RATE, BLOCKSIZE

try:
    import websockets
except ImportError:
    # Network control degrades gracefully to unavailable - stdin control
    # (control_listener) still works fully either way. On Debian/Raspberry
    # Pi OS, `sudo apt install python3-websockets` provides this without
    # needing pip/venv (this system's Python is externally-managed, PEP
    # 668) - that's the path this project's Pi actually used.
    websockets = None

try:
    import dbus
    import dbus.mainloop.glib
    import dbus.service
    from gi.repository import GLib
except ImportError:
    # Bluetooth control degrades gracefully to unavailable, same as
    # websockets above - stdin and WiFi control are unaffected. PyBluez
    # (the obvious first guess) was deliberately NOT used here: it's
    # packaged for Debian/Raspberry Pi OS (`python3-bluez`) but that
    # package is literally PyBluez's last-ever upstream release (0.23,
    # ~2018) with no real maintenance since. dbus-python + PyGObject's
    # GLib (both already present on Raspberry Pi OS - no extra install
    # needed) talking to BlueZ's own D-Bus API is the current, actually-
    # maintained way to do this; the legacy sdptool/hciconfig approach
    # some older PyBluez tutorials use doesn't work on this system at
    # all (bluetoothd runs without --compat, confirmed via `sdptool
    # browse local` failing outright).
    dbus = None
    GLib = None

# --- Hardware: all 8 keys physically wired on one MCP3008 (CH0..CH7 =
# position 0..7). Positions are ALSO the MCP3008 channel numbers directly -
# no separate name/channel table needed. Add/remove entries here if a key
# is ever unwired again.
LIVE_POSITIONS = set(range(8))

CONTROL_INTERVAL = 0.02  # seconds between SPI poll rounds, same as gamaka.py
PRESS_THRESHOLD = 100    # raw ADC counts (0-1023) - validated against real
                         # Sa/Ri hardware in key_press.py. ADC1 note keys
                         # only - the control keys have their own threshold
                         # below (NANO_PRESS_THRESHOLD), since they're now
                         # read by different hardware with its own noise
                         # floor/range, not this same MCP3008.

# --- Arduino Nano 33 BLE: control keys (gamakam, octave+, octave-) --------
# Replaces the second MCP3008 (ADC2) entirely - see module docstring for
# why. A0=gamakam, A1=octave+, A2=octave- on the Nano; A4/A5 avoided since
# they default to this board's I2C bus. Firmware: control_keys/
# control_keys.ino, which streams "gamakam,octave_up,octave_down\n" once
# per ~20ms over USB serial.
NANO_VID = 0x2341
NANO_PID = 0x805A
NANO_FALLBACK_PORT = '/dev/ttyACM0'  # used only if VID/PID auto-detection
                                     # (find_nano_port) finds nothing - the
                                     # port is not assumed stable across
                                     # reboots/reconnects otherwise.
NANO_BAUD = 115200

NANO_PRESS_THRESHOLD = 100  # raw analogRead counts (0-1023 - the Nano's
                            # analogRead defaults to the same 10-bit range
                            # as the MCP3008s). Bench-tested directly
                            # against these three specific FSRs (not
                            # assumed from the note-key threshold above):
                            # idle reads 0-4, presses climb smoothly to
                            # 850-950+, so 100 leaves wide margin on both
                            # sides of this particular hardware's range.

OCTAVE_SHIFT_LIMIT = 2  # +-2 octaves - enough range to be musically useful,
                        # tight enough that a runaway octave_shift (bug,
                        # debounce failure, etc.) can't collapse resolve_
                        # position's target_hz toward zero. Clamped on every
                        # increment/decrement in poll_octave_keys, not just
                        # capped after the fact.

OCTAVE_DEBOUNCE_POLLS = 5  # consecutive above-threshold polls (~100ms at
                            # CONTROL_INTERVAL=0.02s) required before an
                            # octave+/octave- reading counts as a real press
                            # (see _debounced_press). Guards against a raw
                            # value that wobbles across NANO_PRESS_THRESHOLD
                            # (sensor noise, marginal contact) registering as
                            # several spurious edges during one physical
                            # press-and-hold - each edge permanently shifts
                            # octave_shift, unlike a note-key false retrigger
                            # (harmless re-pluck), so only the octave keys
                            # need this. Kept even though the old ADC2 chip
                            # (the original reason this was added) is gone -
                            # cheap insurance against any future sensor
                            # noise on this path, same as the clamps above.

RATE_MIN = 0.5  # -1 octave from the sample's own measured pitch
RATE_MAX = 2.0  # +1 octave - clamps resolve_position's dynamic rate
                # calculation so that even if target_hz is ever extreme
                # (octave_shift misbehaving or otherwise), playback rate
                # physically cannot collapse toward silence-via-near-zero
                # or spike to an ear-damaging pitch. Defense-in-depth on
                # top of the octave_shift clamp above, not a replacement
                # for it. Also the final clamp on the odukkal-combined
                # rate in audio_callback - see MAX_VOICES section below.

UPPER_SA_POSITION = 7  # key 8 - always upper Sa, regardless of raga pattern
                        # length (see resolve_position)

# --- Polyphony ---------------------------------------------------------
MAX_VOICES = 8  # matches the physical key count - see module docstring
                # for why this is enough (each key maps to at most one
                # voice; a same-key re-pluck replaces its own prior voice
                # rather than adding a second one). Voice-stealing in
                # pluck() below is defense-in-depth for a future change
                # that might exceed this, not something normal play can
                # trigger today.

# --- Octave-nearest pluck selection (Ri/Ga/Ma/Pa/Da/Ni only - see
# module docstring for why Sa/upper-Sa are excluded) ------------------
OCTAVE_NEAREST_EXCLUDED_POSITIONS = (0, UPPER_SA_POSITION)

# --- Odukkal (pressure -> pitch bend while a key is held) -------------
ODUKKAL_MAX_CENTS = 50.0    # max upward bend at a firm sustained press,
                            # per the "0 to about +50 cents" ask
ODUKKAL_PRESS_MAX = 900     # raw ADC counts - practical firm-press
                            # ceiling for these FSR402s; same value/
                            # rationale as gamaka.py's ADC_PRACTICAL_MAX
                            # (same sensor hardware). depth=0 right at
                            # PRESS_THRESHOLD (just barely pressed),
                            # depth=1 at this ceiling.

# One-euro filter tuning (Casiez et al. 2012) - ported verbatim from
# gamaka.py's one_euro_softpot, which fixed a measured 60-150c lag
# (spiking past 300c in fast bursts) from a fixed-alpha EMA on this same
# kind of FSR pressure signal. See one_euro_filter below.
ONE_EURO_MIN_CUTOFF = 1.0
ONE_EURO_BETA = 0.007
ONE_EURO_DCUTOFF = 1.0

# --- Attack velocity (dF/dt at press-edge -> pluck loudness) ----------
# At CONTROL_INTERVAL=0.02s (50Hz) polling, most presses complete their
# rise within a single sample, so this is really "how much pressure had
# built up by the first sample above PRESS_THRESHOLD" rather than a
# finer-grained speed measurement - still a usable hardness proxy, but
# the counts/sec numbers it produces are much larger than a naive first
# guess: live-tested against real presses, ordinary hits landed in the
# 11000-30000 c/s range (not the low thousands originally assumed), so
# these bounds reflect that. Still worth tuning further by ear.
VELOCITY_MIN_COUNTS_PER_SEC = 3000    # at/below this: softest attack
VELOCITY_MAX_COUNTS_PER_SEC = 40000   # at/above this: hardest attack
VELOCITY_MIN_AMPLITUDE = 0.5
VELOCITY_MAX_AMPLITUDE = 1.0

# --- MCP3008 ADC1 (note keys, CE0) ------------------------------------------
spi = spidev.SpiDev()
spi.open(0, 0)  # bus 0, CE0
spi.max_speed_hz = 1350000


def read_channel(dev, ch):
    cmd = [1, (8 + ch) << 4, 0]
    reply = dev.xfer2(cmd)
    return ((reply[1] & 3) << 8) | reply[2]


# --- Arduino Nano 33 BLE (control keys) -------------------------------------
def find_nano_port():
    """Auto-detects the Nano by USB VID/PID rather than assuming a fixed
    /dev/ttyACM* path, which is not guaranteed stable across reboots or
    reconnects (particularly if another USB-serial device is ever
    plugged in). Falls back to NANO_FALLBACK_PORT if no matching device
    is found, so this still does something sensible on a system where
    pyserial's device enumeration doesn't expose vid/pid (rare, but seen
    on some platforms)."""
    for port in list_ports.comports():
        if port.vid == NANO_VID and port.pid == NANO_PID:
            return port.device
    return NANO_FALLBACK_PORT


nano_serial = serial.Serial(find_nano_port(), NANO_BAUD, timeout=0)
time.sleep(2)  # let the board finish any reset/re-enumeration after the
                # port opens before trusting its output
nano_serial.reset_input_buffer()

_nano_buf = b''
_nano_last_values = (0, 0, 0)  # (gamakam_raw, octave_up_raw, octave_down_raw)


def poll_nano_values():
    """Non-blocking drain of whatever the Nano has sent since the last
    poll - the same non-blocking-drain principle used for the evdev
    keyboard stand-in this Nano replaces: never block control_loop
    waiting on serial I/O (nano_serial is opened with timeout=0, and
    .in_waiting/.read() here only ever consume bytes already buffered),
    and if several lines arrived since the last poll, only the newest
    complete one matters - older backlog is discarded, not queued or
    processed one-by-one. Returns the latest known (gamakam_raw,
    octave_up_raw, octave_down_raw), carrying forward the previous
    values when no new complete line has arrived yet this poll (a quiet
    poll is NOT treated as a release - see poll_gamakam/poll_octave_keys,
    which only act on values this function returns)."""
    global _nano_buf, _nano_last_values
    n = nano_serial.in_waiting
    if n:
        _nano_buf += nano_serial.read(n)
    if b'\n' in _nano_buf:
        *complete_lines, _nano_buf = _nano_buf.split(b'\n')
        for line in complete_lines:
            parts = line.decode(errors='ignore').strip().split(',')
            if len(parts) == 3:
                try:
                    _nano_last_values = tuple(int(p) for p in parts)
                except ValueError:
                    pass
    return _nano_last_values


# --- Raga corpus + positional mapping (ported from sliding_window_raga.py,
# copied not imported - see module docstring) ------------------------------
RAGA_CORPUS_PATH = f'{ma.BASE_DIR}/ragas.json'
CHROMATIC = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
PATTERN_KEY_COUNT = 7  # positions 0-6 come from the raga pattern; position
                        # 7 (UPPER_SA_POSITION) is always upper Sa


def note_to_index(note):
    letter = note[:-1]
    octave = int(note[-1])
    return octave * 12 + CHROMATIC.index(letter)


def index_to_note(idx):
    octave, pc = divmod(idx, 12)
    return f'{CHROMATIC[pc]}{octave}'


def index_to_hz(idx):
    return 440.0 * 2 ** ((idx - note_to_index('A4')) / 12)


def parse_note(s):
    s = s.strip()
    if len(s) == 3 and s[1].lower() == 'b':
        return s[0].upper() + 'b' + s[2]
    return s[0].upper() + s[1]


def load_raga_corpus(path):
    with open(path) as f:
        data = json.load(f)
    return data['_meta']['swara_semitones'], {r['name'].lower(): r for r in data['ragas']}


def find_raga(ragas_by_name, name):
    key = name.lower()
    if key in ragas_by_name:
        return ragas_by_name[key]
    for raga in ragas_by_name.values():
        if key in [a.lower() for a in raga.get('aliases', [])]:
            return raga
    available = ', '.join(sorted(r['name'] for r in ragas_by_name.values()))
    print(f"Error: raga {name!r} not found in corpus.\nAvailable: {available}", file=sys.stderr)
    sys.exit(1)


def strip_trailing_sa(seq):
    return seq[:-1] if seq[-1] == seq[0] else seq


def distinct_pitch_set(raga, swara_semitones):
    aro = set(strip_trailing_sa(raga['arohanam']))
    ava = set(strip_trailing_sa(raga['avarohanam']))
    return sorted(aro | ava, key=lambda s: swara_semitones[s])


def position_to_semitones(pos, pattern, swara_semitones):
    octave, degree = divmod(pos, len(pattern))
    return octave * 12 + swara_semitones[pattern[degree]]


def position_to_swara(pos, pattern):
    _, degree = divmod(pos, len(pattern))
    return pattern[degree]


# --- Sample sources (ported from gamaka_keyboard_mixer.py) ----------------
SOURCES = ('mandolin', 'guitar', 'flute')
SOURCE_DEFAULT_SA = {
    'mandolin': 'Db4',  # = C#4, the mandolin recordings' own native tonic
    'guitar': 'A3',
    'flute': 'C4',
}
MANDOLIN_POSITION_NOTES = ['sa', 'ri', 'ga', 'ma', 'pa']  # key positions 0-4;
                                                            # 5, 6, and the
                                                            # fixed upper-Sa
                                                            # position 7 have
                                                            # no mandolin file

# --- Per-instrument envelope mode --------------------------------------
# 'plucked' (mandolin, guitar): a real plucked string can't be silenced
# by releasing a finger - attack on press-edge, then play through the
# recording's own natural decay regardless of release. Unchanged
# behavior, exactly as this file has always worked.
# 'sustained' (flute): a wind instrument only sounds while actively
# blown/held - attack on press-edge same as plucked, but release stops
# the note promptly (short fade, see FLUTE_RELEASE_SECONDS) rather than
# letting it play out. A voice's envelope is fixed at pluck time (see
# pluck) from the ACTUAL resolved source_used, not the nominal
# sample_source - if the flute source falls back to a guitar sample
# (outside flute's recorded range), what's actually ringing is a guitar
# pluck recording, so it correctly gets plucked-mode behavior, not a
# fade cutting off a plucked sample's own natural decay. Switching
# sample_source later never retroactively changes an already-ringing
# voice's envelope.

FLUTE_RELEASE_SECONDS = 0.05  # 50ms fade-out on release - within the
                              # requested 30-80ms range, short enough to
                              # feel prompt, long enough to avoid an
                              # audible click/pop from a hard cut. Real-
                              # time-based (sample-accurate per-block
                              # linspace in audio_callback), independent
                              # per voice.

# Sustain (hold) behavior: the recorded flute samples do have a genuine
# quasi-steady-state region after their attack (checked directly - RMS
# envelope stays in a natural ~0.03-0.10 range from about 0.1s to
# 2.0-2.5s before decaying to near-silence), but that region has real
# breath/vibrato variation rather than a flat plateau, so a loop point
# picked without per-note manual tuning/listening risks an audible seam
# - exactly the artifact a naive auto-loop would introduce. Since each
# note's usable pre-decay window (~2-2.5s) already covers most realistic
# holds, and true crossfaded looping needs per-sample-file judgment that
# isn't safe to automate blind, this revision uses the simpler fallback:
# a held note just plays its natural recorded length (never cut short
# while held - already true of every envelope mode, since nothing in
# this file cuts a voice on elapsed hold time). The part that must not
# be skipped - prompt, click-free release - gets the real engineering
# effort instead (see FLUTE_RELEASE_SECONDS and audio_callback).


class ChromaticBank:
    """Wide, densely-chromatic sample set (guitar_placeholder,
    flute_placeholder) - nearest-available-note lookup, played at rate=1.0.
    Ported unchanged from gamaka_keyboard_mixer.py's ChromaticBank (itself
    ported from sliding_window_raga.py's SampleBank)."""
    def __init__(self, sample_dir, suffix):
        self.dir = sample_dir
        self.suffix = suffix
        self.available_indices = set()
        for idx in range(0, 120):
            name = index_to_note(idx).lower()
            if os.path.exists(os.path.join(self.dir, f'{name}{self.suffix}.wav')):
                self.available_indices.add(idx)
        self._cache = {}

    def nearest_index(self, target_idx):
        if target_idx in self.available_indices:
            return target_idx
        return min(self.available_indices, key=lambda i: abs(i - target_idx))

    def get(self, target_idx):
        idx = self.nearest_index(target_idx)
        if idx not in self._cache:
            name = index_to_note(idx).lower()
            path = os.path.join(self.dir, f'{name}{self.suffix}.wav')
            audio, sr = sf.read(path, dtype='float32', always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if sr != SAMPLE_RATE:
                audio = ma.linear_resample(audio, sr / SAMPLE_RATE)
            self._cache[idx] = audio
        return self._cache[idx], idx, (idx == target_idx)


class MandolinBank:
    """The 5 recorded mandolin swaras, reused as generic voices for key-
    POSITIONS 0-4 (not swara identities - the raga corpus uses variant
    swara names like R1/R2/G2/G3 that the mandolin's plain files don't
    distinguish anyway). Ported unchanged from gamaka_keyboard_mixer.py's
    MandolinBank."""
    def __init__(self):
        self.by_position = {}
        for i, note in enumerate(MANDOLIN_POSITION_NOTES):
            samples = ma.load_sample(note, label=note)
            pitch_hz = ma.detect_pitch(samples)
            self.by_position[i] = (samples, pitch_hz)

    def get(self, position):
        return self.by_position.get(position)


def resolve_position(position, reference_hz=None):
    """Returns (samples, rate, target_hz, source_used, note_label, swara)
    for the given key position under the current raga/tonic/source/
    octave_shift. Position UPPER_SA_POSITION (7) is a hardcoded override -
    always Sa at +12 semitones from sa_idx - regardless of what the generic
    pattern-continuation formula would otherwise produce for a short raga
    (see module docstring). Positions 0-6 use position_to_semitones/
    position_to_swara verbatim (their own next-octave continuation for
    raga patterns shorter than 7 is untouched, reused as-is). octave_shift
    (Nano octave+/octave- keys) is applied uniformly to every position
    here, so the whole instrument's active octave moves together.

    reference_hz, when given, additionally nudges the result a whole
    octave up or down - whichever lands nearest reference_hz - for any
    position NOT in OCTAVE_NEAREST_EXCLUDED_POSITIONS (Sa and upper Sa
    are excluded; see module docstring for why). Only pluck() passes
    reference_hz (the most recently sounded voice's pitch); print_mapping
    and start_jaru's own resolve_position call both omit it, so they see
    the plain structural/default-octave mapping. This never changes
    which swara/semitone-within-octave is meant, only which octave.

    The mandolin path's dynamically-computed rate is clamped to [RATE_MIN,
    RATE_MAX] as defense-in-depth (see those constants) - the guitar/flute
    fallback paths always use a literal rate of 1.0, which is already
    within that range."""
    if position == UPPER_SA_POSITION:
        swara = 'S'
        semitones = 12
    else:
        swara = position_to_swara(position, pattern)
        semitones = position_to_semitones(position, pattern, swara_semitones)
    target_idx = sa_idx + semitones + 12 * octave_shift

    if reference_hz is not None and position not in OCTAVE_NEAREST_EXCLUDED_POSITIONS:
        candidate_indices = (target_idx - 12, target_idx, target_idx + 12)
        target_idx = min(candidate_indices,
                          key=lambda i: abs(ma.cents_between(reference_hz, index_to_hz(i))))

    target_hz = index_to_hz(target_idx)

    if sample_source == 'mandolin':
        entry = mandolin_bank.get(position)
        if entry is not None:
            samples, measured_hz = entry
            rate = max(RATE_MIN, min(RATE_MAX, target_hz / measured_hz))
            return samples, rate, target_hz, 'mandolin', f'{MANDOLIN_POSITION_NOTES[position]}_mid (corrected)', swara
        samples, idx, exact = guitar_bank.get(target_idx)
        label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest)'
        return samples, 1.0, target_hz, f'guitar (fallback: mandolin has no key {position + 1})', label, swara

    if sample_source == 'flute':
        if target_idx in flute_bank.available_indices:
            samples, idx, exact = flute_bank.get(target_idx)
            return samples, 1.0, target_hz, 'flute', index_to_note(idx), swara
        samples, idx, exact = guitar_bank.get(target_idx)
        label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest)'
        return samples, 1.0, target_hz, "guitar (fallback: outside flute's G3-G6 range)", label, swara

    samples, idx, exact = guitar_bank.get(target_idx)
    label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest, target was {index_to_note(target_idx)})'
    return samples, 1.0, target_hz, 'guitar', label, swara


def nearest_octave_hz(base_hz, current_hz):
    """Of the target's own octave, one octave up, and one octave down,
    return whichever is closest in cents to current_hz. A real jaru is a
    small continuous pitch movement, so it should never snap a whole
    octave away from wherever the voice is currently ringing just because
    that's the target key's own mapped octave. Considers BOTH directions
    (up and down) - a deliberate generalization beyond the task's single
    worked example (upper Sa -> Ri lands on upper Ri), since the symmetric
    case (e.g. Sa -> Ni should land on the Ni just below Sa, not the one
    almost an octave above) needs 'down' too."""
    candidates = (base_hz, base_hz * 2.0, base_hz / 2.0)
    return min(candidates, key=lambda hz: abs(ma.cents_between(current_hz, hz)))


def find_voice(voices, position):
    """The (at most one) currently-active voice mapped to this key
    position, or None. Linear scan over at most MAX_VOICES=8 entries -
    not worth a dict-by-position structure for a pool this small."""
    for v in voices:
        if v['position'] == position:
            return v
    return None


def _one_euro_alpha(cutoff_hz, dt):
    tau = 1.0 / (2 * np.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)


def one_euro_filter(state, raw, dt):
    """Velocity-aware low-pass filter (Casiez et al. 2012, "1 euro
    filter") - smooths hard when the signal is still, relaxes toward the
    raw value as it moves faster, avoiding the lag a fixed-alpha EMA has
    no way to avoid without sacrificing one for the other. Ported from
    gamaka.py's one_euro_softpot (same ONE_EURO_* tuning), which fixed a
    measured 60-150c lag (spiking past 300c during fast bursts) from a
    fixed alpha=0.2 EMA on this same kind of FSR pressure signal - used
    here for odukkal's pressure->bend smoothing for the same reason.
    `state` is a per-voice dict {'initialized','value','prev_raw','dx'}
    the caller holds (one per voice - see pluck's 'odukkal_filter' field)
    so every voice's filter is fully independent of every other's."""
    if not state['initialized']:
        state['initialized'] = True
        state['value'] = float(raw)
        state['prev_raw'] = float(raw)
        state['dx'] = 0.0
        return state['value']
    dx = (raw - state['prev_raw']) / dt
    dx_alpha = _one_euro_alpha(ONE_EURO_DCUTOFF, dt)
    state['dx'] = dx_alpha * dx + (1 - dx_alpha) * state['dx']
    cutoff = ONE_EURO_MIN_CUTOFF + ONE_EURO_BETA * abs(state['dx'])
    alpha = _one_euro_alpha(cutoff, dt)
    state['value'] = alpha * raw + (1 - alpha) * state['value']
    state['prev_raw'] = raw
    return state['value']


def update_odukkal(voice, raw, dt):
    """Updates voice['odukkal_cents'] from this voice's own key's live
    raw pressure, one-euro-smoothed (see one_euro_filter). depth 0 right
    at PRESS_THRESHOLD (just barely pressed) rising to 1 at
    ODUKKAL_PRESS_MAX (a firm press), mapped to 0..ODUKKAL_MAX_CENTS.
    Only ever called for a position's own voice with its own raw reading
    (see control_loop) - never mixes one key's pressure into another
    key's bend."""
    smoothed = one_euro_filter(voice['odukkal_filter'], raw, dt)
    depth = (smoothed - PRESS_THRESHOLD) / (ODUKKAL_PRESS_MAX - PRESS_THRESHOLD)
    depth = max(0.0, min(1.0, depth))
    voice['odukkal_cents'] = depth * ODUKKAL_MAX_CENTS


def velocity_to_params(velocity_counts_per_sec):
    """Maps attack velocity (dF/dt in raw ADC counts/sec, measured at a
    fresh pluck's press-edge - see control_loop) to playback parameters.
    Only 'mid' stress-level mandolin samples exist on disk today (see
    mandolin_audio.STRESS_LEVEL), so velocity can only scale amplitude
    for now - but this returns a dict (not a bare float) specifically so
    that once low/high stress recordings exist, 'layer' can drive an
    actual sample-bank lookup instead, without restructuring callers."""
    level = (velocity_counts_per_sec - VELOCITY_MIN_COUNTS_PER_SEC) / (
        VELOCITY_MAX_COUNTS_PER_SEC - VELOCITY_MIN_COUNTS_PER_SEC)
    level = max(0.0, min(1.0, level))
    amplitude = VELOCITY_MIN_AMPLITUDE + level * (VELOCITY_MAX_AMPLITUDE - VELOCITY_MIN_AMPLITUDE)
    return {'amplitude': amplitude, 'layer': ma.STRESS_LEVEL}


# --- Double bass drone (gamaka_keyboard.py, unchanged) ---------------------
DRONE_DIR = f'{ma.BASE_DIR}/samples/doublebass'
DRONE_OCTAVES = (1, 2)
DRONE_MIX_LEVEL = 0.07  # see gamaka_keyboard.py for how this was derived


def load_drone_samples():
    samples = {}
    for octave in DRONE_OCTAVES:
        path = f'{DRONE_DIR}/csharp{octave}_mf.wav'
        audio, sr = sf.read(path, dtype='float32', always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != SAMPLE_RATE:
            audio = ma.linear_resample(audio, sr / SAMPLE_RATE)
        samples[octave] = audio
    return samples


# --- 3-band EQ (gamaka_keyboard_mixer.py, unchanged) -----------------------
BASS_FREQ_HZ = 200.0
MID_FREQ_HZ = 1000.0
MID_Q = 0.7
TREBLE_FREQ_HZ = 4000.0
EQ_STEP_DB = 2.0

RAW_BUFFER_SECONDS = 1.5
RAW_BUFFER_LEN = int(SAMPLE_RATE * RAW_BUFFER_SECONDS)
raw_ring = np.zeros(RAW_BUFFER_LEN, dtype=np.float32)
raw_ring_pos = 0

# --- Master volume - NEW: no volume control existed before this revision.
MASTER_VOLUME_MIN = 0.0
MASTER_VOLUME_MAX = 1.0
MASTER_VOLUME_STEP = 0.1  # matches the EQ's step-per-command convention
master_volume = 1.0       # default: unchanged from today's implicit 100%


def build_band(name, gain_db):
    if gain_db == 0.0:
        return None
    if name == 'bass':
        return ma.LowShelf(SAMPLE_RATE, BASS_FREQ_HZ, gain_db)
    if name == 'mid':
        return ma.PeakingEQ(SAMPLE_RATE, MID_FREQ_HZ, gain_db, q=MID_Q)
    return ma.HighShelf(SAMPLE_RATE, TREBLE_FREQ_HZ, gain_db)


def apply_chain_unclipped(mix, bass_f, mid_f, treble_f):
    for f in (bass_f, mid_f, treble_f):
        if f is not None:
            mix = f.process(mix)
    return mix * ma.EXISTING_GAIN * master_volume


def predicted_peak(candidate_gains):
    buf = raw_ring.copy()
    bass_f = build_band('bass', candidate_gains['bass'])
    mid_f = build_band('mid', candidate_gains['mid'])
    treble_f = build_band('treble', candidate_gains['treble'])
    out = apply_chain_unclipped(buf, bass_f, mid_f, treble_f)
    return float(np.max(np.abs(out)))


def adjust_band(name, steps):
    """steps is a signed integer number of EQ_STEP_DB increments (not raw
    dB) - matches the granularity of the physical b+/b-/m+/m-/t+/t-
    stdin commands (each one step), while allowing a network caller to
    jump multiple steps in one call (e.g. steps=2 for a slider-driven
    Android UI). See PROTOCOL.md for the exact network contract."""
    global eq_bass, eq_mid, eq_treble
    candidate = dict(band_gains)
    candidate[name] = band_gains[name] + steps * EQ_STEP_DB
    peak = predicted_peak(candidate)
    if peak > 1.0:
        over_db = 20 * np.log10(peak)
        print(f"[EQ] CEILING REACHED - {name}={candidate[name]:+.0f}dB would peak at "
              f"{over_db:+.1f}dBFS (over 0dBFS). Not applied. Current: "
              f"bass={band_gains['bass']:+.0f}dB mid={band_gains['mid']:+.0f}dB "
              f"treble={band_gains['treble']:+.0f}dB", flush=True)
        return
    band_gains[name] = candidate[name]
    if name == 'bass':
        eq_bass = build_band('bass', band_gains['bass'])
    elif name == 'mid':
        eq_mid = build_band('mid', band_gains['mid'])
    else:
        eq_treble = build_band('treble', band_gains['treble'])
    peak_db = 20 * np.log10(peak) if peak > 1e-9 else float('-inf')
    headroom_db = 0.0 - peak_db
    print(f"[EQ] bass={band_gains['bass']:+.0f}dB mid={band_gains['mid']:+.0f}dB "
          f"treble={band_gains['treble']:+.0f}dB  peak={peak_db:+.1f}dBFS  "
          f"headroom={headroom_db:.1f}dB", flush=True)
    broadcast_state()


def set_volume(value):
    global master_volume
    # round() clears float binary-representation noise (e.g. repeated
    # +-MASTER_VOLUME_STEP adjustments landing on 0.49999999999999994
    # instead of 0.5) before it reaches the JSON state push.
    master_volume = round(max(MASTER_VOLUME_MIN, min(MASTER_VOLUME_MAX, float(value))), 3)
    print(f"[volume] {master_volume:.2f}", flush=True)
    broadcast_state()


def adjust_volume(steps):
    set_volume(master_volume + steps * MASTER_VOLUME_STEP)


EQ_COMMANDS = {
    'b+': ('bass', +1), 'b-': ('bass', -1),
    'm+': ('mid', +1), 'm-': ('mid', -1),
    't+': ('treble', +1), 't-': ('treble', -1),
}
VOLUME_COMMANDS = {'v+': +1, 'v-': -1}

# --- Dual output (gamaka_keyboard_mixer.py, unchanged) ---------------------
HEADPHONE_DEVICE = "bcm2835 Headphones"
HEADPHONE_HANDOFF_MAXLEN = 8

dual_output_enabled = False
headphone_stream = None
headphone_handoff = collections.deque(maxlen=HEADPHONE_HANDOFF_MAXLEN)


def headphone_callback(outdata, frames, time_info, status):
    if headphone_handoff:
        block = headphone_handoff.popleft()
    else:
        block = np.zeros(frames, dtype=np.float32)
    if len(block) < frames:
        block = np.pad(block, (0, frames - len(block)))
    elif len(block) > frames:
        block = block[:frames]
    outdata[:, 0] = block


def toggle_dual_output():
    global dual_output_enabled, headphone_stream
    if not dual_output_enabled:
        headphone_handoff.clear()
        headphone_stream = sd.OutputStream(
            samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1, dtype='float32',
            device=HEADPHONE_DEVICE, callback=headphone_callback)
        headphone_stream.start()
        dual_output_enabled = True
        print("[output] I2S + headphone jack", flush=True)
    else:
        dual_output_enabled = False
        headphone_stream.stop()
        headphone_stream.close()
        headphone_stream = None
        print("[output] I2S only", flush=True)
    broadcast_state()


# --- Playback state ---------------------------------------------------------
voices = []  # pool of independently-ringing voice dicts, at most MAX_VOICES;
             # each has 'position','samples','pos','jaru_rate','rate','active',
             # 'pitch_hz','amplitude','note','glide','odukkal_cents',
             # 'odukkal_filter','attack_time' - see pluck()
most_recent_voice = None  # whichever voice pluck()/start_jaru() touched last;
                          # gamakam+jaru always acts on this one, regardless
                          # of how many other voices are independently ringing
odukkal_enabled = False  # 'o'+Enter toggle; default OFF (see toggle_odukkal)
drone_octave = None
drone_voice = None
sample_source = 'mandolin'
sa_explicit = False
sa_note = None
sa_idx = None
pattern = None
swara_semitones = None
raga = None
mandolin_bank = None
guitar_bank = None
flute_bank = None
band_gains = {'bass': 0.0, 'mid': 0.0, 'treble': 0.0}
eq_bass = None
eq_mid = None
eq_treble = None
gamakam_held = False
octave_shift = 0  # signed integer, shifted +-1 per octave+/octave- press (Nano)


def audio_callback(outdata, frames, time_info, status):
    global raw_ring_pos
    mix = np.zeros(frames, dtype=np.float32)
    now = time.monotonic()
    for v in voices:
        if not v['active']:
            continue
        g = v['glide']
        if g is not None:
            start_cents, target_cents, start_t = g
            cents, done = ma.ramp_cents(start_cents, target_cents, ma.JARU_GLIDE_SECONDS,
                                         now - start_t)
            v['jaru_rate'] = 2 ** (cents / 1200)
            if done:
                v['glide'] = None
        # odukkal_cents is additive on top of jaru_rate, never a replacement
        # (same principle as gamaka.py's kampita-on-top-of-jaru) - combined
        # rate is clamped here as the final defense-in-depth, same as the
        # structural rate already was in resolve_position.
        combined_rate = v['jaru_rate'] * (2 ** (v['odukkal_cents'] / 1200))
        v['rate'] = max(RATE_MIN, min(RATE_MAX, combined_rate))
        out = ma.advance_voice(v, frames)
        if v['releasing']:
            # Sustained-mode (flute) release fade only - plucked voices
            # (mandolin/guitar) never set 'releasing', so this never runs
            # for them, matching "unchanged" plucked behavior exactly.
            # Sample-accurate (per-frame, not per-block) linear ramp so
            # the ~50ms fade is smooth regardless of block boundaries,
            # and fully independent per voice (each voice has its own
            # 'release_start').
            elapsed_start = now - v['release_start']
            elapsed_end = elapsed_start + len(out) / SAMPLE_RATE
            frac_start = min(1.0, max(0.0, elapsed_start / FLUTE_RELEASE_SECONDS))
            frac_end = min(1.0, max(0.0, elapsed_end / FLUTE_RELEASE_SECONDS))
            fade = np.linspace(1.0 - frac_start, 1.0 - frac_end, len(out), dtype=np.float32)
            out = out * fade
            if frac_end >= 1.0:
                v['active'] = False  # fade complete - this voice is done
        mix[:len(out)] += out * v['amplitude']
    dv = drone_voice
    if dv is not None:
        mix += ma.advance_voice_loop(dv, frames) * DRONE_MIX_LEVEL

    n = len(mix)
    end = raw_ring_pos + n
    if end <= RAW_BUFFER_LEN:
        raw_ring[raw_ring_pos:end] = mix
    else:
        first = RAW_BUFFER_LEN - raw_ring_pos
        raw_ring[raw_ring_pos:] = mix[:first]
        raw_ring[:end - RAW_BUFFER_LEN] = mix[first:]
    raw_ring_pos = end % RAW_BUFFER_LEN

    mix = apply_chain_unclipped(mix, eq_bass, eq_mid, eq_treble)
    np.clip(mix, -1.0, 1.0, out=mix)
    outdata[:, 0] = mix
    if dual_output_enabled:
        headphone_handoff.append(mix)


def pluck(position, velocity):
    """Creates and rings a new voice for this key position. If this same
    position already has a ringing voice, that voice is replaced (a
    real instrument re-plucking its own string cuts its own prior ring
    short) - a DIFFERENT position's voice is never touched. If the pool
    is full of MAX_VOICES *different* keys, the oldest voice is stolen
    (see module docstring - not reachable in normal 8-key play, since
    MAX_VOICES equals the key count and each key holds at most one
    voice). velocity (raw ADC counts/sec, measured at the press-edge -
    see control_loop) sets this voice's amplitude via velocity_to_params,
    independent of the odukkal toggle (attack velocity is always live)."""
    global most_recent_voice
    reference_hz = most_recent_voice['pitch_hz'] if most_recent_voice is not None else None
    samples, rate, target_hz, source_used, note_label, swara = resolve_position(position, reference_hz)
    params = velocity_to_params(velocity)
    envelope = 'sustained' if source_used == 'flute' else 'plucked'
    new_voice = {
        'position': position, 'samples': samples, 'pos': 0.0,
        'jaru_rate': rate, 'rate': rate, 'active': True, 'pitch_hz': target_hz,
        'amplitude': params['amplitude'], 'note': f'key{position + 1}({swara})',
        'glide': None, 'odukkal_cents': 0.0,
        'odukkal_filter': {'initialized': False, 'value': 0.0, 'prev_raw': 0.0, 'dx': 0.0},
        'attack_time': time.monotonic(),
        'envelope': envelope, 'releasing': False, 'release_start': None,
    }
    existing = find_voice(voices, position)
    if existing is not None:
        voices.remove(existing)
    elif len(voices) >= MAX_VOICES:
        oldest = min(voices, key=lambda v: v['attack_time'])
        voices.remove(oldest)
        print(f"[voice-steal] pool full ({MAX_VOICES}), dropped {oldest['note']} "
              f"for {new_voice['note']}", flush=True)
    voices.append(new_voice)
    most_recent_voice = new_voice
    print(f"PLUCK -> {new_voice['note']} [{source_used}: {note_label}] "
          f"({target_hz:.1f} Hz, amp={params['amplitude']:.2f}, "
          f"velocity={velocity:.0f}c/s)", flush=True)


def start_jaru(position):
    """Glides most_recent_voice toward the given key's pitch (nearest
    octave to that voice's current pitch - see nearest_octave_hz) -
    always the most recently plucked/jaru'd voice, regardless of how
    many other voices are independently ringing (one hand does the
    glide motion; other held notes are unaffected)."""
    v = most_recent_voice
    _, _, base_hz, source_used, note_label, swara = resolve_position(position)
    target_hz = nearest_octave_hz(base_hz, v['pitch_hz'])
    if target_hz == base_hz:
        octave_note = 'same octave'
    elif target_hz > base_hz:
        octave_note = 'octave up'
    else:
        octave_note = 'octave down'
    target_cents = ma.cents_between(v['pitch_hz'], target_hz)
    current_cents = 1200.0 * np.log2(v['jaru_rate'])
    v['glide'] = (current_cents, target_cents, time.monotonic())
    print(f"JARU -> {v['note']} sliding to key{position + 1}({swara}) ({octave_note}, "
          f"target {target_hz:.1f}Hz, {target_cents:+.1f}c over "
          f"{ma.JARU_GLIDE_SECONDS * 1000:.0f}ms)", flush=True)


def toggle_drone():
    global drone_octave, drone_voice
    if drone_octave is None:
        drone_octave = DRONE_OCTAVES[0]
    else:
        i = DRONE_OCTAVES.index(drone_octave)
        drone_octave = DRONE_OCTAVES[(i + 1) % len(DRONE_OCTAVES)]
    drone_voice = {'samples': DRONE_SAMPLES[drone_octave], 'pos': 0.0, 'rate': 1.0}
    print(f"[drone] C#{drone_octave}", flush=True)
    broadcast_state()


def stop_drone():
    global drone_octave, drone_voice
    drone_octave = None
    drone_voice = None
    print("[drone] off", flush=True)
    broadcast_state()


def toggle_odukkal():
    global odukkal_enabled
    odukkal_enabled = not odukkal_enabled
    print(f"[odukkal] {'ON' if odukkal_enabled else 'OFF'}", flush=True)
    broadcast_state()


def print_mapping():
    print(f"  mapping [raga={raga['name']}] [source={sample_source}] "
          f"[Sa={sa_note}={index_to_hz(sa_idx):.1f}Hz] [octave={octave_shift:+d}]:", flush=True)
    for position in range(8):
        live = 'LIVE' if position in LIVE_POSITIONS else 'not wired yet'
        samples, rate, target_hz, source_used, note_label, swara = resolve_position(position)
        print(f"    CH{position}=key{position + 1}({swara:<3}) ({live:13s}): "
              f"{target_hz:7.1f}Hz  [{source_used}: {note_label}]", flush=True)


def set_source(name):
    """Directly selects sample_source - unlike cycle_source (the stdin
    'i' command, which only ever advances to the next one), this lets a
    caller pick any instrument directly (used by the network
    'set_instrument' command, since a phone app has a picker rather
    than a single 'next' button). cycle_source is now just a thin
    wrapper over this, so both paths share the exact same Sa-reset/
    print/broadcast behavior."""
    global sample_source, sa_note, sa_idx
    if name not in SOURCES:
        raise ValueError(f"invalid instrument {name!r}, must be one of {SOURCES}")
    sample_source = name
    if not sa_explicit:
        sa_note = SOURCE_DEFAULT_SA[sample_source]
        sa_idx = note_to_index(sa_note)
    print(f"[source] {sample_source}" +
          ("" if sa_explicit else f"  (Sa auto-reset to {sa_note})"), flush=True)
    print_mapping()
    broadcast_state()


def cycle_source():
    i = SOURCES.index(sample_source)
    set_source(SOURCES[(i + 1) % len(SOURCES)])


def control_listener():
    """Reads lines from stdin: 'b'/'c' for the drone, 'i' for the sample
    source cycle, 's' for dual output, 'o' for the odukkal toggle,
    'b+'/'b-'/'m+'/'m-'/'t+'/'t-' for the live EQ, 'v+'/'v-' for volume -
    typed + Enter, same convention/commands as gamaka_keyboard_mixer.py.
    Note 't+'/'t-' (treble EQ) are two-character commands, distinct from
    a bare 't' - there is no bare-'t' command in this file (tanpura was
    scoped but dropped, see module docstring), so there's no actual
    collision to resolve; likewise 'o' and 'v+'/'v-' collide with
    nothing already bound here. Even if there were a collision, this
    channel (typed + Enter on stdin) is already fully separate from
    note-key input, which in this file comes from FSRs over SPI, not
    the keyboard at all. Runs as a daemon thread so a non-interactive
    stdin (EOF) just ends it quietly.

    This function is now a thin dispatcher only - every command it
    handles is a plain, standalone function (toggle_drone, adjust_band,
    etc.) with no stdin-specific logic in it, and each one calls
    broadcast_state() itself. run_network_server's WebSocket layer
    calls the exact same functions through NETWORK_COMMANDS, so stdin
    and network commands are indistinguishable once they reach this
    layer - a future Bluetooth transport (see run_network_server's
    docstring) would plug in the same way a third time."""
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd == 'b':
            toggle_drone()
        elif cmd == 'c':
            stop_drone()
        elif cmd == 's':
            toggle_dual_output()
        elif cmd == 'i':
            cycle_source()
        elif cmd == 'o':
            toggle_odukkal()
        elif cmd in EQ_COMMANDS:
            band, steps = EQ_COMMANDS[cmd]
            adjust_band(band, steps)
        elif cmd in VOLUME_COMMANDS:
            adjust_volume(VOLUME_COMMANDS[cmd])


# --- Network control (WiFi/WebSocket and Bluetooth SPP) ---------------------
# Full JSON protocol documented in PROTOCOL.md - that's the contract an
# Android (or any other) client is built against, not this file's
# comments. Every command here calls the exact same standalone functions
# stdin calls (toggle_drone, adjust_band, set_source, ...) - this module
# never has two implementations of what a command DOES, only different
# ways a command can ARRIVE (typed + Enter on stdin, {"cmd": ...} JSON
# over a WebSocket, or the identical JSON newline-terminated over a
# Bluetooth SPP/RFCOMM connection - see run_bluetooth_server). All three
# funnel through _dispatch_command/NETWORK_COMMANDS, and every one of
# them reaches broadcast_state(), which pushes to every connected client
# on BOTH network transports regardless of which one triggered the change.
NETWORK_HOST = '0.0.0.0'   # listen on all interfaces, not just localhost,
                           # so the LAN IP (check with `hostname -I` on
                           # the Pi - not hardcoded/assumed stable here,
                           # same reasoning as find_nano_port) is reachable
NETWORK_PORT = 8765        # websockets' own conventional example port;
                           # confirmed free on this Pi before choosing it

_ws_clients = set()  # currently-connected websocket connections
_ws_loop = None      # the asyncio event loop run_network_server is
                     # running on, set once at startup - broadcast_state()
                     # (called from ANY thread: stdin, control_loop, or
                     # either network thread) uses this to safely hand
                     # work to that loop via run_coroutine_threadsafe

_bt_clients = set()             # currently-connected Bluetooth RFCOMM sockets
_bt_clients_lock = threading.Lock()  # RFCOMM sockets are plain blocking
                                      # sockets handled by ordinary threads,
                                      # not asyncio, so - unlike _ws_clients,
                                      # which is only ever touched from the
                                      # single asyncio-loop thread - this
                                      # set can have real concurrent writers
                                      # (each connected client's own reader
                                      # thread) and needs its own lock


def get_full_state():
    """The single source of truth for 'what does the instrument look
    like right now' - sent to a client on connect, on an explicit
    get_state request, and broadcast to all clients on every transport
    after every command (see broadcast_state) regardless of whether that
    command arrived over stdin, WiFi, or Bluetooth. Keep this in sync
    with whatever state PROTOCOL.md documents as the state-push shape."""
    return {
        'instrument': sample_source,
        'sa_note': sa_note,
        'octave_shift': octave_shift,
        'drone': {'on': drone_octave is not None, 'octave': drone_octave},
        'eq': dict(band_gains),
        'odukkal': odukkal_enabled,
        'dual_output': dual_output_enabled,
        'volume': master_volume,
    }


def broadcast_state():
    """Pushes the current full state to every connected client on EVERY
    transport (WebSocket and Bluetooth SPP) - whatever changed, however
    the command that changed it arrived. Safe to call from ANY thread:
    WebSocket clients are reached via run_coroutine_threadsafe (never
    touching asyncio/websockets objects directly from a foreign thread);
    Bluetooth clients are reached via a plain, lock-guarded socket write
    (see _bt_clients_lock). A silent no-op wherever a given transport
    never started (its library wasn't available) or has no clients."""
    message = json.dumps({'type': 'state', 'state': get_full_state()})
    if _ws_loop is not None and _ws_clients:
        asyncio.run_coroutine_threadsafe(_broadcast_ws_async(message), _ws_loop)
    _broadcast_bt(message)


async def _broadcast_ws_async(message):
    if not _ws_clients:
        return
    websockets.broadcast(_ws_clients, message)


def _broadcast_bt(message):
    if not _bt_clients:
        return
    data = (message + '\n').encode()
    with _bt_clients_lock:
        dead = []
        for sock in _bt_clients:
            try:
                sock.sendall(data)
            except OSError:
                dead.append(sock)
        for sock in dead:
            _bt_clients.discard(sock)


def _network_toggle_drone(data):
    toggle_drone()


def _network_stop_drone(data):
    stop_drone()


def _network_toggle_dual_output(data):
    toggle_dual_output()


def _network_cycle_instrument(data):
    cycle_source()


def _network_set_instrument(data):
    set_source(data.get('value'))


def _network_toggle_odukkal(data):
    toggle_odukkal()


def _coerce_int_delta(value, label):
    """JSON doesn't distinguish '2' from '2.0' as strongly as Python
    does, so accept either and reject only genuinely fractional/non-
    numeric values - avoids rejecting a perfectly reasonable request
    just because some JSON encoder always emits floats."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not float(value).is_integer():
        raise ValueError(f"{label} must be a whole number, not {value!r}")
    return int(value)


def _network_set_eq(data):
    band = data.get('band')
    if band not in band_gains:
        raise ValueError(f"invalid band {band!r}, must be one of {sorted(band_gains)}")
    steps = _coerce_int_delta(data.get('delta'),
                              f"delta (in {EQ_STEP_DB:.0f}dB steps)")
    adjust_band(band, steps)


def _network_set_volume(data):
    value = data.get('value')
    if not isinstance(value, (int, float)):
        raise ValueError(f"value must be a number 0.0-1.0, not {value!r}")
    set_volume(value)


def _network_adjust_volume(data):
    steps = _coerce_int_delta(data.get('delta'), "delta (in volume steps)")
    adjust_volume(steps)


NETWORK_COMMANDS = {
    'toggle_drone': _network_toggle_drone,
    'stop_drone': _network_stop_drone,
    'toggle_dual_output': _network_toggle_dual_output,
    'cycle_instrument': _network_cycle_instrument,
    'set_instrument': _network_set_instrument,
    'toggle_odukkal': _network_toggle_odukkal,
    'set_eq': _network_set_eq,
    'set_volume': _network_set_volume,
    'adjust_volume': _network_adjust_volume,
    # 'get_state' is intentionally NOT in this table - it changes no
    # state (nothing to broadcast), so it's handled as a direct-reply
    # special case below instead, unlike every other command here.
}


def _dispatch_command(raw_message):
    """The ONE place command dispatch happens, regardless of transport -
    WebSocket (_handle_ws_message) and Bluetooth SPP (_handle_bt_client)
    both call this instead of each reimplementing JSON parsing/
    NETWORK_COMMANDS lookup/error formatting independently. Returns a
    dict to send back directly to ONLY the client that sent raw_message
    (an error, or the get_state reply), or None if nothing should be
    sent directly - a successful state-changing command's own
    broadcast_state() call (fired from inside toggle_drone/adjust_band/
    etc.) is the only response needed, reaching the sender the same way
    it reaches every other connected client on every transport. (An
    earlier version sent a separate direct reply in addition to the
    broadcast for the WebSocket case specifically; with only one client,
    both messages went to the same socket and interleaved in a way that
    made replies consistently lag one command behind. Sending state
    exactly once per change removes the ambiguity entirely - this is
    also why get_state and errors, which are genuinely direct-reply-only
    with nothing to broadcast, stay clearly separate from that path.)"""
    try:
        data = json.loads(raw_message)
        cmd = data['cmd']
    except (json.JSONDecodeError, KeyError, TypeError):
        return {'type': 'error', 'message': 'expected JSON object with a "cmd" field'}
    if cmd == 'get_state':
        return {'type': 'state', 'state': get_full_state()}
    handler = NETWORK_COMMANDS.get(cmd)
    if handler is None:
        return {'type': 'error', 'message': f'unknown cmd {cmd!r} - see PROTOCOL.md'}
    try:
        handler(data)
    except Exception as e:
        return {'type': 'error', 'message': str(e)}
    return None


async def _handle_ws_message(websocket, raw_message):
    reply = _dispatch_command(raw_message)
    if reply is not None:
        await websocket.send(json.dumps(reply))


async def _ws_handler(websocket):
    _ws_clients.add(websocket)
    print(f"[network] client connected ({websocket.remote_address}); "
          f"{len(_ws_clients)} total", flush=True)
    try:
        await websocket.send(json.dumps({'type': 'state', 'state': get_full_state()}))
        async for raw_message in websocket:
            await _handle_ws_message(websocket, raw_message)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        _ws_clients.discard(websocket)
        print(f"[network] client disconnected ({websocket.remote_address}); "
              f"{len(_ws_clients)} total", flush=True)


def run_network_server():
    """Runs the WebSocket server's own asyncio event loop in this thread
    (started as a daemon thread from main - see there) - fully separate
    from control_loop's real-time SPI/serial polling in the main thread,
    so nothing here can add latency to note reading regardless of how
    many clients connect or how much traffic they send. See
    run_bluetooth_server for the Bluetooth SPP transport, which runs in
    its own separate thread the same way and shares _dispatch_command/
    NETWORK_COMMANDS with this one."""
    global _ws_loop
    if websockets is None:
        print("[network] 'websockets' package not available - network "
              "control disabled (stdin control is unaffected).", flush=True)
        return
    _ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_ws_loop)

    async def _serve():
        async with websockets.serve(_ws_handler, NETWORK_HOST, NETWORK_PORT):
            print(f"[network] WebSocket server listening on ws://<pi-ip>:{NETWORK_PORT} "
                  f"(run `hostname -I` on the Pi for its current LAN IP)", flush=True)
            await asyncio.Future()  # run forever

    _ws_loop.run_until_complete(_serve())


# --- Bluetooth SPP (RFCOMM) transport ---------------------------------------
# Same NETWORK_COMMANDS/_dispatch_command layer as the WebSocket transport
# above - see the "Network control" section header comment. Framing over
# this raw stream socket (no WebSocket-style message boundaries) is
# newline-delimited JSON, one command/reply per line - the same
# convention poll_nano_values already uses for the Arduino Nano's serial
# link, for the same reason (a plain byte stream needs an explicit
# message boundary).
BT_ADAPTER_PATH = '/org/bluez/hci0'
BT_ADAPTER_ALIAS = 'Jaladarangam'  # friendly name shown to a phone while
                                   # scanning/pairing, instead of this
                                   # Pi's generic hostname
BT_SPP_UUID = '00001101-0000-1000-8000-00805f9b34fb'  # the standard,
                                                       # well-known Serial
                                                       # Port Profile UUID
                                                       # - any generic SPP
                                                       # terminal app looks
                                                       # for exactly this
BT_PROFILE_PATH = '/jaladarangam/bt_profile'
BT_AGENT_PATH = '/jaladarangam/bt_agent'
BT_RFCOMM_CHANNEL = 1


def _set_adapter_property(bus, name, value):
    adapter = bus.get_object('org.bluez', BT_ADAPTER_PATH)
    dbus.Interface(adapter, 'org.freedesktop.DBus.Properties').Set(
        'org.bluez.Adapter1', name, value)


def _handle_bt_client(sock, device_path):
    """Runs in its own thread per connected Bluetooth client (spawned by
    _BluetoothProfile.NewConnection below) - a plain blocking read loop,
    completely separate from the GLib mainloop thread that handles D-Bus/
    pairing/connection-setup, so a slow or stalled client can never block
    new Bluetooth connections or D-Bus callbacks. Mirrors _ws_handler's
    responsibilities (register, send initial state, dispatch incoming
    commands, clean up on disconnect) for this transport."""
    with _bt_clients_lock:
        _bt_clients.add(sock)
    print(f"[bluetooth] client connected ({device_path}), fd={sock.fileno()}; "
          f"{len(_bt_clients)} total", flush=True)
    try:
        sock.sendall((json.dumps({'type': 'state', 'state': get_full_state()}) + '\n').encode())
        buf = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                print(f"[bluetooth] recv() returned empty - remote closed "
                      f"({device_path})", flush=True)
                break
            buf += chunk
            while b'\n' in buf:
                line, buf = buf.split(b'\n', 1)
                line = line.decode(errors='ignore').strip()
                if not line:
                    continue
                reply = _dispatch_command(line)
                if reply is not None:
                    sock.sendall((json.dumps(reply) + '\n').encode())
    except OSError as e:
        print(f"[bluetooth] socket error on ({device_path}): {e!r}", flush=True)
    finally:
        with _bt_clients_lock:
            _bt_clients.discard(sock)
        sock.close()
        print(f"[bluetooth] client disconnected ({device_path}); "
              f"{len(_bt_clients)} total", flush=True)


if dbus is not None:
    class _BluetoothProfile(dbus.service.Object):
        """The registered SPP server profile object - bluetoothd (running
        as root; see the D-Bus policy note in run_bluetooth_server) calls
        these methods on us over D-Bus. Defined conditionally on dbus
        being importable, since dbus.service.Object doesn't exist at all
        otherwise (this whole class would fail to define, not just fail
        to run, if dbus is None)."""
        @dbus.service.method('org.bluez.Profile1', in_signature='', out_signature='')
        def Release(self):
            print('[bluetooth] profile released', flush=True)

        @dbus.service.method('org.bluez.Profile1', in_signature='oha{sv}', out_signature='')
        def NewConnection(self, device, fd, properties):
            # fd is a dbus.types.UnixFd - .take() hands us the real
            # underlying file descriptor (and ownership of it); wrapping
            # it as a socket lets us use ordinary recv/sendall on what is
            # actually an already-connected RFCOMM socket.
            try:
                sock = socket.socket(fileno=fd.take())
                # The fd BlueZ hands us over D-Bus is non-blocking (that
                # flag lives on the underlying kernel file description,
                # inherited from how bluetoothd itself uses the socket -
                # wrapping it in a new socket.socket() object here does
                # NOT reset it). Without this, the very first sendall()
                # in _handle_bt_client raises BlockingIOError(EAGAIN)
                # immediately, silently tearing the connection down
                # before a single byte is sent - this exact failure
                # (connects, then disconnects within the same second,
                # every time) was diagnosed live via verbose fd/errno
                # logging during development; see this file's PR
                # discussion for the full trace that caught it.
                sock.setblocking(True)
                threading.Thread(target=_handle_bt_client, args=(sock, str(device)),
                                  daemon=True).start()
            except Exception:
                import traceback
                traceback.print_exc()
                raise

        @dbus.service.method('org.bluez.Profile1', in_signature='o', out_signature='')
        def RequestDisconnection(self, device):
            print(f'[bluetooth] disconnection requested: {device}', flush=True)

    class _BluetoothAgent(dbus.service.Object):
        """A 'NoInputNoOutput' pairing agent - this capability is what
        gets Bluetooth Secure Simple Pairing's 'Just Works' mode: neither
        side is asked to confirm a PIN/passkey, appropriate for a device
        with no display/keyboard for that (and fine for a local-network
        demo instrument). AuthorizeService/RequestConfirmation both just
        return immediately (== approve) rather than raising - BlueZ takes
        a method returning normally as authorization granted."""
        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
        def Release(self):
            pass

        @dbus.service.method('org.bluez.Agent1', in_signature='os', out_signature='')
        def AuthorizeService(self, device, uuid):
            return

        @dbus.service.method('org.bluez.Agent1', in_signature='ou', out_signature='')
        def RequestConfirmation(self, device, passkey):
            return

        @dbus.service.method('org.bluez.Agent1', in_signature='', out_signature='')
        def Cancel(self):
            pass


def run_bluetooth_server():
    """Runs the Bluetooth SPP transport's D-Bus/GLib mainloop in this
    thread (started as a daemon thread from main - see there) - separate
    from both control_loop's real-time polling AND run_network_server's
    asyncio loop, so none of the three can block each other. Registers:
    (1) a NoInputNoOutput pairing agent for 'Just Works' pairing, (2) an
    SPP server profile at the standard Serial Port Profile UUID, so any
    generic Bluetooth SPP terminal app can find and connect to it exactly
    like it would any other serial-over-Bluetooth device.

    Runs as the ordinary pyru1 user, not root - verified directly (not
    assumed) that this works: this system's /usr/share/dbus-1/system.d/
    bluetooth.conf grants send_destination=org.bluez to the D-Bus
    "default" policy context (i.e. every user), and separately grants
    send_interface=org.bluez.{Profile1,Agent1} to user=root - the latter
    covers bluetoothd (which runs as root) calling INTO the objects we
    register below, not us calling BlueZ, so it doesn't require this
    process to run as root. Bench-tested with a throwaway profile/agent
    registration script as pyru1 before writing this function for real.

    Also required getting the adapter itself into a state where any of
    this could work at all: it was rfkill soft-blocked (Bluetooth had
    never been used on this Pi before), which silently made even
    Adapter1.Set(Powered, True) fail. The systemd unit (see systemd/
    jaladarangam.service) unblocks that on every start via an
    ExecStartPre, since that state is not guaranteed to survive a
    reboot and requires root to change (this process, running as
    pyru1, cannot fix that itself)."""
    if dbus is None:
        print("[bluetooth] 'dbus'/'PyGObject' not available - Bluetooth "
              "control disabled (stdin and WiFi control are unaffected).",
              flush=True)
        return

    try:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        _set_adapter_property(bus, 'Alias', dbus.String(BT_ADAPTER_ALIAS))
        _set_adapter_property(bus, 'Powered', dbus.Boolean(True))
        _set_adapter_property(bus, 'DiscoverableTimeout', dbus.UInt32(0))  # 0 = never times out
        _set_adapter_property(bus, 'Discoverable', dbus.Boolean(True))
        _set_adapter_property(bus, 'PairableTimeout', dbus.UInt32(0))
        _set_adapter_property(bus, 'Pairable', dbus.Boolean(True))

        agent = _BluetoothAgent(bus, BT_AGENT_PATH)
        agent_manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'),
                                        'org.bluez.AgentManager1')
        agent_manager.RegisterAgent(BT_AGENT_PATH, 'NoInputNoOutput')
        agent_manager.RequestDefaultAgent(BT_AGENT_PATH)

        profile = _BluetoothProfile(bus, BT_PROFILE_PATH)
        profile_manager = dbus.Interface(bus.get_object('org.bluez', '/org/bluez'),
                                          'org.bluez.ProfileManager1')
        profile_manager.RegisterProfile(BT_PROFILE_PATH, BT_SPP_UUID, {
            'Name': dbus.String('Jaladarangam Control'),
            'Role': dbus.String('server'),
            'Channel': dbus.UInt16(BT_RFCOMM_CHANNEL),
            'RequireAuthentication': dbus.Boolean(False),
            'RequireAuthorization': dbus.Boolean(False),
        })
    except Exception as e:
        print(f"[bluetooth] setup failed ({e}) - Bluetooth control disabled "
              "(stdin and WiFi control are unaffected).", flush=True)
        return

    print(f"[bluetooth] SPP service '{BT_ADAPTER_ALIAS}' registered on RFCOMM "
          f"channel {BT_RFCOMM_CHANNEL} (UUID {BT_SPP_UUID}); discoverable and "
          "pairable now, no PIN required (Just Works).", flush=True)

    GLib.MainLoop().run()


def poll_gamakam(raw, prev_pressed):
    """Edge-triggered read of the real gamakam FSR (Nano A0, via
    poll_nano_values) - same press/release detection pattern as the ADC1
    note keys, and the same logic as the original ADC2 implementation
    this replaces (only the raw-value source changed). Updates and
    returns the module-level gamakam_held flag, printing on every
    press/release transition so hardware behavior is directly observable.
    Returns (held, now_pressed) so the caller can track the edge state."""
    global gamakam_held
    now_pressed = raw >= NANO_PRESS_THRESHOLD
    if now_pressed != prev_pressed:
        gamakam_held = now_pressed
        print(f"[gamakam] {'PRESSED' if gamakam_held else 'RELEASED'} (raw={raw})", flush=True)
    return gamakam_held, now_pressed


def _debounced_press(raw, state):
    """Returns True exactly once per confirmed physical press of a Nano
    octave key. `state` is a per-key dict {'count', 'armed'} the caller
    holds across polls (see poll_octave_keys). Requires OCTAVE_DEBOUNCE_
    POLLS consecutive above-NANO_PRESS_THRESHOLD reads before firing - any
    read that drops back below threshold resets the count to 0, so a value
    that wobbles across the threshold (sensor noise, marginal contact) has
    to settle above it for the full debounce window before it counts,
    rather than firing on the first crossing. Re-arms (allows a second
    press to fire) only after a below-threshold read is seen, so a single
    sustained press can't itself repeat-fire once confirmed."""
    if raw >= NANO_PRESS_THRESHOLD:
        state['count'] += 1
        if state['armed'] and state['count'] >= OCTAVE_DEBOUNCE_POLLS:
            state['armed'] = False
            return True
    else:
        state['count'] = 0
        state['armed'] = True
    return False


def poll_octave_keys(raw_up, raw_down, octave_up_state, octave_down_state):
    """Debounced, edge-triggered read of the real octave+/octave- FSRs
    (Nano A1/A2, via poll_nano_values; see _debounced_press). Each
    confirmed press shifts the module-level octave_shift by +-1, clamped
    to +-OCTAVE_SHIFT_LIMIT on every increment/decrement - a press at the
    limit is a no-op (with its own print) rather than silently doing
    nothing, so it's clear from the console that the limit, not a missed
    press, is why nothing changed. octave_up_state/octave_down_state are
    per-key dicts the caller holds across polls; mutated in place."""
    global octave_shift
    if _debounced_press(raw_up, octave_up_state):
        if octave_shift < OCTAVE_SHIFT_LIMIT:
            octave_shift += 1
            print(f"[octave] UP -> {octave_shift:+d}", flush=True)
            print_mapping()
        else:
            print(f"[octave] UP ignored - already at max +{OCTAVE_SHIFT_LIMIT}", flush=True)

    if _debounced_press(raw_down, octave_down_state):
        if octave_shift > -OCTAVE_SHIFT_LIMIT:
            octave_shift -= 1
            print(f"[octave] DOWN -> {octave_shift:+d}", flush=True)
            print_mapping()
        else:
            print(f"[octave] DOWN ignored - already at min -{OCTAVE_SHIFT_LIMIT}", flush=True)


def control_loop():
    pressed = {position: False for position in range(8)}
    prev_raw = {position: 0 for position in range(8)}  # for attack-velocity
                                                         # (dF/dt) at press-edge
    gamakam_prev_pressed = False
    octave_up_state = {'count': 0, 'armed': True}
    octave_down_state = {'count': 0, 'armed': True}

    while True:
        gamakam_raw, octave_up_raw, octave_down_raw = poll_nano_values()
        held, gamakam_prev_pressed = poll_gamakam(gamakam_raw, gamakam_prev_pressed)
        poll_octave_keys(octave_up_raw, octave_down_raw, octave_up_state, octave_down_state)

        for position in range(8):
            if position not in LIVE_POSITIONS:
                continue
            raw = read_channel(spi, position)
            now_pressed = raw >= PRESS_THRESHOLD

            if now_pressed and not pressed[position]:
                velocity = (raw - prev_raw[position]) / CONTROL_INTERVAL
                ringing = most_recent_voice is not None and most_recent_voice['active']
                if held and ringing:
                    start_jaru(position)
                else:
                    if held and not ringing:
                        print(f"(gamakam+key{position + 1}: nothing currently ringing to "
                              f"glide from - plucking instead)", flush=True)
                    pluck(position, velocity)
            elif not now_pressed and pressed[position]:
                # Release edge: only sustained-mode (flute) voices react -
                # plucked voices (mandolin/guitar) ring through untouched,
                # exactly as before this feature existed. Only this
                # position's own voice is ever released here.
                voice = find_voice(voices, position)
                if (voice is not None and voice['active']
                        and voice['envelope'] == 'sustained' and not voice['releasing']):
                    voice['releasing'] = True
                    voice['release_start'] = time.monotonic()
                    print(f"RELEASE -> {voice['note']} (fading, "
                          f"{FLUTE_RELEASE_SECONDS * 1000:.0f}ms)", flush=True)

            # Odukkal: only ever this position's own voice from this
            # position's own raw reading - never another key's voice.
            voice = find_voice(voices, position)
            if voice is not None and voice['active']:
                if odukkal_enabled and now_pressed:
                    update_odukkal(voice, raw, CONTROL_INTERVAL)
                else:
                    voice['odukkal_cents'] = 0.0

            pressed[position] = now_pressed
            prev_raw[position] = raw

        voices[:] = [v for v in voices if v['active']]  # drop naturally-
                                                          # finished voices

        time.sleep(CONTROL_INTERVAL)


def parse_args():
    parser = argparse.ArgumentParser(description='jaladarangam - the hardware-driven instrument.')
    parser.add_argument('--raga', required=True, help='raga name from the corpus, e.g. Shankarabharanam')
    parser.add_argument('--sa', default=None,
                         help='reference tonic pitch, e.g. A3 (default depends on sample '
                              'source: Db4/C#4 for mandolin, A3 for guitar, C4 for flute - '
                              'switches automatically with the source unless set here)')
    parser.add_argument('--bass-db', type=float, default=ma.BASS_BOOST_DB,
                         help=f'starting bass band gain in dB (default {ma.BASS_BOOST_DB:.0f})')
    parser.add_argument('--mid-db', type=float, default=0.0, help='starting mid band gain in dB')
    parser.add_argument('--treble-db', type=float, default=0.0, help='starting treble band gain in dB')
    return parser.parse_args()


def main():
    global DRONE_SAMPLES, eq_bass, eq_mid, eq_treble
    global sample_source, sa_explicit, sa_note, sa_idx
    global pattern, swara_semitones, raga
    global mandolin_bank, guitar_bank, flute_bank

    args = parse_args()

    swara_semitones, ragas_by_name = load_raga_corpus(RAGA_CORPUS_PATH)
    raga = find_raga(ragas_by_name, args.raga)
    pattern = distinct_pitch_set(raga, swara_semitones)
    if len(pattern) > PATTERN_KEY_COUNT:
        print(f"Error: {raga['name']} has {len(pattern)} distinct pitches "
              f"({' '.join(pattern)}) - more than the {PATTERN_KEY_COUNT} keys "
              f"available for raga-pattern positions (key 8 is reserved for "
              f"upper Sa). Not supported in this version.", file=sys.stderr)
        sys.exit(1)

    sample_source = 'mandolin'
    sa_explicit = args.sa is not None
    sa_note = parse_note(args.sa) if sa_explicit else SOURCE_DEFAULT_SA[sample_source]
    sa_idx = note_to_index(sa_note)

    mandolin_bank = MandolinBank()
    guitar_bank = ChromaticBank(f'{ma.BASE_DIR}/samples/guitar_placeholder', '_mf')
    flute_bank = ChromaticBank(f'{ma.BASE_DIR}/samples/flute_placeholder', '_mf')
    DRONE_SAMPLES = load_drone_samples()

    band_gains['bass'] = args.bass_db
    band_gains['mid'] = args.mid_db
    band_gains['treble'] = args.treble_db
    eq_bass = build_band('bass', band_gains['bass'])
    eq_mid = build_band('mid', band_gains['mid'])
    eq_treble = build_band('treble', band_gains['treble'])

    print('jaladarangam.py running. Ctrl+C to stop.', flush=True)
    print(f"Raga: {raga['name']}  distinct pitches: {' '.join(pattern)}", flush=True)
    print(f"Live keys (real FSR hardware wired): "
          f"{', '.join(str(p + 1) for p in sorted(LIVE_POSITIONS)) or '(none)'}", flush=True)
    print_mapping()
    print("Sample source: 'i'+Enter cycles mandolin -> guitar -> flute -> mandolin. "
          f"[source] {sample_source}", flush=True)
    print("Double bass drone: 'b'+Enter = toggle on (C#1) / cycle octave, "
          "'c'+Enter = off. [drone] off", flush=True)
    print(f"Live EQ ({EQ_STEP_DB:.0f}dB/step): 'b+'/'b-' = bass (low-shelf <{BASS_FREQ_HZ:.0f}Hz), "
          f"'m+'/'m-' = mid (peaking @{MID_FREQ_HZ:.0f}Hz), "
          f"'t+'/'t-' = treble (high-shelf >{TREBLE_FREQ_HZ:.0f}Hz)", flush=True)
    print(f"  starting: bass={band_gains['bass']:+.0f}dB mid={band_gains['mid']:+.0f}dB "
          f"treble={band_gains['treble']:+.0f}dB", flush=True)
    print("Dual output: 's'+Enter = toggle headphone jack on/off alongside I2S "
          "(additive). [output] I2S only", flush=True)
    print("Gamakam (jaru trigger): HOLD the gamakam FSR (Nano A0) + press a note "
          "key while another note is ringing = jaru glide (nearest octave).",
          flush=True)
    print("Octave shift: octave+ (Nano A1) / octave- (Nano A2) each shift the "
          "whole instrument's active octave by one, edge-triggered (once per "
          f"press, clamped to +-{OCTAVE_SHIFT_LIMIT}). [octave] {octave_shift:+d}",
          flush=True)
    print(f"Polyphony: up to {MAX_VOICES} notes ring independently; a key's own "
          "re-pluck replaces only that key's own prior voice.", flush=True)
    print("Octave-nearest plucks: Ri/Ga/Ma/Pa/Da/Ni land in whichever octave is "
          "closest to the last note played (Sa/upper-Sa unaffected - always "
          "exactly key 1 / key 8).", flush=True)
    print("Odukkal (pressure->bend): 'o'+Enter toggles 0 to "
          f"+{ODUKKAL_MAX_CENTS:.0f}c upward bend from sustained pressure on a "
          "held, ringing key. [odukkal] OFF", flush=True)
    print("Attack velocity (always on): how fast you press scales pluck "
          "loudness.", flush=True)
    print(f"Volume: 'v+'/'v-'+Enter, {MASTER_VOLUME_STEP:.1f}/step "
          f"[{MASTER_VOLUME_MIN:.1f}-{MASTER_VOLUME_MAX:.1f}]. [volume] {master_volume:.2f}",
          flush=True)

    listener_thread = threading.Thread(target=control_listener, daemon=True)
    listener_thread.start()
    network_thread = threading.Thread(target=run_network_server, daemon=True)
    network_thread.start()
    bluetooth_thread = threading.Thread(target=run_bluetooth_server, daemon=True)
    bluetooth_thread.start()

    try:
        with sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                              dtype='float32', callback=audio_callback):
            control_loop()
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        if headphone_stream is not None:
            headphone_stream.stop()
            headphone_stream.close()
        spi.close()
        nano_serial.close()


if __name__ == '__main__':
    main()
