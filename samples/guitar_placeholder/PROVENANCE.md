# Guitar placeholder samples - provenance

Source: University of Iowa Electronic Music Studios, Musical Instrument
Samples database - https://theremin.music.uiowa.edu/MISguitar.html

License: per the MIS database's own usage statement
(https://theremin.music.uiowa.edu/MIS.html), these recordings "may be
downloaded and used for any projects, without restrictions." Verified
directly against that page's text before downloading, independent of
this being a stated assumption.

Dynamic: mf (mezzo-forte) only, downloaded as mono AIFF.

Processing: each source file is a chromatic run of multiple notes
concatenated (e.g. `Guitar.mf.sulE.E2B2.mono.aif` contains E2 through B2,
not a single note), not individual note recordings. Split into individual
notes via librosa onset detection, with note count cross-checked against
the range implied by the filename, and every split segment's pitch
independently verified via librosa's pyin against the expected chromatic
note (flagging anything off by more than 50 cents as a likely
mis-split - none were).

Coverage: 44 notes, E2 through B5, zero gaps. Consistently tuned ~10-40
cents flat of standard A440 equal temperament across the whole set (this
is the real guitar's actual tuning at recording time, not a detection
error - confirmed by the fact that every chromatic interval between
adjacent notes measures as a clean 100 cents). Not corrected/retuned -
matches this project's existing convention (see gamaka.py) of measuring
real pitch from the actual audio rather than assuming standard tuning.

3 of the 15 downloaded source files had onset-detection count mismatches
and were excluded rather than trusted: Guitar.mf.sulA.C3B3.mono.aif,
Guitar.mf.sulD.D3B3.mono.aif, Guitar.mf.sulG.C5Db5.mono.aif. Their note
ranges are fully covered by other, cleanly-split files, so exclusion
caused no coverage gap.

File naming: `<note>_mf.wav`, note in lowercase scientific pitch notation
with flats (e.g. `gb4_mf.wav` = G-flat 4). Sample rate 48000Hz mono,
matching this project's existing pipeline (gamaka.py SAMPLE_RATE).
