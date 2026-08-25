#!/usr/bin/env python3
"""One-time preprocessing: split the University of Iowa alto flute source
recordings (samples/_src_flute_*.aif) into individual notes and write
samples/flute_placeholder/<note>_mf.wav, 48000Hz mono, matching this
project's existing sample-set conventions (guitar_placeholder,
doublebass). See samples/flute_placeholder/PROVENANCE.md for full
details on the source and the onset-detection splitting approach (same
technique already used for guitar_placeholder and the double bass
drone in this project)."""
import numpy as np
import soundfile as sf
import mandolin_audio as ma

TARGET_RATE = ma.SAMPLE_RATE

CHROMATIC = ['c', 'db', 'd', 'eb', 'e', 'f', 'gb', 'g', 'ab', 'a', 'bb', 'b']


def note_hz(name):
    """'g3' -> Hz, equal temperament, A4=440. Used only to give
    detect_pitch a tight search window (+-~2.5 semitones) around each
    note's expected pitch - flutes have much weaker fundamentals than
    the plucked strings this pitch detector was validated against, so a
    single broad fmin/fmax for a whole file let autocorrelation lock
    onto a strong overtone instead of the true fundamental for several
    of the higher notes (measured directly: e.g. bb4 came back at
    461.5Hz, a clean octave-plus-a-bit off). Narrowing the window per
    note, informed by the note's own expected identity, fixes this
    without abandoning the same measured-pitch approach used everywhere
    else in this project."""
    letter, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((octave - 4) + (CHROMATIC.index(letter) - 9) / 12)

SOURCES = [
    # (file, expected notes in order, onset min-gap seconds)
    ('samples/_src_flute_G3B3.aif', ['g3', 'ab3', 'a3', 'bb3', 'b3'], 1.0),
    ('samples/_src_flute_C4B4.aif', ['c4', 'db4', 'd4', 'eb4', 'e4', 'f4', 'gb4',
                                      'g4', 'ab4', 'a4', 'bb4', 'b4'], 1.0),
    ('samples/_src_flute_C5B5.aif', ['c5', 'db5', 'd5', 'eb5', 'e5', 'f5', 'gb5',
                                      'g5', 'ab5', 'a5', 'bb5', 'b5'], 1.0),
    ('samples/_src_flute_C6G6.aif', ['c6', 'db6', 'd6', 'eb6', 'e6', 'f6', 'gb6', 'g6'], 2.5),
]


def segment_by_onsets(audio, sr, min_gap_s, thresh_ratio=0.08):
    win = int(0.02 * sr)
    hop = int(0.01 * sr)
    n_frames = (len(audio) - win) // hop
    env = np.array([np.sqrt(np.mean(audio[i * hop:i * hop + win] ** 2)) for i in range(n_frames)])
    thresh = env.max() * thresh_ratio
    above = env > thresh
    onsets = [i * hop for i in range(1, len(above)) if above[i] and not above[i - 1]]
    merged = []
    for o in onsets:
        if not merged or (o - merged[-1]) > int(min_gap_s * sr):
            merged.append(o)
    return merged


for path, expected_notes, min_gap in SOURCES:
    audio, sr = sf.read(path, dtype='float32', always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    onsets = segment_by_onsets(audio, sr, min_gap)
    onsets.append(len(audio))
    if len(onsets) - 1 != len(expected_notes):
        print(f"{path}: onset count {len(onsets)-1} != expected {len(expected_notes)} "
              f"- SKIPPING this file, not trusting the split (same policy as "
              f"guitar_placeholder's provenance: exclude rather than guess)")
        continue
    for i, note in enumerate(expected_notes):
        seg = audio[onsets[i]:onsets[i + 1]]
        seg48k = ma.linear_resample(seg, sr / TARGET_RATE) if sr != TARGET_RATE else seg
        out_path = f'samples/flute_placeholder/{note}_mf.wav'
        sf.write(out_path, seg48k, TARGET_RATE, subtype='PCM_16')
        expected_hz = note_hz(note)
        measured_hz = ma.detect_pitch(seg48k, sr=TARGET_RATE,
                                       fmin=expected_hz * 0.84, fmax=expected_hz * 1.19)
        off_cents = 1200 * np.log2(measured_hz / expected_hz)
        flag = '  <-- >30c off, check' if abs(off_cents) > 30 else ''
        print(f"  {note}_mf.wav: {len(seg48k)/TARGET_RATE:.2f}s, expected {expected_hz:.1f}Hz, "
              f"measured {measured_hz:.1f}Hz ({off_cents:+.0f}c){flag}")
