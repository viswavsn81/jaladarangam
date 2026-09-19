#!/usr/bin/env bash
# Produce fabrication outputs from the routed board.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/kienv.sh"

HW="$(cd "$HERE/.." && pwd)"
PROJ="$HW/jaladarangam-control-board"
NAME="jaladarangam-control-board"
PCB="$PROJ/$NAME.kicad_pcb"
SCH="$PROJ/$NAME.kicad_sch"
OUT="$HW/fab"

cli() { "$KICAD_APPIMAGE" kicad-cli "$@"; }
step() { printf '\n=== %s ===\n' "$1"; }

mkdir -p "$OUT/gerbers"

step "1/4  gerbers"
cli pcb export gerbers --output "$OUT/gerbers/" \
    --layers "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" \
    --no-protel-ext "$PCB" | tail -1

step "2/4  drill files"
cli pcb export drill --output "$OUT/gerbers/" --format excellon \
    --drill-origin absolute --excellon-units mm \
    --generate-map --map-format gerberx2 "$PCB" | tail -1

step "3/4  BOM"
cli sch export bom --output "$OUT/bom_kicad.csv" \
    --fields 'Reference,Value,Footprint,${QUANTITY},Description,${DNP}' \
    --labels 'Refs,Value,Footprint,Qty,Description,DNP' \
    --group-by 'Value,Footprint,${DNP}' "$SCH" | tail -1
python3 "$HERE/make_bom.py" --out "$OUT/bom.csv"

step "4/4  review renders"
cli sch export pdf --output "$HW/docs/schematic.pdf" "$SCH" | tail -1
cli pcb export pdf --layers "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts" --mode-single \
    --output "$HW/docs/pcb_routed.pdf" "$PCB" | tail -1

printf '\nFabrication outputs in %s\n' "$OUT"
