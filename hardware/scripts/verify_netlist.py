#!/usr/bin/env python3
"""Cross-check KiCad's exported netlist against board_spec.

The schematic is generated from board_spec, so this closes the loop: KiCad
parses the drawing independently and the connectivity it derives must match
the spec pad-for-pad.  Power symbols (#PWR/#FLG) are not real parts and are
ignored.
"""
import argparse
import sys

import kisexp
import board_spec as spec


def netlist_nets(path):
    root = kisexp.parse_one(open(path).read())
    nets_node = kisexp.find(root, "nets")
    out = {}
    for net in kisexp.find_all(nets_node, "net"):
        name = str(kisexp.value(net, "name", ""))
        pads = set()
        for node in kisexp.find_all(net, "node"):
            ref = str(kisexp.value(node, "ref", ""))
            pin = str(kisexp.value(node, "pin", ""))
            if ref.startswith("#"):      # power symbol / PWR_FLAG, not a part
                continue
            pads.add((ref, pin))
        out[name.lstrip("/")] = pads
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("netlist")
    args = ap.parse_args()

    comps = spec.build_components()
    expected = {n: set(p) for n, p in spec.build_nets(comps).items()}
    actual = netlist_nets(args.netlist)
    actual = {n: p for n, p in actual.items() if p}   # drop empty power-only nets

    # KiCad invents a single-pad "unconnected-(...)" net for every pin left
    # deliberately open.  Check that set is exactly what the spec intends
    # rather than treating each one as a mismatch.
    auto = {n: p for n, p in actual.items() if n.startswith("unconnected-")}
    actual = {n: p for n, p in actual.items() if not n.startswith("unconnected-")}

    open_pads = {("J1", pin) for pin in spec.PI_UNUSED}
    open_pads |= {("U2", "9"), ("U4", "7")}     # both QH' outputs, not daisy-chained
    auto_pads = set().union(*auto.values()) if auto else set()

    problems = []
    if auto_pads != open_pads:
        problems.append("unconnected pins differ:\n    only in spec:       %s\n"
                        "    only in schematic:  %s"
                        % (sorted(open_pads - auto_pads), sorted(auto_pads - open_pads)))

    for name in sorted(set(expected) | set(actual)):
        want = expected.get(name)
        got = actual.get(name)
        if want is None:
            problems.append("net %r exists in the schematic but not in the spec: %s"
                            % (name, sorted(got)))
        elif got is None:
            problems.append("net %r is in the spec but not in the schematic" % name)
        elif want != got:
            problems.append("net %r differs:\n    only in spec:       %s\n"
                            "    only in schematic:  %s"
                            % (name, sorted(want - got), sorted(got - want)))

    print("spec: %d nets   schematic: %d nets   (+%d intentionally open pins)"
          % (len(expected), len(actual), len(auto_pads)))
    if problems:
        print("\nMISMATCHES (%d):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("\nOK - every net matches the spec pad for pad, and every\n     deliberately unconnected pin is accounted for.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
