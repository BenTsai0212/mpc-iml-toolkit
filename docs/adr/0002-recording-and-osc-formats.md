# ADR 0002: Recording format and OSC message format

- Status: Accepted
- Date: 2026-11-16
- Related: RFC 0001, ADR 0001, #10 (hardware check), #11

## Context

ADR 0001 fixes Python, MIDI input and OSC output but leaves two public interfaces
open: how example data is recorded, stored and replayed, and which OSC messages the
toolkit sends. Practice repositories and papers will depend on both.

The hardware check (#10, MPC Sample firmware v1.3.0) found:

- Gesture input over USB is the pads only: velocity 1–127 and polyphonic pressure
  1–127. The knobs, encoder and fader send nothing.
- Pressure is sent only when it changes, about every 10 ms per pad; pads scanned in
  the same cycle share timestamps. The first pressure message comes about 70 ms
  after `Note On`, and pressure does not return to 0 before `Note Off`.
- Banks A–H map each (bank, pad) to a unique note:
  note = (36 + 16 × bank + pad) mod 128, with bank and pad counted from 0.
- Play and Stop send CC 7 and CC 64 (sequencer state, not gestures).
- With the Full Level setting on, every outgoing velocity is 127.

## Options

### What to store

- **Events only (chosen).** Store every MIDI message with its time; compute frames
  for models from the events. Lossless, and replay goes through the same path as
  live input.
- **Frames only.** Store fixed-rate vectors. Loses the original messages and fixes
  the frame rate and features at recording time.
- **Both.** Two copies that can disagree.

### File format

- **JSON Lines (chosen).** One JSON object per line; readable, meaningful diffs for
  test fixtures, standard library only. Worst case about 10 MB per minute (all 16
  pads changing continuously); typical example recordings are far smaller.
- **CSV.** Readable, but metadata (format version, firmware, settings) does not fit
  well.
- **Binary (Parquet, NPZ).** Smallest, but needs extra dependencies and is not
  readable or diffable.

### OSC messages

- **Wekinator conventions (chosen).** Existing IML tools, teaching material and
  synthesiser patches connect without an adapter, and a practice repository can
  swap the built-in model for Wekinator without changing the receiving side.
- **A toolkit-specific namespace.** More descriptive addresses, but every receiver
  needs an adapter, and ADR 0001's later "Wekinator-compatible adapter" would still
  be needed.

## Decision

### Recording file

- A recording is a JSON Lines file. The first line is a header; every following
  line is one event, in time order.
- Header fields: `type: "header"`, `format: "mpc-iml-recording"`,
  `format_version` (starts at 1), `toolkit_version`, `device`, `firmware`, and
  `settings` (for example `full_level`, as declared by the person recording).
- Event time `t` is seconds since the start of the recording, measured when the Mac
  receives the message. Its effective resolution is the MPC's scan cycle (about
  10 ms).
- MIDI events store channel voice messages as decoded fields (`kind`, `channel`,
  `note` or `control`, `value`); any other message is stored as raw `bytes`.
  Values are stored as received: no velocity curve, no normalisation.
- Examples are marked in the same file by `example_start` events (with a `label`
  string for classification or a `targets` list of numbers for regression) and
  `example_end` events. One recording can hold several examples.
- Changing the format increments `format_version`; the toolkit documents each
  version and reads every earlier version it has released.

Example:

```jsonl
{"type": "header", "format": "mpc-iml-recording", "format_version": 1, "toolkit_version": "0.1.0", "device": "MPC Sample", "firmware": "1.3.0", "settings": {"full_level": false}}
{"t": 0.500, "type": "example_start", "label": "soft-roll"}
{"t": 0.512, "type": "midi", "kind": "note_on", "channel": 1, "note": 36, "value": 30}
{"t": 0.584, "type": "midi", "kind": "poly_pressure", "channel": 1, "note": 36, "value": 63}
{"t": 0.640, "type": "midi", "kind": "note_off", "channel": 1, "note": 36, "value": 0}
{"t": 2.500, "type": "example_end"}
{"t": 3.000, "type": "midi", "kind": "control_change", "channel": 1, "control": 7, "value": 90}
```

### Frames

- Frames are computed from events by one toolkit function, used both live and in
  replay. The default rate is 100 Hz, matching the hardware; practice repositories
  can change it.
- A frame describes the 16 physical pads, whatever the bank: for each pad, the
  latest pressure, the latest velocity, and whether it is held; plus the current
  bank (0–7). That is 49 values. Bank and pad come from the note by the formula
  above; files keep only the original note.
- Each pad holds its last pressure until the next pressure message; `Note Off` sets
  pressure to 0 and "held" to false.
- Messages that are not pad notes or pad pressure (for example CC 7 and CC 64) stay
  in the recording but are ignored by frames.
- The toolkit does not distinguish strikes from holds. The roughly 70 ms pressure
  onset is documented for feature design in practice repositories.
- When a recording has at least 8 notes and every velocity is 127, the toolkit
  warns that Full Level may have been on. It does not block the recording.

### OSC

- **Gesture features**: `/wek/inputs` to `127.0.0.1:6448`, 49 floats in a fixed
  order: 16 pressures, 16 velocities, 16 held flags, then the bank. Pressure and
  velocity are normalised to 0–1, held is 0 or 1, bank is 0–7. Sent once per frame,
  even when nothing changed.
- **Model outputs**: `/wek/outputs` to `127.0.0.1:12000`, N floats where N is set
  by the practice repository's model.
- Addresses, hosts and ports are configurable; the values above are defaults.
- Normalisation happens only in the OSC layer; recordings keep raw values.
- Because the toolkit follows Wekinator's defaults, ADR 0001's later
  "Wekinator-compatible adapter" is not needed.
- Not in Phase 1: Wekinator control messages (remote record or train) and separate
  per-strike event messages.

## Consequences

Benefits:

- Recordings are lossless; frame rate and features can change without re-recording.
- Replay and live input share one code path, so CI and coding agents can test the
  input layer with recorded fixtures.
- Swapping the built-in model for Wekinator changes nothing on the receiving side,
  which serves the third Phase 1 gate in RFC 0001.

Costs:

- Frames are recomputed on every read; heavy offline analysis may want a cache
  later.
- The 49-value frame is large for small-data IML; practice repositories may need to
  select features.
- Timestamps reflect host receive time, not the MPC's internal clock.

Follow-up work:

- Record replay fixtures (human, with the MPC) once the recorder exists; #10 kept
  no raw captures.
- Implement the recording reader and writer, the frame function, and the OSC
  sender in the input-interface, IML-loop and OSC-output Issues of Epic #7.
