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
SCH="$PROJ/jaladarangam-control-board.kicad_sch"
OUT="$HW/review"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cli() { "$KICAD_APPIMAGE" kicad-cli "$@"; }
kpy() { "$KICAD_ROOT/AppRun" python3.11 "$@"; }
step() { printf '\n=== %s ===\n' "$1"; }

mkdir -p "$OUT"

step "1/5  3D renders"
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

step "2/5  board-area SVG plots"
cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet \
    --layers "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts" \
    --output "$TMP/layout.svg" "$PCB" | tail -1
# Black-and-white for the silkscreen views: KiCad's silkscreen yellow on a
# white page is low contrast, and these exist to be read.
cli pcb export svg --mode-single --page-size-mode 2 --exclude-drawing-sheet \
    --black-and-white --layers "F.Silkscreen,Edge.Cuts" \
    --output "$TMP/silk.svg" "$PCB" | tail -1

step "3/5  connector crop regions"
kpy "$HERE/dump_regions.py" "$PCB" "$TMP/regions.json"

step "4/5  rasterise"
python3 "$HERE/rasterize_svg.py" "$TMP/layout.svg" --out "$OUT/pcb_2d_layout.png" \
    --px-per-mm 16
python3 "$HERE/rasterize_svg.py" "$TMP/silk.svg" --out "$OUT/pcb_silkscreen.png" \
    --px-per-mm 16 --crops "$TMP/regions.json" --crop-dir "$OUT" \
    --crop-px-per-mm 60

step "5/5  schematic + routed-board PDFs"
# PDF is the primary schematic deliverable: it stays vector, so a dense A2
# sheet is readable at any zoom. A 300 dpi PNG goes alongside it for quick
# viewing without a PDF reader.
cli sch export pdf --output "$OUT/schematic.pdf" "$SCH" | tail -1
cli pcb export pdf --layers "F.Cu,B.Cu,F.Silkscreen,Edge.Cuts" --mode-single \
    --output "$OUT/pcb_routed.pdf" "$PCB" | tail -1

# One PNG per schematic sheet. This board is a single sheet, but naming is
# driven by the actual page count so extra sheets do not silently go missing.
pages="$(pdfinfo "$OUT/schematic.pdf" | awk '/^Pages:/{print $2}')"
rm -f "$OUT"/schematic_p*.png "$OUT"/schematic.png
if [ "$pages" -eq 1 ]; then
    pdftoppm -r 300 -png -singlefile "$OUT/schematic.pdf" "$OUT/schematic"
    echo "$OUT/schematic.png (1 sheet, 300 dpi)"
else
    pdftoppm -r 300 -png "$OUT/schematic.pdf" "$OUT/schematic_p"
    echo "$OUT/schematic_p*.png ($pages sheets, 300 dpi)"
fi

printf '\nReview images in %s\n' "$OUT"
ls -1 "$OUT"
