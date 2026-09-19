#!/usr/bin/env python3
"""Check that routed copper respects the analog / motor zone separation.

Placement puts the two domains on opposite sides of an empty corridor, but an
autorouter is free to run a trace anywhere it likes.  This asserts that the
result actually honours the spec's priority: motor switching current must not
run alongside FSR signal lines.

GND and +3V3 legitimately span the board - GND is the shared return, and the
motor zone's logic ICs need 3.3V - so they are reported but not constrained.
"""

import argparse
import sys

import pcbnew
import board_spec as spec


def net_x_extents(board):
    """net name -> (min_x, max_x) over every track and via, in mm."""
    out = {}
    for item in board.GetTracks():
        name = item.GetNetname()
        if not name:
            continue
        if item.Type() == pcbnew.PCB_VIA_T:
            points = [item.GetPosition()]
        else:
            points = [item.GetStart(), item.GetEnd()]
        for p in points:
            x = pcbnew.ToMM(p.x)
            lo, hi = out.get(name, (float("inf"), float("-inf")))
            out[name] = (min(lo, x), max(hi, x))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.board)
    extents = net_x_extents(board)
    left, right = spec.ISOLATION_GAP
    problems = []

    print("isolation corridor: x = %.0f .. %.0f mm" % (left, right))

    motor_nets = [spec.NET_MOTOR] + ["MOTOR%d" % i for i in range(8)]
    print("\nmotor-domain copper must stay right of x = %.0f:" % left)
    for net in motor_nets:
        if net not in extents:
            problems.append("%s has no copper at all" % net)
            continue
        lo, hi = extents[net]
        ok = lo >= left
        if not ok:
            problems.append("%s reaches x=%.1f, left of the corridor" % (net, lo))
        print("  [%s] %-9s x %6.1f .. %6.1f mm" % ("ok " if ok else "XX ", net, lo, hi))

    print("\nanalog-domain copper must stay left of x = %.0f:" % right)
    for i in range(8):
        net = "FSR%d" % i
        if net not in extents:
            problems.append("%s has no copper at all" % net)
            continue
        lo, hi = extents[net]
        ok = hi <= right
        if not ok:
            problems.append("%s reaches x=%.1f, right of the corridor" % (net, hi))
        print("  [%s] %-9s x %6.1f .. %6.1f mm" % ("ok " if ok else "XX ", net, lo, hi))

    print("\nshared rails (expected to span the board):")
    for net in (spec.NET_GND, spec.NET_3V3):
        lo, hi = extents.get(net, (0, 0))
        print("      %-9s x %6.1f .. %6.1f mm" % (net, lo, hi))

    if problems:
        print("\nFAILED (%d):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - motor and analog copper stay in their own zones.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
