# ADR 0007: Engine protocol 1.3, kits, modules and pad selection

- Status: Accepted
- Date: 2026-11-17
- Related: RFC 0003, ADR 0002, ADR 0004, ADR 0005, ADR 0006, #97, #96 (Epic), #86
- Accepted: 2026-11-17, implemented in #105, #108 and #111 (#121)

## Context

RFC 0003 (Accepted) changes the default experience from "demonstrate from nothing"
to "start from something that plays". It adds named outputs, modules that generate
examples for one pad, and starter kits (a resting sound plus a module on each pad),
with a pad editor where the musician selects a pad by hitting it on the MPC Sample.

These touch three public interfaces: the preset plugin interface (#63), the example
data (ADR 0002) and the engine protocol (ADR 0004 to ADR 0006). RFC 0003 leaves open
how a module's curve is described, how many examples it writes and how they weigh
against demonstrations, how combined presses are handled, and what the first kits
contain. This ADR answers those questions and defines protocol 1.3. It adds no code;
the implementation follows in later Issues.

## Options

### 1. How front ends learn the output names

- **A new reply `/mpciml/names` (chosen).** A new reply is a minor change, and front
  ends ignore replies they do not know.
- Trailing arguments on `/mpciml/layout`: one reply fewer, but it changes the
  argument count of an existing reply, which Pd `[unpack f f]` and Max patches that
  read `layout` may not tolerate.

### 2. How a module describes its curve

- **Points with linear interpolation per named output (chosen).** Any shape,
  including "up then down", with a generator of a few lines.
- Fixed shapes (`linear`, `ease-in`, `ease-out`) with a depth: smaller files, but
  every new shape needs code, and non-monotonic curves are impossible.

Amount: **a per-pad amount (chosen)**, set with the assignment rather than stored in
the module, so one module serves both subtle and strong pads.

### 3. Example generation

Takes per pad:

- **4 levels, pressure 0.25, 0.5, 0.75 and 1.0 (chosen).**
- 8 levels: smoother curves, twice the data.

Marking generated takes, so that changing one pad's module replaces only its takes
and a saved set restores the assignments:

- **Optional fields in `example_start` and the header, as recording
  `format_version` 2 (chosen).** One file stays the whole truth. Older toolkits
  refuse version 2 instead of misreading it.
- A side file `<name>.pads.json`: no format change, but two files that can get out
  of sync, and the `.jsonl` alone no longer says which examples are generated.

Weighting against recorded demonstrations:

- **By frame count, with no model change (chosen).** A module gives 80 frames per
  pad (about 0.8 s of demonstration), so a demonstration of 2-3 s on the same pad
  outweighs it, as RFC 0003 intends.
- Per-example sample weights: needs a weights argument on `Model.fit`, a plugin
  interface change for every backend. Deferred.
- Dropping a pad's generated takes once it has recorded takes: simple, but not
  "trained together" as RFC 0003 asks.

Combined presses:

- **Additive pairs for every two pads with a module other than `none` (chosen)**,
  with a kit option to turn them off.
- No combined takes: least data, but with pressure features a combined press is an
  unseen input and may jump.
- Kit-declared pairs only: more control, but kit authors must write them.

### 4. First kits

- **The ADR fixes each kit's purpose and pad assignment (chosen)**; exact resting
  values are set after a hardware playtest and recorded in the kit files.
- The ADR records purposes only and leaves the assignments to the implementation.

### 5. Extension by other packages

- **A new entry point group `mpc_iml.content` (chosen).** Another package can add
  kits and modules to `pressure` without redefining the preset.
- `Preset.kits` and `Preset.modules` fields only: simpler, but only the preset's own
  package can add content.

### 6. `pad/module` during a retrain

- **`wrong_state` in 1.3 (chosen)**, as `train` already does; revisited after the
  playtest.
- Queue one pending retrain: smoother when changing pads quickly, but adds a pending
  state.

### 7. Where the kit controls go in the front ends

- **A new group 2 Kit after Connect (chosen).**
- Inside Teach: keeps 7 groups, but Teach is already the busiest group.

### 8. Interaction log

- **A later ADR (chosen).** Nothing in the 1.3 messages depends on it.
- In this ADR: would fix a research data format before any study design.

## Decision

### Named outputs

- The plugin interface gains an optional field
  `Preset.output_names: tuple[str, ...] | None` (default `None`). Its length must
  equal `targets`. Names use lower case letters, digits and hyphens, and are unique.
- `pressure` declares, in CC order 20-27: `brightness`, `resonance`, `drive`,
  `space`, `motion`, `pitch`, `texture`, `level`.
- Modules and kits need `output_names`: a preset without them lists no modules or
  kits.

### Modules

- A module is a JSON file:

```json
{"format": "mpc-iml-module", "format_version": 1, "name": "bite", "title": "Bite",
 "preset": "pressure", "description": "Brightness and resonance rise with pressure.",
 "outputs": {"brightness": [[0, 0], [1, 0.5]], "resonance": [[0, 0], [1, 0.5]]}}
```

- `outputs` maps named outputs to points `[pressure, offset]`. Pressure is 0-1 and
  strictly increasing; offsets are -1 to 1. The first point is `[0, 0]`, so a
  released pad gives the resting sound. Between points the offset is interpolated
  linearly; after the last point it holds the last offset. Outputs not listed keep
  their resting value.
- At pressure `p`, output `o` is `clamp(rest[o] + amount × offset_o(p), 0, 1)`.
- `amount` is 0-1 (default 1), set per pad with the assignment.
- The module ids are `none`, `brighten`, `darken`, `bite`, `push`, `distance`,
  `wobble`, `bend`, `grain`, `swell` (the RFC 0003 names; the title is the
  capitalised id). `none` is built in and has no file: its takes are at the resting
  values, so the model learns that the pad changes nothing.
- First offsets at pressure 1, straight lines from `[0, 0]`; the implementation
  Issue tunes them on hardware:

| Module | Offsets at pressure 1 |
| --- | --- |
| `brighten` | brightness +0.6 |
| `darken` | brightness -0.6 |
| `bite` | brightness +0.5, resonance +0.5 |
| `push` | drive +0.5, level +0.3 |
| `distance` | space +0.6, brightness -0.2 |
| `wobble` | motion +0.7 |
| `bend` | pitch +0.4 |
| `grain` | texture +0.6, drive +0.2 |
| `swell` | level +0.4, space +0.5 |

### Kits

```json
{"format": "mpc-iml-kit", "format_version": 1, "name": "filter-play",
 "title": "Filter play", "preset": "pressure", "default": true,
 "description": "Play the filter: brighter, sharper or darker as you press.",
 "combine": "add",
 "rest": {"brightness": 0.3, "resonance": 0.2, "drive": 0.1, "space": 0.2,
          "motion": 0.0, "pitch": 0.5, "texture": 0.0, "level": 0.7},
 "pads": ["brighten", "brighten", {"module": "bite", "amount": 0.5}, "..."]}
```

- `rest` names every output of the preset, each 0-1. `pads` has exactly 16 entries
  in pad order 1-16 (pads 1-4 are the bottom row); each is a module id or
  `{"module": id, "amount": a}`. `combine` is `"add"` (default) or `"none"`.
  `default: true` marks the kit listed first; at most one kit per preset has it.
- The first kits (the resting values above are placeholders; the implementation
  Issue sets them after a hardware playtest):

| Kit | Purpose and rest | Pads 1-4 | 5-8 | 9-12 | 13-16 |
| --- | --- | --- | --- | --- | --- |
| `filter-play` (default) | Brightness and resonance; rest dark and clean | `brighten` | `bite` | `darken` | `wobble`, `wobble`, `bend`, `none` |
| `texture-lab` | Drive, texture, motion; rest with some drive | `grain` | `push` | `wobble` | `bite`, `bite`, `darken`, `none` |
| `ambient-space` | Space, swell, distance; rest quiet and wide | `swell` | `distance` | `darken` | `wobble`, `wobble`, `bend`, `none` |

### Example generation

- **Single-pad takes.** For each pad, 4 takes at pressure 0.25, 0.5, 0.75 and 1.0,
  each 0.2 s (20 frames at 100 Hz): `example_start` with the computed `targets`,
  then at the same `t` a `note_on` (velocity 100, bank A, note 35 + pad) and a
  `poly_pressure` (value `round(127 × p)`), then `note_off` and `example_end` 0.2 s
  later. The engine already turns frames into events this way for `examples/save`
  (#73). A pad gives 80 frames.
- **Rest take.** One take per kit with no pad pressed and the resting values as
  targets.
- **Combined takes.** With `combine: "add"`, for every pair of pads that both have a
  module other than `none`: 2 takes of 10 frames, both pads at 0.5 and both at 1.0,
  with the targets `clamp(rest + offset_a + offset_b)` (each offset already scaled
  by its pad's amount). At most 120 pairs, so at most 2,400 frames. Kits cannot
  declare individual pairs in 1.3.
- A kit without combined takes gives about 1,300 frames (16 × 80 + 20).
- **Weighting** is by frame count; the model interface does not change.
- **Recorded demonstrations** are not marked and are never replaced by generated
  takes. A demonstration on a pad trains together with that pad's module.

### Recording format version 2

Generated takes are marked with optional fields, so ADR 0002's recording format
becomes `format_version` 2:

- `example_start` may carry `module`, `pad` and `amount`. A single-pad take has
  `module` (an id), `pad` (1-16) and `amount`. The rest take has `"module": "none"`,
  `"pad": 0` and `"amount": 0`. A combined take has two-element lists for all three.
  A take without `module` is a recorded demonstration.
- The header may carry `kit` (the kit name the set started from) and `combine`.
- The toolkit writes version 2 only for files that contain generated takes, and
  reads versions 1 and 2. Version 1 files are unchanged.
- Loading a version 2 file restores the pad assignments from the single-pad takes,
  the resting values from the rest take, and the kit name and `combine` from the
  header.

### Data location and extension

- In a package, kits live in `<root>/kits/<preset>/<name>.json` and modules in
  `<root>/modules/<preset>/<name>.json`, read with `importlib.resources`. The file
  name equals `name`. The built-in root is the `mpc_iml` package
  (`mpc_iml/kits/pressure/`, `mpc_iml/modules/pressure/`).
- A new entry point group **`mpc_iml.content`**. Each entry is a
  `Content(preset="pressure", root="<package>")` (or `"<package>:<dir>"` for a
  folder inside the package), or a zero-argument callable that returns one. The built-in entry is `pressure-content = "mpc_iml.pressure:CONTENT"`.
- Two files that define the same kit or module name for one preset are an error, as
  duplicate presets are. Content for a preset that is not installed is ignored. A
  kit that names a module no installed content defines is an error when listed.

### Protocol 1.3

The protocol version becomes **1.3** (`PROTOCOL_VERSION = (1, 3)`). ADR 0004,
ADR 0005 and ADR 0006 stay as they are; this ADR adds messages and replies only,
which is a minor change. Pads are numbered 1-16, as `midi/learn` outputs are 1-based.

| Message | Arguments | Effect |
| --- | --- | --- |
| `/mpciml/kit/list` | none | Replies `/mpciml/kits` for the active preset |
| `/mpciml/kit/load` | `s` name | Replaces the whole example set with the kit's generated takes, then trains |
| `/mpciml/module/list` | none | Replies `/mpciml/modules` |
| `/mpciml/pad/module` | `i` pad, `s` module, optional `f` amount (default 1) | Replaces that pad's generated takes and the combined takes that include it, keeps recorded takes, then trains |
| `/mpciml/pad/select/start` | none | Reports every pad hit until `pad/select/stop` |
| `/mpciml/pad/select/stop` | none | Stops reporting |

| Reply | Arguments | When |
| --- | --- | --- |
| `/mpciml/names` | `s`… output names, none when the preset has none | After `/mpciml/layout` on `preset/load`, and in the full state |
| `/mpciml/kits` | `s`… names, the default kit first, then by name | Reply to `kit/list` |
| `/mpciml/modules` | `s`… ids, `none` first, then by id | Reply to `module/list` |
| `/mpciml/kit` | `s` name, or `""` | After `kit/load`, `preset/load`, `examples/load`, `examples/clear`, and in the full state |
| `/mpciml/pads` | 16 × (`s` module, `f` amount); `""` and 1 for a pad without generated takes | After `kit/load`, `pad/module`, `examples/load`, `examples/clear`, `preset/load`, and in the full state |
| `/mpciml/pad/hit` | `i` pad 1-16 | On each `note_on` with velocity above 0 while selecting, any bank |

- A preset without `output_names` replies to `kit/list` and `module/list` with no
  names.
- **Full state**: `state`, `preset`, `layout`, `names`, `kit`, `pads`, `counts`,
  `trained`, in that order.
- **Automatic training**: after `kit/load` and `pad/module`, the engine trains as
  `/mpciml/train` would: from `idle` through `training` back to `idle`; in `running`
  it retrains and keeps running. `counts`, then `train/done` or `train/failed`
  follow.
- `pad/module` needs resting values: from `kit/load`, or from the rest take of a
  loaded version 2 set. Without them it is `bad_arguments` ("load a kit first").
- `examples/clear` also clears the assignments, the resting values and the kit.
  `examples/delete` does not apply to module presets (they are regression presets).
- **Selection** ends on `pad/select/stop`, `record/start` and `preset/load`. The
  engine only reports hits; the front end keeps the selected pad. While selecting,
  the engine reads MIDI input also in `idle` and `training`.

| Message | `idle` | `recording` | `training` | `running` |
| --- | --- | --- | --- | --- |
| `kit/list`, `module/list` | ✓ | ✓ | ✓ | ✓ |
| `kit/load`, `pad/module` | ✓ | ✗ | ✗ | ✓ (✗ while a retrain is in progress) |
| `pad/select/start`, `pad/select/stop` | ✓ | ✗ | ✓ | ✓ |

**Errors** (no new codes): `not_found` for an unknown kit or module;
`bad_arguments` for a pad outside 1-16, an amount outside 0-1, a kit for another
preset, a preset without `output_names` (including classification presets), or
`pad/module` without resting values.

### Front-end spec update (ADR 0006)

Both front ends follow this update. A new group **2 Kit** comes after Connect;
Teach to Messages become groups 3-8. ADR 0006's other names, order and rules stay.

| # | Group | Controls, in order |
| --- | --- | --- |
| 2 | Kit | kit chooser, `select pad` toggle, selected pad, module chooser, `amount` (0-1), module of the selected pad |

- **Kit chooser.** Lists `/mpciml/kits` (Pd: up to 8 buttons, as the preset
  chooser; Max: `umenu`). Choosing one sends `/mpciml/kit/load <name>` and shows
  `/mpciml/kit`. With no kits the group is shown inactive.
- **Pad selection.** The `select pad` toggle sends `pad/select/start` or
  `pad/select/stop`, and turns off when the front end sends `record/start`.
  `/mpciml/pad/hit N` sets the selected pad. A pad number box (1-16) also selects a
  pad without the MPC. The selected pad's module and amount come from
  `/mpciml/pads`.
- **Module chooser.** Lists `/mpciml/modules` (Pd: 10 buttons; Max: `umenu`).
  Choosing a module, or releasing `amount`, sends
  `/mpciml/pad/module <pad> <module> <amount>`.
- **Names.** Teach `t1`-`t8` and Outputs `o1`-`o8` are labelled with
  `/mpciml/names` when present, otherwise `tN` and `oN`. CC numbers do not change.
- **Recording on a kit.** `record` still sends the target sliders, so a kit plus a
  recording is a demonstration on top of the module.
- **Connect** also sends `/mpciml/kit/list` and `/mpciml/module/list`.

### Interaction log

Protocol 1.3 adds no logging. The log's format and content are decided in a later
ADR, before any study (RFC 0003: off by default, written only to the user's data
folder, never in the repository).

## Consequences

- A musician gets a playing instrument from one message (`kit/load`) and edits it
  pad by pad, with demonstrations still trained together with the modules.
- **ADR 0002 is extended**: the recording format gains `format_version` 2 (optional
  `module`, `pad`, `amount` in `example_start`; `kit` and `combine` in the header),
  defined in this ADR. ADR 0002's file is not edited. Toolkits before 1.3 refuse
  version 2 files instead of misreading them; version 1 files read as before.
- **The plugin interface grows**: `Preset.output_names` and the entry point group
  `mpc_iml.content`. Both are optional, so existing presets keep working.
- Front ends written for 1.0 to 1.2 keep working: they ignore the new replies and
  never send the new messages.
- Weighting by frame count means a long demonstration can fully override a module,
  and a short one only nudges it. If the playtest shows this is wrong, sample
  weights need a later ADR.
- A kit with 15 non-`none` pads and `combine: "add"` holds about 3,400 frames;
  training time on that set is checked in the implementation Issue.
- Changing pads quickly during a retrain gets `wrong_state` until the retrain ends.
- Follow-up work: engine 1.3 and the version 2 reader and writer; `output_names`,
  `Content`, and the kit and module files; the Pure Data patch and Max for Live
  device updates; tuning the module offsets and kit resting values on hardware;
  AGENTS.md rows once implemented; the interaction log ADR.
