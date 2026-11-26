# ADR 0015: Generator files

- Status: Proposed
- Date: 2026-11-26
- Related: RFC 0006, ADR 0010, ADR 0013, #268, #270, #272, #274, #284
- Amended: 2026-11-26 (#288)

## Context

Step 4 of RFC 0006 generates single notes and drum hits with a model the musician has
installed, and builds a sound set from them. The toolkit must not bundle, download or
host a model, and holds no key (RFC 0006, "Rules"). Models differ in how they are run
(a command of their own, a Python library, flags) and in how a prompt is best written
for them.

On 2026-11-25 a set was made by hand with a fixed script. The model played the note
name it was asked for, but often one octave away (5 of 8 notes of one instrument, none
of another), and one note in fifty was not clean. So nothing a model returns is trusted
before it is measured.

## Options

### 1. How the model is called
- **A command the musician configures (chosen)**: the toolkit runs it and reads the
  WAV file it wrote. It adds no dependency and imports nothing of the model.
- A library the toolkit imports: a dependency for each model, and the toolkit would
  have to follow each model's API.

### 2. Where what is specific to a model lives
- **In the generator file (chosen)**: the command, and how a prompt for a single note
  and for a drum hit is written for it. The toolkit knows nothing about any one model;
  the docs carry an example for the open weights of Stable Audio 3.
- In the toolkit: each new model would be a code change.

### 3. How the command runs
- **A list of arguments, run without a shell (chosen)**: the musician's words reach the
  model as one argument, whatever quotes, `;`, `$(...)` or newlines they hold.
- A command line run by a shell: words could run commands.

### 4. Where generated takes are kept
- **In the sound set, under `takes/` (chosen)**: a take was made for the set and has no
  other home; without it the instrument cannot be built again. This amends ADR 0013,
  which says source recordings are not copied into the set. Recordings the musician
  made are still not copied.
- Next to the generator, or in a temporary folder: the set would name files it cannot
  find, and the takes would be lost.

## Decision

### Format 1 of a generator file

```json
{
  "format": "mpc-iml-generator",
  "format_version": 1,
  "name": "example",
  "title": "Example model",
  "model": "example-model-small",
  "folder": "/path/to/the/model",
  "command": ["uv", "run", "example", "-p", "{prompt}", "--seed", "{seed}", "--duration", "{seconds}", "-o", "{out}"],
  "note_prompt": "{words}, one single note, {note}, dry, no reverb",
  "hit_prompt": "{words}, one-shot, dry, no reverb",
  "timeout": 120
}
```

- The envelope and the name rule of ADR 0010: `format`, `format_version` 1, `name`
  (lower case letters, digits and hyphens, equal to the file name), and optional
  `title` and `description`. A generator belongs to no preset, so there is no `preset`.
  Other fields are errors.
- `model` (required, text) is recorded as the `model` of each origin.
- `command` (required): a list of at least one string. `{prompt}`, `{seed}`,
  `{seconds}` and `{out}` are replaced inside an argument, in one pass (a value that
  holds braces is not read again); `{prompt}` and `{out}` are required, and any other
  `{...}` is an error. It runs with `folder` as its working directory (`folder` is
  optional, `~` is expanded; without it, the current one).
- `note_prompt` (required) holds `{words}` and `{note}` (a note name such as `E2` or
  `F#2`); `hit_prompt` (required) holds `{words}`. Any other `{...}` in a prompt is an
  error.
- `timeout`: seconds for one take, a number above 0, optional, 120 by default. A take
  that runs past it is stopped with what it started.
- The file lives on the musician's machine. None is added to the repository outside
  the docs and the tests.

### What is generated

- `python -m mpc_iml.sounds.generate notes` asks for each note, measures each take
  (`notes.measure`), and asks again, in up to `--rounds` rounds, for each note no clean
  take answered (clean by `instrument.CLEAN`, measured within 2 semitones). When the
  closest clean take of that note came out a whole number of octaves from the note
  asked, it asks that many octaves the other way; otherwise the same note with the next
  seed. It then builds the instrument from every take that could be measured, with
  `instrument.build`.
- `python -m mpc_iml.sounds.generate hit` asks for one take and makes the hit with
  `hits.make_hit`.
- A take is written to `takes/<name>-<asked note>-s<seed>.wav` (`#` as `s`), or
  `takes/<name>-s<seed>.wav` for a hit. Takes are first written to a folder of their
  own inside the set and moved into `takes/` only after `sound-set.json` is written, so
  a run where nothing can be used changes nothing in the set.
- Each take has an origin `{"kind": "generated", "model": …, "prompt": <the prompt
  sent>, "seed": …, "settings": {"generator": <name>, "words": <the words>, "asked":
  <note name>, "seconds": <duration>, "round": <n>}}`; a hit's settings have
  `generator`, `words` and `seconds`. `words` was added by #288 so that the band tab
  can show the words an instrument or hit was made with; `settings` is a free object
  in format 1 of ADR 0013, so the format does not change. `generate band` also records
  `"band": <band name>` next to `words` (#288), so that the band tab does not offer a
  set made for one band to another band that shares player names.
- Generating an instrument or a hit again removes the takes its earlier entry named
  that no entry names now. Nothing else in the folder is deleted.
- The generator file, the options and `sound-set.json` are checked before anything is
  asked of the model. `instrument.build` and `hits.make_hit` check the origins they
  are given before they write anything.

## Consequences

- Any model with a command line can be used without a change to the toolkit; one
  without a command needs a small script of the musician's.
- The toolkit runs a program the musician named, with the musician's rights. It sends
  nothing anywhere itself; what the model does is the model's.
- Sets grow by their takes. A musician may delete `takes/`: the set still loads and
  `soundset check` says how many takes are missing, but the instrument cannot be built
  again from them.
- Default words for the players of a band and the command for a whole set (step 5),
  and generating from the band tab (step 3, second part), build on these functions.
