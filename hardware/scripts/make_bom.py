#!/usr/bin/env python3
"""Build the assembly BOM from board_spec.

KiCad's own BOM export lists only what has a symbol on the schematic.  This
board is specified to run all four ICs in sockets, and the sockets are separate
parts to order, so they are derived here from the DIP footprints.  The
off-board parts the board is useless without - the FSRs and the motors - are
listed too, clearly marked as not board-mounted.
"""

import argparse
import collections
import csv

import board_spec as spec

# DIP footprint -> the socket you actually order for it.
SOCKET_FOR = {
    spec.FP_DIP16: ("DIP-16 socket, 7.62mm", "16-pin 0.3in DIP IC socket"),
    spec.FP_DIP18: ("DIP-18 socket, 7.62mm", "18-pin 0.3in DIP IC socket"),
}

# Parts the board connects to but does not carry.
OFF_BOARD = [
    ("FSR0-FSR7", "Force-sensing resistor", 8,
     "Note key sensor, wired to J2-J9. Forms the upper leg of each divider "
     "against the on-board 10k pulldown."),
    ("M0-M7", "Vibration motor", 8,
     "Wired to J10-J17. Positive lead to the header's MOTOR_V+ pin, negative "
     "to the ULN2803A output pin."),
    ("PSU", "Motor supply", 1,
     "Separate supply into J18, sized for 8 motors. Shares only GND with the "
     "3.3V logic domain."),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    comps = spec.build_components()

    rows = []
    groups = collections.OrderedDict()
    for comp in comps:
        key = (comp.value, comp.footprint, comp.dnp)
        groups.setdefault(key, []).append(comp)

    for (value, footprint, dnp), members in groups.items():
        refs = ",".join(c.ref for c in members)
        rows.append({
            "Item": "Board part",
            "Refs": refs,
            "Qty": len(members),
            "Value": value,
            "Footprint": footprint,
            "DNP": "DNP" if dnp else "",
            "Notes": members[0].desc,
        })

    # Sockets, one per socketed IC.
    socket_counts = collections.Counter(
        c.footprint for c in comps if c.footprint in SOCKET_FOR)
    for footprint, count in socket_counts.items():
        value, desc = SOCKET_FOR[footprint]
        refs = ",".join(c.ref for c in comps if c.footprint == footprint)
        rows.append({
            "Item": "Socket",
            "Refs": "for %s" % refs,
            "Qty": count,
            "Value": value,
            "Footprint": footprint,
            "DNP": "",
            "Notes": desc + " - fit the socket even where the IC is DNP.",
        })

    for refs, value, qty, note in OFF_BOARD:
        rows.append({
            "Item": "Off-board",
            "Refs": refs,
            "Qty": qty,
            "Value": value,
            "Footprint": "",
            "DNP": "",
            "Notes": note,
        })

    fields = ["Item", "Refs", "Qty", "Value", "Footprint", "DNP", "Notes"]
    with open(args.out, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    board = sum(r["Qty"] for r in rows if r["Item"] == "Board part")
    sockets = sum(r["Qty"] for r in rows if r["Item"] == "Socket")
    dnp = sum(r["Qty"] for r in rows if r["DNP"])
    print("wrote %s" % args.out)
    print("  %d board parts in %d line items (%d DNP), %d sockets, %d off-board items"
          % (board, len([r for r in rows if r["Item"] == "Board part"]), dnp,
             sockets, len(OFF_BOARD)))


if __name__ == "__main__":
    main()
