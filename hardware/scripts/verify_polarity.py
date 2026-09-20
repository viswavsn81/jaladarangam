#!/usr/bin/env python3
"""Check every polarity mark against the pad it actually sits beside.

board_spec.sanity_check already proves each mark agrees with the netlist.
This proves the *placed silkscreen* agrees too: for each mark it finds the
text on the board, finds the nearest pad to it, and requires that pad to be
the one the mark names and to carry the net the mark asserts.

That closes the gap a coordinate check leaves open - a mark can be correct in
the table and still land closer to the neighbouring pin, which on a 2.54 mm
header would tell an assembler to wire a motor backwards.
"""

import argparse
import sys

import pcbnew
import board_spec as spec


def mark_positions(board):
    """Silkscreen texts whose content matches a polarity caption."""
    captions = {caption for _r, _p, caption, _s, _n in spec.PAD_POLARITY_LABELS}
    out = []
    for item in board.GetDrawings():
        if item.Type() == pcbnew.PCB_TEXT_T and item.GetLayer() == pcbnew.F_SilkS:
            if item.GetText() in captions:
                pos = item.GetPosition()
                out.append((item.GetText(),
                            pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))
    return out


def all_pads(board):
    out = []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            pos = pad.GetPosition()
            out.append((fp.GetReference(), pad.GetNumber(), pad.GetNetname(),
                        pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    args = ap.parse_args()

    board = pcbnew.LoadBoard(args.board)
    pads = all_pads(board)
    marks = mark_positions(board)
    problems = []

    expected = spec.PAD_POLARITY_LABELS
    print("%d polarity marks expected, %d found on F.Silkscreen"
          % (len(expected), len(marks)))
    if len(marks) != len(expected):
        problems.append("expected %d marks on the board, found %d"
                        % (len(expected), len(marks)))

    used = set()
    for ref, number, caption, side, asserts in expected:
        # The pad this mark is supposed to describe.
        target = [p for p in pads if p[0] == ref and p[1] == number]
        if not target:
            problems.append("%s pad %s does not exist on the board" % (ref, number))
            continue
        _r, _n, net, tx, ty = target[0]

        # The placed text nearest that pad, among marks with this caption.
        candidates = [m for m in marks if m[0] == caption]
        if not candidates:
            problems.append("no %r mark found for %s pad %s" % (caption, ref, number))
            continue
        mark = min(candidates, key=lambda m: (m[1] - tx) ** 2 + (m[2] - ty) ** 2)
        key = (mark[1], mark[2])
        if key in used:
            problems.append("%s pad %s: mark at (%.2f, %.2f) already claimed by "
                            "another pad" % (ref, number, mark[1], mark[2]))
        used.add(key)

        # Now the real test: which pad is that text closest to?
        nearest = min(pads, key=lambda p: (p[3] - mark[1]) ** 2 + (p[4] - mark[2]) ** 2)
        dist = ((nearest[3] - mark[1]) ** 2 + (nearest[4] - mark[2]) ** 2) ** 0.5

        if (nearest[0], nearest[1]) != (ref, number):
            problems.append(
                "%r mark for %s pad %s sits nearest %s pad %s (%s) instead"
                % (caption, ref, number, nearest[0], nearest[1], nearest[2]))
        elif net != asserts:
            problems.append("%s pad %s is marked %r claiming %s but carries %s"
                            % (ref, number, caption, asserts, net))
        else:
            print("  [ok ] %-4s pad %s  mark %-3r  %.2f mm away  net %s"
                  % (ref, number, caption, dist, net))

    if problems:
        print("\nFAILED (%d):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - every mark sits nearest the pad it names, and that pad "
          "carries the net it asserts.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
