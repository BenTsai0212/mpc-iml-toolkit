# ADR 0011: Progression files for `ensemble`

- Status: Proposed
- Date: 2026-11-23
- Related: ADR 0009, ADR 0010, RFC 0005, #221, #232, #236

## Context

`ensemble` plays its loops over a fixed chord progression. The two progressions
(`minor-two`, `minor-four`) were a Python table (`ensemble.PROGRESSIONS`), so only
a code change could add one. Loop notes are chord tones (ADR 0010), so every loop
already follows whatever progression plays, and more progressions are the cheapest
way to give the band more to answer with. In the trials the band's few answers made
the learning modes sound alike (2026-11-23).

The `## Decision` on #236 (2026-11-23) accepts the plan posted there with the
recommended choices: the tonic as a note name, a new ADR rather than an ADR 0010
amendment, one `reload-loops` for loops and progressions, `m7b5` as the only new
quality, five hip-hop progressions, and `<` name `>` in Pure Data group 8.

## Options

### 1. Where the format is recorded
- **A new ADR (chosen)**: a progression is a separate content kind with its own
  parser; ADR 0010 stays as accepted.
- An ADR 0010 amendment: mixes two formats in one record.

### 2. How the tonic is written
- **A note name, `C` to `B` with an optional `#` or `b` (chosen)**: a musician
  editing a file thinks "A", not "9".
- A pitch class 0-11, as `Progression.tonic` stores it.

### 3. How chord lengths are written
- **`bars` per chord (chosen)**: a progression can hold a 2-bar chord next to
  1-bar ones (`two-five-one`: Dm7, G7, Cmaj7 for 2).
- One `bars_per_chord` for the progression, as the Python table had.

## Decision

### Format 1

```json
{
  "format": "mpc-iml-progression",
  "format_version": 1,
  "name": "minor-two",
  "title": "Minor two",
  "description": "Am7 and Fmaj7, 2 bars each.",
  "preset": "ensemble",
  "tonic": "A",
  "chords": [
    {"root": 0, "quality": "m7", "bars": 2},
    {"root": 8, "quality": "maj7", "bars": 2}
  ]
}
```

- The envelope is the loop file's (ADR 0010): `name` (lower case letters, digits
  and hyphens) equals the file name, `title` and `description` are optional,
  `preset` is `ensemble`. Other top-level fields are errors.
- `tonic` is a note name: `C` to `B` with an optional `#` or `b`.
- `chords` holds 1 to 8 chords. A chord has a required `root` (0-11, semitones above
  the tonic), a required `quality` (a key of `melody.QUALITIES`; the error lists
  them) and an optional `bars` (1-4, default 1). Other fields are errors.
- The whole progression lasts 1, 2, 4 or 8 bars, so it lines up with the 4-bar
  phrase that drives surprises, `bass_stage` and the learn log.
- Errors are `ContentError`s naming the file and the chord, for example
  `lofi.json: chords[2]: quality must be one of m7, maj7, 7, got 'm9'`.

### Content kind and loading

- Files live under `<root>/progressions/ensemble/<name>.json` of a `Content`
  registered in `mpc_iml.content` for `ensemble`, next to loops.
  `progressions.load_progressions` reads them: built-in content first (`minor-two`,
  `minor-four`, then the others by name), then installed packages by name. A bad
  file, a file name that differs from `name`, and two progressions with the same
  name are errors when `ensemble` loads, as for loops.
- The built-in progressions move into such files with the same tonic, chords and
  lengths, so the sound does not change; the Python table is removed. `minor-two`
  stays the default.
- `python -m mpc_iml.progressions check <file>…` validates files and prints the
  chords by name; `list` prints the progressions.

### Later steps (#236)

- The quality `m7b5` (tones 0-3: root, minor third, flat fifth, minor seventh) and
  five built-in hip-hop progressions; the control `progression-step` and Pure Data
  group 8 as `<` name `>`.
- User progressions in `<data folder>/progressions/*.json`, read when the preset
  loads and on `reload-loops`; a bad file, or one that reuses a name, is skipped
  and counted in a reply `progression-errors`. The controls and replies are an
  ADR 0009 amendment.
- `--data` for the tools that take `--progression`, and the next bar's chord in the
  status line.

### Unchanged

The protocol stays 1.5. No new dependency. The loop format (ADR 0010) does not
change: loop notes stay chord tones, so any loop plays on any progression. No
import or export of progressions: a file is a few lines of JSON.

## Consequences

- Musicians and packages can add progressions without changing code; a progression
  file and a loop file are independent.
- Per-chord lengths replace `bars_per_chord`; for the two built-in progressions
  every bar gets the same chord as before (tested for bars −1 to 31).
- The order of the reply `progressions` stays `minor-two`, `minor-four` first; the
  list grows as progressions are added.
