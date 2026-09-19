#!/usr/bin/env bash
# Regenerate every project artefact from board_spec.py, in dependency order.
#
# Order matters and is not incidental:
#   board_spec  ->  .kicad_pro  ->  .kicad_pcb  ->  .dsn
# make_project_file writes the net classes into the project; gen_pcb then binds
# that project to the board before saving, so SaveBoard preserves them instead
# of overwriting them with pcbnew's built-in defaults.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/kienv.sh"

HW="$(cd "$HERE/.." && pwd)"
PROJ="$HW/jaladarangam-control-board"
NAME="jaladarangam-control-board"
SCH="$PROJ/$NAME.kicad_sch"
PCB="$PROJ/$NAME.kicad_pcb"
PRO="$PROJ/$NAME.kicad_pro"
SYM="$PROJ/jaladarangam.kicad_sym"

step() { printf '\n=== %s ===\n' "$1"; }
cli() { "$KICAD_APPIMAGE" kicad-cli "$@"; }
kpy() { "$KICAD_ROOT/AppRun" python3.11 "$@"; }

cd "$HERE"

step "1/8  board_spec self-check"
python3 board_spec.py | tail -2

step "2/8  project symbol library"
python3 make_project_lib.py --symbols "$KICAD10_SYMBOL_DIR" --out "$SYM"

step "3/8  project file (design rules + net classes)"
python3 make_project_file.py --template "$KICAD_ROOT/share/kicad/template/kicad.kicad_pro" --out "$PRO"

step "4/8  schematic"
python3 gen_schematic.py --symbols "$KICAD10_SYMBOL_DIR" --project-lib "$SYM" --out "$SCH"

step "5/8  PCB (inherits net classes from the project)"
kpy gen_pcb.py --footprints "$KICAD10_FOOTPRINT_DIR" --project "$PRO" --out "$PCB"

step "6/8  ERC"
cli sch erc --output "$PROJ/erc.rpt" --severity-all "$SCH" | tail -2

step "7/8  netlist cross-check against board_spec"
cli sch export netlist --format kicadsexpr --output "$HW/routing/netlist.net" "$SCH" >/dev/null
python3 verify_netlist.py "$HW/routing/netlist.net"

step "8/8  Specctra DSN export + net class verification"
kpy export_dsn.py "$PCB" "$HW/routing/board.dsn"
python3 verify_netclasses.py "$HW/routing/board.dsn"

printf '\nBuild complete.\n'
