#!/usr/bin/env bash
# Shared environment for every KiCad invocation in this project.
#
# KiCad is used from the official 10.0.6 AppImage (no root needed).  Config and
# library tables are kept inside the project so builds are self-contained and
# do not depend on a developer's ~/.config/kicad state.
set -euo pipefail

KICAD_APPIMAGE="${KICAD_APPIMAGE:-/home/pyru/opt/kicad10/kicad-10.0.6-x86_64-lite.AppImage}"
KICAD_ROOT="${KICAD_ROOT:-/home/pyru/opt/kicad10/squashfs-root}"
HW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

export KICAD10_SYMBOL_DIR="$KICAD_ROOT/share/kicad/symbols"
export KICAD10_FOOTPRINT_DIR="$KICAD_ROOT/share/kicad/footprints"
# The lite AppImage ships no 3D models; the full extract provides them and is
# used for 3D renders when present.
KICAD_FULL_ROOT="${KICAD_FULL_ROOT:-/home/pyru/opt/kicad10-full/squashfs-root}"
if [ -d "$KICAD_FULL_ROOT/share/kicad/3dmodels" ]; then
    export KICAD10_3DMODEL_DIR="$KICAD_FULL_ROOT/share/kicad/3dmodels"
else
    export KICAD10_3DMODEL_DIR="$KICAD_ROOT/share/kicad/3dmodels"
fi
export KICAD10_TEMPLATE_DIR="$KICAD_ROOT/share/kicad/template"
# KiCad resolves its settings dir as $XDG_CONFIG_HOME/kicad/<version>/.
export XDG_CONFIG_HOME="$HW_DIR/.kicad-config"

# First use: seed the library tables from KiCad's own templates.
mkdir -p "$XDG_CONFIG_HOME/kicad/10.0"
for tbl in sym-lib-table fp-lib-table; do
    dest="$XDG_CONFIG_HOME/kicad/10.0/$tbl"
    [ -f "$dest" ] || cp "$KICAD_ROOT/share/kicad/template/$tbl" "$dest"
done

kicad_cli() { "$KICAD_APPIMAGE" kicad-cli "$@"; }
kicad_python() { "$KICAD_ROOT/AppRun" python3.11 "$@"; }
