# ADR 0006: Engine protocol 1.2, preset layout, and the shared front-end spec

- Status: Accepted
- Date: 2026-11-16
- Related: ADR 0004, ADR 0005, RFC 0002, #66, #86, #61 (Epic)
- Accepted: 2026-11-17, implemented in protocol 1.2 and mpc-iml.pd; Phase 2.5 gate passed in #66 (#122)

## Context

Two front ends are planned against the same engine: the reference Pure Data patch
(#66) and a Max for Live device (#86). Both should work with any preset and feel the
same to a musician.

Protocol 1.1 does not tell a front end the shape of the active preset.
`/mpciml/counts` shows the class labels, and regression uses the label `""`, but
nothing reports how many target values the preset expects or whether it has MIDI
output. A front end would have to guess (always 8 sliders and 8 learn buttons), and a
preset with 4 targets would get `bad_arguments` on every `targets`, or would need a
table of built-in presets in each front end.

## Options

### Telling a front end the preset's shape

- **A new reply `/mpciml/layout`, protocol 1.2 (chosen).** One reply, sent with the
  preset, that both front ends read. Under ADR 0004's Versioning rules a new reply
  is a minor change, so front ends written for 1.0 or 1.1 keep working.
- **No engine change**: fixed 8 sliders and 8 learn buttons, and wrong counts shown
  as errors. Simple, but every preset that is not shaped like `pressure` looks broken.
- **A table of built-in presets in each front end.** Duplicated in Pd and Max, and
  presets from other packages get a manual mode.

### Where the address lives

- **`/mpciml/layout` (chosen)**, outside `/mpciml/preset/…`, so no preset name is
  reserved (ADR 0004, Preset messages).
- `/mpciml/preset/layout`: would reserve the preset name `layout`.

### Where the shared front-end spec lives

- **In this ADR, next to the reply it depends on (chosen).** One place for #66 and
  #86 to follow.
- A separate `docs/front-ends.md`: easier to change, but the spec and the protocol
  change would be reviewed apart.

## Decision

### Protocol 1.2

The protocol version becomes **1.2** (`PROTOCOL_VERSION = (1, 2)`). ADR 0004 and
ADR 0005 stay as they are; this ADR adds one reply. No message, state rule, error
code or plugin interface changes.

| Reply | Arguments | When |
| --- | --- | --- |
| `/mpciml/layout` | `i` targets, `i` controllers | After `preset/load` and in the full state, right after `/mpciml/preset` |

- `targets` is the preset's declared number of target values (`Preset.targets`),
  or 0 when the preset declares none: classification presets such as `demo`, and
  presets that leave the task to the examples. A front end shows the regression
  controls only when `targets` is at least 1, so a regression preset should declare
  `targets`.
- `controllers` is the number of MIDI controllers of the preset's first
  `MidiCcOutput`, or 0 without MIDI output. It is what the preset declares, also when
  the MIDI port could not be opened; `midi/learn` then answers `bad_arguments`
  (`MIDI output not open`, ADR 0005).
- The full state becomes `state`, `preset`, `layout`, `counts` and `trained`, in
  that order. `preset/load` sends `preset`, `layout`, `counts` and then `trained` if
  it changed.
- `pressure` reports `8 8`; `demo` reports `0 0`.

### Shared front-end spec

The Pure Data patch (#66) and the Max for Live device (#86) follow this spec, so a
musician finds the same controls in the same place. A front end may lay the groups
out in rows or columns, but keeps their order and the order inside each group.

**Names.** Button and field names are written as below. Where a label cannot
contain a space (Pure Data), the space becomes `_` (`stop_recording`).

| # | Group | Controls, in order |
| --- | --- | --- |
| 1 | Connect | `connect`, `ping`, preset chooser, engine version, active preset, `state` |
| 2 | Teach | Classification: `class` name field, class buttons `c1`-`c8`. Regression: target sliders `t1`-`t8` |
| 3 | Examples | `record`, `stop recording`, counts, `delete`, `clear` |
| 4 | Model | `train`, `run`, `stop`, `trained` indicator, training time |
| 5 | Library | `name` field, `save`, `load`, `list`, saved names |
| 6 | Outputs | Regression: outputs `o1`-`o8`. Classification: the predicted class. Learn buttons `l1`-`l8`, under `o1`-`o8` |
| 7 | Messages | One status line |

**Behaviour.**

1. **Connect.** `connect` sends `/mpciml/hello 1 6451`, then `/mpciml/preset/list`
   and `/mpciml/examples/list`; the front end also does this once when it opens.
   `ping` sends `/mpciml/ping` and shows that the engine answered (`pong`). The preset
   chooser lists `/mpciml/presets`; choosing one sends `/mpciml/preset/load <name>`.
   The version, preset and state come from `/mpciml/version`, `/mpciml/preset` and
   `/mpciml/state`.
2. **Teach.** With `targets` 0, the class buttons are labelled with the labels of
   `/mpciml/counts` in order (the first 8); a preset's fixed classes appear as soon as
   it loads. Clicking a class button, or entering a label in `class`, sends
   `/mpciml/class <label>` and marks that class as current. With `targets` from 1 to
   8, `t1` to `t<targets>` are active (0-1) and the other sliders are shown
   inactive. With more than 8 targets, the status line says the front end supports up
   to 8.
3. **Examples.** `record` sends the current class (`/mpciml/class`) or exactly
   `targets` values (`/mpciml/targets`), then `/mpciml/record/start`.
   `stop recording` sends `/mpciml/record/stop`. Counts show each label and its
   count from `/mpciml/counts` (regression: the number of examples). `delete` sends
   `/mpciml/examples/delete` with the current class; `clear` sends
   `/mpciml/examples/clear`.
4. **Model.** `train`, `run` and `stop` send `/mpciml/train`, `/mpciml/run` and
   `/mpciml/stop`. The indicator follows `/mpciml/trained`; the training time is the
   seconds of `/mpciml/train/done`.
5. **Library.** `name` defaults to `<preset>-examples` when a preset loads. `save` and
   `load` send `/mpciml/examples/save <name>` and `/mpciml/examples/load <name>`;
   `list` sends `/mpciml/examples/list`, and the saved names show
   `/mpciml/examples/names`.
6. **Outputs.** Regression shows the values of `/wek/outputs` (port 12000) on
   `o1`-`o<targets>`. Classification shows the predicted class number of
   `/wek/outputs` and, when the number is a position in the counts list, its label.
   Learn button `lN` sends `/mpciml/midi/learn N` and is active only for `N` up to
   `controllers`. `/mpciml/midi/sent N M` is shown as `output N on CC M`.
7. **Messages.** The status line shows the latest of: `/mpciml/error` as
   `<code> <address>: <message>` (this includes `version_mismatch`),
   `/mpciml/train/failed` as `train failed: <reason>`, and the front end's own
   errors. Errors are shown in the front end, not only in the Pd or Max window.
   `connect` clears the line.

**Rules for every front end.**

- Only core messages of ADR 0004, ADR 0005 and this ADR; no preset subtree messages
  are needed for these controls.
- Replies a front end does not know are ignored, so later minor versions do not break
  it.
- The front ends listen on ports 6451 and 12000, so only one of them runs at a time.
- A change to the groups, names or order is made in a new ADR that both front ends
  then follow.

## Consequences

- Both front ends adapt to any preset from the engine, without a preset table: class
  buttons for `demo`, 8 sliders and 8 learn buttons for `pressure`, the right number
  for presets from other packages that declare `targets`.
- Front ends written for 1.0 or 1.1 keep working:
  the major version is unchanged, and they ignore or print the new reply.
- A preset that leaves its task to the examples (`targets` not declared) is shown
  with the classification controls even when its examples are regression.
- The front ends are limited to 8 classes, 8 targets and 8 learn buttons; a preset
  with more gets an error on the status line.
- Follow-up work: the general Pure Data patch `patches/mpc-iml.pd` (#66, PR 2), the
  launch command `uv run mpc-iml` with an option to start only the engine (#66, PR
  3), and the Max for Live device (#86).
