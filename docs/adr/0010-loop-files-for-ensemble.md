# ADR 0010: Loop files for `ensemble`

- Status: Accepted
- Date: 2026-11-21
- Related: ADR 0002, ADR 0007, ADR 0008, ADR 0009, RFC 0005, #144, #148, #158, #166,
  #173, #113 (Epic)
- Accepted: 2026-11-22, implemented in #173 and played on `main` (#211)

## Context

The `ensemble` bass and melody loops and their variations (#144, #148, #158) are
Python tables (`bass.BASS_LOOPS`, `melody.LOOPS`), so only a code change can
replace them. In the #158 check the decision maker found the bass too plain, and
wants the musical content to come from people (first himself, later other
performers) and later from IML, not from code tuned by agents. The later steps
(weights, likes, learning while playing, rhythm transfer) will build on this data.

The `## Decision` on #173 (2026-11-21) accepts the plan posted there, adds timing
offsets, and grants an exception under RFC 0005 "Core changes" for one provisional
plugin field (`Preset.data_folder`, below).

## Options

### 1. What a file holds
- **One loop with all its variations (chosen)**, as kits and modules are one per
  file: a musician adds, shares or deletes one line at a time.
- A set of loops per file: one bad note fails the whole set.
- One file per variation: the selection works on loops, so files would have to be
  grouped by a shared name.

### 2. How a pitch is written
- **A chord tone with `chord` and `semitones`, as `melody.LoopNote` (chosen)**: the
  line follows any progression and chord quality, and approach notes work as in
  #148.
- A scale degree: needs a key and mode, and `minor-four`'s A7 needs accidentals.
- Semitones above the chord root: does not follow the chord quality.

### 3. Where files are registered
- **A content kind `loops` in `mpc_iml.content` (chosen)**: a package adds loops as
  it adds kits.
- A separate entry point group: a second registration for no gain.
- Loops inside a kit (a "style"): deferred by #144.

### 4. Parsing MIDI files
- **The standard library (chosen)**: a small Standard MIDI File reader and writer.
- `mido`: a new dependency, not needed for this much parsing.

## Decision

### Format 1

```json
{
  "format": "mpc-iml-loop",
  "format_version": 1,
  "name": "boom",
  "title": "Boom",
  "description": "A 1-bar boom-bap line.",
  "preset": "ensemble",
  "part": "bass",
  "bars": 1,
  "variations": {
    "home": [
      {"bar": 0, "step": 0, "tone": 0, "length": 3, "skeleton": true},
      {"bar": 0, "step": 14, "tone": 0, "length": 2, "chord": 1, "semitones": -1,
       "offset": 0.17}
    ]
  }
}
```

- `name` (lower case letters, digits and hyphens) equals the file name. `title` and
  `description` are optional. `preset` is `ensemble`; `part` is `bass` or `melody`;
  `bars` is 1, 2 or 4. Other top-level fields are errors.
- Variation names are fixed per part, because the #158 rules choose by them: bass
  `home`, `push`, `drive`; melody `home`, `open`, `busy`. `home` is required; a
  missing variation plays `home`; a written one has at least one note. Other names
  are errors that list the allowed names. Allowing new names later does not need a
  new format version.
- A note: required `bar` (0 to `bars` − 1), `step` 0-15 (16ths), `tone` 0-3 (root,
  third, fifth, seventh of the chord's quality), `length` 1-64 (16ths). Optional,
  with defaults: `level` 1 (2 is an ornament), `octave` 0 (−2 to 3, above the
  part's base octave), `velocity` 1.0 (a weight, 0.05-1), `chord` 0 (1 takes the
  next bar's chord), `semitones` 0 (−11 to 11, added after the tone), `offset` 0,
  `skeleton` false. Other fields are errors.
- `offset` is how far the note sits from its step, as a fraction of a 16th, −0.5 to
  0.5. `skeleton` (only in `home`) marks the notes `no-drums thin` plays; without
  any, `thin` plays `home`'s level 1.
- Bass notes of a variation may not overlap, also across the loop's end when it
  repeats: the bass is monophonic (#148). Melody notes may overlap.
- Errors are `ContentError`s naming the file and the note, for example
  `boom.json: variations.push[3]: step must be 0-15, got 16`.

**Representation and its aesthetic consequence.** Steps are 16ths, but the format
keeps what a player does between them: a timing `offset` per note and non-chord
tones (`semitones` over a chord tone). So it does not force quantized, chord-tone
lines: a laid-back bass note, a 9th or a chromatic approach is written as played.
What it cannot hold is a grid finer than 1/6 of a 16th as heard (the 24 PPQN clock),
triplet bars, or a pitch fixed regardless of the chord.

### Content kind and loading

- Files live under `<root>/loops/ensemble/<name>.json` of a `Content` registered in
  `mpc_iml.content` for the preset `ensemble`. `loops.load_loops` reads them,
  built-in content (the `mpc_iml` package) first, then installed packages, each by
  name. A bad built-in or installed file, a file name that differs from `name`, and
  two loops with the same name are errors when `ensemble` loads, as for kits.
- The built-in loops move into such files with the same notes, so the sound does
  not change; the Python tables are then removed.
- User loops are read from `<data folder>/loops/*.json` (the engine's folder, for
  example `./mpc-iml-data`). The engine passes the folder to a preset through a new
  optional, provisional plugin field `Preset.data_folder`; no protocol message
  changes. A bad user file, or one that reuses a built-in or installed name, is
  skipped with a log line and counted in a reply `loop-errors`, so one bad export
  never stops playing. `reload-loops` reads them again. The `ensemble` controls and
  replies are an ADR 0009 amendment.

### Import and export

- `python -m mpc_iml.loops import <clip.mid>` turns a standard MIDI file into a loop
  file (or one variation of an existing file with `--into`), `export` writes a loop
  as a MIDI clip, and `check` validates a file.
- Each pitch becomes the nearest chord tone over the progression and start bar the
  musician names (ties to the lower tone), with the rest in `semitones`. A
  non-chord tone in a bar's last 2 steps within 2 semitones of a tone of the next
  bar's chord becomes `chord` 1; there a tie goes to the higher tone, because an
  approach resolves upwards (G♯ before Am7 is the root − 1, not the seventh + 1).
  Steps are rounded to 16ths and the remainder is kept in `offset`, rounded to 1/6
  of a 16th. Velocities become weights relative to the loudest note;
  `--ornament-below` makes quiet notes level 2. `export` writes the offsets back,
  so a round trip keeps them.
- `export` writes ornaments (level 2) on MIDI channel 2 and `import` reads notes on
  channel 2 as level 2, because the built-in loops have ornaments as loud as their
  full line, so velocity alone cannot carry the level. A clip from Live is on
  channel 1, so this does not change an import from Live.
- A round trip keeps what is heard over the progression it was exported on, but
  not always how a note is written: a clip holds pitches, not intent. `walk`
  approaches its next chord from step 10, so `import` writes those notes as tones
  of their own bar (`chord` 0), which sound the same over that progression and
  differ over another. `skeleton` marks are not in a clip either.
- The mapping is `mpc_iml.loop_midi` (`from_midi`, `to_midi`; no file I/O), which
  also holds the commands. `import` writes new files into
  `./mpc-iml-data/loops/` by default (`--out`), refuses to overwrite one without
  `--force`, and starts a new file with `home`; other variations are added with
  `--into`. Replacing `home` with `--into` drops its `skeleton` marks, so `thin`
  plays its level 1. Files are written with one note per line and the defaults
  left out, as the built-in files. `export` takes a loop name (built-in, installed
  or in `--data`'s `loops/`) or a file.
- A new core module `mpc_iml.smf` reads and writes Standard MIDI Files with the
  standard library; the #166 MIDI download (`webdemo.midifile`) builds its format
  1 file with its `track`, `tempo` and `file`.

### Unchanged

The protocol stays 1.5. No new dependency. The selection rules, the bass fill and
the melody surprises stay in code and work on any loop. The recording format,
`clock`, the Max for Live device and the Ableton set do not change. `webdemo.sim`
keeps working with the built-in names.

## Consequences

- Musicians write lines in a DAW and play them without changing the toolkit; the
  later Issues (weights, likes, learning, rhythm transfer) have data to build on.
- Fixed variation names keep the #158 rules unchanged, at the cost of not allowing
  a musician's own variation names yet.
- Playback of `offset` is applied when a bar is scheduled, through the
  `Scheduler`'s tick timing (`ticks_per_step` 1), with no protocol or core change
  (#173 PR 2). The offset is rounded to a tick. A note cannot sound before the bar
  line its bar is planned at, so a negative offset on step 0 plays on the bar line.
  A bass note ends by the next bass note's start and the bar's end, so offsets keep
  the bass monophonic.
- Work in order (#173): the format, validation and loader; the built-in files;
  the user folder and controls; `mpc_iml.smf` with import and export; Pure Data
  group 8 and the README.
