#!/usr/bin/env python3
"""One-time preprocessing: derive D3 and G3 guitar plucks from the eb3/gb3
source samples (karoryfer.shinyguitar, CC0) via a 1-semitone pitch shift,
and resample to 48000Hz to match this Pi audio graphs quantum."""
import numpy as np
import soundfile as sf

TARGET_RATE = 48000

def linear_resample(x, stride):
    # stride > 1 speeds through the source faster -> fewer output samples -> pitch/tempo up
    n_out = int(len(x) / stride)
    src_idx = np.arange(n_out) * stride
    i0 = np.floor(src_idx).astype(np.int64)
    frac = src_idx - i0
    i0 = np.clip(i0, 0, len(x) - 2)
    return (1 - frac) * x[i0] + frac * x[i0 + 1]

def process(src_path, semitone_shift, out_path):
    audio, sr = sf.read(src_path, dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio[:, 0]
    audio = linear_resample(audio, sr / TARGET_RATE)          # sample-rate convert to 48000
    pitch_stride = 2 ** (semitone_shift / 12)                  # positive = shift up
    audio = linear_resample(audio, pitch_stride)                # apply pitch shift
    sf.write(out_path, audio, TARGET_RATE, subtype="PCM_16")
    print(f"{out_path}: {len(audio)} samples, {len(audio)/TARGET_RATE:.2f}s @ {TARGET_RATE}Hz")

process("samples/_src_eb3.wav", -1, "samples/d3_pluck.wav")   # Eb3 -> D3 (down 1 semitone)
process("samples/_src_gb3.wav", 1, "samples/g3_pluck.wav")    # Gb3 -> G3 (up 1 semitone)
