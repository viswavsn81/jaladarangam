# Double bass drone samples - provenance

Source: University of Iowa Electronic Music Studios, Musical Instrument
Samples database - https://theremin.music.uiowa.edu/MISdoublebass2012.html
(the 2012 recordings, which include the sulC low-C-extension string; the
older MISdoublebass.html set only goes down to E1 and doesn't cover C#1).

License: per the MIS database's own usage statement
(https://theremin.music.uiowa.edu/MIS.html), these recordings "may be
downloaded and used for any projects, without restrictions." Same source
and license as samples/guitar_placeholder.

Articulation: pizzicato (plucked), mf (mezzo-forte) dynamic, mono AIFF -
matches the plucked-string character of the rest of the instrument.

Source files downloaded:
- `Bass.pizz.sulC.mf.C1Eb1.mono.aif` - a chromatic run of C1, C#1, D1, Eb1
  concatenated in one file, not individual notes.
- `Bass.pizz.sulA.mf.C2B2.mono.aif` - chromatic run of all 12 notes C2
  through B2.

Processing:
1. Split into individual notes via onset detection (short-time RMS
   envelope, threshold crossings merged with a >=2.5s minimum gap - the
   very low fundamentals here have slow, complex envelopes that produce
   spurious extra crossings at a shorter gap). Segment count and order
   cross-checked against the chromatic sequence implied by each
   filename's range (4 notes for C1Eb1, 12 for C2B2) - both matched
   exactly. Only the 2nd segment of each file (C#1, C#2) was kept; see
   `samples/_src_doublebass_csharp1.wav` and `_src_doublebass_csharp2.wav`
   in the parent samples/ dir for the isolated raw extracts (44100Hz, as
   recorded, pitch not yet corrected).
2. Pitch measured via mandolin_audio.detect_pitch (the same autocorrelation
   approach gamaka.py uses for its portamento) - C#1 measured 34.53Hz,
   C#2 measured 68.58Hz, both ~6-18 cents flat of exact equal-temperament
   (C#1=34.65Hz, C#2=69.30Hz, A4=440). Corrected via
   mandolin_audio.linear_resample (the same varispeed resampler used
   throughout this project, e.g. prepare_samples.py), same technique as
   gamaka.py's bend-to-exact-pitch, not assumed already in tune. Verified
   after correction: both land within 3 cents of target.
3. Resampled to 48000Hz to match this project's audio pipeline.
4. Looped for continuous sustain: a real pizzicato note decays rather than
   sustaining forever, so there's no way to loop it without *some* seam.
   The attack transient (~0.2s) and the last ~0.3s (mostly silence/noise
   floor) are trimmed, then the tail is crossfaded into the head over
   0.25s (linear crossfade) - the standard sampler technique for looping
   a decaying recording. This does not achieve bit-exact continuity, only
   a perceptually smoothed transition; if the seam turns out to be
   audible in practice, first things to try are a longer crossfade or a
   different loop-start point (see `prepare_doublebass.py`).
5. Normalized to peak amplitude 0.45 (the loop region, with the loud
   attack trimmed off, is much quieter than the raw pluck) - comparable
   to the mandolin samples' own peak range (~0.35-0.5), so the drone
   isn't lost once mixed under the melodic notes.

File naming: `csharp{1,2}_mf.wav`, mono, 48000Hz, matching this project's
existing sample-set conventions.

Regenerate with: `python3 prepare_doublebass.py` (reads the two
`_src_doublebass_*.wav` files, writes the two files in this directory).
