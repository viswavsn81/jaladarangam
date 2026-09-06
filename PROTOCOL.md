# jaladarangam.py network control protocol

This is the contract for any client (Android app, browser dev console, test
script, Bluetooth SPP terminal app) controlling `jaladarangam.py` remotely.
The **same JSON command set and state-push shape** applies over both
transports below - only how the bytes get to/from the process differs.

## Transport 1: WiFi (WebSocket)

- URL: `ws://<pi-ip>:8765`
- The Pi's LAN IP is **not fixed** in this document on purpose - run
  `hostname -I` on the Pi to get its current address, or check the
  `[network] WebSocket server listening on ...` line the instrument prints
  at startup. Port `8765` is fixed.
- No authentication, no TLS. This is a local-network-only control channel -
  do not expose port 8765 outside your LAN (e.g. via router port-forwarding).
- Every message, both directions, is a single JSON object per WebSocket
  text frame (not newline-delimited, not batched).

## Transport 2: Bluetooth (Classic SPP / RFCOMM)

- Device name shown while scanning/pairing: **`Jaladarangam`** (this Pi's
  Bluetooth alias - not its hostname).
- Service: standard Serial Port Profile, UUID `00001101-0000-1000-8000-00805f9b34fb`,
  RFCOMM channel 1. Any generic Bluetooth SPP terminal app (Android or
  otherwise) that connects "by UUID" (the normal way - `BluetoothDevice.
  createRfcommSocketToServiceRecord(SPP_UUID)` on Android) finds this
  automatically; you should not need to hardcode channel 1, though it's
  fixed if a client needs it.
- **Pairing is "Just Works" - no PIN or passkey needed on either side.**
  The Pi registers a `NoInputNoOutput` pairing agent, which is what
  triggers Secure Simple Pairing's Just Works mode. From a phone: scan for
  Bluetooth devices, tap "Jaladarangam", confirm the pairing prompt (there
  is nothing to type or compare) - that's the whole flow.
- The Pi is **always discoverable and pairable** while `jaladarangam.py` is
  running (no discoverability timeout is set) - this is a local demo
  device, not a device meant to hide from casual scanning.
- **Framing is newline-delimited JSON**, one JSON object per line (`\n`-
  terminated) - unlike a WebSocket, a raw RFCOMM socket has no built-in
  per-message framing, so this project uses the same line-per-message
  convention already used for the Arduino Nano's serial link. Any SPP
  terminal app that sends/displays plain text with normal line endings
  works fine; do not send multiple JSON objects on one line, and do not
  split one JSON object across multiple lines.
- No authentication beyond standard Bluetooth pairing/bonding. Once
  paired, a bonded device can reconnect without re-pairing (normal
  Bluetooth behavior) - unpair from your phone's Bluetooth settings to
  revoke that.

## Client -> server: commands (both transports)

Every command is `{"cmd": "<name>", ...fields}`. Unknown `cmd` values or
malformed JSON get back a `type: "error"` reply (see below) - they never
crash the connection.

| cmd | fields | effect |
|---|---|---|
| `toggle_drone` | none | Turns the double bass drone on (starting at octave C#1) if off, or cycles it to the next octave if already on - mirrors stdin `b`. |
| `stop_drone` | none | Turns the drone off - mirrors stdin `c`. |
| `toggle_dual_output` | none | Toggles the headphone-jack output on/off alongside the main I2S output - mirrors stdin `s`. |
| `cycle_instrument` | none | Advances to the next instrument (mandolin -> guitar -> flute -> mandolin) - mirrors stdin `i`. |
| `set_instrument` | `value`: one of `"mandolin"`, `"guitar"`, `"flute"` | Directly selects an instrument (no stdin equivalent - stdin only cycles). Invalid `value` returns an error and changes nothing. |
| `toggle_odukkal` | none | Toggles odukkal (pressure-to-pitch-bend) on/off - mirrors stdin `o`. |
| `set_eq` | `band`: one of `"bass"`, `"mid"`, `"treble"`; `delta`: whole number (int, or a float with no fractional part e.g. `2.0`) | Adjusts the named EQ band by `delta` steps of 2dB each (matches the granularity of stdin's `b+`/`b-`/`m+`/`m-`/`t+`/`t-` - `delta` is a STEP COUNT, not raw dB). `delta: 1` == one `b+`; `delta: -3` == three `b-` in one call. If the resulting gain would clip the output, the command is rejected (logged on the Pi as `[EQ] CEILING REACHED`) and no state changes - you will not see a state push confirming a change that didn't happen. |
| `set_volume` | `value`: number, `0.0`-`1.0` | Sets master volume directly. Out-of-range values are clamped, not rejected. |
| `adjust_volume` | `delta`: whole number (int, or integer-valued float) | Adjusts master volume by `delta` steps of 0.1 each (matches stdin `v+`/`v-`). |
| `get_state` | none | Requests an immediate state reply (see below) with no side effects - useful right after reconnecting if you don't want to wait, though you also get state automatically on connect (see below). |

Fields not listed for a command are ignored, not rejected.

### Not in this protocol: tanpura

There is no `toggle_tanpura` (or similar) command. `jaladarangam.py` never
implemented a tanpura drone at all (a suitable license-clean, downloadable
sample could not be sourced - see the module docstring) - there is no
feature behind such a command to expose. Do not build UI for it.

## Server -> client: state pushes

After **every command that actually changes something** - whether it
arrived over WiFi, Bluetooth, or the Pi's local stdin console - the server
pushes the full current state to **every connected client on both
transports**. A change made from a Bluetooth-connected phone is seen
immediately by a WebSocket-connected client too, and vice versa:

```json
{
  "type": "state",
  "state": {
    "instrument": "flute",
    "sa_note": "C4",
    "octave_shift": 0,
    "drone": {"on": true, "octave": 1},
    "eq": {"bass": 16.0, "mid": 0.0, "treble": 0.0},
    "odukkal": true,
    "dual_output": false,
    "volume": 0.7
  }
}
```

(Over Bluetooth SPP, this same JSON is followed by a `\n` - see the framing
note above. Over WebSocket, it's the entire content of one text frame.)

Field meanings:

- `instrument`: `"mandolin"` | `"guitar"` | `"flute"` - the currently active sample source.
- `sa_note`: the current tonic (Sa) note name, e.g. `"C4"` - changes automatically when `instrument` changes (unless `--sa` was passed on the command line at startup, in which case it's fixed).
- `octave_shift`: integer, `-2` to `+2` - set by the physical octave+/octave- hardware keys (Arduino Nano A1/A2), **not controllable over this protocol** - included here for display only.
- `drone.on`: boolean. `drone.octave`: `1`, `2`, or `null` when off.
- `eq.bass` / `eq.mid` / `eq.treble`: current gain in dB for each band (can be negative).
- `odukkal`: boolean - whether pressure-to-pitch-bend is currently enabled.
- `dual_output`: boolean - whether the headphone jack is active alongside I2S.
- `volume`: float, `0.0`-`1.0`.

**You always get a state push immediately on connecting**, before sending
anything - so a client that just opened the connection (or reconnected
after a drop) sees accurate current state without needing to send
`get_state` first. `get_state` exists for polling mid-session if you want
it, not as a required handshake step.

A command that does **not** change anything (an unknown `cmd`, a rejected
`set_eq` that would clip, an invalid `set_instrument` value) produces **no
state push** - only the direct error reply below, sent to the client that
issued it.

## Server -> client: errors

Sent only to the client whose command caused the error - never broadcast:

```json
{"type": "error", "message": "invalid instrument 'trumpet', must be one of ('mandolin', 'guitar', 'flute')"}
```

Common causes: malformed JSON, missing `cmd` field, unknown `cmd`, an
invalid `band`/`instrument` value, a non-numeric or fractional `delta`/
`value`, or an EQ change that would clip the output.

## Running persistently (systemd)

`jaladarangam.py` (both transports, plus stdin) runs as a `systemd --user`
service on the Pi (`~/.config/systemd/user/jaladarangam.service`, also
checked into this repo at `systemd/jaladarangam.service`), with lingering
enabled (`loginctl enable-linger pyru1`) so it starts at boot without
needing an interactive login and restarts automatically on failure. Common
commands (run on the Pi, as the `pyru1` user - no `sudo` needed for these):

```
systemctl --user status jaladarangam.service    # is it running?
systemctl --user restart jaladarangam.service   # e.g. after editing the .py
journalctl --user-unit=jaladarangam.service -f  # live logs (PLUCK/JARU/etc.)
```

### Bluetooth troubleshooting: rfkill

The very first time Bluetooth was used on this Pi, the adapter was
rfkill **soft-blocked** (`Powered` couldn't even be set to true until
unblocked - `cat /sys/class/rfkill/rfkill*/soft`, `1` means blocked).
`systemd-rfkill` persists the unblocked state across reboots automatically
once fixed, so this shouldn't recur - but if Bluetooth ever silently stops
working again and `bluetoothctl show` reports `Powered: no`, check rfkill
state first before assuming a code problem:

```
cat /sys/class/rfkill/rfkill*/soft   # 0 = unblocked, 1 = blocked
echo 0 | sudo tee /sys/class/rfkill/rfkillN/soft   # unblock the bluetooth one
```

## Implementation notes (why these libraries)

- **WiFi**: `websockets` (installed via `sudo apt install python3-websockets`
  - not pip, since this system's Python is externally-managed per PEP 668).
- **Bluetooth**: `dbus-python` + PyGObject's `GLib` (both already present on
  Raspberry Pi OS), talking directly to BlueZ's own D-Bus API
  (`org.bluez.ProfileManager1`, `org.bluez.AgentManager1`) - **not**
  PyBluez. PyBluez is packaged for Debian (`python3-bluez`) but that
  package is literally PyBluez's last-ever upstream release (0.23,
  ~2018) with no real maintenance since. The older `sdptool`/`hciconfig`
  approach some PyBluez-era tutorials use doesn't work on this system's
  BlueZ at all (`bluetoothd` runs without the legacy `--compat` flag it
  requires). The RFCOMM socket I/O itself uses only Python's built-in
  `socket` module (`AF_BLUETOOTH`/`BTPROTO_RFCOMM`), which needs no
  extra package at all.
- `NETWORK_COMMANDS` and `_dispatch_command` in `jaladarangam.py` are the
  single dispatch layer both transports use - a command's *behavior* is
  defined exactly once, regardless of which transport (or stdin) it
  arrived through.
- **A real gotcha worth knowing if this ever needs touching again**: the
  file descriptor BlueZ hands over via `Profile1.NewConnection`'s D-Bus
  call is in **non-blocking mode** - that flag lives on the underlying
  kernel file description (inherited from how `bluetoothd` itself uses
  the socket), not something `socket.socket(fileno=...)` resets just by
  wrapping it. Without an explicit `sock.setblocking(True)` right after
  wrapping it, the first `sendall()` raises `BlockingIOError(EAGAIN)`
  immediately - which looked, from a phone's SPP terminal app, exactly
  like "pairs fine, connects, then silently disconnects within the same
  second, every single time," with `bluetoothd`'s own logs showing
  nothing wrong. Confirmed live via verbose fd/errno logging during
  development before landing on this fix.
