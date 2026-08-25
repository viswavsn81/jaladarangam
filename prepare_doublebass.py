#!/usr/bin/env python3
"""One-time preprocessing: derive the C#1 and C#2 double bass drone loops
from their raw source recordings (University of Iowa MIS database, see
samples/doublebass/PROVENANCE.md), correcting each to exact equal-
temperament pitch via the same measured-pitch + linear-interpolation
varispeed approach as gamaka.py's portamento (reusing detect_pitch and
linear_resample from mandolin_audio.py, not reimplementing pitch
correction), then building a seamless crossfaded loop for continuous
sustain."""
import numpy as np
import soundfile as sf
import mandolin_audio as ma

TARGET_RATE = ma.SAMPLE_RATE  # 48000, matches this project's audio pipeline
NORMALIZE_PEAK = 0.45  # the loop region (attack transient trimmed off, to
                        # avoid a repeating click) is much quieter than the
                        # pluck's onset - normalize to roughly the mandolin
                        # samples' own peak level (~0.35-0.5) so the drone
                        # isn't lost under the melodic notes once mixed.


def note_hz(midi):
    """Equal-temperament frequency for a MIDI note number, A4=440Hz."""
    return 440.0 * 2 ** ((midi - 69) / 12)


def make_seamless_loop(audio, sr, attack_skip_s, tail_trim_s, crossfade_s):
    """Skip the pluck's attack transient and a bit of near-silent tail,
    then crossfade the remaining tail back into the head so the clip
    can repeat indefinitely without an audible seam at the wrap point -
    the standard sampler technique for looping a decaying/sustained
    recording that was never actually infinite."""
    start = int(attack_skip_s * sr)
    end = len(audio) - int(tail_trim_s * sr)
    seg = audio[start:end].copy()
    cf = int(crossfade_s * sr)
    fade = np.linspace(0.0, 1.0, cf, dtype=np.float32)
    blended_tail = seg[-cf:] * (1 - fade) + seg[:cf] * fade
    seg[-cf:] = blended_tail
    return seg


def process(src_path, target_midi, out_path, fmin, fmax,
            attack_skip_s=0.2, tail_trim_s=0.3, crossfade_s=0.25):
    audio, sr = sf.read(src_path, dtype='float32', always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)

    measured_hz = ma.detect_pitch(audio, sr=sr, fmin=fmin, fmax=fmax)
    target_hz = note_hz(target_midi)
    pitch_stride = target_hz / measured_hz  # >1 raises pitch, <1 lowers it
    print(f"{src_path}: measured {measured_hz:.2f}Hz, target {target_hz:.2f}Hz, "
          f"correcting by {1200*np.log2(target_hz/measured_hz):+.1f} cents")

    audio = ma.linear_resample(audio, sr / TARGET_RATE)  # sample-rate convert
    audio = ma.linear_resample(audio, pitch_stride)       # pitch correction

    looped = make_seamless_loop(audio, TARGET_RATE, attack_skip_s, tail_trim_s, crossfade_s)
    looped = looped * (NORMALIZE_PEAK / np.max(np.abs(looped)))
    sf.write(out_path, looped, TARGET_RATE, subtype='PCM_16')

    verify_hz = ma.detect_pitch(looped, sr=TARGET_RATE, fmin=fmin, fmax=fmax)
    print(f"  -> {out_path}: {len(looped)/TARGET_RATE:.2f}s loop @ {TARGET_RATE}Hz, "
          f"verified {verify_hz:.2f}Hz ({1200*np.log2(verify_hz/target_hz):+.1f}c off target)")


process('samples/_src_doublebass_csharp1.wav', 25, 'samples/doublebass/csharp1_mf.wav',
        fmin=20.0, fmax=100.0)
process('samples/_src_doublebass_csharp2.wav', 37, 'samples/doublebass/csharp2_mf.wav',
        fmin=40.0, fmax=200.0)
