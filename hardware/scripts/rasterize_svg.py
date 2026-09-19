#!/usr/bin/env python3
"""Rasterise KiCad's board-area SVG plots to PNG, whole board or cropped.

KiCad's ``--page-size-mode 2`` SVG has a viewBox in board millimetres starting
at the board origin, so a crop is just a narrowed viewBox - no pixel-space
guesswork and no dependence on the rasteriser's DPI.
"""

import argparse
import json
import os
import re

import cairosvg

SVG_TAG = re.compile(
    r'(width=")[^"]*("\s+height=")[^"]*("\s+viewBox=")[^"]*(")')


def svg_viewbox(text):
    match = re.search(r'viewBox="([\d.\s-]+)"', text)
    return [float(v) for v in match.group(1).split()]


def reframe(text, x, y, w, h):
    """Return the SVG with its viewport narrowed to a board-space rectangle."""
    replacement = r'\g<1>%.4fmm\g<2>%.4fmm\g<3>%.4f %.4f %.4f %.4f\g<4>' % (
        w, h, x, y, w, h)
    out, count = SVG_TAG.subn(replacement, text, count=1)
    if count != 1:
        raise SystemExit("could not rewrite the SVG viewport")
    return out


def render(text, out_path, px_per_mm, width_mm):
    cairosvg.svg2png(bytestring=text.encode("utf-8"), write_to=out_path,
                     output_width=int(round(width_mm * px_per_mm)),
                     background_color="white")
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("svg")
    ap.add_argument("--out", required=True, help="output PNG (whole board)")
    ap.add_argument("--px-per-mm", type=float, default=16.0)
    ap.add_argument("--crops", help="JSON region list from dump_regions.py")
    ap.add_argument("--crop-px-per-mm", type=float, default=60.0)
    ap.add_argument("--crop-dir")
    args = ap.parse_args()

    text = open(args.svg).read()
    vb = svg_viewbox(text)

    render(text, args.out, args.px_per_mm, vb[2])
    print("%s  (%.0f x %.0f mm board area)" % (args.out, vb[2], vb[3]))

    if not args.crops:
        return

    regions = json.load(open(args.crops))
    for region in regions:
        cropped = reframe(text, region["x"], region["y"],
                          region["w"], region["h"])
        path = os.path.join(args.crop_dir, region["name"] + ".png")
        render(cropped, path, args.crop_px_per_mm, region["w"])
        print("%s  (%s)" % (path, region["caption"]))


if __name__ == "__main__":
    main()
