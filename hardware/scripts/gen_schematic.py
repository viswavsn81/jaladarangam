#!/usr/bin/env python3
"""Generate the Jaladarangam control board schematic (.kicad_sch, KiCad 10).

Every pin of every component gets a short wire stub terminating in either a
net label or a power symbol.  That keeps the drawing unambiguous and makes the
generated connectivity match ``board_spec`` exactly, which ERC and the exported
netlist then verify independently.
"""

import argparse
import os
import uuid as uuidmod

import kisexp
from kisexp import Atom, QStr
import symlib
import board_spec as spec

SCH_VERSION = "20260306"
GENERATOR_VERSION = "10.0"
PAPER = "A2"

# Deterministic UUIDs keep regenerated files diffable.
NS = uuidmod.UUID("6f1a5c2e-9d44-4b8a-9f3e-2c7d18a6b405")

STUB = 5.08          # stub length for a pin that ends in a net label, mm
# Power symbols carry their own graphic, so they sit closer in.  On a 2.54 mm
# pitch connector a 5.08 mm stub would push a GND triangle straight through the
# neighbouring pin's label.
STUB_POWER = 2.54
LABEL_FONT = 1.27

POWER_SYMS = {
    spec.NET_3V3: "power:+3V3",
    spec.NET_GND: "power:GND",
    spec.NET_MOTOR: "jaladarangam:MOTOR_V+",
}

# Pins deliberately left unconnected, flagged so ERC stays clean.
NO_CONNECT_PINS = [
    ("U2", "9"),    # 74HC595 QH' - no daisy-chained second 595
    ("U4", "7"),    # 74HC165 QH' - no daisy-chained second 165
]

ZONE_NOTES = [
    (95.0, 40.0, "ANALOG INPUT ZONE - 8 FSR note keys -> MCP3008 SPI ADC"),
    (260.0, 40.0, "MOTOR DRIVER ZONE - 74HC595 -> ULN2803A -> 8 vibration motors"),
    (95.0, 240.0, "DIGITAL INPUT EXPANSION (DNP) - socket fitted, populate later"),
    (25.0, 40.0, "RASPBERRY PI 3 INTERFACE"),
    (260.0, 250.0,
     "MOTOR_V+ is a separate supply rail. It shares ONLY GND with the 3.3V"),
    (260.0, 255.0,
     "logic domain and is never tied to +3V3."),
    (260.0, 265.0,
     "All four ICs are socketed. Only U4 is DNP - its socket is fitted and its\npulldowns R9-R16 and header J19 are populated, so the 74HC165 can be\ndropped in later without rework."),
]


def det_uuid(key):
    return QStr(str(uuidmod.uuid5(NS, key)))


def effects(size=LABEL_FONT, justify=None, hide=False):
    node = [Atom("effects"), [Atom("font"), [Atom("size"), Atom(_n(size)), Atom(_n(size))]]]
    if justify:
        node.append([Atom("justify")] + [Atom(j) for j in justify])
    if hide:
        node.append([Atom("hide"), Atom("yes")])
    return node


def _n(v):
    """Format a number the way KiCad does - no trailing zeros."""
    s = ("%.4f" % float(v)).rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def prop(name, value, at, hide=False, justify=None, size=LABEL_FONT):
    node = [Atom("property"), QStr(name), QStr(value),
            [Atom("at"), Atom(_n(at[0])), Atom(_n(at[1])), Atom(_n(at[2] if len(at) > 2 else 0))],
            [Atom("show_name"), Atom("no")],
            [Atom("do_not_autoplace"), Atom("no")]]
    if hide:
        node.append([Atom("hide"), Atom("yes")])
    node.append(effects(size, justify))
    return node


def wire(p1, p2, key):
    return [Atom("wire"),
            [Atom("pts"),
             [Atom("xy"), Atom(_n(p1[0])), Atom(_n(p1[1]))],
             [Atom("xy"), Atom(_n(p2[0])), Atom(_n(p2[1]))]],
            [Atom("stroke"), [Atom("width"), Atom("0")], [Atom("type"), Atom("default")]],
            [Atom("uuid"), det_uuid("wire:" + key)]]


def label(text, at, angle, justify, key):
    return [Atom("label"), QStr(text),
            [Atom("at"), Atom(_n(at[0])), Atom(_n(at[1])), Atom(_n(angle))],
            effects(LABEL_FONT, justify),
            [Atom("uuid"), det_uuid("label:" + key)]]


def text_note(at, body, key, size=1.778):
    return [Atom("text"), QStr(body),
            [Atom("exclude_from_sim"), Atom("no")],
            [Atom("at"), Atom(_n(at[0])), Atom(_n(at[1])), Atom("0")],
            effects(size, ["left", "bottom"]),
            [Atom("uuid"), det_uuid("text:" + key)]]


def no_connect(at, key):
    return [Atom("no_connect"),
            [Atom("at"), Atom(_n(at[0])), Atom(_n(at[1]))],
            [Atom("uuid"), det_uuid("nc:" + key)]]


class SchematicBuilder:
    def __init__(self, lib, project_name):
        self.lib = lib
        self.project = project_name
        self.items = []
        self.used_lib_ids = []
        self.pwr_count = 0
        self.flag_count = 0

    def need(self, lib_id):
        if lib_id not in self.used_lib_ids:
            self.used_lib_ids.append(lib_id)

    # ------------------------------------------------------------ symbols
    def place(self, ref, value, lib_id, at, footprint="", desc="", dnp=False,
              in_bom=True, on_board=True, show_value=True, ref_at=None, val_at=None):
        self.need(lib_id)
        pins = self.lib.pins(lib_id)
        x, y = at

        # KiCad positions Reference and Value from the library definition, in
        # symbol space (Y up).  Reuse those so text lands where the symbol's
        # author intended rather than wherever a bounding box suggests.
        if ref_at is None:
            ref_at = self._lib_prop_at(lib_id, "Reference", at)
        if val_at is None:
            val_at = self._lib_prop_at(lib_id, "Value", at)

        node = [Atom("symbol"),
                [Atom("lib_id"), QStr(lib_id)],
                [Atom("at"), Atom(_n(x)), Atom(_n(y)), Atom("0")],
                [Atom("unit"), Atom("1")],
                [Atom("body_style"), Atom("1")],
                [Atom("exclude_from_sim"), Atom("no")],
                [Atom("in_bom"), Atom("yes" if in_bom else "no")],
                [Atom("on_board"), Atom("yes" if on_board else "no")],
                [Atom("in_pos_files"), Atom("yes" if on_board else "no")],
                [Atom("dnp"), Atom("yes" if dnp else "no")],
                [Atom("uuid"), det_uuid("sym:" + ref)],
                prop("Reference", ref, ref_at),
                prop("Value", value, val_at, hide=not show_value),
                prop("Footprint", footprint, (x, y, 0), hide=True),
                prop("Datasheet", "", (x, y, 0), hide=True),
                prop("Description", desc, (x, y, 0), hide=True)]

        for number in sorted(pins, key=lambda p: (len(p), p)):
            node.append([Atom("pin"), QStr(number),
                         [Atom("uuid"), det_uuid("pin:%s:%s" % (ref, number))]])

        node.append([Atom("instances"),
                     [Atom("project"), QStr(self.project),
                      [Atom("path"), QStr("/" + str(self.root_uuid)),
                       [Atom("reference"), QStr(ref)],
                       [Atom("unit"), Atom("1")]]]])
        self.items.append(node)
        return pins

    def _lib_prop_at(self, lib_id, name, origin):
        """Screen position of a library property, for a symbol placed at origin."""
        node = self.lib.flat(lib_id)
        for child in node:
            if isinstance(child, list) and kisexp.head(child) == "property" \
                    and str(child[1]) == name:
                at = kisexp.find(child, "at")
                if at:
                    return (round(origin[0] + float(at[1]), 4),
                            round(origin[1] - float(at[2]), 4),
                            float(at[3]) if len(at) > 3 else 0.0)
        return (origin[0], origin[1], 0.0)

    # -------------------------------------------------------------- stubs
    def stub(self, ref, number, pin, origin, net):
        """Draw the stub from one pin and terminate it with a label or power symbol."""
        start = symlib.pin_endpoint(pin, origin)
        dx, dy = symlib.pin_outward(pin)
        length = STUB_POWER if net in POWER_SYMS else STUB
        end = (round(start[0] + dx * length, 4), round(start[1] + dy * length, 4))
        key = "%s.%s" % (ref, number)
        self.items.append(wire(start, end, key))

        if net in POWER_SYMS:
            self.place_power(POWER_SYMS[net], end, (dx, dy), key)
        else:
            if dx > 0.5:
                angle, just = 0, ["left", "bottom"]
            elif dx < -0.5:
                angle, just = 0, ["right", "bottom"]
            elif dy < -0.5:
                angle, just = 90, ["left", "bottom"]
            else:
                angle, just = 90, ["right", "bottom"]
            self.items.append(label(net, end, angle, just, key))

    def place_power(self, lib_id, point, direction, key):
        """Place a power symbol so its single pin lands exactly on ``point``."""
        self.need(lib_id)
        pins = self.lib.pins(lib_id)
        pin = list(pins.values())[0]
        # screen = origin + (px, -py)  =>  origin = point - (px, -py)
        origin = (round(point[0] - pin["x"], 4), round(point[1] + pin["y"], 4))
        self.pwr_count += 1
        ref = "#PWR%02d" % self.pwr_count
        name = lib_id.split(":", 1)[1]
        self.place(ref, name, lib_id, origin, in_bom=False, on_board=False)
        # A power symbol's reference is never shown on the drawing.
        _hide_property(self.items[-1], "Reference")

    def power_flag(self, net, at):
        """A PWR_FLAG so ERC sees the rail as driven."""
        lib_id = "power:PWR_FLAG"
        self.need(lib_id)
        pins = self.lib.pins(lib_id)
        pin = list(pins.values())[0]
        origin = (round(at[0] - pin["x"], 4), round(at[1] + pin["y"], 4))
        self.flag_count += 1
        ref = "#FLG%02d" % self.flag_count
        self.place(ref, "PWR_FLAG", lib_id, origin, in_bom=False, on_board=False)
        _hide_property(self.items[-1], "Reference")
        # Tie the flag to the rail with its own stub + power symbol.
        end = (origin[0], round(origin[1] + 5.08, 4))
        self.items.append(wire((origin[0], round(origin[1] - pin["y"], 4)), end,
                               "flag%s" % ref))
        self.place_power(POWER_SYMS[net], end, (0, 1), "flag%s" % ref)


def _hide_property(sym_node, name):
    for child in sym_node:
        if isinstance(child, list) and kisexp.head(child) == "property" and str(child[1]) == name:
            child.insert(5, [Atom("hide"), Atom("yes")])
            return


def build(lib, out_path):
    comps = spec.build_components()
    nets = spec.build_nets(comps)
    problems = spec.sanity_check(comps, nets)
    if problems:
        raise SystemExit("board_spec sanity check failed:\n  " + "\n  ".join(problems))

    b = SchematicBuilder(lib, spec.PROJECT_NAME)
    b.root_uuid = det_uuid("sheet:root")

    for i, (x, y, body) in enumerate(ZONE_NOTES):
        b.items.append(text_note((x, y), body, "zone%d" % i,
                                 size=1.778 if i < 4 else 1.27))

    nc = dict(NO_CONNECT_PINS)
    for comp in comps:
        pins = b.place(comp.ref, comp.value, comp.lib_id, comp.sch_at,
                       footprint=comp.footprint, desc=comp.desc, dnp=comp.dnp)
        for number, pin in pins.items():
            net = comp.pins.get(number)
            if net:
                b.stub(comp.ref, number, pin, comp.sch_at, net)
            else:
                # Unused pin: mark it no-connect right at the pin.
                point = symlib.pin_endpoint(pin, comp.sch_at)
                b.items.append(no_connect(point, "%s.%s" % (comp.ref, number)))

    # Rails come in through passive connector pins, so ERC needs an explicit
    # driver on each one.
    b.power_flag(spec.NET_3V3, (25.4, 190.5))
    b.power_flag(spec.NET_GND, (43.18, 190.5))
    b.power_flag(spec.NET_MOTOR, (466.09, 190.5))

    lib_symbols = [Atom("lib_symbols")]
    for lib_id in sorted(b.used_lib_ids):
        lib_symbols.append(lib.flat(lib_id))

    root = [Atom("kicad_sch"),
            [Atom("version"), Atom(SCH_VERSION)],
            [Atom("generator"), QStr("jaladarangam-hardware-gen")],
            [Atom("generator_version"), QStr(GENERATOR_VERSION)],
            [Atom("uuid"), b.root_uuid],
            [Atom("paper"), QStr(PAPER)],
            [Atom("title_block"),
             [Atom("title"), QStr(spec.BOARD_TITLE)],
             [Atom("date"), QStr("")],
             [Atom("rev"), QStr(spec.REVISION)],
             [Atom("company"), QStr(spec.COMPANY)],
             [Atom("comment"), Atom("1"),
              QStr("Raspberry Pi 3 | 8x FSR analog in | 8x vibration motor out")],
             [Atom("comment"), Atom("2"),
              QStr("Logic 3.3V. MOTOR_V+ is a separate rail, common GND only.")]],
            lib_symbols]
    root.extend(b.items)
    root.append([Atom("sheet_instances"),
                 [Atom("path"), QStr("/"), [Atom("page"), QStr("1")]]])
    root.append([Atom("embedded_fonts"), Atom("no")])

    with open(out_path, "w") as fh:
        fh.write(kisexp.dumps(root))
        fh.write("\n")
    return comps, nets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", required=True, help="KiCad symbol library root")
    ap.add_argument("--project-lib", required=True,
                    help="project .kicad_sym holding MOTOR_V+")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    lib = SymbolLibrary_with_project(args.symbols, args.project_lib)
    comps, nets = build(lib, args.out)
    print("wrote %s" % args.out)
    print("  %d components, %d nets" % (len(comps), len(nets)))


class SymbolLibrary_with_project(symlib.SymbolLibrary):
    """Symbol lookup that also resolves the project-local ``jaladarangam`` lib."""

    def __init__(self, root, project_lib):
        super().__init__(root)
        self.project_lib = project_lib

    def _raw(self, nickname, name):
        if nickname == "jaladarangam":
            with open(self.project_lib) as fh:
                lib = kisexp.parse_one(fh.read())
            for node in kisexp.find_all(lib, "symbol"):
                if str(node[1]) == name:
                    return node
            raise KeyError("no %s in project library" % name)
        return super()._raw(nickname, name)


if __name__ == "__main__":
    main()
