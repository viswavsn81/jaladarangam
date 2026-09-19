#!/usr/bin/env python3
"""Write the .kicad_pro project file.

Started from KiCad's own project template so every default KiCad expects is
present, then the design rules and net classes from board_spec are rendered
into it.  This file is the project-level home of those rules; gen_pcb.py loads
it and binds it to the board before saving, so the two cannot drift.
"""
import argparse
import json
import os

import board_spec as spec


def netclass_entry(nc):
    """One net class in the shape KiCad's project schema expects."""
    return {
        "name": nc["name"],
        "clearance": nc["clearance"],
        "track_width": nc["track_width"],
        "via_diameter": nc["via_diameter"],
        "via_drill": nc["via_drill"],
        "microvia_diameter": 0.3,
        "microvia_drill": 0.1,
        "diff_pair_width": 0.2,
        "diff_pair_gap": 0.25,
        "diff_pair_via_gap": 0.25,
        "line_style": 0,
        "pcb_color": "rgba(0, 0, 0, 0.000)",
        "schematic_color": "rgba(0, 0, 0, 0.000)",
        "wire_width": 6,
        "bus_width": 12,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    pro = json.load(open(args.template))

    ds = pro["board"]["design_settings"]
    rules = ds.setdefault("rules", {})
    rules["min_clearance"] = spec.CLEARANCE
    rules["min_track_width"] = spec.TRACK_SIGNAL
    rules["min_via_diameter"] = 0.8
    rules["min_through_hole_diameter"] = spec.MIN_THROUGH_DRILL
    rules["min_hole_clearance"] = spec.CLEARANCE
    rules["min_hole_to_hole"] = spec.CLEARANCE
    rules["min_silk_clearance"] = 0.0
    rules["solder_mask_to_copper_clearance"] = 0.0

    defaults = ds.setdefault("defaults", {})
    defaults["board_outline_line_width"] = 0.1
    defaults["copper_line_width"] = spec.TRACK_SIGNAL
    defaults["silk_line_width"] = 0.15
    defaults["silk_text_size_h"] = 1.0
    defaults["silk_text_size_v"] = 1.0
    defaults["silk_text_thickness"] = 0.15

    widths = sorted({0.0, spec.TRACK_SIGNAL, 0.6, spec.TRACK_POWER, 1.2})
    ds["track_widths"] = widths
    ds["via_dimensions"] = [{"diameter": 0.0, "drill": 0.0}] + [
        {"diameter": nc["via_diameter"], "drill": nc["via_drill"]}
        for nc in spec.NETCLASSES
    ]

    net_settings = pro.setdefault("net_settings", {})
    net_settings["classes"] = [netclass_entry(nc) for nc in spec.NETCLASSES]
    net_settings["netclass_assignments"] = spec.netclass_assignments()
    net_settings["netclass_patterns"] = [
        {"netclass": cls, "pattern": net}
        for net, cls in sorted(spec.netclass_assignments().items())
    ]

    pro["meta"] = {"filename": os.path.basename(args.out), "version": 3}
    pro["libraries"] = {"pinned_footprint_libs": [], "pinned_symbol_libs": []}
    pro["sheets"] = [["00000000-0000-0000-0000-000000000000", "Root"]]
    pro["text_variables"] = {}

    with open(args.out, "w") as fh:
        json.dump(pro, fh, indent=2)
        fh.write("\n")

    print("wrote %s" % args.out)
    for nc in spec.NETCLASSES:
        print("  netclass %-8s track %.2f mm  via %.1f/%.1f mm"
              % (nc["name"], nc["track_width"], nc["via_diameter"], nc["via_drill"]))
    print("  %d nets assigned to %s" % (len(spec.power_class_nets()),
                                        spec.POWER_CLASS_NAME))


if __name__ == "__main__":
    main()
