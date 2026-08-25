# Flute placeholder samples - provenance

Source: University of Iowa Electronic Music Studios, Musical Instrument
Samples database - https://theremin.music.uiowa.edu/MISaltoflute.html
Same source/license as samples/guitar_placeholder and
samples/doublebass.

License: per the MIS database's own usage statement
(https://theremin.music.uiowa.edu/MIS.html), "may be downloaded and
used for any projects, without restrictions."

Instrument: **Alto Flute**, not standard C Flute - chosen deliberately
for its lower/mellower register, as a possible fix for mandolin's
mids/highs sounding shrill. Vibrato articulation (the only articulation
this instrument was recorded with in this database), mf (mezzo-forte)
dynamic, matching this project's "mid dynamic" convention elsewhere.

Source files downloaded (4, covering the full recorded range):
- `_src_flute_G3B3.aif`, `_src_flute_C4B4.aif`, `_src_flute_C5B5.aif`,
  `_src_flute_C6G6.aif` - each a chromatic run of multiple notes
  concatenated (same pattern as guitar_placeholder and the double bass
  source files), not individual-note recordings.

Processing (`prepare_flute.py`):
1. Split into individual notes via onset detection (short-time RMS
   envelope, threshold crossings). Segment count cross-checked against
   the chromatic span implied by each filename (5/12/12/8 notes) -
   all 4 files matched exactly once C6G6 was given a longer minimum
   onset-gap (2.5s vs 1.0s for the others - its notes have longer
   decay/reverb tails at that register, which produced one spurious
   extra onset at the shorter gap).
2. Pitch measured via mandolin_audio.detect_pitch per note - but with a
   *narrow* search window (+-~2.5 semitones) centered on that note's own
   expected equal-temperament pitch, not one broad window for the whole
   file. This was necessary, not just careful: with a broad window,
   several higher notes came back autocorrelation-locked onto a strong
   overtone instead of the true fundamental (e.g. bb4 measured at
   461.5Hz, off by over an octave) - flutes have much weaker
   fundamentals relative to their overtones than the plucked strings
   this pitch detector was originally validated against (mandolin,
   guitar). With the narrowed per-note window, all 37 notes measured
   within 37 cents of their expected pitch, montonically consistent
   note-to-note - not corrected/retuned, left as measured, matching
   this project's existing convention for guitar_placeholder (documented
   there as "10-40 cents flat... not corrected").
3. Resampled to 48000Hz mono via mandolin_audio.linear_resample.

Not normalized: peak levels vary considerably across the set (0.094 to
0.991), a real characteristic of the source recording (breath pressure/
projection naturally varies by register) - left as-is, matching
guitar_placeholder's own precedent of not normalizing per-note levels.
If some notes sound noticeably quieter/louder than others in practice,
that's the reason; per-note normalization would be the fix.

Coverage: 37 notes, G3 through G6, zero gaps, no files excluded (all 4
source files' onset counts matched their expected note count exactly).
This is a considerably narrower and higher range than guitar_placeholder
(E2-B5) or the mandolin's own register (sa=C#4 - see gamaka.py) - see
gamaka_keyboard_mixer.py's own reporting for whether this range
comfortably covers a given raga/tonic/octave-shift combination; it will
NOT cover an octave-down shift from a Sa around A3-C#4, since G3
(196Hz) sits close to or above where such a shift would land.

File naming: `<note>_mf.wav`, lowercase scientific pitch notation with
flats (e.g. `gb4_mf.wav` = G-flat 4), mono, 48000Hz - matching
guitar_placeholder's exact convention.

Regenerate with: `python3 prepare_flute.py`.
