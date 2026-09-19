#!/usr/bin/env python3
"""Dump the board rectangle to crop for each connector close-up, as JSON.

Runs under KiCad's interpreter because it needs pcbnew.  Regions are taken from
the footprints themselves rather than hard-coded, so they stay correct if
placement in board_spec changes.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcbnew

# Close-ups to produce: output name -> (caption, [refs to cover])
GROUPS = [
    ("silk_fsr_headers", "FSR note-key headers J2-J9",
     ["J%d" % i for i in range(2, 10)]),
    ("silk_motor_headers", "Vibration motor headers J10-J17",
     ["J%d" % i for i in range(10, 18)]),
    ("silk_motor_power", "Motor supply input J18", ["J18"]),
    ("silk_aux_header", "AUX digital input header J19", ["J19"]),
    ("silk_pi_header", "Raspberry Pi GPIO header J1", ["J1"]),
]

PAD_MM = 5.0        # breathing room around the group


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("out")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.board)
    by_ref = {fp.GetReference(): fp for fp in board.GetFootprints()}

    regions = []
    for name, caption, refs in GROUPS:
        xs, ys = [], []
        for ref in refs:
            fp = by_ref[ref]
            # Include silkscreen so the caption is inside the crop.
            box = fp.GetBoundingBox(True, False)
            xs += [pcbnew.ToMM(box.GetLeft()), pcbnew.ToMM(box.GetRight())]
            ys += [pcbnew.ToMM(box.GetTop()), pcbnew.ToMM(box.GetBottom())]
        regions.append({
            "name": name,
            "caption": caption,
            "x": round(min(xs) - PAD_MM, 3),
            "y": round(min(ys) - PAD_MM, 3),
            "w": round(max(xs) - min(xs) + 2 * PAD_MM, 3),
            "h": round(max(ys) - min(ys) + 2 * PAD_MM, 3),
        })

    with open(args.out, "w") as fh:
        json.dump(regions, fh, indent=2)
    print("wrote %s (%d regions)" % (args.out, len(regions)))
    for r in regions:
        print("  %-20s x %.1f y %.1f  %.1f x %.1f mm"
              % (r["name"], r["x"], r["y"], r["w"], r["h"]))


if __name__ == "__main__":
    main()
