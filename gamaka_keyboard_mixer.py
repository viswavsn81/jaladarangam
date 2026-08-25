#!/usr/bin/env python3
"""7-key positional raga fingering (Mode B - see sliding_window_raga.py
for the original design this is ported from) on top of the same jaru/
drone/EQ/dual-output engine already built in this file, plus a 3-way
sample source (mandolin / guitar / flute).

Fingering: key 1 (z) is always Sa; keys 2-7 (e r t y 7 u) map to the
NEXT distinct pitches of the ACTIVE RAGA's sequence in order (arohanam
union avarohanam, deduplicated, sorted ascending from Sa) - never a
fixed sa/ri/ga/ma/pa/dha/ni mapping, since that depends entirely on
which raga is selected. Ragas whose distinct-pitch count exceeds 7 are
rejected at startup (reported below). '[' / ']' shift all 7 keys down/
up one octave together - hand shape and Sa's position never change,
only which octave they sound in. No sliding window, no paging, no
correction key - the simple fixed/stateless version only. Raga and the
initial tonic (Sa) are chosen via --raga/--sa at startup, the same
corpus/CLI mechanism as the earlier sliding_window_raga.py prototype
(ported into this file - it has no raga/corpus code of its own).

Sample source ('i' + Enter cycles mandolin -> guitar -> flute -> back):
  - mandolin: only 5 notes recorded (see gamaka.py/gamaka_keyboard.py's
    samples/mandolin) - reused here as generic voices for key-POSITIONS
    1-5 (not swara identities - the raga corpus uses variant swara
    names like R1/R2/G2/G3 that the mandolin's plain files don't
    distinguish anyway), pitch-corrected via measured-pitch varispeed
    (the same detect_pitch + rate approach as gamaka.py's portamento) to
    whatever exact frequency that position needs for the current raga/
    tonic/octave. Positions 6-7 have no mandolin recording.
  - guitar: samples/guitar_placeholder, full chromatic coverage E2-B5,
    nearest-available-note lookup at rate=1.0 (this project's existing
    precedent for this sample set - not re-corrected/re-measured here).
  - flute (Alto Flute, chosen for a lower/mellower register than
    standard C Flute): samples/flute_placeholder, full chromatic
    coverage G3-G6 - same nearest-available/rate=1.0 handling as guitar.
    Narrower range than guitar; see that directory's PROVENANCE.md.
  Missing-note policy, consistent across all three sources: mandolin
  positions 6-7, or any flute target outside G3-G6, fall back to guitar
  (guitar's own wide range makes it the natural universal fallback) -
  never a crash, always printed. Guitar itself never "runs out" (nearest-
  available clamping), so it needs no further fallback.

Jaru (shift + note key), the double bass drone (b/c), the live 3-band
EQ (b+/b-/m+/m-/t+/t-), and the dual I2S+headphone output (s) all
continue to work exactly as before - they operate on whichever voice/
frequency is currently resolved for a key, not on a fixed note name.
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
import evdev
from evdev import ecodes
import mandolin_audio as ma
from mandolin_audio import SAMPLE_RATE, BLOCKSIZE

HEADPHONE_DEVICE = "bcm2835 Headphones"
HEADPHONE_HANDOFF_MAXLEN = 8  # ~170ms of buffering at BLOCKSIZE/SAMPLE_RATE;
                               # bounds how far the two independently-clocked
                               # streams can drift before old blocks start
                               # getting dropped in favor of newer ones

JARU_GLIDE_SECONDS = ma.JARU_GLIDE_SECONDS  # 200ms default portamento duration

KEYBOARD_NAME = "Logitech K400 Plus"
FALLBACK_DEVICE = "/dev/input/event0"

# --- 7-key positional mapping (Mode B) ---------------------------------
NOTE_KEYS = {
    ecodes.KEY_Z: 0, ecodes.KEY_E: 1, ecodes.KEY_R: 2, ecodes.KEY_T: 3,
    ecodes.KEY_Y: 4, ecodes.KEY_7: 5, ecodes.KEY_U: 6,
}
KEY_LABELS = ['z', 'e', 'r', 't', 'y', '7', 'u']
SHIFT_KEYS = (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT)
OCTAVE_DOWN_KEY = ecodes.KEY_LEFTBRACE   # '['
OCTAVE_UP_KEY = ecodes.KEY_RIGHTBRACE    # ']'

# --- Raga corpus (ported from sliding_window_raga.py - this file has no
# corpus code of its own) ------------------------------------------------
RAGA_CORPUS_PATH = f'{ma.BASE_DIR}/ragas.json'
CHROMATIC = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']


def note_to_index(note):
    """'A3' -> absolute semitone index, C0 = 0."""
    letter = note[:-1]
    octave = int(note[-1])
    return octave * 12 + CHROMATIC.index(letter)


def index_to_note(idx):
    octave, pc = divmod(idx, 12)
    return f'{CHROMATIC[pc]}{octave}'


def index_to_hz(idx):
    return 440.0 * 2 ** ((idx - note_to_index('A4')) / 12)


def parse_note(s):
    """Normalizes user-typed note names ('a3', 'Db4', 'DB4') to this
    file's exact CHROMATIC casing, without blindly .upper()-ing the
    whole string (that would turn 'Db4' into 'DB4', which CHROMATIC
    doesn't recognize)."""
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
    """Arohanam UNION avarohanam, deduplicated, sorted ascending by
    semitone from Sa - the raga's real distinct pitch inventory."""
    aro = set(strip_trailing_sa(raga['arohanam']))
    ava = set(strip_trailing_sa(raga['avarohanam']))
    return sorted(aro | ava, key=lambda s: swara_semitones[s])


def position_to_semitones(pos, pattern, swara_semitones):
    """Positions past the pattern's length (audava/shadava ragas with
    fewer than 7 distinct pitches) continue into the next octave rather
    than IndexError-ing."""
    octave, degree = divmod(pos, len(pattern))
    return octave * 12 + swara_semitones[pattern[degree]]


def position_to_swara(pos, pattern):
    _, degree = divmod(pos, len(pattern))
    return pattern[degree]


# --- Sample sources ------------------------------------------------------
SOURCES = ('mandolin', 'guitar', 'flute')
SOURCE_DEFAULT_SA = {
    'mandolin': 'Db4',  # = C#4, the mandolin recordings' own native tonic
    'guitar': 'A3',     # matches sliding_window_raga.py's original default
    'flute': 'C4',      # comfortably inside flute's G3-G6 recorded range
}
MANDOLIN_POSITION_NOTES = ['sa', 'ri', 'ga', 'ma', 'pa']  # key positions 0-4;
                                                            # 5,6 have no file


class ChromaticBank:
    """Wide, densely-chromatic sample set (guitar_placeholder,
    flute_placeholder) - nearest-available-note lookup, played at
    rate=1.0. Ported from sliding_window_raga.py's SampleBank, renamed
    for clarity now that there are two chromatic sources instead of one."""
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
    """The 5 recorded mandolin notes, reused as generic voices for key-
    positions 1-5 (see module docstring for why this is positional, not
    swara-name-matched). Each measured once at startup; playback rate is
    computed per-pluck from the current target frequency."""
    def __init__(self):
        self.by_position = {}
        for i, note in enumerate(MANDOLIN_POSITION_NOTES):
            samples = ma.load_sample(note, label=note)
            pitch_hz = ma.detect_pitch(samples)
            self.by_position[i] = (samples, pitch_hz)

    def get(self, position):
        return self.by_position.get(position)


def resolve_note(position, octave_shift):
    """Returns (samples, rate, target_hz, source_used, note_label) for
    the given key position under the current raga/tonic/octave/source.
    target_hz is always the theoretical equal-tempered frequency for
    that position (measured-pitch-corrected via rate for mandolin;
    guitar/flute play their nearest sample at rate=1.0, matching this
    project's existing precedent of not live-correcting those two dense
    chromatic sets)."""
    swara = position_to_swara(position, pattern)
    semitones = position_to_semitones(position, pattern, swara_semitones) + 12 * octave_shift
    target_idx = sa_idx + semitones
    target_hz = index_to_hz(target_idx)

    if sample_source == 'mandolin':
        entry = mandolin_bank.get(position)
        if entry is not None:
            samples, measured_hz = entry
            rate = target_hz / measured_hz
            return samples, rate, target_hz, 'mandolin', f'{MANDOLIN_POSITION_NOTES[position]}_mid (corrected)'
        samples, idx, exact = guitar_bank.get(target_idx)
        label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest)'
        return samples, 1.0, target_hz, 'guitar (fallback: mandolin has no key ' \
                                         f'{position+1})', label

    if sample_source == 'flute':
        if target_idx in flute_bank.available_indices:
            samples, idx, exact = flute_bank.get(target_idx)
            return samples, 1.0, target_hz, 'flute', index_to_note(idx)
        samples, idx, exact = guitar_bank.get(target_idx)
        label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest)'
        return samples, 1.0, target_hz, 'guitar (fallback: outside flute\'s ' \
                                         'G3-G6 range)', label

    samples, idx, exact = guitar_bank.get(target_idx)
    label = index_to_note(idx) if exact else f'{index_to_note(idx)} (nearest, target was {index_to_note(target_idx)})'
    return samples, 1.0, target_hz, 'guitar', label


DRONE_DIR = f'{ma.BASE_DIR}/samples/doublebass'
DRONE_OCTAVES = (1, 2)  # C#1, C#2 - cycle order on repeated 'b' presses
DRONE_MIX_LEVEL = 0.07  # see gamaka_keyboard.py for how this was derived
                         # (the drone alone through a 14dB bass boost hit a
                         # true unclipped peak of 2.55/+8.1dBFS at full
                         # level) - same reasoning applies here since the
                         # bass band can reach well past 14dB live.

# Band definitions. Bass/treble corners match this task's own suggestion
# (~200Hz, ~4000Hz); mid center is the geometric mean of the requested
# 500Hz-2kHz range, with Q=0.7 chosen so the band's gain actually spans
# roughly that range (verified: +8dB peaking @ 1000Hz/Q=0.7 gives ~+3.8dB
# already at 500Hz and 2000Hz, tapering to near-0 by 200Hz/5000Hz - stays
# clear of the bass and treble bands).
BASS_FREQ_HZ = 200.0
MID_FREQ_HZ = 1000.0
MID_Q = 0.7
TREBLE_FREQ_HZ = 4000.0
EQ_STEP_DB = 2.0

RAW_BUFFER_SECONDS = 1.5  # matches gamaka.py's earlier boost diagnostic -
                           # long enough to still hold a recent attack
                           # transient if you press an EQ key promptly
                           # after playing something, short enough that
                           # the one-shot predictor (scipy lfilter, not a
                           # per-sample loop - see LowShelf's docstring)
                           # stays well under a block period.
RAW_BUFFER_LEN = int(SAMPLE_RATE * RAW_BUFFER_SECONDS)
raw_ring = np.zeros(RAW_BUFFER_LEN, dtype=np.float32)
raw_ring_pos = 0


def parse_args():
    parser = argparse.ArgumentParser(
        description='7-key positional raga fingering with jaru, drone, live EQ, and dual output.')
    parser.add_argument('--raga', required=True, help='raga name from the corpus, e.g. Mohanam')
    parser.add_argument('--sa', default=None,
                         help='reference tonic pitch, e.g. A3 (default depends on sample '
                              'source: Db4/C#4 for mandolin, A3 for guitar, C4 for flute - '
                              'switches automatically with the source unless set here)')
    parser.add_argument('--bass-db', type=float, default=ma.BASS_BOOST_DB,
                         help=f'starting bass band gain in dB (default {ma.BASS_BOOST_DB:.0f})')
    parser.add_argument('--mid-db', type=float, default=0.0, help='starting mid band gain in dB')
    parser.add_argument('--treble-db', type=float, default=0.0, help='starting treble band gain in dB')
    return parser.parse_args()


def find_keyboard():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == KEYBOARD_NAME:
            return dev
    return evdev.InputDevice(FALLBACK_DEVICE)


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


# Monophonic melodic voice + independent drone layer - identical model to
# gamaka_keyboard.py.
active_voice = None
glide = None
drone_octave = None
drone_voice = None

# Mode B fingering state.
octave_shift = 0
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

# The live 3-band EQ. band_gains is the single source of truth (dB);
# eq_bass/eq_mid/eq_treble are the corresponding stateful filter objects
# actually used by audio_callback, or None (bypass) at 0dB - rebuilt
# (fresh state) only when that band's gain changes.
band_gains = {'bass': 0.0, 'mid': 0.0, 'treble': 0.0}
eq_bass = None
eq_mid = None
eq_treble = None

# Dual output. dual_output_enabled is the single source of truth for
# whether the primary callback bothers handing off blocks at all;
# headphone_stream is the second OutputStream object (or None) so it can
# be stopped/closed on toggle-off. deque.append/popleft are individually
# thread-safe in CPython without an explicit lock (documented guarantee),
# which is all that's needed here: one thread appends, the other pops.
dual_output_enabled = False
headphone_stream = None
headphone_handoff = collections.deque(maxlen=HEADPHONE_HANDOFF_MAXLEN)


def build_band(name, gain_db):
    if gain_db == 0.0:
        return None
    if name == 'bass':
        return ma.LowShelf(SAMPLE_RATE, BASS_FREQ_HZ, gain_db)
    if name == 'mid':
        return ma.PeakingEQ(SAMPLE_RATE, MID_FREQ_HZ, gain_db, q=MID_Q)
    return ma.HighShelf(SAMPLE_RATE, TREBLE_FREQ_HZ, gain_db)


def apply_chain_unclipped(mix, bass_f, mid_f, treble_f):
    """Bass -> mid -> treble -> EXISTING_GAIN, deliberately with NO clip -
    used both by the live callback (which clips separately as its own
    last step) and by predicted_peak (which must see the true unclipped
    peak; clipping here would cap it at 1.0 and make every ceiling check
    silently pass no matter how far over it actually was - a real bug
    caught by testing this in an earlier version). Same output-stage
    gain as mandolin_audio.finalize_output, but that function only takes
    one filter - this generalizes it to three without touching
    finalize_output itself (gamaka.py and gamaka_keyboard.py still rely
    on its exact current behavior)."""
    for f in (bass_f, mid_f, treble_f):
        if f is not None:
            mix = f.process(mix)
    return mix * ma.EXISTING_GAIN


def predicted_peak(candidate_gains):
    """Run a FRESH (zero-state) candidate chain over the most recent raw
    buffer and return the resulting UNCLIPPED peak."""
    buf = raw_ring.copy()
    bass_f = build_band('bass', candidate_gains['bass'])
    mid_f = build_band('mid', candidate_gains['mid'])
    treble_f = build_band('treble', candidate_gains['treble'])
    out = apply_chain_unclipped(buf, bass_f, mid_f, treble_f)
    return float(np.max(np.abs(out)))


def audio_callback(outdata, frames, time_info, status):
    global glide, raw_ring_pos
    mix = np.zeros(frames, dtype=np.float32)
    v = active_voice
    if v is not None and v['active']:
        g = glide
        if g is not None:
            start_cents, target_cents, start_t = g
            cents, done = ma.ramp_cents(start_cents, target_cents, JARU_GLIDE_SECONDS,
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


def headphone_callback(outdata, frames, time_info, status):
    """Consumes blocks the primary (I2S) callback hands off, rather than
    recomputing - recomputing would call advance_voice/advance_voice_loop
    a second time per logical block and double-advance the shared,
    mutable voice/drone playback position. Falls back to silence (not an
    error) if the hand-off queue is empty, e.g. right after the stream
    starts before the first block has arrived."""
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
        dual_output_enabled = False  # stop handing off new blocks first
        headphone_stream.stop()
        headphone_stream.close()
        headphone_stream = None
        print("[output] I2S only", flush=True)


def print_mapping():
    parts = []
    for pos in range(len(NOTE_KEYS)):
        samples, rate, target_hz, source_used, note_label = resolve_note(pos, octave_shift)
        swara = position_to_swara(pos, pattern)
        parts.append(f"{KEY_LABELS[pos]}={swara}({target_hz:.0f}Hz,{source_used}:{note_label})")
    print(f"  mapping [source={sample_source}] [Sa={sa_note}={index_to_hz(sa_idx):.1f}Hz] "
          f"[octave={octave_shift:+d}]:", flush=True)
    for p in parts:
        print(f"    {p}", flush=True)


def pluck(position):
    global active_voice, glide
    samples, rate, target_hz, source_used, note_label = resolve_note(position, octave_shift)
    swara = position_to_swara(position, pattern)
    active_voice = {'samples': samples, 'pos': 0.0, 'rate': rate,
                     'active': True, 'pitch_hz': target_hz,
                     'note': f'key{position+1}({KEY_LABELS[position]})={swara}'}
    glide = None
    print(f"PLUCK -> {active_voice['note']} [{source_used}: {note_label}] ({target_hz:.1f} Hz)", flush=True)


def start_jaru(position):
    global glide
    v = active_voice
    samples, rate, target_hz, source_used, note_label = resolve_note(position, octave_shift)
    swara = position_to_swara(position, pattern)
    target_cents = ma.cents_between(v['pitch_hz'], target_hz)
    current_cents = 1200.0 * np.log2(v['rate'])
    glide = (current_cents, target_cents, time.monotonic())
    print(f"JARU -> {v['note']} sliding to key{position+1}({KEY_LABELS[position]})={swara} "
          f"[{source_used}] ({target_cents:+.1f}c over {JARU_GLIDE_SECONDS * 1000:.0f}ms)", flush=True)


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


def shift_octave(direction):
    global octave_shift
    octave_shift += direction
    print(f"[octave] {octave_shift:+d}", flush=True)
    print_mapping()


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


def adjust_band(name, direction):
    """direction is +1 or -1. Refuses (and reports) rather than clips."""
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


def control_listener():
    """Reads lines from stdin: 'b'/'c' for the drone, 'i' for the sample
    source cycle, 's' for dual output, 'b+'/'b-'/'m+'/'m-'/'t+'/'t-' for
    the live EQ - typed + Enter throughout, deliberately separate from
    the evdev note/shift/octave keys since none of this is a performance
    gesture. Runs as a daemon thread so a non-interactive stdin (EOF)
    just ends it quietly."""
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
            name, direction = EQ_COMMANDS[cmd]
            adjust_band(name, direction)


def run(dev):
    shift_held = False
    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY:
            continue

        if event.code in SHIFT_KEYS:
            if event.value == 1:
                shift_held = True
            elif event.value == 0:
                shift_held = False
            continue

        if event.value != 1:
            continue  # only fresh key-down presses trigger anything

        if event.code == OCTAVE_DOWN_KEY:
            shift_octave(-1)
            continue
        if event.code == OCTAVE_UP_KEY:
            shift_octave(+1)
            continue

        if event.code not in NOTE_KEYS:
            continue
        position = NOTE_KEYS[event.code]

        ringing = active_voice is not None and active_voice['active']
        if shift_held and ringing:
            start_jaru(position)
        else:
            if shift_held and not ringing:
                print(f"(shift+key{position+1}: nothing currently ringing to glide from - "
                      f"plucking instead)", flush=True)
            pluck(position)


def main():
    global DRONE_SAMPLES, eq_bass, eq_mid, eq_treble
    global sample_source, sa_explicit, sa_note, sa_idx, octave_shift
    global pattern, swara_semitones, raga
    global mandolin_bank, guitar_bank, flute_bank

    args = parse_args()

    swara_semitones, ragas_by_name = load_raga_corpus(RAGA_CORPUS_PATH)
    raga = find_raga(ragas_by_name, args.raga)
    pattern = distinct_pitch_set(raga, swara_semitones)
    if len(pattern) > len(NOTE_KEYS):
        print(f"Error: {raga['name']} has {len(pattern)} distinct pitches "
              f"({' '.join(pattern)}) - more than the {len(NOTE_KEYS)} available "
              f"note keys. Not supported in this version.", file=sys.stderr)
        sys.exit(1)

    sample_source = 'mandolin'
    sa_explicit = args.sa is not None
    sa_note = parse_note(args.sa) if sa_explicit else SOURCE_DEFAULT_SA[sample_source]
    sa_idx = note_to_index(sa_note)
    octave_shift = 0

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

    print('7-key raga fingering with jaru, drone, live EQ, and dual output running. '
          'Ctrl+C to stop.', flush=True)
    print(f"Raga: {raga['name']}  distinct pitches: {' '.join(pattern)}", flush=True)
    print('  z e r t y 7 u = key positions 1-7 (Sa always on z). shift+key while a note '
          'rings = jaru glide. [ / ] = octave down/up.', flush=True)
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

    dev = find_keyboard()
    print(f"Listening on {dev.path} ({dev.name}).", flush=True)

    listener_thread = threading.Thread(target=control_listener, daemon=True)
    listener_thread.start()

    try:
        with sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                              dtype='float32', callback=audio_callback):
            run(dev)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
    finally:
        if headphone_stream is not None:
            headphone_stream.stop()
            headphone_stream.close()


if __name__ == '__main__':
    main()
