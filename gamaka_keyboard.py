#!/usr/bin/env python3
"""Keyboard-driven mandolin player, for quick feel-testing without the
physical FSR rig. Reuses gamaka.py's validated engine pieces from
mandolin_audio.py - variable-rate playback, measured-interval portamento
via pitch-detection, and the ramp/output-stage math - rather than
reimplementing any of it.

Usage:
    python3 gamaka_keyboard.py

Only sa/ri/ga/ma/pa are recorded, mapped to 5 keys (left-to-right on the
home/top row, right hand):
    z = sa   e = ri   r = ga   t = ma   y = pa

Behavior (monophonic, one voice at a time - same model as gamaka.py):
  - A note key alone = a fresh pluck: restarts that note's sample from
    the top, no bend.
  - shift + a note key, while a voice is already actively ringing = a
    jaru: does NOT retrigger or restart a sample. Instead it glides the
    CURRENTLY RINGING voice's pitch from wherever it is right now to the
    new key's measured pitch, over JARU_GLIDE_SECONDS - the same
    measured-interval-via-pitch-detection approach as gamaka.py's FSR
    jaru, not a hardcoded swara-to-semitone table. If a new jaru starts
    while a previous one is still gliding, it retargets smoothly from the
    current in-flight position rather than restarting.
  - shift + a note key, with nothing currently ringing = nothing to
    glide from, so it plucks fresh instead (and says so).
  - Releasing shift has no effect on a glide already in progress - once
    triggered, it completes on its own.

The glide itself is computed inside the audio callback each block (a
few floating-point ops - time.monotonic() plus mandolin_audio.ramp_cents
- not the blocking SPI reads gamaka.py's control loop exists to keep out
of the callback), so no separate ticking thread is needed the way
gamaka.py's control_loop is for polling hardware.

A double bass drone plays independently of and simultaneously with the
note keys above, as a separate always-on layer - it doesn't interrupt or
get interrupted by plucks/jaru. Controlled over stdin (typed + Enter, the
same convention gamaka.py's bass-boost diagnostic used), not the evdev
note keys, since it's a background layer rather than a performance
gesture:
    'b' + Enter: toggle the drone on (starts at C#1), or cycle it to the
                 other octave if it's already playing (C#1<->C#2).
    'c' + Enter: stop the drone entirely.
The drone samples are pitch-corrected, looped double bass pizzicato
recordings - see samples/doublebass/PROVENANCE.md for how they were
derived (measured-pitch correction via the same detect_pitch approach as
gamaka.py's portamento, then crossfaded into a seamless loop, since a
real pluck decays rather than sustaining forever).
"""
import argparse
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

JARU_GLIDE_SECONDS = ma.JARU_GLIDE_SECONDS  # 200ms default portamento duration

KEYBOARD_NAME = "Logitech K400 Plus"
FALLBACK_DEVICE = "/dev/input/event0"

NOTE_KEYS = {
    ecodes.KEY_Z: 'sa',
    ecodes.KEY_E: 'ri',
    ecodes.KEY_R: 'ga',
    ecodes.KEY_T: 'ma',
    ecodes.KEY_Y: 'pa',
}
SHIFT_KEYS = (ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT)

DRONE_DIR = f'{ma.BASE_DIR}/samples/doublebass'
DRONE_OCTAVES = (1, 2)  # C#1, C#2 - cycle order on repeated 'b' presses
DRONE_MIX_LEVEL = 0.07  # NOT a subtle background-mix choice - the drone's
                         # fundamental (C#1/C#2, ~35-70Hz) sits almost
                         # entirely inside BASS_BOOST_DB's flat-boosted
                         # region, unlike the mandolin notes (277-417Hz,
                         # well above the shelf's corner). Measured directly
                         # (not assumed): the drone loop alone, through the
                         # shared 14dB boost + 1.3x gain, hits a true
                         # unclipped peak of 2.55 (+8.1dBFS) at full level -
                         # it would clip badly on its own before any melodic
                         # note is even added. 0.07 was solved from that
                         # measurement to land the drone alone around
                         # -15dBFS; checked against all 5 notes x both
                         # octaves at full block overlap (worst case),
                         # nothing clips (worst margin: ri+C#2 at -0.97dBFS).


def parse_args():
    parser = argparse.ArgumentParser(description='Keyboard-driven mandolin player.')
    parser.add_argument('--bass-boost-db', type=float, default=ma.BASS_BOOST_DB,
                         help=f'low-shelf bass boost in dB, applied below '
                              f'{ma.BASS_BOOST_FREQ_HZ:.0f}Hz (default {ma.BASS_BOOST_DB:.0f}, '
                              f'0 disables it)')
    return parser.parse_args()


def find_keyboard():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == KEYBOARD_NAME:
            return dev
    return evdev.InputDevice(FALLBACK_DEVICE)


# Preload every note's sample + measured pitch up front, same as gamaka.py's
# build_voices - the bend/glide math always needs the actual measured pitch,
# never an assumed note-name table.
def load_notes():
    notes = {}
    for note in NOTE_KEYS.values():
        samples = ma.load_sample(note, label=note)
        pitch_hz = ma.detect_pitch(samples)
        notes[note] = {'samples': samples, 'pitch_hz': pitch_hz}
    return notes


def load_drone_samples():
    """The two pre-corrected, pre-looped drone WAVs (see
    samples/doublebass/PROVENANCE.md / prepare_doublebass.py) - already at
    exact pitch and already seamless, so this just reads them, no further
    pitch or loop processing at runtime."""
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


# Monophonic model, same as gamaka.py: at most one voice ringing at a time.
# active_voice is None or {'samples','pos','rate','active','pitch_hz','note'}.
active_voice = None
# None, or (start_cents, target_cents, start_time) - read+updated inside the
# audio callback each block; retargeted (not restarted) by a new jaru while
# one is already in flight.
glide = None

# Independent drone layer. drone_octave is None (off), 1, or 2 - the
# source of truth for what's printed/toggled. drone_voice is None or
# {'samples','pos','rate'} (no 'active' - the drone doesn't self-stop,
# only 'c' or a fresh 'b' cycle changes it), read by the audio callback
# via ma.advance_voice_loop.
drone_octave = None
drone_voice = None


def audio_callback(outdata, frames, time_info, status):
    global glide
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
    mix = ma.finalize_output(mix, boost_shelf)
    outdata[:, 0] = mix


def pluck(note):
    global active_voice, glide
    n = NOTES[note]
    active_voice = {'samples': n['samples'], 'pos': 0.0, 'rate': 1.0,
                     'active': True, 'pitch_hz': n['pitch_hz'], 'note': note}
    glide = None
    print(f"PLUCK -> {note} ({n['pitch_hz']:.1f} Hz)", flush=True)


def start_jaru(note):
    global glide
    v = active_voice
    target_cents = ma.cents_between(v['pitch_hz'], NOTES[note]['pitch_hz'])
    current_cents = 1200.0 * np.log2(v['rate'])
    glide = (current_cents, target_cents, time.monotonic())
    print(f"JARU -> {v['note']} sliding to {note} ({target_cents:+.1f}c over "
          f"{JARU_GLIDE_SECONDS * 1000:.0f}ms)", flush=True)


def toggle_drone():
    """'b': off -> C#1; C#1 -> C#2; C#2 -> C#1. Always resets playback
    position to 0 on a change - the two octaves are different recordings
    (not a bend of one into the other), so a hard cut between them is
    expected, not a discontinuity to smooth over."""
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


def drone_listener():
    """Reads lines from stdin: 'b' toggles/cycles the drone, 'c' stops it
    - typed + Enter, the same convention gamaka.py's bass-boost diagnostic
    used, deliberately separate from the evdev note keys since this is a
    background layer, not a performance gesture. Runs as a daemon thread
    so a non-interactive stdin (EOF) just ends it quietly."""
    for line in sys.stdin:
        cmd = line.strip().lower()
        if cmd == 'b':
            toggle_drone()
        elif cmd == 'c':
            stop_drone()


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

        if event.value != 1 or event.code not in NOTE_KEYS:
            continue  # only fresh key-down presses on note keys trigger anything
        note = NOTE_KEYS[event.code]

        ringing = active_voice is not None and active_voice['active']
        if shift_held and ringing:
            start_jaru(note)
        else:
            if shift_held and not ringing:
                print(f"(shift+{note}: nothing currently ringing to glide from - "
                      f"plucking instead)", flush=True)
            pluck(note)

        print(f"  active={active_voice['note'] if active_voice else None}  "
              f"jaru_in_progress={glide is not None}", flush=True)


def main():
    global boost_shelf, NOTES, DRONE_SAMPLES
    args = parse_args()
    NOTES = load_notes()
    DRONE_SAMPLES = load_drone_samples()
    boost_shelf = ma.make_bass_boost(args.bass_boost_db)

    print('Keyboard mandolin player running. Ctrl+C to stop.', flush=True)
    print('  z=sa  e=ri  r=ga  t=ma  y=pa   (shift+key while a note rings = jaru glide)', flush=True)
    for note, n in NOTES.items():
        print(f"  {note}: measured {n['pitch_hz']:.1f} Hz", flush=True)
    print(f"Bass boost: {'+%.0fdB @ %.0fHz' % (args.bass_boost_db, ma.BASS_BOOST_FREQ_HZ) if args.bass_boost_db > 0 else 'off'} "
          f"(--bass-boost-db to change)", flush=True)
    print("Double bass drone: 'b'+Enter = toggle on (C#1) / cycle octave, "
          "'c'+Enter = off. [drone] off", flush=True)

    dev = find_keyboard()
    print(f"Listening on {dev.path} ({dev.name}).", flush=True)

    drone_thread = threading.Thread(target=drone_listener, daemon=True)
    drone_thread.start()

    try:
        with sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                              dtype='float32', callback=audio_callback):
            run(dev)
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == '__main__':
    main()
