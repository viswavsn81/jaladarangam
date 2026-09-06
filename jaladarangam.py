#!/usr/bin/env python3
"""jaladarangam.py - the real hardware-driven instrument: 8 physical FSR
note keys on a single MCP3008 (raga-selectable positional layout, ported
from sliding_window_raga.py/gamaka_keyboard_mixer.py), mandolin/guitar/
flute instrument switching, the double bass drone, the live 3-band EQ,
and dual I2S+headphone output.

All 8 keys (CH0..CH7) are physically wired with real FSRs. No vibration
motors in this build (see key_press.py for that, on its own throwaway
test rig - unrelated to this instrument's hardware). A second MCP3008 for
future gamakam/octave keys exists only in the design, not in hardware,
and is not referenced here.

There's no dedicated gamakam (jaru-trigger) key wired yet - it's stood in
for by the keyboard's spacebar (see poll_gamakam_input). That function is
the ONLY place that knows the stand-in is a keyboard; swapping in a real
FSR-based gamakam key later means replacing its body, not the jaru
trigger logic in control_loop/start_jaru.

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
file's note keys are FSRs read over SPI, not keyboard keys (only the
spacebar gamakam stand-in reads the keyboard at all).

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
import spidev
import evdev
from evdev import ecodes
import mandolin_audio as ma
from mandolin_audio import SAMPLE_RATE, BLOCKSIZE

# --- Hardware: all 8 keys physically wired on one MCP3008 (CH0..CH7 =
# position 0..7). Positions are ALSO the MCP3008 channel numbers directly -
# no separate name/channel table needed. Add/remove entries here if a key
# is ever unwired again.
LIVE_POSITIONS = set(range(8))

CONTROL_INTERVAL = 0.02  # seconds between SPI poll rounds, same as gamaka.py
PRESS_THRESHOLD = 100    # raw ADC counts (0-1023) - validated against real
                         # Sa/Ri hardware in key_press.py.

KEYBOARD_NAME = "Logitech K400 Plus"
FALLBACK_DEVICE = "/dev/input/event0"
GAMAKAM_STANDIN_KEY = ecodes.KEY_SPACE  # temporary - see poll_gamakam_input

UPPER_SA_POSITION = 7  # key 8 - always upper Sa, regardless of raga pattern
                        # length (see resolve_position)

# --- MCP3008 (ADC1 - the only physically wired one) ------------------------
spi = spidev.SpiDev()
spi.open(0, 0)  # bus 0, CE0
spi.max_speed_hz = 1350000


def read_channel(ch):
    cmd = [1, (8 + ch) << 4, 0]
    reply = spi.xfer2(cmd)
    return ((reply[1] & 3) << 8) | reply[2]


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
    for the given key position under the current raga/tonic/source.
    Position UPPER_SA_POSITION (7) is a hardcoded override - always Sa at
    +12 semitones from sa_idx - regardless of what the generic pattern-
    continuation formula would otherwise produce for a short raga (see
    module docstring). Positions 0-6 use position_to_semitones/
    position_to_swara verbatim (their own next-octave continuation for
    raga patterns shorter than 7 is untouched, reused as-is)."""
    if position == UPPER_SA_POSITION:
        swara = 'S'
        semitones = 12
    else:
        swara = position_to_swara(position, pattern)
        semitones = position_to_semitones(position, pattern, swara_semitones)
    target_idx = sa_idx + semitones
    target_hz = index_to_hz(target_idx)

    if sample_source == 'mandolin':
        entry = mandolin_bank.get(position)
        if entry is not None:
            samples, measured_hz = entry
            rate = target_hz / measured_hz
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
          f"[Sa={sa_note}={index_to_hz(sa_idx):.1f}Hz]:", flush=True)
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


def find_keyboard():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == KEYBOARD_NAME:
            return dev
    return evdev.InputDevice(FALLBACK_DEVICE)


def poll_gamakam_input(dev):
    """Non-blocking poll of the temporary gamakam stand-in (held spacebar).
    Drains every currently-queued keyboard event via dev.read_one() (which
    returns None immediately rather than blocking when the queue is empty)
    and updates/returns the module-level gamakam_held flag.

    This is the ONLY function that knows the gamakam key is a keyboard
    stand-in. Swapping in a real FSR-based gamakam key later means
    replacing this function's body with an MCP3008 threshold check -
    control_loop/start_jaru's trigger logic (gamakam_held and ringing =
    jaru) doesn't change."""
    global gamakam_held
    while True:
        event = dev.read_one()
        if event is None:
            break
        if event.type == ecodes.EV_KEY and event.code == GAMAKAM_STANDIN_KEY:
            if event.value == 1:
                gamakam_held = True
            elif event.value == 0:
                gamakam_held = False
    return gamakam_held


def control_loop(dev):
    pressed = {position: False for position in range(8)}

    while True:
        held = poll_gamakam_input(dev)

        for position in range(8):
            if position not in LIVE_POSITIONS:
                continue
            raw = read_channel(position)
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
    print("Gamakam (jaru trigger) stand-in: HOLD SPACEBAR + press a note key while "
          "another note is ringing = jaru glide (nearest octave). No dedicated "
          "gamakam FSR key wired yet.", flush=True)

    dev = find_keyboard()
    print(f"Listening for spacebar on {dev.path} ({dev.name}).", flush=True)

    listener_thread = threading.Thread(target=control_listener, daemon=True)
    listener_thread.start()

    try:
        with sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                              dtype='float32', callback=audio_callback):
            control_loop(dev)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        if headphone_stream is not None:
            headphone_stream.stop()
            headphone_stream.close()
        spi.close()


if __name__ == '__main__':
    main()
