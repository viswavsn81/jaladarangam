#!/usr/bin/env bash
# Produce the review images in hardware/review/: 3D views, the 2D layout, and
# silkscreen-only views including a close-up of every off-board connector.
#
# The silkscreen views plot F.Silkscreen and Edge.Cuts only, so connector
# captions are legible with no copper behind them.  Edge.Cuts is kept purely
# for orientation - it is the board outline, not copper.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/kienv.sh"

HW="$(cd "$HERE/.." && pwd)"
PROJ="$HW/jaladarangam-control-board"
PCB="$PROJ/jaladarangam-control-board.kicad_pcb"
OUT="$HW/review"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cli() { "$KICAD_APPIMAGE" kicad-cli "$@"; }
kpy() { "$KICAD_ROOT/AppRun" python3.11 "$@"; }
step() { printf '\n=== %s ===\n' "$1"; }

mkdir -p "$OUT"

step "1/4  3D renders"
if [ ! -d "$KICAD10_3DMODEL_DIR" ]; then
    echo "WARNING: no 3D models at $KICAD10_3DMODEL_DIR - components will be missing"
fi
cli pcb render --output "$OUT/pcb_3d_top.png" --width 2200 --height 1700 \
    --side top --quality high --background opaque --zoom 0.9 "$PCB" | tail -1
cli pcb render --output "$OUT/pcb_3d_iso.png" --width 2200 --height 1700 \
    --side top --rotate "-30,0,25" --perspective --floor --quality high \
    --background opaque --zoom 0.95 "$PCB" | tail -1
cli pcb render --output "$OUT/pcb_3d_bottom.png" --width 2200 --height 1700 \
    --side bottom --quality high --background opaque --zoom 0.9 "$PCB" | tail -1

step "2/4  board-area SVG plots"
cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet \
    --layers "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts" \
    --output "$TMP/layout.svg" "$PCB" | tail -1
# Black-and-white for the silkscreen views: KiCad's silkscreen yellow on a
# white page is low contrast, and these exist to be read.
cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet \
    --black-and-white --layers "F.Silkscreen,Edge.Cuts" \
    --output "$TMP/silk.svg" "$PCB" | tail -1

step "3/4  connector crop regions"
kpy "$HERE/dump_regions.py" "$PCB" "$TMP/regions.json"

step "4/4  rasterise"
python3 "$HERE/rasterize_svg.py" "$TMP/layout.svg" --out "$OUT/pcb_2d_layout.png" \
    --px-per-mm 16
python3 "$HERE/rasterize_svg.py" "$TMP/silk.svg" --out "$OUT/pcb_silkscreen.png" \
    --px-per-mm 16 --crops "$TMP/regions.json" --crop-dir "$OUT" \
    --crop-px-per-mm 60

printf '\nReview images in %s\n' "$OUT"
ls -1 "$OUT"
