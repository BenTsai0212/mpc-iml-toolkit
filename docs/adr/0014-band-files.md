# ADR 0014: Band files

- Status: Proposed
- Date: 2026-11-26
- Related: RFC 0006, ADR 0010, ADR 0011, ADR 0013, ADR 0015, #262, #274, #276, #286
- Amended: 2026-11-26 (#286)

> **Amendment (2026-11-26, #286).** A band says what each player sounds like by
> default and which drum hits it needs, so that one command can make a whole sound set
> for it (RFC 0006 step 5): each player gains a required `sound` (`words`, `seconds`,
> `takes`) and the band a required `hits` (`kick`, `snare` and `hat`, and other names).
> Format 1 is amended in place, without a new format version: this ADR is still
> Proposed and the only band files are the built-in ones. A band file without these
> fields is refused. The words are defaults the musician can replace; they say what a
> player sounds like, never what it plays. See option 5 and "Format 1".

## Context

A band was a table in the docs (a bass loop, a melody loop and a progression written
to go together, #262) and a set of devices in the DAW (which track plays which notes,
#274). Step 2 of RFC 0006 auditions a band with a sound set, and step 3 lets a
musician choose a band in the web demo and describe the sound of each player. Both
need to know, without the DAW, what the band plays, at what tempo, who plays which
notes, and which drums to play it with.

The decision maker agreed to band files on 2026-11-26. The two built-in bands were
written by the decision centre from the sets played on 2026-11-25: the roles are the
ones used in the DAW that day, and the drum patterns are those of the style previews
the musician heard.

## Options

### 1. Where a band lives
- **A file of its own (chosen)**: a sound set gives the players of one band their
  sounds, and several sound sets can be made for one band.
- Three names in a table (the docs until now): nothing says who plays what.
- Part of a sound set: a second set for the same band would repeat the band.

### 2. How a player is described
- **By what it plays (chosen)**: part, keys, velocity and octave, the `plays` of
  ADR 0013. Words change what a player sounds like, never what it plays (RFC 0006).
- By a sound: the same band could not take another sound set.

### 3. Which drums the audition plays
- **A pattern that is part of the band (chosen)**: the band is written for a kind of
  drumming, and its changes are heard only when the drums change.
- One pattern for every band: a lo-fi groove at 140 BPM does not move a trap band.

### 4. How a band is chosen while playing
- **With the existing controls (chosen)**: `bass-loop`, `loop` and `progression`, and
  the tempo of the DAW (RFC 0006, "Rules").
- An engine control or a protocol message: out of scope, and the band plays the same.

### 5. Where the default sound of a player lives (#286)
- **In the band file (chosen)**: the band is written for a kind of sound as much as for
  a kind of drumming, and one command can then make a set for it with nothing typed
  for each player.
- Only on the command line: the musician would type the words of every player each
  time.
- In a sound set: a set is what was made, not what to ask for.

## Decision

### Format 1

```json
{
  "format": "mpc-iml-band",
  "format_version": 1,
  "name": "lofi",
  "title": "Lo-fi",
  "description": "A lazy lo-fi band at about 76 BPM.",
  "preset": "ensemble",
  "tempo": 76,
  "content": {"bass_loop": "haze-bass", "loop": "haze-keys", "progression": "haze"},
  "players": [
    {"name": "bass", "title": "Bass", "description": "The bass line.",
     "plays": {"part": "bass", "keys": [0, 127], "min_velocity": 1, "octave": 1},
     "release": 0.12, "prefer": "clean",
     "sound": {"words": "Upright bass, plucked, warm, close mic", "seconds": 3, "takes": 2}}
  ],
  "hits": {
    "kick": {"words": "Dusty boom bap kick drum, deep, short decay, close mic", "seconds": 0.6},
    "snare": {"words": "Crisp snare drum, tight, short tail", "seconds": 0.45},
    "hat": {"words": "Closed hi-hat, very short, bright, no ring", "seconds": 0.2}
  },
  "patterns": {
    "groove-1": {"kick": [70, 0, …], "snare": […], "hat": […]}
  },
  "audition": ["groove-1", "groove-1"]
}
```

- The envelope is ADR 0010's: `format`, `format_version` 1, `name` (lower case
  letters, digits and hyphens; equal to the file name), `title`, `description`,
  `preset` (`ensemble`). Other top-level fields are errors.
- `tempo`: beats a minute, a whole number the web demo's simulation accepts (60-160).
- `content`: `bass_loop`, `loop` and `progression`, each the name of a built-in file of
  that kind (a bass loop, a melody loop, a progression).
- `players`: a list. Each has `name` (a name as in ADR 0013), `title`, `description`,
  `plays` (as in ADR 0013, with `part` required: `null` is refused) and the defaults
  for building its instrument, `release` (seconds, 0-10) and `prefer` (`clean` or
  `rich`). Names are unique, and each part has at least one player.
- Each player has `sound` (#286): `words` (the description sent to the model, not
  empty), `seconds` (how long a note is asked for, above 0) and `takes` (how many
  takes of each note in round 1, at least 1). Other fields are errors.
- `hits` (#286): an object keyed by hit name (a name as in ADR 0013), each with
  `words` (not empty) and `seconds` (the length of the hit that is kept, as
  `sounds.hits --seconds`, above 0). `kick`, `snare` and `hat` are required, because
  the audition plays them; other names are allowed, and the musician puts those on
  their own pads. Other fields are errors.
- The words of `sound` and `hits` are defaults. They say what a player sounds like,
  never what it plays (RFC 0006). The note name, "a single note" and "dry" are not
  part of them: the generator file adds those (ADR 0015).
- `patterns`: named bars of drums. Each has `kick`, `snare` and `hat`, 16 steps each:
  0 is no hit, 1 to 127 a velocity.
- `audition`: the bars of the audition by pattern name, 1 to 64 (the simulation's
  most).
- Errors are `ContentError`s naming the file and the field, for example
  `lofi.json: players[2]: two players are named 'keys'`.

### Code

- `mpc_iml.bands` (core, standard library only) reads the built-in bands from
  `src/mpc_iml/bands/ensemble/`: `Band.grid()` is the audition as the grid
  `webdemo.sim.simulate` takes, `Band.controls()` what `ensemble` is set to.
- `python -m mpc_iml.bands check <file>…` and `list`.
- `mpc_iml.bands` parses and checks `sound` and `hits` and nothing more. Which notes
  to ask for and the command that makes a whole set are in `mpc_iml.sounds.bandset`
  (`python -m mpc_iml.sounds.generate band`, #286), which needs the simulation.
- `plays` is checked once, in the core module `mpc_iml.plays`: `mpc_iml.sounds.soundset`
  and `mpc_iml.bands` both call it, so they refuse the same `plays` with the same words.

### Unchanged

No engine control and no protocol change. Loops, progressions and what `ensemble`
plays do not change. Only built-in bands are read: not from the data folder, not from
installed packages.

## Consequences

- The audition is "this band with this sound set", and the web demo can list bands
  and their players.
- A player of a band is built with `sounds.instrument --part --keys --min-velocity
  --octave --release --prefer` from its line in the band.
- Drum timing (swing) is not part of a pattern; the audition plays on the grid.
- A boom bap band waits for its content to be built in.
- A whole sound set for a band is one command; words for any one model are not tuned
  here, and note names with sharps or flats are not asked for (#286).
