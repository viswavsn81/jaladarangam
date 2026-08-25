"""Shared audio engine for the mandolin instrument scripts (gamaka.py,
gamaka_keyboard.py): sample loading + pitch measurement, the variable-rate
single-voice playback model, ramp interpolation, and the output stage
(bass boost + gain + clip). Extracted so gamaka.py's hard-won pieces -
measured-interval portamento via pitch-detection, variable-rate playback,
and smooth ramping - aren't reimplemented from scratch for the keyboard
version, and so the bass boost lives in exactly one place.
"""
import glob
import os
import sys
import numpy as np
import soundfile as sf
from scipy.signal import lfilter

SAMPLE_RATE = 48000
BLOCKSIZE = 1024

BASE_DIR = '/home/pyru1/mindfulness-instrument'
MANDOLIN_DIR = f'{BASE_DIR}/samples/mandolin'
STRESS_LEVEL = 'mid'  # only stress level recorded so far

# Output stage. BASS_BOOST_DB was a live b/c-toggle diagnostic in gamaka.py
# during A/B testing on the exciter; it tested well and is now a normal
# default (still overridable via each script's --bass-boost-db flag), not
# a runtime toggle. EXISTING_GAIN is gamaka.py's earlier 0.8->1.3 headroom
# bump, kept as one named constant here so it's applied consistently
# wherever audio is rendered rather than duplicated per script.
BASS_BOOST_DB = 14.0
BASS_BOOST_FREQ_HZ = 180.0
EXISTING_GAIN = 1.3

JARU_GLIDE_SECONDS = 0.2  # default portamento duration for a keyboard jaru


class LowShelf:
    """RBJ audio-EQ-cookbook low-shelf biquad. Uses scipy.signal.lfilter
    (C-level, vectorized) rather than a per-sample Python loop - measured
    on the Pi, a naive per-sample loop took 573ms for a 1.5s buffer (at
    BLOCKSIZE=1024 that's ~8ms of a ~21ms callback budget, enough to risk
    audible glitching), where lfilter takes ~5ms for the same buffer.
    State (zi) carries across calls so streaming stays click-free at
    block boundaries."""
    def __init__(self, fs, f0, gain_db, shelf_slope=1.0):
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * f0 / fs
        alpha = np.sin(w0) / 2 * np.sqrt((A + 1 / A) * (1 / shelf_slope - 1) + 2)
        cos_w0 = np.cos(w0)
        sqrt_a = np.sqrt(A)
        b0 = A * ((A + 1) - (A - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = 2 * A * ((A - 1) - (A + 1) * cos_w0)
        b2 = A * ((A + 1) - (A - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (A + 1) + (A - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = -2 * ((A - 1) + (A + 1) * cos_w0)
        a2 = (A + 1) + (A - 1) * cos_w0 - 2 * sqrt_a * alpha
        self.b = np.array([b0, b1, b2]) / a0
        self.a = np.array([1.0, a1 / a0, a2 / a0])
        self.zi = np.zeros(2)

    def process(self, x):
        y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
        return y.astype(np.float32)


def make_bass_boost(gain_db=BASS_BOOST_DB, freq_hz=BASS_BOOST_FREQ_HZ):
    """A LowShelf configured for the bass boost, or None (bypass) if
    gain_db <= 0."""
    return LowShelf(SAMPLE_RATE, freq_hz, gain_db) if gain_db > 0 else None


class HighShelf:
    """RBJ audio-EQ-cookbook high-shelf biquad - same lfilter-based
    approach as LowShelf (see that class for why: a per-sample Python
    loop measured 573ms for a 1.5s buffer on this Pi, ~100x too slow for
    both real-time use and an interactive clipping-check predictor)."""
    def __init__(self, fs, f0, gain_db, shelf_slope=1.0):
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * f0 / fs
        alpha = np.sin(w0) / 2 * np.sqrt((A + 1 / A) * (1 / shelf_slope - 1) + 2)
        cos_w0 = np.cos(w0)
        sqrt_a = np.sqrt(A)
        b0 = A * ((A + 1) + (A - 1) * cos_w0 + 2 * sqrt_a * alpha)
        b1 = -2 * A * ((A - 1) + (A + 1) * cos_w0)
        b2 = A * ((A + 1) + (A - 1) * cos_w0 - 2 * sqrt_a * alpha)
        a0 = (A + 1) - (A - 1) * cos_w0 + 2 * sqrt_a * alpha
        a1 = 2 * ((A - 1) - (A + 1) * cos_w0)
        a2 = (A + 1) - (A - 1) * cos_w0 - 2 * sqrt_a * alpha
        self.b = np.array([b0, b1, b2]) / a0
        self.a = np.array([1.0, a1 / a0, a2 / a0])
        self.zi = np.zeros(2)

    def process(self, x):
        y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
        return y.astype(np.float32)


class PeakingEQ:
    """RBJ audio-EQ-cookbook peaking (bell) biquad - boosts/cuts around a
    center frequency rather than above/below a corner. Same lfilter-based
    approach as LowShelf/HighShelf."""
    def __init__(self, fs, f0, gain_db, q=0.7):
        A = 10 ** (gain_db / 40)
        w0 = 2 * np.pi * f0 / fs
        alpha = np.sin(w0) / (2 * q)
        cos_w0 = np.cos(w0)
        b0 = 1 + alpha * A
        b1 = -2 * cos_w0
        b2 = 1 - alpha * A
        a0 = 1 + alpha / A
        a1 = -2 * cos_w0
        a2 = 1 - alpha / A
        self.b = np.array([b0, b1, b2]) / a0
        self.a = np.array([1.0, a1 / a0, a2 / a0])
        self.zi = np.zeros(2)

    def process(self, x):
        y, self.zi = lfilter(self.b, self.a, x, zi=self.zi)
        return y.astype(np.float32)


def finalize_output(mix, boost_shelf, gain=EXISTING_GAIN):
    """The output stage every script's audio callback should end with:
    bass boost -> gain -> clip. The one place the boost is applied,
    regardless of which script is rendering."""
    if boost_shelf is not None:
        mix = boost_shelf.process(mix)
    mix = mix * gain
    np.clip(mix, -1.0, 1.0, out=mix)
    return mix


def linear_resample(x, stride):
    # stride > 1 speeds through the source faster -> fewer output samples
    n_out = int(len(x) / stride)
    src_idx = np.arange(n_out) * stride
    i0 = np.floor(src_idx).astype(np.int64)
    frac = src_idx - i0
    i0 = np.clip(i0, 0, len(x) - 2)
    return (1 - frac) * x[i0] + frac * x[i0 + 1]


def available_notes(sample_dir=MANDOLIN_DIR, stress_level=STRESS_LEVEL):
    """Notes currently on disk (for error messages) - discovered from the
    directory rather than assumed, since the note set isn't fixed yet."""
    pattern = os.path.join(sample_dir, f'*_{stress_level}.wav')
    suffix = f'_{stress_level}.wav'
    return sorted(os.path.basename(p)[:-len(suffix)] for p in glob.glob(pattern))


def load_sample(note, stress_level=STRESS_LEVEL, sample_dir=MANDOLIN_DIR, label=None):
    """Look up and load a recording by (note, stress_level), converting it
    to mono float32 at SAMPLE_RATE regardless of the source file's own
    channel count / sample rate."""
    path = f'{sample_dir}/{note}_{stress_level}.wav'
    if not os.path.exists(path):
        print(
            f"Error: no sample file for {label or note!r} "
            f"(expected {path}, which does not exist).\n"
            f"Notes currently available in {sample_dir}: "
            f"{', '.join(available_notes(sample_dir, stress_level)) or '(none found)'}",
            file=sys.stderr,
        )
        sys.exit(1)
    audio, sr = sf.read(path, dtype='float32', always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)  # downmix to mono
    if sr != SAMPLE_RATE:
        audio = linear_resample(audio, sr / SAMPLE_RATE)
    return audio


def detect_pitch(samples, sr=SAMPLE_RATE, fmin=60.0, fmax=1500.0):
    """Autocorrelation pitch estimate on a sustained window of the sample,
    computed via FFT (O(n log n)) rather than numpy's naive correlate
    (O(n^2), which took 10+ seconds per sample on the Pi's CPU). Skips the
    first 0.1s (onset transient) and analyzes a 0.4s window past that - not
    highly precise, but the actual bend range must come from the real
    recordings, not an assumed note-name table."""
    start = int(0.1 * sr)
    dur = int(0.4 * sr)
    seg = samples[start:start + dur].astype(np.float64)
    seg = seg - seg.mean()
    seg = seg * np.hanning(len(seg))
    n = len(seg)
    nfft = 1 << (2 * n - 1).bit_length()
    spectrum = np.fft.rfft(seg, n=nfft)
    corr = np.fft.irfft(spectrum * np.conj(spectrum), n=nfft)[:n]
    lag_min = int(sr / fmax)
    lag_max = min(int(sr / fmin), n - 1)
    corr_slice = corr[lag_min:lag_max]
    peak_lag = lag_min + int(np.argmax(corr_slice))
    return sr / peak_lag


def cents_between(f1_hz, f2_hz):
    """Measured interval in cents from f1 to f2 - always derived from the
    actual recordings' measured pitch, never an assumed swara-to-semitone
    table, since note pairs are arbitrary."""
    return 1200.0 * np.log2(f2_hz / f1_hz)


def ramp_cents(start_cents, target_cents, duration_s, elapsed_s):
    """Linear interpolation from start_cents to target_cents over
    duration_s, given elapsed_s since the ramp began. Returns
    (current_cents, done) - done is True once elapsed_s >= duration_s, at
    which point current_cents == target_cents exactly."""
    if duration_s <= 0:
        return target_cents, True
    frac = min(1.0, elapsed_s / duration_s)
    return start_cents + (target_cents - start_cents) * frac, frac >= 1.0


def advance_voice(voice, frames):
    """Render up to `frames` samples of a voice dict's current playback
    position/rate (variable-rate linear-interpolation read - this is what
    lets pitch bend continuously while a note rings, since pygame.mixer
    can't vary playback speed live per voice). Advances voice['pos'] and
    sets voice['active'] = False if the sample runs out mid-block.
    Returns a float32 array of length <= frames (shorter iff the sample
    ended mid-block) - the caller adds it into the front of its mix
    buffer, leaving the rest as silence.

    voice must have: 'samples' (1D float32 array), 'pos' (float),
    'rate' (float), 'active' (bool, only used for this function's own
    end-of-sample side effect)."""
    samples = voice['samples']
    n = len(samples)
    pos = voice['pos']
    rate = voice['rate']
    idx = pos + np.arange(frames) * rate
    end_mask = idx >= (n - 1)
    if np.any(end_mask):
        last_valid = int(np.argmax(end_mask))  # first True index
        idx = idx[:last_valid]
        voice['active'] = False  # sample finished on its own - not a release
    else:
        last_valid = frames
    if last_valid > 0:
        i0 = idx.astype(np.int64)
        frac = idx - i0
        out = (1 - frac) * samples[i0] + frac * samples[i0 + 1]
    else:
        out = np.zeros(0, dtype=np.float32)
    voice['pos'] = pos + last_valid * rate
    return out


def advance_voice_loop(voice, frames):
    """Like advance_voice, but wraps the position back to the start
    instead of deactivating at the end of the sample - for a
    continuously-sustained drone rather than a one-shot pluck. voice's
    'samples' should already be a seamless (crossfaded) loop; voice
    needs the same 'samples'/'pos'/'rate' fields as advance_voice but no
    'active' side effect - the caller controls on/off separately."""
    samples = voice['samples']
    n = len(samples)
    pos = voice['pos']
    rate = voice['rate']
    idx = (pos + np.arange(frames) * rate) % n
    i0 = idx.astype(np.int64)
    i1 = (i0 + 1) % n
    frac = idx - i0
    out = (1 - frac) * samples[i0] + frac * samples[i1]
    voice['pos'] = (pos + frames * rate) % n
    return out
