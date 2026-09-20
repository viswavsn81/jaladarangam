#!/usr/bin/env python3
"""Generate the unrouted .kicad_pcb from board_spec, using KiCad's pcbnew API.

Must run under KiCad's own interpreter (see kienv.sh: ``kicad_python``), which
is where the pcbnew module lives.

Placement follows the spec's priorities: functional groups left to right in
signal-flow order, the analog input zone held clear of the motor driver zone,
and every off-board connector on a board edge with a silkscreen caption.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pcbnew
import board_spec as spec

EDGE_WIDTH = 0.15
SILK_WIDTH = 0.15
CAPTION_SIZE = 1.0
CAPTION_GAP = 1.8       # clearance from a connector's copper to its caption

# SETTINGS_MANAGER owns the PROJECT it loads, so it has to outlive the board
# that binds to it.  Module scope keeps it alive for the whole run.
_SETTINGS_MANAGER = None


def bind_project(board, project_path):
    """Bind the board to the real .kicad_pro so it inherits its net classes.

    A bare pcbnew.BOARD() starts with KiCad's built-in defaults - one 0.2 mm
    "Default" class and no assignments.  Saving such a board writes those
    defaults straight over the project file, which is exactly how the
    MOTOR_V+ Power class got wiped before.  Loading the project first makes
    the project authoritative in both directions.
    """
    global _SETTINGS_MANAGER
    if not os.path.exists(project_path):
        raise SystemExit(
            "project file %s does not exist - run make_project_file.py first"
            % project_path)
    _SETTINGS_MANAGER = pcbnew.SETTINGS_MANAGER()
    if not _SETTINGS_MANAGER.LoadProject(project_path):
        raise SystemExit("could not load project %s" % project_path)
    board.SetProject(_SETTINGS_MANAGER.GetProject(project_path))


def check_netclasses(board):
    """Fail loudly if the board did not inherit the intended track widths.

    Without this the pipeline can silently fall back to 0.2 mm everywhere and
    the only symptom is an undersized motor rail on the finished board.
    """
    settings = board.GetDesignSettings().m_NetSettings
    wrong = []
    for net in sorted(spec.build_nets(spec.build_components())):
        want = spec.expected_track_width(net)
        got = pcbnew.ToMM(settings.GetEffectiveNetClass(net).GetTrackWidth())
        if abs(got - want) > 1e-6:
            wrong.append("%s: expected %.2f mm, got %.2f mm" % (net, want, got))
    if wrong:
        raise SystemExit("net classes did not reach the board:\n  "
                         + "\n  ".join(wrong))


def mm(x, y):
    return pcbnew.VECTOR2I_MM(float(x), float(y))


def pad_bbox_center(fp):
    """Centre of the footprint's copper, ignoring silkscreen and courtyard."""
    xs, ys = [], []
    for pad in fp.Pads():
        box = pad.GetBoundingBox()
        xs += [box.GetLeft(), box.GetRight()]
        ys += [box.GetTop(), box.GetBottom()]
    return ((min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2)


def pad_bbox_mm(fp):
    """(left, top, right, bottom) of the footprint's copper, in mm."""
    xs, ys = [], []
    for pad in fp.Pads():
        box = pad.GetBoundingBox()
        xs += [box.GetLeft(), box.GetRight()]
        ys += [box.GetTop(), box.GetBottom()]
    return (pcbnew.ToMM(min(xs)), pcbnew.ToMM(min(ys)),
            pcbnew.ToMM(max(xs)), pcbnew.ToMM(max(ys)))


def caption_position(fp, caption, side, gap=CAPTION_GAP):
    """Where a connector caption goes, relative to the connector's copper."""
    left, top, right, bottom = pad_bbox_mm(fp)
    width = len(caption) * CAPTION_SIZE * 0.85
    if side == "below":
        return (left, bottom + gap)
    if side == "above":
        return (left, top - gap)
    if side == "left":
        return (left - gap - width, (top + bottom) / 2.0)
    return (right + gap, (top + bottom) / 2.0)


def pad_position_mm(fp, number):
    for pad in fp.Pads():
        if pad.GetNumber() == number:
            pos = pad.GetPosition()
            return (pcbnew.ToMM(pos.x), pcbnew.ToMM(pos.y))
    raise SystemExit("%s has no pad %s" % (fp.GetReference(), number))


def load_footprint(fp_root, footprint_id):
    lib, name = footprint_id.split(":", 1)
    path = os.path.join(fp_root, lib + ".pretty")
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit("could not load footprint %s from %s" % (footprint_id, path))
    return fp


def add_text(board, x, y, text, size, rotation=0.0, layer=None, centre=False):
    item = pcbnew.PCB_TEXT(board)
    item.SetText(text)
    item.SetPosition(mm(x, y))
    item.SetLayer(pcbnew.F_SilkS if layer is None else layer)
    item.SetTextSize(pcbnew.VECTOR2I(pcbnew.FromMM(size), pcbnew.FromMM(size)))
    item.SetTextThickness(pcbnew.FromMM(SILK_WIDTH))
    item.SetTextAngleDegrees(rotation)
    item.SetHorizJustify(pcbnew.GR_TEXT_H_ALIGN_CENTER if centre
                         else pcbnew.GR_TEXT_H_ALIGN_LEFT)
    board.Add(item)
    return item


def add_edge(board, p1, p2):
    seg = pcbnew.PCB_SHAPE(board)
    seg.SetShape(pcbnew.SHAPE_T_SEGMENT)
    seg.SetStart(mm(*p1))
    seg.SetEnd(mm(*p2))
    seg.SetLayer(pcbnew.Edge_Cuts)
    seg.SetWidth(pcbnew.FromMM(EDGE_WIDTH))
    board.Add(seg)


def build(fp_root, out_path, project_path):
    comps = spec.build_components()
    nets = spec.build_nets(comps)
    problems = spec.sanity_check(comps, nets)
    if problems:
        raise SystemExit("board_spec sanity check failed:\n  " + "\n  ".join(problems))

    board = pcbnew.BOARD()
    bind_project(board, project_path)

    ds = board.GetDesignSettings()
    ds.SetCopperLayerCount(2)
    ds.m_TrackMinWidth = pcbnew.FromMM(spec.TRACK_SIGNAL)
    ds.m_ViasMinSize = pcbnew.FromMM(0.8)
    ds.m_MinThroughDrill = pcbnew.FromMM(spec.MIN_THROUGH_DRILL)

    # Board outline.
    w, h = spec.BOARD_W, spec.BOARD_H
    for p1, p2 in [((0, 0), (w, 0)), ((w, 0), (w, h)), ((w, h), (0, h)), ((0, h), (0, 0))]:
        add_edge(board, p1, p2)

    # Nets must exist on the board before pads can be assigned to them.
    netinfo = {}
    for name in sorted(nets):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        netinfo[name] = net

    placed = {}
    for comp in comps:
        if comp.ref not in spec.PCB_PLACEMENT:
            raise SystemExit("no PCB placement for %s" % comp.ref)
        cx, cy, rot = spec.PCB_PLACEMENT[comp.ref]

        fp = load_footprint(fp_root, comp.footprint)
        board.Add(fp)
        fp.SetReference(comp.ref)
        fp.SetValue(comp.value)
        fp.SetOrientationDegrees(rot)
        if comp.dnp:
            fp.SetDNP(True)

        # Footprint origins sit on pad 1, so place by pad-bbox centre instead.
        fp.SetPosition(mm(cx, cy))
        cur = pad_bbox_center(fp)
        want = mm(cx, cy)
        fp.Move(pcbnew.VECTOR2I(want.x - cur[0], want.y - cur[1]))

        for pad in fp.Pads():
            net_name = comp.pins.get(pad.GetNumber())
            if net_name:
                pad.SetNet(netinfo[net_name])
        placed[comp.ref] = fp

    # Silkscreen: zone captions and a per-connector caption.
    for x, y, text, size, rot in spec.SILK_ZONE_LABELS:
        add_text(board, x, y, text, size, rot)

    for ref, caption, side, gap in spec.silk_connector_labels():
        x, y = caption_position(placed[ref], caption, side, gap)
        add_text(board, x, y, caption, CAPTION_SIZE)

    # Polarity marks, each centred over the pad it labels.
    for ref, number, caption in spec.PAD_POLARITY_LABELS:
        px, py = pad_position_mm(placed[ref], number)
        add_text(board, px, py - spec.POLARITY_OFFSET, caption,
                 spec.POLARITY_TEXT_SIZE, centre=True)

    check_netclasses(board)

    board.SetFileName(out_path)
    pcbnew.SaveBoard(out_path, board)

    return board, comps, nets


def report(board, comps, nets):
    print("board %.0f x %.0f mm, 2 layers" % (spec.BOARD_W, spec.BOARD_H))
    print("%d footprints, %d nets" % (len(comps), len(nets)))
    total_pads = sum(len(list(fp.Pads())) for fp in board.GetFootprints())
    connected = sum(1 for fp in board.GetFootprints() for p in fp.Pads()
                    if p.GetNetname())
    print("%d pads, %d carry a net, %d intentionally open"
          % (total_pads, connected, total_pads - connected))
    settings = board.GetDesignSettings().m_NetSettings
    for net in (spec.NET_MOTOR, "MOTOR0", spec.NET_3V3, spec.NET_GND, "SPI_SCLK"):
        nc = settings.GetEffectiveNetClass(net)
        print("  %-9s track %.2f mm" % (net, pcbnew.ToMM(nc.GetTrackWidth())))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--footprints", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--project", required=True,
                    help=".kicad_pro to inherit design rules and net classes from")
    args = ap.parse_args()
    board, comps, nets = build(args.footprints, args.out, args.project)
    print("wrote %s" % args.out)
    report(board, comps, nets)


if __name__ == "__main__":
    main()
