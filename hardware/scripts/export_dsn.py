#!/usr/bin/env python3
"""Export the board to Specctra DSN for the autorouter."""
import argparse
import pcbnew


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("dsn")
    args = ap.parse_args()
    board = pcbnew.LoadBoard(args.board)
    if not pcbnew.ExportSpecctraDSN(board, args.dsn):
        raise SystemExit("ExportSpecctraDSN failed")
    print("wrote %s" % args.dsn)


if __name__ == "__main__":
    main()
