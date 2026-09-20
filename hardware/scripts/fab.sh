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

step "1/3  gerbers"
cli pcb export gerbers --output "$OUT/gerbers/" \
    --layers "F.Cu,B.Cu,F.Silkscreen,B.Silkscreen,F.Mask,B.Mask,Edge.Cuts" \
    --no-protel-ext "$PCB" | tail -1

step "2/3  drill files"
cli pcb export drill --output "$OUT/gerbers/" --format excellon \
    --drill-origin absolute --excellon-units mm \
    --generate-map --map-format gerberx2 "$PCB" | tail -1

step "3/3  BOM"
cli sch export bom --output "$OUT/bom_kicad.csv" \
    --fields 'Reference,Value,Footprint,${QUANTITY},Description,${DNP}' \
    --labels 'Refs,Value,Footprint,Qty,Description,DNP' \
    --group-by 'Value,Footprint,${DNP}' "$SCH" | tail -1
python3 "$HERE/make_bom.py" --out "$OUT/bom.csv"

printf '\nFabrication outputs in %s\n' "$OUT"
printf 'Review renders are produced by scripts/make_review.sh into %s/review\n' "$HW"
