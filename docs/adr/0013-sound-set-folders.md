# ADR 0013: Sound set folders

- Status: Proposed
- Date: 2026-11-26
- Related: RFC 0006, ADR 0010, #268, #270, #272, #274
- Amended: 2026-11-26 (#274)

> **Amendment (2026-11-26, #274).** Each instrument records which notes of the band
> it plays (`plays`: its part, its keys, the softest note it plays and its octave),
> and its SFZ file plays only those notes. Format 1 is amended in place, without a new
> format version: this ADR is still Proposed and no set has been made with it outside
> tests. A `sound-set.json` whose instruments have no `plays` is refused. See option 5
> and "What an instrument plays".

## Context

Step 1 of RFC 0006 measures recordings of single notes (#268) and builds an SFZ
instrument from them (#270). A band needs several instruments and drum hits, and the
later steps of RFC 0006 (audition, the web demo tab, generation) need to know what a
folder holds, what was measured in each recording, and why a recording was used or
left out. Guessing that from file names breaks as soon as a musician renames a file.

The sets played so far were made by hand: an SFZ file for each pitched part, and the
drum hits as WAV files that the musician put on their own pads.

## Options

### 1. Drum hits
- **WAV files, one for each hit (chosen; the decision maker chose this on
  2026-11-26)**: the musician puts the hits on their own pads, as for the sets
  played so far.
- A drum SFZ file mapped to pads: needs a pad layout, and the layout differs
  between musicians. The open question of RFC 0006 about pads stays open.

### 2. Where the record lives
- **One file for the folder (chosen)**: the later steps load a whole set.
- One file for each instrument: a whole set would mean reading and merging several
  files.

### 3. How files are named
- **File names for the sources, paths relative to the folder for what the set
  holds (chosen)**: the folder can be moved or shared without leaking where the
  recordings sit on the musician's machine. Source recordings are not copied into
  the set.
- Paths as given: they hold the musician's folders and break when a folder moves.

### 4. Where a recording came from
- **An optional `origin` in format 1 (chosen)**: the generation step (step 4 of RFC
  0006) sets it without a new format.
- Add it in a later format version: every set made before would need converting.

### 5. Who plays which notes (#274)
- **The instrument (chosen; the decision maker chose this on 2026-11-26)**: each
  instrument records its part, its keys, the softest note it plays and its octave,
  and its SFZ file plays only those notes. The musician puts each instrument on its
  own track that receives its part, with no key or velocity filter, and the audition
  and the web demo read the same facts from `sound-set.json`.
- Devices in the DAW and flags of the audition, as in the sets played on
  2026-11-25 (the keys under C5 and a bell from C5 up, a pad only for notes hit hard,
  one bass an octave above the notes it was sent): nothing in the set says how it was
  meant to be played, and the audition would need the same settings again.

## Decision

### Layout

```text
<folder>/
  sound-set.json
  <instrument>.sfz
  samples/<instrument>-<note>.wav
  hits/<hit>.wav
```

### Format 1 of `sound-set.json`

```json
{
  "format": "mpc-iml-sound-set",
  "format_version": 1,
  "instruments": {
    "bass": {
      "sfz": "bass.sfz",
      "settings": {"prefer": "clean", "release": 0.12, "clean": 0.985},
      "plays": {"part": "bass", "keys": [0, 127], "min_velocity": 1, "octave": 0},
      "span": [28, 55],
      "uncovered": [[50, 55]],
      "files": [
        {
          "file": "take-1.wav",
          "measured": {
            "start": 2205, "frequency": 41.25, "note": 28, "cents": 2.1,
            "clean": 0.998, "rich": 0.31, "other": null, "attack_cents": -3.0,
            "length": 1.4, "seconds": 3.0, "peak_db": -6.2
          },
          "region": {
            "sample": "samples/bass-E1.wav", "low": 0, "high": 30,
            "centre": 28, "tune": -2, "gain_db": 1.5
          },
          "origin": {"kind": "recorded"}
        },
        {"file": "take-3.wav", "left_out": "the recording is silent"}
      ]
    }
  },
  "hits": {
    "kick": {"sample": "hits/kick.wav", "file": "kick-take-2.wav", "seconds": 0.6, "gain_db": -2.1}
  }
}
```

- `format`, `format_version`, `instruments` and `hits` are required. `instruments`
  and `hits` are objects keyed by name; either may be empty. A name is lower case
  letters, digits and hyphens, as `name` in ADR 0010.
- An instrument has `sfz`, `settings` (`prefer`, `release`, `clean`: what `build`
  was given), `plays` (see below), `span` (the lowest and the highest key the part
  plays, in notes the band sends, or `null`), `uncovered` (the stretches `build`
  returns) and `files`.
- Each entry of `files` has `file` and exactly one of `region` and `left_out`.
  `measured` holds the fields of `notes.Measurement` and is absent only when the
  file could not be measured.
- A hit has `sample`, `file`, `seconds` (the length written) and `gain_db` (how much
  its level was moved).
- `file` is a file name, with no path separator. `sfz` and `sample` are paths
  relative to the folder that stay inside it.
- Each entry of `files` and each hit may have an `origin`: `{"kind": "recorded"}`, or
  `{"kind": "generated", "model": …, "prompt": …, "seed": …, "settings": {…}}` with
  `model`, `prompt` and `seed` required and `settings` an optional free object.
- A region's `low`, `high` and `centre` are the values written in the SFZ file.
- Other fields are errors, at every level except inside `settings` of an `origin`.
  A new field means a new format version.

### What an instrument plays (#274)

`plays` holds four values, all about the notes the band sends, before any shift:

- `part`: `"bass"`, `"melody"` or `null` (not said). It is recorded here only; the
  SFZ file does not filter MIDI channels.
- `keys`: `[low, high]`, the lowest and the highest note it plays, 0 to 127. Default
  `[0, 127]`.
- `min_velocity`: it plays only notes hit at least this hard, 1 to 127. Default 1.
- `octave`: it sounds this many octaves above the notes it is sent, -4 to 4. Default 0.

The SFZ file uses only basic opcodes. Each kept note's `pitch_keycenter` is moved
down by 12 times `octave`, the key ranges are split between the moved centres (the
lowest and the highest still reach to the ends of the keyboard), and each region's
`lokey` and `hikey` are then cut to `keys`. A note whose range falls outside `keys`
gets no region and no sample, and is left out with a reason. An `octave` that moves
a kept note off the keyboard is refused before anything is written. With
`min_velocity` above 1 the `<global>` line holds `lovel`. With the defaults the SFZ
file and the samples are what they were before this amendment.

A reader that plays the regions as written, and skips notes under `min_velocity`,
plays what an SFZ player plays. `uncovered` lists the keys in both `span` and `keys`
that are more than 6 semitones from every note with a region, counted in notes the
band sends.

### Writing and reading

- Building an instrument adds or replaces its entry and keeps the other instruments
  and the hits. Building it again removes the samples its earlier entry listed that
  no entry uses now; nothing else in the folder is deleted.
- A `sound-set.json` whose format cannot be accepted stops the instrument and the hit
  commands before they write anything. A file it names that is missing does not stop
  them: building again is how a missing sample comes back.
- `soundset.load` refuses a set with any problem, a missing file included, and
  `python -m mpc_iml.sounds.soundset check <folder>` lists every problem.

## Consequences

- The later steps of RFC 0006 read one file for a whole set, and the reasons a
  recording was left out are kept with the set.
- The musician puts each instrument on its own track that receives its part; no key
  or velocity filter and no octave shift go in front of it.
- Hits have no pad mapping; how hits map to pads stays an open question of RFC 0006.
- A set does not hold its source recordings: building an instrument again needs them.
