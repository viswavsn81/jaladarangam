#!/usr/bin/env python3
"""Create the project-local symbol library.

The board needs a MOTOR_V+ power symbol so the separate motor rail is drawn and
netted like any other power rail.  KiCad ships no such symbol, so one is derived
from the stock power:+3V3 symbol.
"""
import argparse
import os

import kisexp
from kisexp import Atom, QStr


def rename_power_symbol(node, old, new, description):
    out = []
    for item in node:
        if isinstance(item, list):
            tag = kisexp.head(item)
            if tag == "symbol":
                item = list(item)
                item[1] = QStr(str(item[1]).replace(old, new, 1))
            elif tag == "property":
                name = str(item[1])
                if name == "Value":
                    item = list(item)
                    item[2] = QStr(new)
                elif name == "Description":
                    item = list(item)
                    item[2] = QStr(description)
                elif name == "ki_keywords":
                    item = list(item)
                    item[2] = QStr("global power motor supply")
            out.append(item)
        elif isinstance(item, QStr) and str(item) == old:
            out.append(QStr(new))
        else:
            out.append(item)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    src = os.path.join(args.symbols, "power.kicad_symdir", "+3V3.kicad_sym")
    lib = kisexp.parse_one(open(src).read())
    sym = [s for s in kisexp.find_all(lib, "symbol") if str(s[1]) == "+3V3"][0]
    motor = rename_power_symbol(sym, "+3V3", "MOTOR_V+",
                                'Power symbol creates a global label with name "MOTOR_V+" '
                                '(separate motor supply rail, common GND only)')

    out = [Atom("kicad_symbol_lib"),
           [Atom("version"), Atom("20251024")],
           [Atom("generator"), QStr("jaladarangam-hardware-gen")],
           [Atom("generator_version"), QStr("10.0")],
           motor]
    with open(args.out, "w") as fh:
        fh.write(kisexp.dumps(out))
        fh.write("\n")
    print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
