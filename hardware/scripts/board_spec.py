"""Jaladarangam Instrument Control Board - single source of truth.

Every downstream artefact (schematic, PCB, netlist, BOM) is generated from the
tables in this module, so the electrical intent lives in exactly one place.

System summary
--------------
A Raspberry Pi 3 reads 8 analog FSR note keys through an MCP3008 SPI ADC, and
drives 8 vibration motors through a 74HC595 shift register feeding a ULN2803A
Darlington array.  A 74HC165 parallel-in shift register is fitted as a socketed
but unpopulated (DNP) digital-input expansion.

All logic runs at 3.3 V.  Motor power is a separate rail (MOTOR_V+) that shares
only GND with the logic domain and is never tied to +3V3.
"""

PROJECT_NAME = "jaladarangam-control-board"
BOARD_TITLE = "Jaladarangam Instrument Control Board"
REVISION = "A"
COMPANY = "Jaladarangam"

# Net names used throughout.  Power nets are handled with KiCad power symbols.
NET_3V3 = "+3V3"
NET_GND = "GND"
NET_MOTOR = "MOTOR_V+"
POWER_NETS = (NET_3V3, NET_GND, NET_MOTOR)


# KiCad's default schematic connection grid.  Symbol origins must land on it
# or every pin ends up off-grid and ERC complains about each one.
SCH_GRID = 1.27


def snap(value, grid=SCH_GRID):
    return round(round(float(value) / grid) * grid, 4)


class Comp:
    """One placed component.

    ``pins`` maps pin number (as a string) to the net it connects to.
    ``sch_at`` / ``pcb_at`` are (x, y) in mm, ``pcb_rot`` in degrees.
    ``sch_at`` is snapped to the schematic grid on construction.
    """

    def __init__(self, ref, value, lib_id, footprint, pins, sch_at,
                 pcb_at=(0, 0), pcb_rot=0, dnp=False, desc="", zone=""):
        self.ref = ref
        self.value = value
        self.lib_id = lib_id
        self.footprint = footprint
        self.pins = pins
        self.sch_at = (snap(sch_at[0]), snap(sch_at[1]))
        self.pcb_at = pcb_at
        self.pcb_rot = pcb_rot
        self.dnp = dnp
        self.desc = desc
        self.zone = zone

    def __repr__(self):
        return "<Comp %s %s>" % (self.ref, self.value)


# --------------------------------------------------------------------------
# Footprint choices.  Through-hole throughout: the board is hand-assembled,
# all four ICs sit in sockets, and every off-board connection is a header.
# --------------------------------------------------------------------------
FP_DIP16 = "Package_DIP:DIP-16_W7.62mm_Socket"
FP_DIP18 = "Package_DIP:DIP-18_W7.62mm_Socket"
FP_HDR_2X20 = "Connector_PinHeader_2.54mm:PinHeader_2x20_P2.54mm_Vertical"
FP_HDR_1X02 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
FP_HDR_1X10 = "Connector_PinHeader_2.54mm:PinHeader_1x10_P2.54mm_Vertical"
FP_SCREW_2 = "TerminalBlock:TerminalBlock_MaiXu_MX126-5.0-02P_1x02_P5.00mm"
FP_R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal"
FP_C_DISC = "Capacitor_THT:C_Disc_D5.0mm_W2.5mm_P5.00mm"
FP_C_EL5 = "Capacitor_THT:CP_Radial_D5.0mm_P2.50mm"
FP_C_EL8 = "Capacitor_THT:CP_Radial_D8.0mm_P3.50mm"


# --------------------------------------------------------------------------
# Raspberry Pi 40-pin GPIO header.  Physical pin -> net.
# Unlisted pins are deliberately left unconnected.
# --------------------------------------------------------------------------
PI_PINS = {
    "1": NET_3V3,          # 3V3 power
    "17": NET_3V3,         # 3V3 power
    "6": NET_GND, "9": NET_GND, "14": NET_GND, "20": NET_GND,
    "25": NET_GND, "30": NET_GND, "34": NET_GND, "39": NET_GND,
    "11": "SR_SER",        # GPIO17 -> 74HC595 SER
    "13": "SR_RCLK",       # GPIO27 -> 74HC595 RCLK
    "15": "SR_SRCLK",      # GPIO22 -> 74HC595 SRCLK
    "16": "IN_SHLD",       # GPIO23 -> 74HC165 SH/LD
    "18": "IN_CLK",        # GPIO24 -> 74HC165 CLK (separate from SR_SRCLK)
    "19": "SPI_MOSI",      # GPIO10 -> MCP3008 DIN
    "21": "SPI_MISO",      # GPIO9  <- MCP3008 DOUT
    "22": "IN_QH",         # GPIO25 <- 74HC165 QH
    "23": "SPI_SCLK",      # GPIO11 -> MCP3008 CLK
    "24": "SPI_CE0",       # GPIO8  -> MCP3008 CS/SHDN
}

# Pi header pins with no board connection, flagged no-connect so ERC is clean.
PI_UNUSED = [p for p in (str(i) for i in range(1, 41)) if p not in PI_PINS]

# Human-readable annotation for the Pi header pins we actually use.
PI_PIN_LABELS = {
    "1": "3V3", "6": "GND", "9": "GND", "11": "GPIO17", "13": "GPIO27",
    "14": "GND", "15": "GPIO22", "16": "GPIO23", "17": "3V3", "18": "GPIO24",
    "19": "GPIO10", "20": "GND", "21": "GPIO9", "22": "GPIO25", "23": "GPIO11",
    "24": "GPIO8", "25": "GND", "30": "GND", "34": "GND", "39": "GND",
}

# 74HC595 output pin numbers in Q0..Q7 order (QA=15, QB..QH=1..7).
HC595_Q = ["15", "1", "2", "3", "4", "5", "6", "7"]
# ULN2803A: IN1..IN8 are pins 1..8, OUT1..OUT8 are pins 18..11.
ULN_IN = ["1", "2", "3", "4", "5", "6", "7", "8"]
ULN_OUT = ["18", "17", "16", "15", "14", "13", "12", "11"]
# 74HC165 parallel inputs D0..D7, per the board spec.
HC165_D = ["11", "12", "13", "14", "3", "4", "5", "6"]


def build_components():
    """Return every component on the board, in reference order."""
    c = []

    # ---------------- Pi interface ----------------
    c.append(Comp(
        "J1", "RPi_GPIO_2x20", "Connector_Generic:Conn_02x20_Odd_Even",
        FP_HDR_2X20, dict(PI_PINS), sch_at=(50.0, 110.0),
        desc="Raspberry Pi 3 40-pin GPIO header", zone="pi"))

    # ---------------- Analog input zone ----------------
    mcp = {
        "16": NET_3V3,     # VDD
        "15": NET_3V3,     # VREF
        "14": NET_GND,     # AGND
        "9": NET_GND,      # DGND
        "13": "SPI_SCLK",
        "11": "SPI_MOSI",  # DIN
        "12": "SPI_MISO",  # DOUT
        "10": "SPI_CE0",   # CS/SHDN
    }
    for i in range(8):
        mcp[str(i + 1)] = "FSR%d" % i   # CH0..CH7 on pins 1..8
    c.append(Comp("U1", "MCP3008", "Analog_ADC:MCP3008", FP_DIP16, mcp,
                  sch_at=(190.0, 100.0),
                  desc="8-channel 10-bit SPI ADC (socketed)", zone="analog"))

    # FSR voltage dividers: external FSR from +3V3 into the channel pin, 10k
    # from the channel pin to GND.  R pin 1 is the top (signal) pin.
    for i in range(8):
        c.append(Comp("R%d" % (i + 1), "10k", "Device:R", FP_R,
                      {"1": "FSR%d" % i, "2": NET_GND},
                      sch_at=(105.0 + i * 15.24, 195.0),
                      desc="FSR divider pulldown, channel %d" % i, zone="analog"))

    # One 2-pin header per FSR: pin 1 = +3V3, pin 2 = channel node.
    for i in range(8):
        c.append(Comp("J%d" % (i + 2), "FSR%d" % i, "Connector_Generic:Conn_01x02",
                      FP_HDR_1X02, {"1": NET_3V3, "2": "FSR%d" % i},
                      sch_at=(110.0, 55.0 + i * 15.24),
                      desc="Off-board FSR note key %d" % i, zone="analog"))

    # ---------------- Motor driver zone ----------------
    hc595 = {
        "16": NET_3V3,     # VCC
        "8": NET_GND,      # GND
        "10": NET_3V3,     # MR / SRCLR tied high
        "13": NET_GND,     # OE tied low
        "14": "SR_SER",
        "11": "SR_SRCLK",
        "12": "SR_RCLK",
        # pin 9 (QH') intentionally left unconnected - no daisy-chained 595
    }
    for i, p in enumerate(HC595_Q):
        hc595[p] = "MTRDRV%d" % i
    c.append(Comp("U2", "74HC595", "74xx:74HC595", FP_DIP16, hc595,
                  sch_at=(290.0, 95.0),
                  desc="8-bit serial-in parallel-out shift register (socketed)",
                  zone="motor"))

    uln = {"9": NET_GND, "10": NET_MOTOR}   # GND, COM (flyback diode common)
    for i in range(8):
        uln[ULN_IN[i]] = "MTRDRV%d" % i
        uln[ULN_OUT[i]] = "MOTOR%d" % i
    c.append(Comp("U3", "ULN2803A", "Transistor_Array:ULN2803A", FP_DIP18, uln,
                  sch_at=(370.0, 95.0),
                  desc="8-channel Darlington driver array (socketed)",
                  zone="motor"))

    # One 2-pin header per motor: pin 1 = MOTOR_V+, pin 2 = driver output.
    for i in range(8):
        c.append(Comp("J%d" % (i + 10), "MOTOR%d" % i,
                      "Connector_Generic:Conn_01x02", FP_HDR_1X02,
                      {"1": NET_MOTOR, "2": "MOTOR%d" % i},
                      sch_at=(440.0, 55.0 + i * 15.24),
                      desc="Off-board vibration motor %d" % i, zone="motor"))

    # Motor supply input.  Ground is the board's common ground.
    c.append(Comp("J18", "MOTOR_PWR", "Connector_Generic:Conn_01x02",
                  FP_SCREW_2, {"1": NET_MOTOR, "2": NET_GND},
                  sch_at=(440.0, 195.0),
                  desc="Separate motor supply input (V+ / GND)", zone="motor"))

    # ---------------- Digital input expansion (DNP) ----------------
    hc165 = {
        "16": NET_3V3,     # VCC
        "8": NET_GND,      # GND
        "15": NET_GND,     # CLK INH tied low
        "1": "IN_SHLD",    # SH/LD
        "2": "IN_CLK",
        "9": "IN_QH",
        "10": NET_GND,     # SER tied low - no daisy-chained 165
        # pin 7 (QH') intentionally left unconnected
    }
    for i, p in enumerate(HC165_D):
        hc165[p] = "AUX%d" % i
    c.append(Comp("U4", "74HC165", "74xx:74HC165", FP_DIP16, hc165,
                  sch_at=(190.0, 290.0), dnp=True,
                  desc="8-bit parallel-in shift register (socketed, DNP)",
                  zone="aux"))

    for i in range(8):
        c.append(Comp("R%d" % (i + 9), "10k", "Device:R", FP_R,
                      {"1": "AUX%d" % i, "2": NET_GND},
                      sch_at=(105.0 + i * 15.24, 345.0),
                      desc="AUX input pulldown %d" % i, zone="aux"))

    # 1x10 rather than 1x08: pins 1 and 10 are GND so a future sensor wired
    # from either end has a ground reference next to its signal pin.
    aux_hdr = {"1": NET_GND, "10": NET_GND}
    aux_hdr.update({str(i + 2): "AUX%d" % i for i in range(8)})
    c.append(Comp("J19", "AUX_IN", "Connector_Generic:Conn_01x10", FP_HDR_1X10,
                  aux_hdr, sch_at=(110.0, 275.0),
                  desc="Auxiliary digital input header (GND, D0..D7, GND)",
                  zone="aux"))

    # ---------------- Decoupling and bulk ----------------
    caps = [
        ("C1", "100nF", FP_C_DISC, NET_3V3, (232.0, 190.0), "U1 VDD decoupling", "analog"),
        ("C2", "10uF", FP_C_EL5, NET_3V3, (248.0, 190.0), "MCP3008 VREF/VDD bulk", "analog"),
        ("C3", "100nF", FP_C_DISC, NET_3V3, (265.0, 150.0), "U2 VCC decoupling", "motor"),
        ("C4", "100nF", FP_C_DISC, NET_3V3, (245.0, 290.0), "U4 VCC decoupling", "aux"),
        ("C6", "100nF", FP_C_DISC, NET_3V3, (62.0, 175.0), "Pi 3V3 rail decoupling", "pi"),
        ("C7", "10uF", FP_C_EL5, NET_3V3, (80.0, 175.0), "Pi 3V3 rail bulk", "pi"),
    ]
    for ref, val, fp, net, at, desc, zone in caps:
        lib = "Device:C_Polarized" if fp in (FP_C_EL5, FP_C_EL8) else "Device:C"
        c.append(Comp(ref, val, lib, fp, {"1": net, "2": NET_GND},
                      sch_at=at, desc=desc, zone=zone))

    # Motor rail decoupling / bulk - on MOTOR_V+, never on +3V3.
    c.append(Comp("C5", "100nF", "Device:C", FP_C_DISC,
                  {"1": NET_MOTOR, "2": NET_GND}, sch_at=(355.0, 165.0),
                  desc="ULN2803A COM rail decoupling", zone="motor"))
    c.append(Comp("C8", "220uF", "Device:C_Polarized", FP_C_EL8,
                  {"1": NET_MOTOR, "2": NET_GND}, sch_at=(375.0, 165.0),
                  desc="Motor supply bulk reservoir", zone="motor"))

    return c


def build_nets(components):
    """net name -> sorted list of (ref, pin) pads on that net."""
    nets = {}
    for comp in components:
        for pin, net in comp.pins.items():
            nets.setdefault(net, []).append((comp.ref, pin))
    for net in nets:
        nets[net].sort(key=lambda rp: (rp[0], int(rp[1]) if rp[1].isdigit() else 0))
    return nets


def sanity_check(components, nets):
    """Fail loudly on the mistakes that actually matter for this board."""
    problems = []

    refs = [c.ref for c in components]
    dupes = {r for r in refs if refs.count(r) > 1}
    if dupes:
        problems.append("duplicate references: %s" % sorted(dupes))

    # Every net must have at least two pads, or it is a wiring mistake.
    for net, pads in nets.items():
        if len(pads) < 2:
            problems.append("net %s has only one pad: %s" % (net, pads))

    # The motor rail must never touch the logic rail.
    motor_pads = set(nets.get(NET_MOTOR, []))
    logic_pads = set(nets.get(NET_3V3, []))
    if motor_pads & logic_pads:
        problems.append("MOTOR_V+ and +3V3 share pads: %s" % (motor_pads & logic_pads))

    # Each FSR channel: ADC pin + pulldown + header, exactly 3 pads.
    for i in range(8):
        pads = nets.get("FSR%d" % i, [])
        if len(pads) != 3:
            problems.append("FSR%d should have 3 pads, has %d: %s" % (i, len(pads), pads))

    # Each motor output: ULN pin + header, exactly 2 pads.
    for i in range(8):
        if len(nets.get("MOTOR%d" % i, [])) != 2:
            problems.append("MOTOR%d should have 2 pads" % i)
        if len(nets.get("MTRDRV%d" % i, [])) != 2:
            problems.append("MTRDRV%d should have 2 pads" % i)

    # J19 carries a ground reference on both end pins.
    aux_hdr = next((c for c in components if c.ref == "J19"), None)
    if aux_hdr is not None:
        ends = {aux_hdr.pins.get("1"), aux_hdr.pins.get("10")}
        if ends != {NET_GND}:
            problems.append("J19 end pins 1 and 10 must both be GND, got %s" % ends)

    # Polarity marks must agree with the net actually on that pad.
    by_ref = {c.ref: c for c in components}
    for ref, pin, caption, _side, asserts in PAD_POLARITY_LABELS:
        comp = by_ref.get(ref)
        if comp is None:
            problems.append("polarity mark refers to missing component %s" % ref)
            continue
        actual = comp.pins.get(pin)
        if actual != asserts:
            problems.append("%s pad %s is marked %r claiming %s, but carries %s"
                            % (ref, pin, caption, asserts, actual))

    # Each AUX input: 165 pin + pulldown + header, exactly 3 pads.
    for i in range(8):
        if len(nets.get("AUX%d" % i, [])) != 3:
            problems.append("AUX%d should have 3 pads" % i)

    return problems


# --------------------------------------------------------------------------
# Design rules and net classes
#
# These live here, not in the project file, so the schematic, the PCB and the
# .kicad_pro all derive from one table.  make_project_file.py renders them into
# the .kicad_pro; gen_pcb.py then loads that project and binds it to the board
# before saving, so the board and the project can never disagree.
#
# Values are deliberately generous: a hand-soldered 2-layer board well inside
# any low-cost fab's capability.  The motor rail and the eight motor outputs
# carry real current, so they get their own wider class.
# --------------------------------------------------------------------------
CLEARANCE = 0.25
TRACK_SIGNAL = 0.4
TRACK_POWER = 0.8
MIN_THROUGH_DRILL = 0.3

NETCLASSES = [
    {"name": "Default", "track_width": TRACK_SIGNAL, "clearance": CLEARANCE,
     "via_diameter": 0.8, "via_drill": 0.4},
    {"name": "Power", "track_width": TRACK_POWER, "clearance": CLEARANCE,
     "via_diameter": 1.0, "via_drill": 0.5},
]

POWER_CLASS_NAME = "Power"


def power_class_nets():
    """Nets assigned to the wider Power class: both rails, GND, motor outputs."""
    return [NET_3V3, NET_GND, NET_MOTOR] + ["MOTOR%d" % i for i in range(8)]


def netclass_assignments():
    return {net: POWER_CLASS_NAME for net in power_class_nets()}


def expected_track_width(net):
    """Track width a given net must end up with, for verification."""
    return TRACK_POWER if net in power_class_nets() else TRACK_SIGNAL


# --------------------------------------------------------------------------
# PCB layout
#
# Signal flow runs left to right: Pi header, then the analog input zone, then
# the motor driver zone.  The 74HC165 expansion sits as its own block along the
# bottom edge, away from both.
#
# The analog zone (x 25..78) and the motor driver zone (x 92..170) are kept
# apart by an empty corridor so motor switching current has no reason to run
# near an FSR signal line.  Every off-board connector lands on a board edge.
# --------------------------------------------------------------------------
BOARD_W = 145.0
BOARD_H = 110.0
BOARD_MARGIN = 0.0        # outline starts at (0, 0)

ANALOG_X0, ANALOG_X1 = 24.0, 78.0
MOTOR_X0, MOTOR_X1 = 92.0, 145.0
ISOLATION_GAP = (ANALOG_X1, MOTOR_X0)   # deliberately empty corridor

# Each entry is ref -> (centre_x, centre_y, rotation_degrees).  Positions are
# the centre of the footprint's pad bounding box, not the pad-1 origin.
PCB_PLACEMENT = {
    # --- Pi interface, left edge ---
    # Rotation 0 keeps the 2x20 header's long axis vertical, running down the
    # left edge where the Pi's ribbon cable lands.
    "J1": (8.0, 55.0, 0.0),
    "C6": (16.0, 30.0, 0.0),
    "C7": (16.0, 41.0, 0.0),

    # --- Analog input zone ---
    "U1": (50.0, 42.0, 90.0),
    "C1": (69.0, 36.0, 0.0),
    "C2": (69.0, 47.0, 0.0),

    # --- Motor driver zone ---
    "U2": (106.0, 24.0, 90.0),
    "C3": (124.0, 34.0, 0.0),
    "U3": (106.0, 50.0, 90.0),
    # Motor supply group sits together along the bottom edge: input terminal,
    # bulk reservoir, and the COM-rail decoupling cap.
    "C5": (96.0, 92.0, 0.0),
    "C8": (107.0, 92.0, 0.0),
    "J18": (122.0, 92.0, 180.0),

    # --- Digital input expansion (DNP), bottom-left block ---
    "U4": (50.0, 90.0, 90.0),
    "C4": (69.0, 90.0, 0.0),
    "J19": (36.0, 103.0, 90.0),
}

# FSR headers along the top edge, their pulldowns directly below.
for _i in range(8):
    PCB_PLACEMENT["J%d" % (_i + 2)] = (28.0 + _i * 6.5, 7.0, 0.0)
    PCB_PLACEMENT["R%d" % (_i + 1)] = (28.0 + _i * 6.5, 22.0, 90.0)

# Motor headers along the right edge.
for _i in range(8):
    PCB_PLACEMENT["J%d" % (_i + 10)] = (139.0, 18.0 + _i * 8.5, 0.0)

# AUX pulldowns above the 74HC165 block.
for _i in range(8):
    PCB_PLACEMENT["R%d" % (_i + 9)] = (28.0 + _i * 6.5, 74.0, 90.0)


# Silkscreen annotation: (x, y, text, size_mm, rotation).  y is the vertical
# centre of the text.  Positions sit in the gaps between component rows so the
# board passes silkscreen-clearance DRC without hand-editing.
SILK_ZONE_LABELS = [
    (80.0, 5.0, "JALADARANGAM INSTRUMENT CONTROL BOARD  REV A", 1.4, 0.0),
    (28.0, 32.0, "ANALOG INPUT - FSR NOTE KEYS", 1.2, 0.0),
    (95.0, 14.0, "MOTOR DRIVER ZONE", 1.2, 0.0),
    (28.0, 82.0, "DIGITAL INPUT EXPANSION (DNP)", 1.2, 0.0),
    (85.0, 60.0, "ANALOG / MOTOR ISOLATION", 1.0, 90.0),
    (95.0, 101.0, "MOTOR_V+ IS A SEPARATE RAIL - COMMON GND ONLY", 1.0, 0.0),
    (95.0, 105.0, "3.3V LOGIC - DO NOT TIE MOTOR_V+ TO +3V3", 1.0, 0.0),
]


def silk_connector_labels():
    """(ref, caption, side, gap_mm) for every off-board connector.

    ``side`` says where the caption goes relative to the connector's copper:
    the motor headers get theirs on the inboard side so a caption never lands
    on the next header down the edge.  ``gap_mm`` is the clearance from that
    copper; J18 needs a wider one to clear its terminal-block body outline and
    leave room for the polarity marks beneath it.
    """
    out = [("J1", "RPi GPIO", "below", 1.8),
           ("J18", "MOTOR PWR", "above", 8.0),
           ("J19", "GND AUX D0-D7 GND", "above", 1.8)]
    out += [("J%d" % (i + 2), "FSR%d" % i, "below", 1.8) for i in range(8)]
    out += [("J%d" % (i + 10), "M%d" % i, "left", 1.8) for i in range(8)]
    return out


# --------------------------------------------------------------------------
# Pad polarity marks: (ref, pad number, caption, side, net_it_asserts).
#
# Both the motor supply input and the eight motor outputs carry the separate
# MOTOR_V+ rail on one pin.  Getting either backwards drives that rail onto
# something it must never touch - the board's ground net at J18, or the
# ULN2803A's open-collector output at J10-J17 - so both pins of each are
# called out on silkscreen instead of relying on the pad-1 square alone.
#
# Each entry states the net it claims is on that pad.  sanity_check enforces
# it, so a mark can never drift out of step with the wiring it describes.
#
# J18's pins sit side by side, so its marks go above each pad.  The motor
# headers stack their pins 2.54 mm apart vertically, too close to caption from
# above, so those marks go in the clear board margin outboard of each pad.
# --------------------------------------------------------------------------
PAD_POLARITY_LABELS = [
    ("J18", "1", "+", "above", NET_MOTOR),
    ("J18", "2", "GND", "above", NET_GND),
]
# Motor headers: pin 1 is the motor's positive lead on MOTOR_V+, pin 2 its
# negative lead, sunk by the matching ULN2803A output.
for _i in range(8):
    PAD_POLARITY_LABELS.append(("J%d" % (_i + 10), "1", "+", "right", NET_MOTOR))
    PAD_POLARITY_LABELS.append(("J%d" % (_i + 10), "2", "-", "right", "MOTOR%d" % _i))

POLARITY_TEXT_SIZE = 1.2
POLARITY_OFFSET_ABOVE = 7.0     # mm above the pad centre
POLARITY_OFFSET_SIDE = 4.3      # mm outboard of the pad centre


if __name__ == "__main__":
    comps = build_components()
    nets = build_nets(comps)
    print("%d components, %d nets" % (len(comps), len(nets)))
    for net in sorted(nets):
        print("  %-10s %2d  %s" % (net, len(nets[net]),
                                   " ".join("%s.%s" % p for p in nets[net])))
    issues = sanity_check(comps, nets)
    print("\nsanity check: %s" % ("OK" if not issues else "\n  ".join([""] + issues)))
