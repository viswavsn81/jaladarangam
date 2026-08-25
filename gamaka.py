#!/usr/bin/env python3
"""Pressure-controlled pitch-bend (gamaka) proof of concept, with jaru
(continuous glide) added via a SoftPot bridging the two FSRs.

Usage:
    python3 gamaka.py <note1> <note2>

FSR1 (MCP3008 CH0) plays/bends <note1>_mid.wav.
FSR2 (MCP3008 CH1) plays/bends <note2>_mid.wav.
SoftPot (MCP3008 CH2) glides the currently-sounding note's pitch toward
the other note's measured pitch.

Example: `python3 gamaka.py sa pa` maps CH0 -> sa_mid.wav, CH1 -> pa_mid.wav.

Architecture: samples are loaded into numpy arrays and streamed through a
sounddevice callback, advancing the current voice through its array with a
variable fractional step (linear interpolation) so pitch can bend
continuously while a note rings - pygame.mixer cannot vary playback speed
live per voice, hence sounddevice for this piece. Sample loading, pitch
measurement, the variable-rate playback step, and the output stage (bass
boost + gain + clip) live in mandolin_audio.py, shared with
gamaka_keyboard.py.

SPI reads happen on the main thread control loop, never inside the audio
callback, to keep the callback free of anything that could block/jitter.

Gesture model: pluck-and-release, not press-and-hold. Once a voice is
triggered it plays through on its own regardless of what fingers do
afterward; it only stops when its own recording naturally ends. A fresh
attack (restart from the top, reset bend to 0, re-anchor) fires on the
rising edge of the *combined* touch state across both FSRs and the
SoftPot - i.e. the moment a fully-untouched instrument becomes touched
by anything - NOT on "the previous sample finished playing". A decaying
sample keeps ringing quietly in the background after a full release, and
should not block an immediate new pluck. A continuous slide (FSR ->
SoftPot -> the other FSR) never drops through a fully-untouched moment,
so it never re-fires this branch - a single glide stays one continuous
note, verified live rather than assumed.

The applied bend is held_bend_cents + kampita_wobble:
  - held_bend_cents is the sample-and-hold baseline, set one of two ways:
    (a) directly by SoftPot position while the SoftPot is touched (this
    IS the jaru bend, not an addition to it), or (b) LOCKED to exactly
    the touched FSR's own note's measured interval from the anchor while
    an FSR is touched and the SoftPot is not - a discrete touch point
    should land you exactly on that note, not an approximation of
    wherever a prior glide's continuous position happened to leave off.
    Reset to 0 only at a fresh attack. kampita never writes this.
  - kampita_wobble (0 to +40 cents) is added on top of whatever
    held_bend_cents currently is (including the just-locked value), from
    whichever FSR is actually pressed right now, not necessarily the one
    that triggered the attack.
  - When neither is touched, held_bend_cents (and hence the applied
    bend) simply doesn't change - that's what lets you pluck, lift off,
    slide, land, and have the note stay on the new pitch with no finger
    touching anything.
  - jaru: SoftPot position -> 0 cents at the anchor's own pitch, up to
    the *measured* interval (cents) to the other note's pitch. Measured
    via autocorrelation on each run's actual loaded samples, never
    hardcoded, since note pairs are arbitrary command-line arguments.

The audibly-applied bend (held_bend_cents + kampita_wobble, smoothed) is
NOT quite the same thing as the raw target above at every instant. A fresh
attack snaps instantly (a brand new note should). Every other moment the
bend source changes - landing on a destination FSR after a glide, or a
finger leaving an FSR (for the softpot or for nothing) - the raw target
jumps: measured live, 127-594c at a landing, 13-32c at a wobble cutoff.
Snapping either instantly is an audible click, so the actual output ramps
onto the new target over a short fixed 35ms window instead, gated on the
bend source itself changing (not on how far the target moved that tick) -
so ordinary fast jaru motion, which also moves tens of cents per tick, is
never mistaken for a discontinuity and stays fully live/unramped.
"""
import argparse
import time
import threading
import numpy as np
import sounddevice as sd
import spidev
import mandolin_audio as ma
from mandolin_audio import SAMPLE_RATE, BLOCKSIZE

FSR_SILENCE_THRESHOLD = 15       # raw ADC counts; FSR touch/no-touch boundary
SOFTPOT_SILENCE_THRESHOLD = 15   # raw ADC counts; softpot touch/no-touch boundary
ADC_PRACTICAL_MAX = 900          # observed real-world max firm FSR-press reading
SOFTPOT_ADC_MAX = 1023           # softpot is a full-scale 10-bit reading
EMA_ALPHA = 0.2                  # smoothing factor for the FSRs (pressure ->
                                  # kampita wobble). The softpot uses a
                                  # separate one-euro filter below - measured
                                  # live, this fixed alpha lagged the softpot's
                                  # raw reading by 60-150c through most of a
                                  # slide (up to 340c+ during fast bursts),
                                  # since a fixed-alpha EMA can't smooth noise
                                  # at rest without also lagging fast motion.
ONE_EURO_MIN_CUTOFF = 1.0        # Hz - filter cutoff when the softpot isn't
                                  # moving; matches roughly the old alpha=0.2
                                  # EMA's resting smoothness (slightly
                                  # stronger), since noise rejection at rest
                                  # doesn't need to be sacrificed for this fix
ONE_EURO_BETA = 0.007            # Hz per (count/sec) of softpot speed - how
                                  # fast the cutoff (and hence responsiveness)
                                  # rises with real finger motion; standard
                                  # one-euro default, cross-checked against
                                  # this system's own measured slide speeds
                                  # (1500-2500 counts/sec cruise, up to ~9500
                                  # counts/sec in fast bursts)
ONE_EURO_DCUTOFF = 1.0           # Hz - cutoff for smoothing the velocity
                                  # estimate itself, so a single noisy sample
                                  # doesn't spike the responsiveness
KAMPITA_TARGET_CENTS = 40.0      # max kampita wobble at full press (30-50 cent ask)
CONTROL_INTERVAL = 0.02          # seconds between SPI polls
PRINT_CENTS_THRESHOLD = 3.0      # only log when bend has moved this many cents
RETRIGGER_GRACE_SECONDS = 0.15   # bridges the brief gap between SoftPot and
                                  # FSR sensors during a slide; long enough to
                                  # cover that, short enough to still feel
                                  # instant for a deliberate new pluck
BEND_RAMP_SECONDS = 0.035       # closes a genuine bend discontinuity at a
                                  # source-transition boundary over a short
                                  # fixed duration instead of snapping - e.g.
                                  # the softpot->FSR landing snap (measured
                                  # live at 127-594c) and the kampita wobble
                                  # cutting to 0 on release/handoff to jaru
                                  # (measured at 13-32c); short enough to
                                  # still feel immediate, not like a slide
BEND_RAMP_MIN_CENTS = 5.0       # below this, it's routine tick-to-tick
                                  # variation, not a real discontinuity -
                                  # don't bother ramping

SOFTPOT_CHANNEL = 2

def parse_args():
    parser = argparse.ArgumentParser(
        description='Gamaka pitch-bend PoC: FSR1/CH0 plays note1, FSR2/CH1 plays note2.')
    parser.add_argument('note1', help='note for FSR1 / MCP3008 CH0 (e.g. sa, ri, ga, ma, pa)')
    parser.add_argument('note2', help='note for FSR2 / MCP3008 CH1')
    parser.add_argument('--bass-boost-db', type=float, default=ma.BASS_BOOST_DB,
                         help=f'low-shelf bass boost in dB, applied below '
                              f'{ma.BASS_BOOST_FREQ_HZ:.0f}Hz (default {ma.BASS_BOOST_DB:.0f}, '
                              f'0 disables it)')
    return parser.parse_args()

BASE_VOICES = [
    {'label': 'FSR1(CH0)', 'adc_channel': 0, 'arg_name': 'note1'},
    {'label': 'FSR2(CH1)', 'adc_channel': 1, 'arg_name': 'note2'},
]

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000
spi_lock = threading.Lock()

def read_channel(ch):
    cmd = [1, (8 + ch) << 4, 0]
    with spi_lock:
        reply = spi.xfer2(cmd)
    return ((reply[1] & 3) << 8) | reply[2]

def _one_euro_alpha(cutoff_hz, dt):
    tau = 1.0 / (2 * np.pi * cutoff_hz)
    return 1.0 / (1.0 + tau / dt)

_softpot_filter_state = {'initialized': False, 'value': 0.0, 'prev_raw': 0.0, 'dx': 0.0}

def one_euro_softpot(raw, dt):
    """Velocity-aware low-pass filter for the softpot reading: smooths hard
    when the finger is still (denoising idle noise same as before), relaxes
    toward the raw signal as it speeds up (eliminating the lag a fixed-alpha
    EMA has no way to avoid without sacrificing one for the other) - see
    Casiez et al. 2012, "1EUR filter". Measured live, the previous fixed
    alpha=0.2 EMA lagged the raw softpot reading by 60-150c through most of
    a slide, spiking past 300c during fast bursts - that lag is what showed
    up as a large pitch jump when landing on the destination FSR right after.
    """
    st = _softpot_filter_state
    if not st['initialized']:
        st['initialized'] = True
        st['value'] = raw
        st['prev_raw'] = raw
        st['dx'] = 0.0
        return st['value']
    dx = (raw - st['prev_raw']) / dt
    dx_alpha = _one_euro_alpha(ONE_EURO_DCUTOFF, dt)
    st['dx'] = dx_alpha * dx + (1 - dx_alpha) * st['dx']
    cutoff = ONE_EURO_MIN_CUTOFF + ONE_EURO_BETA * abs(st['dx'])
    alpha = _one_euro_alpha(cutoff, dt)
    st['value'] = alpha * raw + (1 - alpha) * st['value']
    st['prev_raw'] = raw
    return st['value']

def build_voices(args):
    voices = []
    for base in BASE_VOICES:
        note = getattr(args, base['arg_name'])
        v = dict(base)
        v['note'] = note
        v['label'] = f"{base['label']}->{note}"
        v['samples'] = ma.load_sample(note, label=base['arg_name'])
        v['pitch_hz'] = ma.detect_pitch(v['samples'])
        v['pos'] = 0.0
        v['active'] = False
        v['touching'] = False
        v['smoothed'] = 0.0
        v['rate'] = 1.0
        voices.append(v)
    return voices

# Set by control_loop, read by audio_callback. Only the anchor voice
# (if any) is ever advanced/mixed - this is a monophonic model.
anchor_idx = None
held_bend_cents = 0.0       # sample-and-hold baseline: set by jaru position or
                             # locked to a touched FSR's own interval; reset to
                             # 0 only at attack. kampita never writes this.
last_printed_cents = None
prev_source = None          # bend source on the previous tick ('jaru',
                             # 'kampita', or 'hold'). A CHANGE here is a
                             # genuine discontinuity boundary and is what
                             # starts a ramp; a same-source tick never does,
                             # however much the target itself moved that
                             # tick - that's what keeps fast jaru motion (and
                             # kampita wobble tracking) fully responsive,
                             # never dampened by the ramp below.
ramped_applied_cents = 0.0  # the actual smoothed value driving playback
                             # rate - equals the live target except during a
                             # brief post-transition ramp window
softpot_smoothed = 0.0
any_touched_prev = False    # combined FSR-or-softpot touch state, previous tick
untouched_since = None      # time.monotonic() timestamp of the start of the
                             # current fully-untouched stretch, or None if
                             # currently touched. A touch resuming before
                             # RETRIGGER_GRACE_SECONDS elapses is treated as a
                             # continuation (e.g. the brief physical gap
                             # between the SoftPot and an FSR mid-slide), not
                             # a real release - verified live: without this,
                             # every glide landing misfired as a fresh attack.
bend_ramp = None             # None when no ramp is in progress, else
                             # (start_cents, start_time). Only ever created at
                             # a genuine source-transition tick, then always
                             # interpolates toward the CURRENT live target
                             # each subsequent tick (not a value frozen at
                             # ramp-start) - so if the live target keeps
                             # moving during the ~35ms window (e.g. jaru
                             # resumed sliding), the ramp still converges
                             # onto it exactly by the time it expires, with
                             # no residual snap when direct tracking resumes.

def audio_callback(outdata, frames, time_info, status):
    if status:
        pass  # xruns etc. would show here; ignored for this PoC
    mix = np.zeros(frames, dtype=np.float32)
    idx_anchor = anchor_idx  # snapshot; simple assignment is effectively atomic
    if idx_anchor is not None:
        v = VOICES[idx_anchor]
        if v['active']:
            out = ma.advance_voice(v, frames)
            mix[:len(out)] += out
    mix = ma.finalize_output(mix, boost_shelf)
    outdata[:, 0] = mix

def control_loop():
    global anchor_idx, held_bend_cents, softpot_smoothed, last_printed_cents
    global any_touched_prev, untouched_since
    global prev_source, ramped_applied_cents, bend_ramp
    while True:
        # Read all three sensors for this tick before deciding anything -
        # the attack decision needs the combined state, not a per-sensor edge.
        for v in VOICES:
            raw = read_channel(v['adc_channel'])
            v['smoothed'] = EMA_ALPHA * raw + (1 - EMA_ALPHA) * v['smoothed']
            v['touching'] = raw >= FSR_SILENCE_THRESHOLD

        raw_sp = read_channel(SOFTPOT_CHANNEL)
        softpot_smoothed = one_euro_softpot(raw_sp, CONTROL_INTERVAL)
        softpot_touched = raw_sp >= SOFTPOT_SILENCE_THRESHOLD

        any_touched_now = any(v['touching'] for v in VOICES) or softpot_touched
        just_attacked = False

        if any_touched_now:
            if not any_touched_prev:
                # The combined touch state just went from nothing touched to
                # something touched. This is checked instead of "has the
                # previous sample finished playing" - a decaying sample
                # should not block a new pluck once everything has actually
                # been released. But verified live: a continuous slide
                # (FSR -> SoftPot -> other FSR) DOES briefly pass through a
                # fully-untouched reading at the physical gap between the
                # SoftPot and an FSR, so a grace period is required - without
                # it, every glide landing misfired as a fresh attack instead
                # of locking onto the still-ringing note. Measured live across
                # 8 natural gamaka reps: real landings are 21-62ms, unrelated
                # re-plucks are 0.8s+ - 150ms sits cleanly between the two.
                within_grace = (untouched_since is not None
                                 and time.monotonic() - untouched_since < RETRIGGER_GRACE_SECONDS)
                if not within_grace:
                    newly_pressed = next((i for i, v in enumerate(VOICES) if v['touching']), None)
                    if newly_pressed is not None:
                        anchor_idx = newly_pressed
                        v = VOICES[newly_pressed]
                        v['pos'] = 0.0
                        v['active'] = True
                        held_bend_cents = 0.0
                        v['rate'] = 1.0
                        last_printed_cents = None
                        just_attacked = True
                        print(f"ATTACK -> {v['label']} ({v['note']}, {v['pitch_hz']:.1f} Hz)", flush=True)
            untouched_since = None
        else:
            if any_touched_prev:
                untouched_since = time.monotonic()

        any_touched_prev = any_touched_now

        if anchor_idx is not None:
            anchor = VOICES[anchor_idx]
            other = VOICES[1 - anchor_idx]
            source = 'hold'
            kampita_wobble = 0.0

            if softpot_touched:
                # jaru sets the held baseline directly - it IS the bend,
                # not an addition to it. Deliberately never ramped in itself:
                # a real slide already moves smoothly tick-to-tick, driven by
                # actual finger motion - it needs to stay fully responsive.
                jaru_max_cents = ma.cents_between(anchor['pitch_hz'], other['pitch_hz'])
                raw_frac = (softpot_smoothed - SOFTPOT_SILENCE_THRESHOLD) / (SOFTPOT_ADC_MAX - SOFTPOT_SILENCE_THRESHOLD)
                raw_frac = max(0.0, min(1.0, raw_frac))
                # raw_frac: 0 assumed at the CH0 (FSR1) end of the strip, 1 at
                # the CH1 (FSR2) end - flip if that's backwards on the actual
                # wiring. toward_other should read 0 at the anchor's own end.
                toward_other = raw_frac if anchor_idx == 0 else (1.0 - raw_frac)
                held_bend_cents = jaru_max_cents * toward_other
                source = 'jaru'

                lag_counts = raw_sp - softpot_smoothed
                cents_per_count = jaru_max_cents / (SOFTPOT_ADC_MAX - SOFTPOT_SILENCE_THRESHOLD)
                if abs(lag_counts) > 3:
                    print(f"EMA-LAG raw={raw_sp:4d} smoothed={softpot_smoothed:7.1f} "
                          f"lag={lag_counts:+6.1f}counts ({lag_counts * cents_per_count:+7.1f}c)", flush=True)
            else:
                # An actively-touched FSR LOCKS the baseline to that FSR's
                # own note's exact measured interval from the anchor - not
                # wherever a prior jaru glide happened to leave it - since a
                # discrete touch point should land you exactly on that note,
                # not an approximation of wherever your finger last was on
                # the continuous strip. kampita is then additive on top of
                # that locked baseline. Comes from whichever FSR is actually
                # pressed right now, not necessarily the one that triggered
                # the attack - landing on the *other* FSR mid-glide no
                # longer retriggers, but should still lock+wobble correctly.
                pressed_idx = next((i for i, v in enumerate(VOICES) if v['touching']), None)
                if pressed_idx is not None:
                    pressed = VOICES[pressed_idx]
                    held_bend_cents = ma.cents_between(anchor['pitch_hz'], pressed['pitch_hz'])
                    frac = (pressed['smoothed'] - FSR_SILENCE_THRESHOLD) / (ADC_PRACTICAL_MAX - FSR_SILENCE_THRESHOLD)
                    kampita_wobble = KAMPITA_TARGET_CENTS * max(0.0, min(1.0, frac))
                    source = 'kampita'
                # else: nothing touched -> held_bend_cents itself is unchanged

            target_applied_cents = held_bend_cents + kampita_wobble

            # The audible bend only ever snaps instantly at a fresh attack (a
            # brand new note - that reset SHOULD be instant). Everywhere
            # else, closes over a short fixed ramp instead of snapping:
            # measured live, the softpot->FSR landing produces a 127-594c gap
            # and the kampita wobble cutting to 0 on release/handoff to jaru
            # produces a 13-32c gap. Gated on the *source* actually changing
            # (not on how far the target itself moved this tick), so normal
            # fast jaru motion - which also moves tens of cents per tick -
            # is never mistaken for a discontinuity. Once started, a ramp
            # always interpolates toward the CURRENT live target each tick,
            # so it converges exactly onto wherever that target has moved to
            # by the time it expires - no residual snap when direct,
            # unramped tracking resumes right after.
            if just_attacked:
                bend_ramp = None
                ramped_applied_cents = target_applied_cents
            else:
                if (source != prev_source
                        and abs(target_applied_cents - ramped_applied_cents) > BEND_RAMP_MIN_CENTS):
                    bend_ramp = (ramped_applied_cents, time.monotonic())
                if bend_ramp is not None:
                    start_c, start_t = bend_ramp
                    ramped_applied_cents, ramp_done = ma.ramp_cents(
                        start_c, target_applied_cents, BEND_RAMP_SECONDS, time.monotonic() - start_t)
                    if ramp_done:
                        bend_ramp = None
                else:
                    ramped_applied_cents = target_applied_cents

            prev_source = source
            applied_cents = ramped_applied_cents
            anchor['rate'] = 2 ** (applied_cents / 1200)

            if last_printed_cents is None or abs(applied_cents - last_printed_cents) > PRINT_CENTS_THRESHOLD:
                print(f"{anchor['label']}: source={source:8s} held={held_bend_cents:7.1f}c  "
                      f"wobble={kampita_wobble:5.1f}c  applied={applied_cents:7.1f}c  "
                      f"rate={anchor['rate']:.4f}", flush=True)
                last_printed_cents = applied_cents

        time.sleep(CONTROL_INTERVAL)

args = parse_args()
VOICES = build_voices(args)
boost_shelf = ma.make_bass_boost(args.bass_boost_db)

interval_cents = ma.cents_between(VOICES[0]['pitch_hz'], VOICES[1]['pitch_hz'])
print('Gamaka pitch-bend + jaru PoC running (pluck-and-release gesture). Ctrl+C to stop.', flush=True)
for v in VOICES:
    print(f"  {v['label']}: MCP3008 CH{v['adc_channel']} -> {v['note']}_{ma.STRESS_LEVEL}.wav "
          f"(measured {v['pitch_hz']:.1f} Hz)", flush=True)
print(f"Measured interval {VOICES[0]['note']} -> {VOICES[1]['note']}: {interval_cents:+.1f} cents", flush=True)
print(f'Kampita range: 0 to +{KAMPITA_TARGET_CENTS:.0f} cents. Bend holds at its last value once you', flush=True)
print('let go of everything - it only resets to 0 on a fresh FSR press-edge.', flush=True)
print(f"Bass boost: {'+%.0fdB @ %.0fHz' % (args.bass_boost_db, ma.BASS_BOOST_FREQ_HZ) if args.bass_boost_db > 0 else 'off'} "
      f"(--bass-boost-db to change)", flush=True)

control_thread = threading.Thread(target=control_loop, daemon=True)
control_thread.start()

try:
    with sd.OutputStream(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE, channels=1,
                          dtype='float32', callback=audio_callback):
        while True:
            time.sleep(1)
except KeyboardInterrupt:
    print("\nStopped.", flush=True)
finally:
    spi.close()
