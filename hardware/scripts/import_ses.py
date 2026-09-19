#!/usr/bin/env python3
"""Import FreeRouting's Specctra session file back into the .kicad_pcb.

The board is bound to its project first, for the same reason gen_pcb.py does
it: saving a board whose in-memory settings are pcbnew's defaults would
overwrite the project's net classes.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcbnew
import board_spec as spec

_MGR = None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("ses")
    ap.add_argument("--project", required=True)
    args = ap.parse_args()

    global _MGR
    board = pcbnew.LoadBoard(args.board)
    _MGR = pcbnew.SETTINGS_MANAGER()
    if not _MGR.LoadProject(os.path.abspath(args.project)):
        raise SystemExit("could not load project %s" % args.project)
    board.SetProject(_MGR.GetProject(os.path.abspath(args.project)))

    before = len(list(board.GetTracks()))
    if not pcbnew.ImportSpecctraSES(board, args.ses):
        raise SystemExit("ImportSpecctraSES failed")
    tracks = list(board.GetTracks())
    print("imported %s: %d -> %d track/via items" % (args.ses, before, len(tracks)))

    # Report what actually landed on copper, per net class.
    by_net = {}
    vias = 0
    for item in tracks:
        if item.Type() == pcbnew.PCB_VIA_T:
            vias += 1
            continue
        name = item.GetNetname()
        by_net.setdefault(name, set()).add(round(pcbnew.ToMM(item.GetWidth()), 3))

    wrong = []
    for net, widths in sorted(by_net.items()):
        want = spec.expected_track_width(net)
        bad = [w for w in widths if abs(w - want) > 1e-6]
        if bad:
            wrong.append("%s: expected %.2f mm, found %s" % (net, want, sorted(widths)))

    print("%d vias, %d nets carry copper" % (vias, len(by_net)))
    print("  motor rail  MOTOR_V+ widths: %s mm" % sorted(by_net.get(spec.NET_MOTOR, [])))
    print("  motor out   MOTOR0   widths: %s mm" % sorted(by_net.get("MOTOR0", [])))
    print("  signal      SPI_SCLK widths: %s mm" % sorted(by_net.get("SPI_SCLK", [])))
    if wrong:
        print("\nWARNING - track widths off spec:")
        for w in wrong:
            print("  " + w)

    pcbnew.SaveBoard(args.board, board)
    print("saved %s" % args.board)
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
