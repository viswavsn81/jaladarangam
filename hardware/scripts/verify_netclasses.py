#!/usr/bin/env python3
"""Check that the exported Specctra DSN carries the intended net classes.

The autorouter routes to whatever widths the DSN declares, so this is the last
point at which a collapsed net class can still be caught before copper is laid
down.  A previous run silently exported a single 0.2 mm class for every net,
including the motor rail; this asserts that cannot happen unnoticed again.
"""

import argparse
import re
import sys

import board_spec as spec


def _block(text, start):
    """Return the text of the parenthesised block beginning at ``start``."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise ValueError("unterminated block at offset %d" % start)


def parse_classes(path):
    """class name -> (track_width_mm, clearance_mm, [nets])."""
    text = open(path).read()
    out = {}
    for match in re.finditer(r"\(class\s+(\S+)", text):
        block = _block(text, match.start())
        name = match.group(1)
        # Net names run from after the class name up to the first sub-block.
        head = block[block.index(name) + len(name):]
        cut = head.find("(")
        nets = head[:cut].split() if cut != -1 else head.rstrip(")").split()
        width = re.search(r"\(width\s+([\d.]+)\)", block)
        clearance = re.search(r"\(clearance\s+([\d.]+)\)", block)
        out[name] = (
            float(width.group(1)) / 1000.0 if width else None,
            float(clearance.group(1)) / 1000.0 if clearance else None,
            nets,
        )
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dsn")
    args = ap.parse_args()

    classes = parse_classes(args.dsn)
    if not classes:
        print("FAIL: no (class ...) blocks found in %s" % args.dsn)
        return 1

    print("net classes in %s:" % args.dsn)
    for name, (width, clearance, nets) in sorted(classes.items()):
        print("  %-16s track %.2f mm  clearance %.2f mm  %d nets"
              % (name, width, clearance, len(nets)))

    # Map every net to the width its class declares.
    actual = {}
    for name, (width, _clearance, nets) in classes.items():
        for net in nets:
            actual[net] = width

    expected_nets = set(spec.build_nets(spec.build_components()))
    problems = []

    missing = expected_nets - set(actual)
    if missing:
        problems.append("nets absent from every DSN class: %s" % sorted(missing))

    for net in sorted(expected_nets & set(actual)):
        want = spec.expected_track_width(net)
        got = actual[net]
        if abs(got - want) > 1e-6:
            problems.append("%s: expected %.2f mm, DSN says %.2f mm" % (net, want, got))

    if len(classes) < 2:
        problems.append("expected at least 2 classes (signal + power), found %d"
                        % len(classes))

    print()
    print("motor rail and outputs at %.2f mm, signal nets at %.2f mm:"
          % (spec.TRACK_POWER, spec.TRACK_SIGNAL))
    for net in [spec.NET_MOTOR, "MOTOR0", "MOTOR7", spec.NET_3V3, spec.NET_GND,
                "SPI_SCLK", "FSR0", "MTRDRV0"]:
        got = actual.get(net)
        mark = "ok " if got is not None and abs(got - spec.expected_track_width(net)) < 1e-6 else "BAD"
        print("  [%s] %-10s %.2f mm" % (mark, net, got if got is not None else -1))

    if problems:
        print("\nFAILED (%d):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - every net carries its intended track width into the router.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
