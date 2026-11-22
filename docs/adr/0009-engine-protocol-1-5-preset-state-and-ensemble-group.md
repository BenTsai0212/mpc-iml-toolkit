# ADR 0009: Engine protocol 1.5, preset state replies and a preset group in Pure Data

- Status: Proposed
- Date: 2026-11-20
- Related: ADR 0004, ADR 0005, ADR 0006, ADR 0007, ADR 0008, RFC 0005 (proposed),
  #138, #144, #148, #153, #158, #159, #113 (Epic)

## Context

The built-in `ensemble` preset changes its bass mode (pad 16: `loop`, `rule`, `off`)
and its melody (pad 15: follow, fixed, off) from the MPC, and its loops and
progression from OSC. The only feedback is a line in the engine's terminal, so a
musician cannot see which mode is on, and the Pure Data front end has no controls
for it.

A front end cannot show a preset's state today: the engine sends nothing back after
a preset control (ADR 0004, clarification 6), and ADR 0004 lists "a reply channel
for preset controls" as open work for a minor protocol version. ADR 0006 allows
front ends only core messages, and a change to the groups needs a new ADR.

The `## Decision` on #153 (2026-11-20) accepts the plan posted there and grants an
exception under RFC 0005 "Core changes" for the engine, plugin-interface and
protocol changes below, as for #130, #138 and #144.

## Options

### 1. How a front end learns a preset's state

- **A general preset state reply (chosen).** A preset declares a snapshot hook; the
  engine sends the snapshot under the preset's subtree at fixed moments, and the
  preset can ask for it to be sent again when it changes on its own.
- Preset-specific replies only: a front end that connects, or loses a UDP packet,
  cannot ask for the state, and each later preset reinvents it.
- Front end only: the patch cannot see pad presses or bar lines. Rejected.

### 2. When a change applies

- **"next" and "playing" for the bass and melody modes (chosen).** Mode changes
  wait for the next bar line while the clock runs; a musician needs to see both
  that the press was taken and what is heard.
- Only "playing": a press seems to do nothing until the bar line.
- Only "next": the front end shows a mode not yet heard.

Loops and the progression change the notes of the next bar; front ends show only
the selection.

### 3. Where the controls go in Pure Data

- **An always present group 8 Ensemble in `patches/mpc-iml.pd` (chosen).**
- A separate patch per preset: only one front end can listen on port 6451
  (ADR 0006), so it would copy the whole general patch.
- A subwindow that opens when `ensemble` loads: easy to lose behind the DAW.

## Decision

### Protocol 1.5

The protocol version becomes **1.5** (`PROTOCOL_VERSION = (1, 5)`). ADR 0004 to
ADR 0008 stay as they are; this ADR adds replies and lengthens the full state, which
is a minor change. There is no new message, error code, state rule or port.

| Reply | Arguments | When |
| --- | --- | --- |
| `/mpciml/preset/<name>/<reply>` | as the preset declares (`i`, `f`, `s`) | After `preset/load`; in the full state, after `clock`; after each preset control that succeeds; when the preset calls `ClockAccess.report()` |

- The engine sends the whole snapshot each time, in the order the preset gives, so
  a lost UDP packet is fixed by the next report and `state/get` or `hello` always
  gives the current state.
- **Full state**: `state`, `preset`, `layout`, `names`, `kit`, `pads`, `counts`,
  `trained`, `clock`, then the active preset's state replies.
- A preset control that fails gets only `bad_arguments`, as before.
- Presets without a state hook send nothing new. Front ends written for 1.0 to 1.4
  ignore the new replies.
- The names and arguments of each preset's replies are versioned by the preset
  version (ADR 0004, Preset messages). This closes ADR 0004's clarification 6 and
  its follow-up "a reply channel for preset controls".

### Plugin interface

- New optional field `Preset.state: Callable[[], StateReplies] | None = None`,
  **provisional** like `controls` and `clock`. It returns (reply name, arguments)
  pairs; names are lower case letters, digits and hyphens, arguments are ints,
  floats or strings. The engine skips and logs an invalid pair, and sends nothing
  when the hook raises.
- New `ClockAccess.report()`: asks the engine to send the preset's state again. It
  does nothing once another preset has loaded. The engine calls the hook on the
  calling thread while holding its lock, so a preset must not call `report()` while
  holding a lock its controls also take.

### `ensemble` replies (preset version)

The reply name is the control name where a control exists.

| Reply | Arguments |
| --- | --- |
| `bass` | `s` next, `s` playing (`loop`, `rule`, `off`) |
| `melody-mode` | `s` next, `s` playing (`follow`, `fixed`, `off`) |
| `bass-loop`, `loop`, `progression` | `s` selected name |
| `bass-loops`, `loops`, `progressions` | `s`… the names to choose from, in the order of the built-in tables (loop files since #173, ADR 0010: built-in first, then installed, each by name) |
| `octave`, `melody-octave`, `channel`, `melody-channel`, `length`, `filter-cc`, `layer-pad`, `melody-pad`, `immediate`, `bar` | `i` value |
| `roles` | 16 × `s`, pads 1-16 |

- While the clock is not running, changes apply at once, so next and playing are
  equal. Without `--clock` the melody never plays, so its playing mode is `off`.
- `ensemble` calls `report()` after a pad 15 or 16 press, and at a bar line only
  when the playing bass or melody mode changed there.
- New control `melody-mode follow|fixed|off` sets the melody mode in one message;
  `melody` and `follow` stay. No musical behaviour changes.

### Front ends (update of ADR 0006 and ADR 0007)

- `patches/mpc-iml.pd` gains **group 8 Ensemble**; Messages becomes **group 9** and
  keeps its status line last. Groups 1-7 do not change.
- Controls, in order: `bass` (`loop`, `rule`, `off`, showing playing and next),
  `bass loop` (up to 4 buttons labelled from `bass-loops`), `melody` (`follow`,
  `fixed`, `off`, showing playing and next), `melody loop` (up to 4 from `loops`),
  `progression` (up to 4 from `progressions`) with `octave` and `melody octave`,
  and `roles` (read only, 4 rows of 4 like the pads, 13-16 on top). Changes start at
  the next bar line, which the group's label says.
- The group is always shown. While another preset is active its displays show `-`
  (reset on `/mpciml/preset`), and a click gets the engine's `inactive_preset`
  error on the status line. `ensemble` is loaded with the existing preset buttons.
- In `[pd osc]`, messages routed as `preset` are split by length: 2 elements are
  `/mpciml/preset <name> <version>`, 3 or more are preset replies, of which only
  `ensemble`'s are used.
- The whole patch stays visible without scrolling on a 14-inch MacBook screen: the
  canvas stays within about 1500 × 850. If the group does not fit in a row above
  Messages within that height, it goes in a new column to the right. The PR that
  adds the group states which layout it used, and `tests/test_patch.py` checks the
  canvas size.
- Exception to ADR 0006's rule "only core messages": group 8 uses `ensemble`'s
  subtree. The general patch therefore names one preset.
- The Max for Live device is unchanged; group 8 is Pure Data only, as the clock
  display of ADR 0008.

## Amendment: `learn-cc` (#159)

The `## Decision` on #159 (2026-11-20) accepts this amendment. In a manual test,
Live's MIDI Map Mode mapped a melody note instead of the brightness CC, because the
CC goes out only at a bar line, on the same channel and tick as the melody's notes.
The engine's `/mpciml/midi/learn` (ADR 0005) does not apply: `ensemble` declares no
`MidiCcOutput`.

- New `ensemble` control `learn-cc` (no arguments, preset version): sends only the
  brightness CC (`filter-cc` on `melody-channel`) through `ClockAccess.send_now`, as
  ADR 0005's sweep 0, 32, 64, 96, 127, downwards on every other call. It is refused
  with `bad_arguments` while the clock is `running` (the loops would send notes in
  between), when `filter-cc` is 0, and with arguments. It works without `--clock`.
  As after every control that succeeds, the engine then sends the state replies.
- Group 8 gains a row under `roles`: a `learn_CC` button that sends it, with the
  `filter-cc` and `melody-channel` replies shown next to it as `CC <n> ch <m>`. The
  canvas stays 1490 × 840. The Max for Live device does not change.
- No core message, reply, error code or protocol version changes. Reusing
  `/mpciml/midi/learn` for preset CCs would need a plugin-interface field and
  protocol 1.6; it can be decided when another preset needs it.

## Amendment: follow by variation (#158)

The `## Decision` on #158 (2026-11-20) accepts this amendment. The loops follow the
drums by choosing one of three complete variations of each loop instead of
dropping notes, and keep playing when the drums stop (`no-drums`).

- New `ensemble` controls (preset version): `no-drums lead|hold|thin` (default
  `lead`) and `fade-bars` 0-32 (default 8, 0: never stop). Both are read at each bar
  line.
- New replies after `roles`, in this order:

  | Reply | Arguments |
  | --- | --- |
  | `no-drums` | `s` value |
  | `fade-bars` | `i` value |
  | `surprise` | `i` 0 or 1 (PR 3, below; 0-2 since #178) |
  | `variation` | `s` bass variation playing, `s` melody variation playing (`-` when that loop is silent, not a loop, or there is no `--clock`) |

- `ensemble` calls `report()` at a bar line when the playing bass or melody mode
  **or a playing variation** changed there (instead of "only when the playing bass
  or melody mode changed"); at most one report per bar line.
- Group 8 and the Max for Live device do not change: the new replies are dropped by
  the group's `route`, and the new controls are OSC only.
- No core message, error code or protocol version changes; the protocol stays 1.5.
- A little surprise (PR 3 of #158): the control `surprise 0|1` (default 1) and the
  reply `surprise` (`i` value) between `fade-bars` and `variation`. At the last bar of
  each 4-bar phrase, with probability 1/2, `ensemble` plays a bass fill, the melody an
  octave up or a passing note, only in bars that follow the drums or keep playing
  without them (not fixed, `bass rule`, `thin` or a fade). The draw is seeded
  (`Ensemble(seed=…)`, a fresh seed in each build); a surprise does not change the
  `variation` reply and does not call `report()`. Group 8 does not change.

## Amendment: user loop files (#173)

The `## Decision` on #173 (2026-11-21) accepts this amendment, with ADR 0010. The
loops are loop files, and musicians add their own in `<data folder>/loops/`.

- The engine gives `ensemble` its data folder through the provisional plugin field
  `Preset.data_folder` (ADR 0010), each time it loads the preset. `ensemble` reads
  `<data folder>/loops/*.json` then. A bad file, or one that reuses a built-in,
  installed or other user loop's name, is skipped with a log line.
- New `ensemble` controls (preset version):
  - `reload-loops` (no arguments): reads the user folder again. A changed loop
    plays from the next bar line. A playing loop whose file is gone keeps playing
    (its name stays in `bass-loop` / `loop`) until another loop is chosen.
  - `bass-loop-step 1|-1` and `loop-step 1|-1`: choose the next or previous loop
    of `bass-loops` / `loops`, wrapping around; from a loop no longer listed, the
    first (1) or the last (−1).
- `bass-loop` and `loop` accept every loaded loop of their part; a melody loop
  given to `bass-loop` (or a bass loop to `loop`) is refused with `bad_arguments`.
- `bass-loops` and `loops` list built-in loops first, then installed, then user
  loops, each group by name.
- New reply after `variation`:

  | Reply | Arguments |
  | --- | --- |
  | `loop-errors` | `i` how many user loop files were skipped at the last read |

- Group 8's `bass loop` and `melody loop` rows become `<` name `>` (instead of up
  to 4 buttons): `<` and `>` send `bass-loop-step` / `loop-step` −1 and 1, and the
  box between shows `bass-loop` / `loop`. Under them, `reload` sends `reload-loops`
  and `errors` shows `loop-errors` (#173 PR 5). The group no longer uses the
  `bass-loops` and `loops` replies; `progression` keeps its 4 buttons. The canvas
  stays 1490 × 840 and the Max for Live device does not change.
- No core message, reply, error code or protocol version changes; the protocol
  stays 1.5.

## Amendment: the bass fill by default (#178)

Issue #178 asks for this amendment, following RFC 0005 principle 10 as amended in
#174: by default a surprise keeps to the style's grammar (a bass fill at the end of
a phrase), and the melody surprises, drawn without reference to the drums, are off
unless the musician turns them on.

- The control `surprise` takes 0-2 instead of 0 or 1 (preset version): 0 is off,
  1 (still the default) only the bass fill, 2 the bass fill, the melody an octave
  up or a passing note (the behaviour of 1 before #178). Other values are refused
  with `bad_arguments`, as before.
- The reply `surprise` stays an `i` value, now 0-2, in the same place.
- The draw, its probability (1/2), the phrase (4 bars) and the seed
  (`Ensemble(seed=…)`) do not change; with 1 the draw chooses among the fill only.
- Group 8 and the Max for Live device do not change (they have no surprise
  control).
- No core message, reply, error code or protocol version changes; the protocol
  stays 1.5. A preset's controls are versioned by the preset version (ADR 0004),
  and the message, its type and the reply's place are unchanged.

## Amendment: rhythm transformation (#189)

The `## Decision` on #189 (2026-11-21) accepts this amendment (RFC 0005 step 6).
The bass's onsets move towards the kicks of the last bar, as a layer on the
variations of #158; with `rhythm 2` the melody's onsets move towards the snares
and hats.

- New `ensemble` control (preset version): `rhythm` 0-2 (default 0 since #194;
  1 before), read at
  each bar line. It is a setting, not one of the two controls changed while playing
  (RFC 0005 principle 11): pads 15 and 16 stay those. 0 plays the variations as
  written, exactly as before #189; 1 reshapes the bass; 2 the bass and the melody.
  Other values are refused with `bad_arguments`. The default changed from 1 to 0
  after the manual check on #189 (#194): `rhythm 1` sounded about the same as
  `rhythm 0`, and in steady styles such as hip-hop the moved bass sometimes
  sounded off the beat, where the bass's grid position is part of the skeleton
  (RFC 0005 principle 10).
- New replies after `loop-errors`, in this order:

  | Reply | Arguments |
  | --- | --- |
  | `rhythm` | `i` value |
  | `transform` | `s` bass, `s` melody transformation playing: `plain`, `lock`, `answer`, `backbeat` (the melody, with `rhythm 2`), or `-` when that loop is silent, not a loop, or there is no `--clock` |

- `ensemble` calls `report()` at a bar line where the playing bass or melody mode,
  a playing variation **or a playing transformation** changed; at most one report
  per bar line.
- Group 8 and the Max for Live device do not change: the new replies are dropped by
  the group's `route`, and the control is OSC only.
- No core message, error code or protocol version changes; the protocol stays 1.5.

## Amendment: learning from likes (#196)

The `## Decision` on #196 (2026-11-22) accepts this amendment (RFC 0005 step 8,
PR 2 of #196). Each loop can learn which variation the musician wants for a kind
of drumming, starting from the rules of #158.

- New `ensemble` controls (preset version):
  - `learn off|likes` (default `off`), read at each bar line. It is a setting, not
    one of the two controls changed while playing (RFC 0005 principle 11). `off`
    plays exactly as before #196. With `likes`, each loop's variation in a bar
    that follows the drums is drawn by `learn.Learner` (a weighted softmax that
    starts at the rules, its own seeded generator), in the loop's context of the
    last bar's drums. Other values are refused with `bad_arguments`; `demo` comes
    in a later PR of #196.
  - `like` (no arguments): credits each loop's choice in the bar playing, or in
    the bar before in its first beat. Refused with `bad_arguments` with `learn
    off`, while the clock is not running, and with arguments.
- **Pad 16 changes meaning with `learn likes`:** the layer pad sends a like
  instead of cycling the bass mode, so the two controls changed while playing
  stay pads 15 and 16. The bass mode is then set before playing (`bass`, or group
  8). With `learn off` both pads are as before.
- New replies after `transform`, in this order:

  | Reply | Arguments |
  | --- | --- |
  | `learn` | `s` mode |
  | `likes` | `i` likes that credited a choice in this build |
  | `chose` | `s` bass, `s` melody: where the variation playing came from, `rule` or `bandit` (later `model`, `want`), or `-` when that loop is silent, not a loop, or there is no `--clock` |
  | `learned` | `s` … up to 4 `<part>:<context>><arm>` whose learned top arm differs from the rules, bass first, or one `-` for none |

- `ensemble` calls `report()` after a press of pad 16 (as before), and at a bar
  line where the playing modes, a variation, a transformation, **`chose` or
  `learned`** changed; at most one report per bar line. With `learn off`, `chose`
  follows `variation` and `learned` stays `-`, so the reports are as before.
- Group 8 and the Max for Live device do not change: the new replies are dropped by
  the group's `route`, and the controls are OSC only (a group 8 row is out of
  scope for #196).
- No core message, error code or protocol version changes; the protocol stays 1.5.

### Learning from demonstrations (#196, PR 3)

The same `## Decision` covers this part (point 4, B).

- `learn` also takes `demo`. Pads 16 and 15 then cycle the wanted bass and melody
  variation (`auto`, then the part's variations) instead of the modes, so the two
  controls changed while playing stay pads 15 and 16; the modes are set before
  playing. `ensemble` calls `report()` after each press, as before.
- New control `want bass|melody auto|<variation>`, as the pads. Refused with
  `bad_arguments` unless `learn demo`, and for an unknown part or variation.
- A loop with a wanted variation plays it in the bars that follow the drums. Each
  complete bar with drums (kicks, for the bass) that wanted the same variation from
  its bar line to the next adds an example (`learn.features` mapped to the
  variation), and the loop's decision tree (`sklearn_backend.Tree`) is retrained at
  that bar line. With `auto` the loop plays the tree's prediction, or the rules
  with fewer than 4 examples or one variation among them.
- `chose` also gives `model` and `want`. New replies after `learned`, in this
  order:

  | Reply | Arguments |
  | --- | --- |
  | `want` | `s` bass, `s` melody: the wanted variation, `auto` for none |
  | `examples` | `i` bass, `i` melody: examples in this build |

- A bar line also reports when `want` or `examples` changed; with `learn off` they
  stay `auto` and 0, so the reports are as before. Group 8 and the Max for Live
  device do not change.

### The learning profile (#196, PR 4)

The same `## Decision` covers this part (point 7).

- New controls, no arguments: `save-profile` writes what was learned (the likes'
  weights and the examples) to `<data folder>/learn/ensemble.json`
  (`mpc-iml-ensemble-profile`, format version 1, `learn_profile`); `load-profile`
  reads it again and trains the trees from its examples; `reset-learning` goes back
  to the rules in memory. `save-profile` and `load-profile` are refused with
  `bad_arguments` without a data folder, and `load-profile` also for a missing or
  bad file.
- The profile is also read when the preset gets its data folder, and written at
  each phrase start while `learn` is not `off`. A file that cannot be read is
  logged and kept: the phrase starts do not overwrite it until `save-profile`.
- New reply after `examples`: `profile-errors` (`i`), 1 when the profile could not
  be read at the last try, else 0. `ensemble` calls `report()` after the three
  controls. Group 8 and the Max for Live device do not change.

## Consequences

- A front end can show any preset's state, including changes made on the MPC, with
  no extra request: `hello` and `state/get` already give it.
- **The plugin interface grows** by the provisional `Preset.state` and
  `ClockAccess.report()`; existing presets keep working unchanged.
- The general Pure Data patch knows one preset by name; a later preset with its own
  group needs another ADR.
- Recording format, kits and modules, the clock and scheduler, ADR 0008 and the
  musical behaviour of `ensemble` do not change.
- Follow-up work under #153: the engine and its tests (this ADR's PR); `ensemble`'s
  state, `melody-mode` and `report()` calls; the Pd group and its tests; README and
  AGENTS.md rows; the manual check with `ensemble` running.
