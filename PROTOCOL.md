# jaladarangam.py network control protocol

This is the contract for any client (Android app, browser dev console, test
script) controlling `jaladarangam.py` remotely. It is transport-specific to
WebSocket today; a future Bluetooth (SPP or BLE GATT) transport is planned to
carry the exact same JSON messages over different bytes-in/bytes-out plumbing
(see `run_network_server`'s docstring in `jaladarangam.py`) - nothing in this
document should need to change for that.

## Transport (today: WebSocket)

- URL: `ws://<pi-ip>:8765`
- The Pi's LAN IP is **not fixed** in this document on purpose - run
  `hostname -I` on the Pi to get its current address, or check the
  `[network] WebSocket server listening on ...` line the instrument prints
  at startup. Port `8765` is fixed.
- No authentication, no TLS. This is a local-network-only control channel -
  do not expose port 8765 outside your LAN (e.g. via router port-forwarding).
- Every message, both directions, is a single JSON object per WebSocket
  text frame (not newline-delimited, not batched).

## Client -> server: commands

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
arrived over this WebSocket connection, a different WebSocket connection,
or the Pi's local stdin console - the server pushes the full current state
to **every connected client**:

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

## Design notes for the Bluetooth transport (future work, not yet built)

- `NETWORK_COMMANDS` in `jaladarangam.py` is the single dispatch table
  every transport should use - it maps each `cmd` string above to the
  underlying function (`toggle_drone`, `adjust_band`, etc.), fully
  independent of how the JSON arrived.
- A Bluetooth transport's job is only: accept a connection (SPP) or GATT
  write (BLE), decode the incoming bytes into the same `{"cmd": ...}` JSON
  shape used here, dispatch through `NETWORK_COMMANDS` the same way
  `_handle_ws_message` does, and call `get_full_state()`/`broadcast_state()`
  the same way for whatever client(s) it's serving.
- No protocol redesign should be needed - only new bytes-in/bytes-out code.
