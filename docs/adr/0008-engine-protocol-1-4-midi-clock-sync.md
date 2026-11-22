# ADR 0008: Engine protocol 1.4, MIDI clock sync

- Status: Accepted
- Date: 2026-11-19
- Related: RFC 0004, RFC 0005 (proposed in #131), ADR 0002, ADR 0004, ADR 0006,
  ADR 0007, #130, #113 (Epic)
- Amended: 2026-11-20, #138 (`Preset.clock` without sync, `on_pad`, `send_now`,
  scheduler cleared on a preset switch; see "Amendment for #138")
- Amended: 2026-11-20, #144 (`on_bar` and `BarStart`; see "Amendment for #144")
- Accepted: 2026-11-22, implemented in #130 and played on `main` (#211)

## Context

Two trials on 2026-11-19 (Notochord, Continuator) scored low because neither system
has a beat grid: responses came after a fixed idle time and ignored bar position.
Phrase-level interaction (play N bars, the AI answers at the next bar boundary)
needs the engine to know the DAW's tempo, beat and bar position, and to send notes
at a bar boundary. The core experience must not need Max for Live, so sync must work
with any DAW that sends MIDI clock, including Live Lite, Intro and Standard.

Today the engine cannot do this:

- The MPC input ignores MIDI timing messages (`ignore_types(timing=True)`). The MPC
  Sample sends no clock anyway: Play and Stop send CC 7 and CC 64 (ADR 0002).
- `mpc_iml.midi.decode` already turns system messages (`0xF8`, `0xFA`, `0xFB`,
  `0xFC`, `0xF2`) into raw events, and recordings already store them as
  `{"type": "midi", "bytes": [...]}` (ADR 0002); `frames` ignores them.
- The `mpc-iml` output (`MidiCcSender`) sends control changes only.
- A preset has no access to engine time.

RFC 0004 does not allow core changes in Phase 2.7. The `## Decision` on #130
(2026-11-19) grants this exception, and RFC 0005 ("Core changes") allows the clock,
note output and protocol 1.4. This ADR records the design accepted in the plan on
#130 and defines protocol 1.4. It adds no code; the implementation follows in three
PRs under #130.

## Options

### 1. Clock source

- **MIDI clock only (chosen).** 24 ticks per quarter note, plus Start, Stop,
  Continue and Song Position Pointer. No new dependency: `python-rtmidi` (MIT) is
  already used. Every Live edition, Logic, Bitwig and Reaper can send it. Each tick
  has about 1-2 ms of jitter, well under a 16th (125 ms at 120 BPM); position comes
  from counting ticks, so it never drifts.
- Ableton Link: exact tempo and shared bar phase with no per-message jitter, but the
  Link SDK is GPLv2 (or a commercial licence) and Python bindings that link it
  inherit those terms, so it could only be an optional extra that is never bundled.
  Deferred to its own Issue, if the manual check shows MIDI clock is not good
  enough; a new dependency needs the decision maker's approval (AGENTS.md
  section 6).
- Both: two code paths for the same information.

### 2. How sync is enabled

- **Command-line options, off by default (chosen).** Without `--clock` the engine
  opens no new port and behaves exactly as protocol 1.3.
- On by default with the virtual input always open: an extra port in every DAW's
  list even for musicians who never use sync.
- An OSC message that opens the port: anything that can reach the control port
  could open MIDI ports. It can be added later as a minor change.

### 3. How presets read the clock

- **An optional, provisional `Preset.clock` field (chosen)**, called with a
  read-only accessor when the preset loads.
- Clock values in the frame: changes the 49-value frame of ADR 0002.
- A module-level global: not testable per engine.
- No access until a generator needs it: RFC 0005's bass generator already does.

### 4. Recording format

- **No change (chosen).** Clock messages are already valid raw `midi` events in
  format versions 1 and 2. Grid tags are derived, like frames, so they are computed
  on read and never stored.
- An optional `grid` field on `midi` events (format version 3): redundant, and it
  could disagree with the ticks.
- A separate `clock` event type: also a format version bump.

### 5. How often the engine reports the clock

- **On every status change, and once per beat while running (chosen)**: about
  2 messages per second at 120 BPM, enough for a bar and beat counter.
- Once per tick: 48 messages per second, noise for front ends.
- Under a preset's subtree: sync is engine-wide, so it belongs in the core.

## Decision

### Clock input

- `--clock` enables sync. The engine opens a **virtual MIDI input `mpc-iml clock`**
  (DAWs see it as an output). `--clock-port <text>` reads clock instead from the
  first existing input port whose name contains the text (for example `IAC`).
- The clock input is read with an rtmidi callback on its own thread, so each tick is
  timestamped within about 1 ms, in the same time base as the gesture source. The
  MPC input is unchanged and keeps ignoring timing.
- Raw clock messages that arrive from the gesture source (for example a replayed
  recording) feed the same clock, so replays can carry clock.
- Other options: `--beats-per-bar N` (default 4) and `--clock-lead-ms` (default 0,
  see Scheduling). They are shared by `python -m mpc_iml.engine` and
  `uv run mpc-iml`.

### Position and tempo

New module `mpc_iml.clock` (standard library only):

- `MidiClock.feed(data, t)` handles `0xF8` (tick), `0xFA` (Start: position 0),
  `0xFB` (Continue), `0xFC` (Stop) and `0xF2` (Song Position Pointer: 16ths × 6
  ticks), and ignores every other message.
- `ClockState`, an immutable snapshot: `status`, `bpm` (`None` until 24 ticks have
  arrived; smoothed over one beat), `tick` (since song start), `bar`, `beat`, `step`
  (0-based), `t_tick` (time of the last tick) and `beats_per_bar`.
- `status` is one of:

| Status | Meaning |
| --- | --- |
| `off` | Sync is not enabled |
| `waiting` | Enabled, no tick yet |
| `running` | Ticks arriving after Start or Continue |
| `stopped` | Stop received; the position is kept for Continue |
| `lost` | No tick for 0.5 s while `running`; back to `running` when ticks return |

- Time signature: **4/4 assumed**. MIDI clock carries no meter; `--beats-per-bar`
  sets the bar length in quarter notes. Other denominators are out of scope.
- Bars and beats are 0-based in the Python API and 1-based in protocol replies and
  front ends.

### Grid tagging

- While the clock is `running`, every `note_on` with velocity above 0 from the MPC
  is tagged as `GridHit(t, pad, bank, velocity, bar, step, offset)`:
  - `position_ticks = k + (t - t_k) / tick_interval`, where `k` is the last tick at
    or before `t` and `tick_interval` comes from the smoothed tempo.
  - `step = round(position_ticks / ticks_per_step)`; `bar = step // steps_per_bar`.
  - `offset = position_ticks / ticks_per_step - step`, in steps (-0.5 to 0.5), also
    available in ms.
- Resolution: **16ths by default** (6 ticks per step, 16 steps per bar in 4/4). A
  preset can choose 8ths (12 ticks) or 16th triplets (4 ticks).
- Pressure is continuous and not tagged per message; `position(t)` gives the grid
  position of any time.

### Scheduling

- `Scheduler` in `mpc_iml.clock`: `at(bar, step, messages)`,
  `at_next_bar(messages, n=1, step=0)` (the next boundary where `bar % n == 0`) and
  `note(bar, step, note, velocity, length_steps, channel)` (Note On and its Note
  Off). Each returns a handle for `cancel()`. Messages are raw MIDI bytes.
- Dispatch happens in the clock callback: every message due on a tick is sent when
  that tick arrives, with no timer thread. With `--clock-lead-ms`, messages go out
  that many ms early, estimated from the tempo.
- Output: the existing `mpc-iml` port, through a new
  `MidiCcSender.send_message(bytes)`. When the active preset has no
  `MidiCcOutput`, the scheduler opens the port itself.
- On Stop and `lost`, pending messages are dropped and Note Offs are sent for every
  note the scheduler started, so no note hangs.
- Expected latency from the boundary tick leaving the DAW to the note reaching a
  Live track: about 1-3 ms (CoreMIDI virtual port or IAC, plus the callback). What
  is heard then depends on the DAW's audio buffer, as for a note played live.
  Live's MIDI Clock Sync Delay or `--clock-lead-ms` correct any constant offset.

### Plugin interface

- New optional field `Preset.clock: Callable[[ClockAccess], None] | None = None`,
  **provisional** like `controls`. The engine calls it when the preset loads, with
  or without `--clock` (amended for #138). `ClockAccess` is read-only apart from
  the note output: `state()`, `position(t)`, `on_hit(callback)` (tagged pad hits),
  `on_pad(callback)` and `send_now(messages)` (#138), `on_bar(callback)` (#144),
  and `scheduler`.
- Presets without the field see no change.

### Protocol 1.4

The protocol version becomes **1.4** (`PROTOCOL_VERSION = (1, 4)`). ADR 0004 to
ADR 0007 stay as they are; this ADR adds one message and one reply, which is a minor
change.

| Message | Arguments | Effect |
| --- | --- | --- |
| `/mpciml/clock/test` | `i` 0 or 1 | 1 starts a test pattern from the next bar on the `mpc-iml` port: note 72 on beat 1, note 60 on the other beats, velocity 100, one 16th long. 0 stops it at once, with Note Offs. |

| Reply | Arguments | When |
| --- | --- | --- |
| `/mpciml/clock` | `s` status, `f` bpm (0 when unknown), `i` bar (1-based), `i` beat (1-based) | On every status change; once per beat while `running`; in the full state |

- `clock/test` is accepted in every state. Without `--clock` it is
  `bad_arguments` ("clock sync is off"). No new error codes.
- With sync off, `/mpciml/clock` is sent only in the full state, as `off 0 0 0`.
- **Full state**: `state`, `preset`, `layout`, `names`, `kit`, `pads`, `counts`,
  `trained`, `clock`, in that order.
- Pad input, frames, recording, training and running never wait for the clock, in
  any clock status.
- When `--clock` is on and no tick has arrived, the engine prints one log line that
  names the port and how to turn on Sync in Live. Losing the clock also prints one
  line.

### Front ends (ADR 0006)

- `patches/mpc-iml.pd` gains an optional clock display in the Messages area: status,
  BPM, bar and beat from `/mpciml/clock`, and a `test` toggle that sends
  `/mpciml/clock/test`. ADR 0006's groups and order do not change.
- The Max for Live device is unchanged in 1.4.

### Musician setup

- **Live** (any edition): Settings → Link, Tempo & MIDI → MIDI Ports: turn on
  **Sync** for the output `mpc-iml clock`, and set MIDI Clock Type to **Song** so
  Live sends Song Position Pointer.
- **Logic**: File → Project Settings → Synchronization → MIDI: Transmit MIDI Clock
  to `mpc-iml clock`, with Song Position Pointer.

## Consequences

- Sync works with any DAW that sends MIDI clock, with no new dependency and no
  licence change. Without `--clock`, everything stays exactly as in protocol 1.3,
  apart from the `clock off` reply at the end of the full state.
- Front ends written for 1.0 to 1.3 keep working: they ignore `/mpciml/clock` and
  never send `clock/test`.
- **The plugin interface grows** by the provisional `Preset.clock`; existing presets
  keep working.
- **The recording format does not change** (ADR 0002, ADR 0007). Recordings that
  contain clock bytes can be re-tagged on read.
- Accuracy is limited by MIDI clock jitter (about 1-2 ms per tick) and by the tempo
  estimate between ticks; the manual check on #130 decides whether it is enough.
  Ableton Link remains a possible optional GPL extra in its own Issue.
- Only 4/4-style meters (N quarter notes per bar) are supported.
- No free-running internal clock: without a DAW, presets get no grid. Generators
  that need one propose it in their own Issue.
- Follow-up work under #130: `mpc_iml.clock` with tests; engine wiring (clock input,
  CLI options, `/mpciml/clock`, `Preset.clock`, README setup); the scheduler,
  `send_message`, `clock/test` and the Pd clock display; the manual check with Live
  sending clock; AGENTS.md rows once implemented.

## Amendment for #138

The drum-led `ensemble` preset (RFC 0005, #138) plays a bass note at once on a kick
hit, and must load and play without `--clock`. The decision on #138 allows these
changes to the provisional plugin interface; the protocol stays 1.4.

- **C1: the hook without sync.** The engine calls `Preset.clock` also without
  `--clock`, with a `ClockAccess` whose `state()` is `off_state()`, whose
  `position(t)` is `None` and whose `scheduler` is `None`; `on_hit` never fires.
  New `ClockAccess.on_pad(callback, ticks_per_step=SIXTEENTHS)`: every pad
  `note_on` with velocity above 0, in any clock status, as
  `PadHit(t, pad, bank, velocity, grid)`, where `grid` is the `GridHit` while the
  clock is `running`, otherwise `None`. `on_hit` is unchanged.
- **C2: notes at once.** New `ClockAccess.send_now(messages)` sends raw MIDI
  messages at once on the note path (the preset's first MIDI output, or the
  `mpc-iml` port). With sync on they go through the new `Scheduler.send_now`, so
  the notes they start count as sounding and Stop, `lost`, a jump and `clear` end
  them. Without sync the preset ends its own notes. This avoids holding a hit back
  to the grid: a hit is tagged with the nearest step, so `Scheduler.at` would delay
  an early hit by up to half a step.
- **C3: preset switch.** `preset/load` to another preset calls
  `Scheduler.clear(keep_test=True)` before the old preset's outputs close: pending
  messages are dropped and sounding notes end, so no scheduled note survives a
  switch. A running test pattern (`clock/test`) carries on from the next bar.
- Content formats and the protocol do not change; presets that do not use the new
  methods see no change, apart from the hook being called without `--clock`.

## Amendment for #144

The melody layer of `ensemble` (RFC 0005, #144) decides each bar from the whole bar
before it, including a bar with no hits. `on_pad` cannot see an empty bar, and the
scheduler only sends MIDI bytes. The decision on #144 allows this change to the
provisional plugin interface; the protocol stays 1.4.

- **C4: bar lines.** New `ClockAccess.on_bar(callback, ticks_per_step=SIXTEENTHS)`.
  The callback receives `BarStart(bar, hits, complete, state)` once per bar, on the
  first tick of the bar, while the clock is `running`: `bar` is the bar that starts
  (from 0, so bar 0 right after Start, with no hits), `hits` are the `GridHit`s
  placed in bar `bar - 1` on the requested grid in time order, `complete` is `False`
  when the clock was not running through all of bar `bar - 1` (Start, Continue after
  a Song Position Pointer, `lost`), and `state` is the `ClockState` on that tick. It
  never fires while `waiting`, `stopped` or `lost`, or without `--clock`.
- The engine calls `ClockAccess.bar_line()` after each clock message, **before**
  `Scheduler.update`, so notes a callback schedules for step 0 of the new bar go out
  on the bar line. With `--clock-lead-ms` above 0, those notes go out on the tick
  itself, up to the lead later than notes scheduled earlier.
- A hit is placed on its nearest step, so the hits of a bar are all known half a
  step before its end; a hit that reaches the engine later than that is dropped from
  `hits`. A hit just before the bar line belongs to the new bar.
- Same thread and error rules as `on_hit`: the callback runs on the thread that fed
  the clock message and must return quickly; an exception is logged. A new preset
  gets a new `ClockAccess`, so callbacks of the previous preset stop.
- Content formats and the protocol do not change; presets that do not call `on_bar`
  see no change.
