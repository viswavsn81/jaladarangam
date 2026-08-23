#!/usr/bin/env python3
"""7-key raga prototype with automatic octave rollover - a keyboard stand-in
for the eventual 7-FSR physical instrument (7 note keys + octave-up +
octave-down + gamakam modifier). Replaces the earlier two-mode (sliding
window / stateless) A-B test with a single hybrid design.

Layout:
  Note keys (right hand): z e r t y 7 u
  Control keys (left hand): q = octave down, w = octave up, space = gamakam
  (gamakam is wired up as a detected key but not yet given any sonic
  behavior - same "not part of this prototype yet" status noted before)

Note mapping - purely positional, never bound to a fixed absolute swara
name: the 7 keys map to the raga's DISTINCT pitch set (arohanam UNION
avarohanam, deduplicated, sorted ascending by semitone from Sa), not to
arohanam alone. Sa is always key 1 (z); the hand shape never changes.
Ragas whose distinct-pitch count exceeds 7 (an anya swara / bhashanga
raga using more than 7 distinct notes total, e.g. Bhairavi in this
corpus with both D1 and D2) cannot fit this layout and are rejected at
selection time with a clear error, rather than silently guessing at a
workaround.

Automatic octave rollover: pressing key 1 immediately after key 7 shifts
the octave up by one before sounding (continuing an ascending phrase past
the top into the next octave's Sa, rather than dropping back to mid Sa);
pressing key 7 immediately after key 1 shifts down symmetrically. This is
strict ADJACENT-pair detection on the last two keys pressed - it does not
track melodic direction over more than two notes or infer intent. The
wrap thresholds are separate constants (WRAP_UP_PREV_MIN_SLOT etc.) so the
strict rule can be loosened later (e.g. "previous >=5 and new <=2") without
changing the detection logic itself. The octave-up/down keys manually
override the octave at any time, independent of this auto-detection.
Every automatic rollover and every manual octave-key press is logged with
a timestamp, since the ratio between them is the actual signal for
whether the wrap rule is tuned correctly.

Sample playback: this needs true polyphony (a decaying note may still be
ringing when the next key is pressed), unlike gamaka.py's monophonic
single-anchor-voice model - so instead of gamaka.py's pygame.mixer (used
by spacebar_instrument.py) or its own single-voice sounddevice callback,
this uses a small fixed pool of voice slots mixed together in one
sounddevice callback. A voice slot is replaced with a single atomic list
assignment (voices[i] = {...}), which is safe under the GIL the same way
gamaka.py's own anchor_idx handoff between threads is - the audio callback
either sees the old occupant of a slot or the new one for a given buffer,
never a torn state. Each note plays its own real recorded sample at
native pitch (rate=1.0) - no pitch-shifting needed at all, since the
guitar placeholder set has full chromatic coverage E2-B5 and every raga
swara resolves to an exact available sample for any in-range Sa.
"""
import argparse
import json
import os
import sys
import time
import threading
import numpy as np
import soundfile as sf
import sounddevice as sd
import evdev
from evdev import ecodes

BASE_DIR = '/home/pyru1/mindfulness-instrument'
RAGA_CORPUS_PATH = f'{BASE_DIR}/ragas.json'

SAMPLE_SOURCE = 'guitar_placeholder'  # change to 'mandolin' to switch - the
                                        # only line that needs to change
SAMPLE_SOURCES = {
    'guitar_placeholder': {'dir': f'{BASE_DIR}/samples/guitar_placeholder', 'suffix': '_mf'},
    'mandolin': {'dir': f'{BASE_DIR}/samples/mandolin', 'suffix': '_mid'},
}

SAMPLE_RATE = 48000
BLOCKSIZE = 1024
MAX_VOICES = 16

KEYBOARD_NAME = "Logitech K400 Plus"
FALLBACK_DEVICE = "/dev/input/event0"

CHROMATIC = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

NOTE_KEYS = [ecodes.KEY_Z, ecodes.KEY_E, ecodes.KEY_R, ecodes.KEY_T,
             ecodes.KEY_Y, ecodes.KEY_7, ecodes.KEY_U]
KEY_NAMES = {
    ecodes.KEY_Z: 'z', ecodes.KEY_E: 'e', ecodes.KEY_R: 'r', ecodes.KEY_T: 't',
    ecodes.KEY_Y: 'y', ecodes.KEY_7: '7', ecodes.KEY_U: 'u',
}
OCTAVE_DOWN_KEY = ecodes.KEY_Q
OCTAVE_UP_KEY = ecodes.KEY_W
GAMAKAM_KEY = ecodes.KEY_SPACE

WRAP_UP_PREV_MIN_SLOT = 6   # previous key's slot must be >= this...
WRAP_UP_NEW_MAX_SLOT = 0    # ...and new key's slot <= this, to wrap up
WRAP_DOWN_PREV_MAX_SLOT = 0   # previous key's slot must be <= this...
WRAP_DOWN_NEW_MIN_SLOT = 6    # ...and new key's slot >= this, to wrap down


def note_to_index(note):
    """'A3' -> absolute semitone index, C0 = 0."""
    letter = note[:-1]
    octave = int(note[-1])
    return octave * 12 + CHROMATIC.index(letter)


def index_to_note(idx):
    octave, pc = divmod(idx, 12)
    return f'{CHROMATIC[pc]}{octave}'


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
    semitone from Sa - the raga's real distinct pitch inventory, not just
    whichever notes happen to appear ascending."""
    aro = set(strip_trailing_sa(raga['arohanam']))
    ava = set(strip_trailing_sa(raga['avarohanam']))
    union = aro | ava
    return sorted(union, key=lambda s: swara_semitones[s])


def position_to_semitones(pos, pattern, swara_semitones):
    octave, degree = divmod(pos, len(pattern))
    return octave * 12 + swara_semitones[pattern[degree]]


def position_to_swara(pos, pattern):
    """For audava/shadava ragas (fewer than 7 distinct pitches), keys past
    the pattern's length continue into the next octave rather than
    IndexError-ing - same wraparound as position_to_semitones."""
    _, degree = divmod(pos, len(pattern))
    return pattern[degree]


class SampleBank:
    def __init__(self, source):
        cfg = SAMPLE_SOURCES[source]
        self.dir = cfg['dir']
        self.suffix = cfg['suffix']
        self.available_indices = set()
        for idx in range(0, 120):
            name = index_to_note(idx).lower()
            if os.path.exists(os.path.join(self.dir, f'{name}{self.suffix}.wav')):
                self.available_indices.add(idx)
        self._cache = {}
        if not self.available_indices:
            print(f"Error: no samples found in {self.dir} matching *{self.suffix}.wav", file=sys.stderr)
            sys.exit(1)

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
                raise RuntimeError(f'{path} is {sr}Hz, expected {SAMPLE_RATE}Hz - '
                                    f'samples must already match the pipeline rate')
            self._cache[idx] = audio
        clamped_note = index_to_note(idx)
        exact = (idx == target_idx)
        return self._cache[idx], clamped_note, exact


# Fixed voice-slot pool, mixed together in the audio callback. A slot is
# either None or {'samples': ndarray, 'pos': float}. Replacing a slot is a
# single atomic assignment (see module docstring) - safe to do from the
# evdev thread while the audio callback concurrently reads other slots.
voices = [None] * MAX_VOICES
_next_slot = 0
_slot_lock = threading.Lock()  # only guards _next_slot's round-robin advance


def trigger_voice(samples):
    global _next_slot
    with _slot_lock:
        slot = _next_slot
        _next_slot = (_next_slot + 1) % MAX_VOICES
    voices[slot] = {'samples': samples, 'pos': 0.0}


def audio_callback(outdata, frames, time_info, status):
    if status:
        pass
    mix = np.zeros(frames, dtype=np.float32)
    for i in range(MAX_VOICES):
        v = voices[i]
        if v is None:
            continue
        samples = v['samples']
        n = len(samples)
        pos = v['pos']
        start = int(pos)
        end = min(start + frames, n)
        length = end - start
        if length > 0:
            mix[:length] += samples[start:end]
        new_pos = pos + frames
        if new_pos >= n:
            voices[i] = None  # finished
        else:
            v['pos'] = new_pos
    mix *= 0.6  # headroom for multiple simultaneous voices before clipping
    np.clip(mix, -1.0, 1.0, out=mix)
    outdata[:, 0] = mix


def find_keyboard():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == KEYBOARD_NAME:
            return dev
    return evdev.InputDevice(FALLBACK_DEVICE)


def parse_args():
    parser = argparse.ArgumentParser(description='7-key raga prototype with automatic octave rollover')
    parser.add_argument('--raga', required=True, help='raga name from the corpus, e.g. Mohanam')
    parser.add_argument('--sa', default='A3', help='reference tonic pitch, e.g. A3 (default A3)')
    return parser.parse_args()


def print_mapping(pattern, octave_shift):
    # always show all 7 key positions, even for a shorter (audava/shadava)
    # pattern where keys past its length wrap into the next octave
    swaras = [position_to_swara(i, pattern) for i in range(len(NOTE_KEYS))]
    print(f"  mapping (z..u): {' '.join(swaras)}  [octave={octave_shift:+d}]", flush=True)


def play_slot(slot, pattern, swara_semitones, sa_idx, bank, octave_shift):
    swara = position_to_swara(slot, pattern)
    semitones = position_to_semitones(slot, pattern, swara_semitones) + 12 * octave_shift
    target_idx = sa_idx + semitones
    samples, played_note, exact = bank.get(target_idx)
    trigger_voice(samples)
    tag = '' if exact else f' (nearest available, target was {index_to_note(target_idx)})'
    print(f"  key{slot+1}({KEY_NAMES[NOTE_KEYS[slot]]}) -> swara={swara} -> {played_note}{tag}", flush=True)


def run(dev, pattern, swara_semitones, sa_idx, bank):
    octave_shift = 0
    last_slot = None

    print(f"Keys: z e r t y 7 u = swara positions 1-7 (Sa always on z). "
          f"q = octave down, w = octave up, space = gamakam (not yet functional).", flush=True)
    print_mapping(pattern, octave_shift)

    for event in dev.read_loop():
        if event.type != ecodes.EV_KEY or event.value != 1:
            continue
        code = event.code

        if code == GAMAKAM_KEY:
            print("  (gamakam key pressed - not yet implemented)", flush=True)
            continue

        if code in (OCTAVE_DOWN_KEY, OCTAVE_UP_KEY):
            old = octave_shift
            octave_shift += -1 if code == OCTAVE_DOWN_KEY else 1
            ts = time.strftime('%H:%M:%S')
            direction = 'DOWN' if code == OCTAVE_DOWN_KEY else 'UP'
            print(f"[{ts}] MANUAL OCTAVE {direction} -> {old:+d} -> {octave_shift:+d}", flush=True)
            print_mapping(pattern, octave_shift)
            continue

        if code not in NOTE_KEYS:
            continue
        slot = NOTE_KEYS.index(code)

        if last_slot is not None:
            if last_slot >= WRAP_UP_PREV_MIN_SLOT and slot <= WRAP_UP_NEW_MAX_SLOT:
                old = octave_shift
                octave_shift += 1
                ts = time.strftime('%H:%M:%S')
                print(f"[{ts}] AUTO ROLLOVER UP (key{last_slot+1}->key{slot+1}) "
                      f"-> {old:+d} -> {octave_shift:+d}", flush=True)
            elif last_slot <= WRAP_DOWN_PREV_MAX_SLOT and slot >= WRAP_DOWN_NEW_MIN_SLOT:
                old = octave_shift
                octave_shift -= 1
                ts = time.strftime('%H:%M:%S')
                print(f"[{ts}] AUTO ROLLOVER DOWN (key{last_slot+1}->key{slot+1}) "
                      f"-> {old:+d} -> {octave_shift:+d}", flush=True)

        play_slot(slot, pattern, swara_semitones, sa_idx, bank, octave_shift)
        last_slot = slot


def main():
    args = parse_args()
    swara_semitones, ragas_by_name = load_raga_corpus(RAGA_CORPUS_PATH)
    raga = find_raga(ragas_by_name, args.raga)

    pattern = distinct_pitch_set(raga, swara_semitones)
    if len(pattern) > len(NOTE_KEYS):
        print(f"Error: {raga['name']} has {len(pattern)} distinct pitches "
              f"({' '.join(pattern)}) - more than the {len(NOTE_KEYS)} available "
              f"note keys. Not supported in this version (no variant-key "
              f"workaround has been built yet).", file=sys.stderr)
        sys.exit(1)

    sa_idx = note_to_index(args.sa.upper())

    stream = sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                              dtype='float32', callback=audio_callback)
    bank = SampleBank(SAMPLE_SOURCE)

    print(f"Raga: {raga['name']}  distinct pitches: {' '.join(pattern)}  "
          f"Sa={args.sa.upper()} (idx {sa_idx})  sample source: {SAMPLE_SOURCE}", flush=True)

    dev = find_keyboard()
    print(f"Listening on {dev.path} ({dev.name}). Ctrl+C to quit.", flush=True)

    try:
        with stream:
            run(dev, pattern, swara_semitones, sa_idx, bank)
    except KeyboardInterrupt:
        print("\nExiting.", flush=True)


if __name__ == '__main__':
    main()
