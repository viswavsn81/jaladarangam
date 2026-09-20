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
scripts/fab.sh       gerbers, drill files, BOM
scripts/make_review.sh   3D renders, 2D layout, silkscreen close-ups -> review/
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

## Review images

`review/` is the single home for reviewable output - schematic and board, PDF
and PNG - so the design can be looked at without opening KiCad. It regenerates
with `scripts/make_review.sh`:

| File | What it shows |
|---|---|
| `schematic.pdf` | Full schematic, vector - the one to read properly |
| `schematic.png` | Same sheet at 300 dpi, for a quick look |
| `pcb_routed.pdf` | Routed board, vector |
| `pcb_3d_iso.png` | 3D isometric with component bodies |
| `pcb_3d_top.png` / `pcb_3d_bottom.png` | 3D straight-on, both sides |
| `pcb_2d_layout.png` | 2D layout: both copper layers, silkscreen, outline |
| `pcb_silkscreen.png` | Silkscreen + board outline only, no copper |
| `silk_fsr_headers.png` | Close-up: FSR note-key headers J2-J9 |
| `silk_motor_headers.png` | Close-up: motor headers J10-J17 |
| `silk_motor_power.png` | Close-up: motor supply input J18 |
| `silk_aux_header.png` | Close-up: AUX digital input header J19 |
| `silk_pi_header.png` | Close-up: Raspberry Pi GPIO header J1 |

The silkscreen views plot `F.Silkscreen` and `Edge.Cuts` only, in black and
white - no copper behind the captions, and far better contrast than KiCad's
silkscreen yellow on a white page. `Edge.Cuts` is kept purely for orientation.

Crops come from the footprints themselves (`dump_regions.py` reads the board),
not hard-coded rectangles, so they stay correct if placement changes. KiCad's
`--page-size-mode 2` SVG carries a viewBox in board millimetres, so a crop is
just a narrowed viewBox rather than pixel arithmetic.

The schematic is one A2 sheet. PDF is the primary form because it stays vector
and a dense sheet reads at any zoom; the 300 dpi PNG is there for convenience.
The PNG step is driven by the PDF's actual page count, so extra sheets would be
exported as `schematic_p1.png`, `schematic_p2.png` rather than silently lost.

3D renders need the 3D model packages, which the lite AppImage omits;
`kienv.sh` points `KICAD10_3DMODEL_DIR` at a full KiCad extract when one is
present and warns if it is not. U4 renders as bare pads because KiCad hides
3D models for DNP parts - its socket is still fitted.

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
