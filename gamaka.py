#!/usr/bin/env python3
"""Pressure-controlled pitch-bend (gamaka) proof of concept.

FSR1 (MCP3008 CH0) triggers/bends a D3 guitar pluck.
FSR2 (MCP3008 CH1) triggers/bends a G3 guitar pluck.

Architecture: samples are loaded into numpy arrays and streamed through a
sounddevice callback, advancing each voice through its array with a
variable fractional step (linear interpolation) so pitch can bend
continuously while a note is held - pygame.mixer cannot vary playback
speed live per voice, hence the switch to sounddevice for this piece.

SPI reads happen on the main thread control loop, never inside the audio
callback, to keep the callback free of anything that could block/jitter.
"""
import time
import threading
import numpy as np
import soundfile as sf
import sounddevice as sd
import spidev

SAMPLE_RATE = 48000
BLOCKSIZE = 1024

SILENCE_THRESHOLD = 15      # raw ADC counts; touch/no-touch boundary
ADC_PRACTICAL_MAX = 900     # observed real-world max firm-press reading
EMA_ALPHA = 0.2             # smoothing factor for the bend control signal
TARGET_CENTS = 40.0         # max pitch bend at full press (within the 30-50 cent ask)
CONTROL_INTERVAL = 0.02     # seconds between SPI polls
PRINT_CENTS_THRESHOLD = 3.0 # only log when the bend has moved this many cents

BASE_DIR = '/home/pyru1/mindfulness-instrument'

VOICES = [
    {'label': 'FSR1(CH0)->D3', 'adc_channel': 0, 'sample_path': f'{BASE_DIR}/samples/d3_pluck.wav'},
    {'label': 'FSR2(CH1)->G3', 'adc_channel': 1, 'sample_path': f'{BASE_DIR}/samples/g3_pluck.wav'},
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

for v in VOICES:
    audio, sr = sf.read(v['sample_path'], dtype='float32', always_2d=False)
    assert sr == SAMPLE_RATE, f"{v['sample_path']} is {sr}Hz, expected {SAMPLE_RATE}Hz"
    v['samples'] = audio
    v['pos'] = 0.0
    v['active'] = False
    v['touching'] = False
    v['rate'] = 1.0
    v['smoothed'] = 0.0
    v['last_printed_cents'] = None

def audio_callback(outdata, frames, time_info, status):
    if status:
        pass  # xruns etc. would show here; ignored for this PoC
    mix = np.zeros(frames, dtype=np.float32)
    for v in VOICES:
        if not v['active']:
            continue
        samples = v['samples']
        n = len(samples)
        pos = v['pos']
        rate = v['rate']
        idx = pos + np.arange(frames) * rate
        end_mask = idx >= (n - 1)
        if np.any(end_mask):
            last_valid = int(np.argmax(end_mask))  # first True index
            idx = idx[:last_valid]
            v['active'] = False
        else:
            last_valid = frames
        if last_valid > 0:
            i0 = idx.astype(np.int64)
            frac = idx - i0
            voice_out = (1 - frac) * samples[i0] + frac * samples[i0 + 1]
            mix[:last_valid] += voice_out
        v['pos'] = pos + last_valid * rate
    mix *= 1.3  # boosted from 0.8; still clipped below, so loud peaks are safe
    np.clip(mix, -1.0, 1.0, out=mix)
    outdata[:, 0] = mix

def control_loop():
    while True:
        for v in VOICES:
            raw = read_channel(v['adc_channel'])
            v['smoothed'] = EMA_ALPHA * raw + (1 - EMA_ALPHA) * v['smoothed']

            if raw >= SILENCE_THRESHOLD and not v['touching']:
                v['touching'] = True
                v['pos'] = 0.0
                v['active'] = True
                print(f"{v['label']}: PLUCK (raw={raw})", flush=True)
            elif raw < SILENCE_THRESHOLD and v['touching']:
                v['touching'] = False

            frac = (v['smoothed'] - SILENCE_THRESHOLD) / (ADC_PRACTICAL_MAX - SILENCE_THRESHOLD)
            frac = max(0.0, min(1.0, frac))
            cents = TARGET_CENTS * frac
            v['rate'] = 2 ** (cents / 1200)

            if v['last_printed_cents'] is None or abs(cents - v['last_printed_cents']) > PRINT_CENTS_THRESHOLD:
                print(f"{v['label']}: smoothed={v['smoothed']:5.1f}  bend={cents:5.1f} cents  rate={v['rate']:.4f}", flush=True)
                v['last_printed_cents'] = cents
        time.sleep(CONTROL_INTERVAL)

print('Gamaka pitch-bend PoC running. Press FSR1 for D3, FSR2 for G3. Ctrl+C to stop.', flush=True)
print(f'Target bend range: 0 to +{TARGET_CENTS:.0f} cents (rate x{2**(TARGET_CENTS/1200):.4f} at full press).', flush=True)

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
