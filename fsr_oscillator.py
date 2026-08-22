#!/usr/bin/env python3
"""FSR-controlled sine oscillators. Reads MCP3008 CH0 and CH1 (FSR #1 and FSR #2),
each independently mapped to its own pitch, played on separate channels so both
can be tested (and heard at once, if pressed together)."""
import time
import numpy as np
import pygame
import spidev

SAMPLE_RATE = 48000
SILENCE_THRESHOLD = 15
ADC_MAX = 1023
FREQ_MIN = 200.0
FREQ_MAX = 800.0
UPDATE_INTERVAL = 0.03
FREQ_CHANGE_THRESHOLD = 15.0
CHUNK_DURATION = 0.03
VOLUME = 0.35

SENSORS = [
    {'label': 'FSR1(CH0)', 'adc_channel': 0, 'pygame_channel': 0},
    {'label': 'FSR2(CH1)', 'adc_channel': 1, 'pygame_channel': 1},
]

spi = spidev.SpiDev()
spi.open(0, 0)
spi.max_speed_hz = 1350000

def read_channel(ch):
    cmd = [1, (8 + ch) << 4, 0]
    reply = spi.xfer2(cmd)
    return ((reply[1] & 3) << 8) | reply[2]

def raw_to_freq(raw):
    frac = (raw - SILENCE_THRESHOLD) / (ADC_MAX - SILENCE_THRESHOLD)
    frac = max(0.0, min(1.0, frac))
    return FREQ_MIN + frac * (FREQ_MAX - FREQ_MIN)

def make_sine_sound(freq):
    period_samples = SAMPLE_RATE / freq
    num_cycles = max(1, round(CHUNK_DURATION * freq))
    n = max(8, round(num_cycles * period_samples))
    t = np.arange(n)
    wave = np.sin(2 * np.pi * freq * t / SAMPLE_RATE)
    audio = (wave * 32767 * VOLUME).astype(np.int16)
    return pygame.sndarray.make_sound(audio)

pygame.mixer.init(frequency=SAMPLE_RATE, size=-16, channels=1, buffer=1024)
for s in SENSORS:
    s['channel'] = pygame.mixer.Channel(s['pygame_channel'])
    s['last_freq'] = None
    s['touching'] = False

print('Dual FSR oscillator running (CH0 + CH1). Ctrl+C to stop.', flush=True)

try:
    while True:
        for s in SENSORS:
            raw = read_channel(s['adc_channel'])
            if raw < SILENCE_THRESHOLD:
                if s['touching']:
                    s['channel'].stop()
                    s['touching'] = False
                    print(f"{s['label']}: raw={raw:4d}  -> silence", flush=True)
            else:
                freq = raw_to_freq(raw)
                if not s['touching'] or s['last_freq'] is None or abs(freq - s['last_freq']) > FREQ_CHANGE_THRESHOLD:
                    sound = make_sine_sound(freq)
                    s['channel'].play(sound, loops=-1)
                    s['last_freq'] = freq
                    s['touching'] = True
                    print(f"{s['label']}: raw={raw:4d}  -> {freq:6.1f} Hz", flush=True)
        time.sleep(UPDATE_INTERVAL)
except KeyboardInterrupt:
    print('\nStopped.', flush=True)
finally:
    for s in SENSORS:
        s['channel'].stop()
    spi.close()
