#!/usr/bin/env bash
# Autoroute the board with FreeRouting, import the result, and run DRC.
#
# FreeRouting is a Java app needing JDK 25 (its jar is class-file 69); the
# system JDK is 21, so a local Temurin 25 is used. Everything here is free and
# runs offline - no accounts, no credits.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$HERE/kienv.sh"

HW="$(cd "$HERE/.." && pwd)"
PROJ="$HW/jaladarangam-control-board"
NAME="jaladarangam-control-board"
PCB="$PROJ/$NAME.kicad_pcb"
PRO="$PROJ/$NAME.kicad_pro"

FREEROUTING_JAR="${FREEROUTING_JAR:-/home/pyru/opt/freerouting/freerouting-2.4.1.jar}"
JAVA="${JAVA:-$(ls -d /home/pyru/opt/jdk25/jdk-25*/bin/java | head -1)}"
PASSES="${PASSES:-100}"
THREADS="${THREADS:-4}"

step() { printf '\n=== %s ===\n' "$1"; }

step "1/4  autoroute (FreeRouting headless)"
"$JAVA" -jar "$FREEROUTING_JAR" \
    -de "$HW/routing/board.dsn" -do "$HW/routing/board.ses" \
    -mp "$PASSES" -mt "$THREADS" 2>&1 \
    | grep -E "Auto-routing stage completed|Optimization stage completed|Successfully saved|ERROR"

step "2/4  import the routed session"
"$KICAD_ROOT/AppRun" python3.11 "$HERE/import_ses.py" "$PCB" "$HW/routing/board.ses" --project "$PRO"

step "3/4  DRC on the routed board"
"$KICAD_APPIMAGE" kicad-cli pcb drc --output "$PROJ/drc_routed.rpt" \
    --severity-all --format report "$PCB" | tail -3

step "4/4  zone separation check"
"$KICAD_ROOT/AppRun" python3.11 "$HERE/verify_zones.py" "$PCB"

printf '\nRouting complete.\n'
