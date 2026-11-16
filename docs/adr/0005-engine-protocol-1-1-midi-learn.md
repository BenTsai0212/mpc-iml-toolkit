# ADR 0005: Engine protocol 1.1, MIDI learn

- Status: Accepted
- Date: 2026-11-16
- Related: ADR 0004, #78, #81, #65, #61 (Epic)

## Context

The `pressure` preset (#65) sends 8 MIDI control changes (CC 20-27). While the model
runs, all 8 move together, so a DAW's MIDI learn catches whichever arrives first.
The workaround of training a throwaway model per output, 8 times, is too much for a
musician. A front end needs a way to send one chosen CC on its own.

The engine opens a preset's MIDI output when the preset loads and keeps it open in
every state, so the DAW should learn from that same port (`mpc-iml`, or the bus
chosen with `--midi-port`).

## Options

- **A core control message, protocol 1.1 (chosen).** It uses the port the engine
  already has open, works for any preset with a `MidiCcOutput`, needs only a plain
  `[send]` in Pd, and gets a reply or an `/mpciml/error`. Under ADR 0004's
  Versioning rules a new message and a new reply are a minor change.
- **A preset control** `/mpciml/preset/pressure/learn`. Preset control handlers
  cannot reach the engine's MIDI sender and cannot reply (ADR 0004, clarification
  6), so the plugin interface would have to change, and every MIDI preset would
  repeat the same control.
- **A separate command-line tool.** No protocol change, but while the engine runs it
  opens a second virtual port named `mpc-iml`, so the DAW shows two sources with the
  same name and can map the one that goes away. Pd vanilla cannot run shell
  commands, so the patch could not have buttons for it.

## Decision

The protocol version becomes **1.1** (`PROTOCOL_VERSION = (1, 1)`). Everything in
ADR 0004 stays as it is; this ADR adds one message and one reply. The plugin
interface does not change.

| Address | Arguments | Effect |
| --- | --- | --- |
| `/mpciml/midi/learn` | `i` output | Sends a short sweep on that output's MIDI controller only |

| Reply | Arguments | When |
| --- | --- | --- |
| `/mpciml/midi/sent` | `i` output, `i` controller | After `midi/learn` sent the sweep |

- `output` is 1-based: 1 is the first controller of the preset's `MidiCcOutput`
  (for `pressure`, output 3 is CC 22, as `t3` and `o3` in the patch). A float with
  a whole-number value is accepted, as for every int argument (ADR 0004,
  clarification 7).
- Each message sends 5 control changes on that controller only: 0, 32, 64, 96, 127,
  right away, without sleeping, so the control thread never blocks. When the last
  value sent on that controller was 127, it sends them downwards instead, so
  repeated messages move the value back and forth. The sweep is recorded as the
  controller's last value, so a later `run` still sends only changed values.
- If a preset declares several `MidiCcOutput`s, the sweep goes to each open one that
  has that output; the reply names the controller of the first.
- States: accepted in `idle` and `training`; `wrong_state` in `recording` and
  `running` (while running, all controllers are moving anyway).
- Errors are `bad_arguments`: a wrong count or type, an output outside 1 to the
  number of controllers, a preset without MIDI output (for example `demo`), or a
  MIDI output that could not be opened (the message is `MIDI output not open`).
  No new error code.

The state table of ADR 0004 gains one row:

| Message | `idle` | `recording` | `training` | `running` |
| --- | --- | --- | --- | --- |
| `midi/learn` | ✓ | ✗ | ✓ | ✗ |

## Consequences

- A musician maps all 8 CCs of `pressure` with 8 buttons in `patches/pressure.pd`
  (`l1`-`l8`), one at a time, without training anything.
- Front ends written for 1.0 keep working: the major version is unchanged.
- Tests use a fake MIDI backend to check that only the chosen CC is sent; mapping in
  a real DAW was the manual check in #78. It was confirmed on hardware with a DAW
  (#78): with the engine `idle`, each button `l1`-`l8` let Ableton Live's MIDI Map
  Mode learn exactly one CC, and `run` then moved all 8 parameters as trained.
- A separate command-line tool can still be added later for setups without a front
  end, if needed.
