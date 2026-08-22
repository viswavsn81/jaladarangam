#!/usr/bin/env python3
"""Continuously print raw MCP3008 CH0 readings for wiring verification.
Only prints when the value changes meaningfully, to keep output readable."""
import time
import spidev

CHANNEL = 0
CHANGE_THRESHOLD = 15

spi = spidev.SpiDev()
spi.open(0, 0)  # bus 0, CE0
spi.max_speed_hz = 1350000

def read_channel(ch):
    cmd = [1, (8 + ch) << 4, 0]
    reply = spi.xfer2(cmd)
    value = ((reply[1] & 3) << 8) | reply[2]
    return value

print(f'Reading MCP3008 CH{CHANNEL}. Ctrl+C to stop.', flush=True)
last_printed = None
try:
    while True:
        val = read_channel(CHANNEL)
        if last_printed is None or abs(val - last_printed) > CHANGE_THRESHOLD:
            print(val, flush=True)
            last_printed = val
        time.sleep(0.05)
except KeyboardInterrupt:
    print('\nStopped.', flush=True)
finally:
    spi.close()
