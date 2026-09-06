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

Usage:
    python3 jaladarangam.py --raga Shankarabharanam
"""
import argparse
import collections
import json
import os
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
                # for it.

UPPER_SA_POSITION = 7  # key 8 - always upper Sa, regardless of raga pattern
                        # length (see resolve_position)

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


def resolve_position(position):
    """Returns (samples, rate, target_hz, source_used, note_label, swara)
    for the given key position under the current raga/tonic/source/
    octave_shift. Position UPPER_SA_POSITION (7) is a hardcoded override -
    always Sa at +12 semitones from sa_idx - regardless of what the generic
    pattern-continuation formula would otherwise produce for a short raga
    (see module docstring). Positions 0-6 use position_to_semitones/
    position_to_swara verbatim (their own next-octave continuation for
    raga patterns shorter than 7 is untouched, reused as-is). octave_shift
    (Nano octave+/octave- keys) is applied uniformly to every position
    here, so the whole instrument's active octave moves together. The
    mandolin path's dynamically-computed rate is clamped to [RATE_MIN,
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
    return mix * ma.EXISTING_GAIN


def predicted_peak(candidate_gains):
    buf = raw_ring.copy()
    bass_f = build_band('bass', candidate_gains['bass'])
    mid_f = build_band('mid', candidate_gains['mid'])
    treble_f = build_band('treble', candidate_gains['treble'])
    out = apply_chain_unclipped(buf, bass_f, mid_f, treble_f)
    return float(np.max(np.abs(out)))


def adjust_band(name, direction):
    global eq_bass, eq_mid, eq_treble
    candidate = dict(band_gains)
    candidate[name] = band_gains[name] + direction * EQ_STEP_DB
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


EQ_COMMANDS = {
    'b+': ('bass', +1), 'b-': ('bass', -1),
    'm+': ('mid', +1), 'm-': ('mid', -1),
    't+': ('treble', +1), 't-': ('treble', -1),
}

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


# --- Playback state ---------------------------------------------------------
active_voice = None  # None or {'samples','pos','rate','active','pitch_hz','note'}
glide = None          # None, or (start_cents, target_cents, start_time)
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
    global glide, raw_ring_pos
    mix = np.zeros(frames, dtype=np.float32)
    v = active_voice
    if v is not None and v['active']:
        g = glide
        if g is not None:
            start_cents, target_cents, start_t = g
            cents, done = ma.ramp_cents(start_cents, target_cents, ma.JARU_GLIDE_SECONDS,
                                         time.monotonic() - start_t)
            v['rate'] = 2 ** (cents / 1200)
            if done:
                glide = None
        out = ma.advance_voice(v, frames)
        mix[:len(out)] += out
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


def pluck(position):
    global active_voice, glide
    samples, rate, target_hz, source_used, note_label, swara = resolve_position(position)
    active_voice = {'samples': samples, 'pos': 0.0, 'rate': rate, 'active': True,
                     'pitch_hz': target_hz, 'note': f'key{position + 1}({swara})'}
    glide = None
    print(f"PLUCK -> {active_voice['note']} [{source_used}: {note_label}] ({target_hz:.1f} Hz)", flush=True)


def start_jaru(position):
    global glide
    v = active_voice
    _, _, base_hz, source_used, note_label, swara = resolve_position(position)
    target_hz = nearest_octave_hz(base_hz, v['pitch_hz'])
    if target_hz == base_hz:
        octave_note = 'same octave'
    elif target_hz > base_hz:
        octave_note = 'octave up'
    else:
        octave_note = 'octave down'
    target_cents = ma.cents_between(v['pitch_hz'], target_hz)
    current_cents = 1200.0 * np.log2(v['rate'])
    glide = (current_cents, target_cents, time.monotonic())
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


def stop_drone():
    global drone_octave, drone_voice
    drone_octave = None
    drone_voice = None
    print("[drone] off", flush=True)


def print_mapping():
    print(f"  mapping [raga={raga['name']}] [source={sample_source}] "
          f"[Sa={sa_note}={index_to_hz(sa_idx):.1f}Hz] [octave={octave_shift:+d}]:", flush=True)
    for position in range(8):
        live = 'LIVE' if position in LIVE_POSITIONS else 'not wired yet'
        samples, rate, target_hz, source_used, note_label, swara = resolve_position(position)
        print(f"    CH{position}=key{position + 1}({swara:<3}) ({live:13s}): "
              f"{target_hz:7.1f}Hz  [{source_used}: {note_label}]", flush=True)


def cycle_source():
    global sample_source, sa_note, sa_idx
    i = SOURCES.index(sample_source)
    sample_source = SOURCES[(i + 1) % len(SOURCES)]
    if not sa_explicit:
        sa_note = SOURCE_DEFAULT_SA[sample_source]
        sa_idx = note_to_index(sa_note)
    print(f"[source] {sample_source}" +
          ("" if sa_explicit else f"  (Sa auto-reset to {sa_note})"), flush=True)
    print_mapping()


def control_listener():
    """Reads lines from stdin: 'b'/'c' for the drone, 'i' for the sample
    source cycle, 's' for dual output, 'b+'/'b-'/'m+'/'m-'/'t+'/'t-' for the
    live EQ - typed + Enter, same convention/commands as
    gamaka_keyboard_mixer.py. Note 't+'/'t-' (treble EQ) are two-character
    commands, distinct from a bare 't' - there is no bare-'t' command in
    this file (tanpura was scoped but dropped, see module docstring), so
    there's no actual collision to resolve; even if there were, this
    channel (typed + Enter on stdin) is already fully separate from note-
    key input, which in this file comes from FSRs over SPI, not the
    keyboard at all. Runs as a daemon thread so a non-interactive stdin
    (EOF) just ends it quietly."""
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
        elif cmd in EQ_COMMANDS:
            band, direction = EQ_COMMANDS[cmd]
            adjust_band(band, direction)


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
                ringing = active_voice is not None and active_voice['active']
                if held and ringing:
                    start_jaru(position)
                else:
                    if held and not ringing:
                        print(f"(gamakam+key{position + 1}: nothing currently ringing to "
                              f"glide from - plucking instead)", flush=True)
                    pluck(position)
            pressed[position] = now_pressed

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

    listener_thread = threading.Thread(target=control_listener, daemon=True)
    listener_thread.start()

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
