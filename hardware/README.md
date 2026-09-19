# Jaladarangam Instrument Control Board

KiCad 10 project for the instrument's control board: a Raspberry Pi 3 reads 8
analog FSR note keys through an MCP3008 SPI ADC, and drives 8 vibration motors
through a 74HC595 shift register feeding a ULN2803A Darlington array. A 74HC165
is fitted as a socketed but unpopulated digital-input expansion.

Logic runs at 3.3 V. **MOTOR_V+ is a separate supply rail** sharing only GND
with the logic domain — it is never tied to +3V3.

Board: 145 × 110 mm, 2 layers, through-hole throughout, all four ICs socketed.

## Everything is generated from one file

`scripts/board_spec.py` is the single source of truth: components, pin-to-net
assignments, schematic and PCB placement, design rules and net classes. The
schematic, PCB, project file and BOM are all generated from it, so there is no
second place for the wiring to drift.

Nothing here is hand-edited. To change the board, change `board_spec.py` and
re-run the pipeline.

```
scripts/build.sh     board_spec -> .kicad_pro -> .kicad_sch -> .kicad_pcb -> .dsn
scripts/route.sh     autoroute, import the session, DRC, zone check
scripts/fab.sh       gerbers, drill files, BOM, review PDFs
```

The order in `build.sh` matters. `make_project_file.py` writes the net classes
into the `.kicad_pro`; `gen_pcb.py` then **binds that project to the board**
before saving. A bare `pcbnew.BOARD()` carries KiCad's built-in defaults (one
0.2 mm class), and saving such a board writes those defaults straight over the
project file — which is exactly how the MOTOR_V+ Power class was silently lost
once. `gen_pcb.py` now refuses to write a board whose net classes are wrong.

## Verification

Each stage is checked independently rather than trusted:

| Check | What it proves |
|---|---|
| `board_spec.sanity_check` | No duplicate refs, no single-pad nets, MOTOR_V+ and +3V3 share no pad, divider/driver/aux nets have the right pad counts |
| `kicad-cli sch erc` | KiCad's own electrical rules — 0 violations |
| `verify_netlist.py` | KiCad's exported netlist matches `board_spec` pad-for-pad, and every deliberately open pin is accounted for |
| `verify_netclasses.py` | The DSN handed to the router really carries 0.8 mm on the motor rail and 0.4 mm on signals |
| `import_ses.py` | Track widths that actually landed on copper match their net class |
| `kicad-cli pcb drc` | 0 violations, 0 unconnected |
| `verify_zones.py` | Motor and analog copper stayed in their own zones after routing |

## Toolchain

No root, no paid services.

- **KiCad 10.0.6**, official AppImage in `/home/pyru/opt/kicad10`. Provides
  `kicad-cli` and a bundled `python3.11` with `pcbnew`.
- **FreeRouting 2.4.1** headless CLI in `/home/pyru/opt/freerouting`, via a
  Specctra DSN → SES round-trip.
- **Temurin JDK 25** in `/home/pyru/opt/jdk25` — FreeRouting's jar is
  class-file 69 and the system JDK is 21.

`scripts/kienv.sh` wires these together and keeps KiCad's config and library
tables inside `hardware/.kicad-config/`, so builds do not depend on any
developer's `~/.config/kicad` state.

## Layout

Signal flow runs left to right, with the two noisy domains held apart:

```
Pi header | analog input zone | << 14 mm empty corridor >> | motor driver zone
(left edge) (FSR headers top    (nothing routed across it   (motor headers
             edge, pulldowns,     but GND and +3V3)          right edge,
             MCP3008)                                        supply bottom)
                 |
   74HC165 expansion block (DNP) along the bottom edge
```

Every off-board connector is edge-accessible and captioned on silkscreen:
`FSR0-7`, `M0-7`, `MOTOR PWR`, `GND AUX D0-D7 GND`, `RPi GPIO`.

## Notes for assembly

- Fit all four IC sockets, **including U4's** — the 74HC165 itself is the only
  DNP part, so the expansion can be populated later with no rework. Its
  pulldowns (R9-R16) and header (J19) are populated.
- J19 is a 1×10: pins 1 and 10 are GND, pins 2-9 are D0-D7.
- Each FSR header is `+3V3` on pin 1, channel node on pin 2. The 10 k pulldown
  is on-board; the FSR forms the upper leg of the divider.
- Each motor header is `MOTOR_V+` on pin 1, the ULN2803A output on pin 2.
- `fab/bom.csv` includes the sockets and the off-board parts;
  `fab/bom_kicad.csv` is KiCad's own export of the schematic parts only.
