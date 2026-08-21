#!/usr/bin/env python3
"""Play a guitar sample on spacebar keydown, read via evdev from /dev/input."""
import sys
import evdev
from evdev import ecodes
import pygame

SAMPLE_PATH = "/home/pyru1/mindfulness-instrument/samples/guitar_note.wav"
KEYBOARD_NAME = "Logitech K400 Plus"
FALLBACK_DEVICE = "/dev/input/event0"


def find_keyboard():
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == KEYBOARD_NAME:
            return dev
    return evdev.InputDevice(FALLBACK_DEVICE)


def main():
    pygame.mixer.init(frequency=48000, size=-16, channels=1, buffer=1024)
    sound = pygame.mixer.Sound(SAMPLE_PATH)

    dev = find_keyboard()
    print(f"Listening on {dev.path} ({dev.name}). Press spacebar to play; Ctrl+C to quit.")
    sys.stdout.flush()

    try:
        for event in dev.read_loop():
            if event.type == ecodes.EV_KEY and event.code == ecodes.KEY_SPACE:
                if event.value == 1:  # keydown only; 0=keyup, 2=autorepeat
                    sound.play()
                    print("spacebar -> played")
                    sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":
    main()
