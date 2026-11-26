# Measuring notes and building instruments

English | [繁體中文](sounds.zh-TW.md)

The first part of step 1 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#268):
find out what a recording of a single note really holds before it becomes part of a
sound set. A model that generates single notes cannot be trusted to play the pitch it
was asked for: in the first notes made this way the note name was always right, but
the octave was wrong for several of them, and two notes were not clean. The second part (#270) builds an instrument from the measured notes: see
[Build an instrument](#build-an-instrument); the last part (#272) gathers instruments
and drum hits into a [sound set](#sound-sets).

## Run it

The command needs `numpy`, which comes with the `demo` extra:

```bash
uv sync --extra demo
uv run python -m mpc_iml.sounds.notes bass-E1.wav bass-A1.wav
```

It prints one line for each file:

```text
file                         note        Hz  cents   clean   rich  attack
bass-E1.wav                  E1        41.3     +4   99.8%  24.6%     -2c
```

A file it cannot read or measure is reported on the error output, and the command
ends with status 1 after the other files.

It reads WAV files: 16, 24 and 32-bit PCM and 32-bit float, mono or stereo. Chunks it
does not know (`fact`, `PEAK`, `LIST`, `bext` and others) are skipped. Other formats
are refused with an error. No audio library is needed. Recordings stay on your machine;
the tests use synthetic tones.

## What the numbers mean

- **note** and **cents**: the nearest MIDI note to the fundamental and how far the note
  is from it; positive is sharp. The pitch is measured on the **sustain**, from 0.15 s
  after the sound starts, not on the attack: the attack of a plucked or struck sound is
  often sharp, and a sample tuned by its attack plays flat.
- **Hz**: the fundamental of the sustain. A candidate fundamental must be a spectral
  peak itself, or have both its second and its third harmonic present. Without that
  rule, a note with one stray partial is read as a clean note at half or a third of
  its real fundamental.
- **clean**: the share of the energy of the spectral peaks that lies on harmonics of
  the fundamental (within 35 cents). A clean pitched note is close to 100%; noise or a
  partial that is not a harmonic lowers it. The strongest such partial is kept as
  `other` (its frequency and its level under the strongest peak).
- **rich**: the share of the energy around harmonics 2 to 4. A pure sine is near 0%;
  a bright bass with strong low harmonics is over 50%.
- **attack**: how far the first 120 ms are from the sustain, in cents. A plucked note
  that starts sharp shows a positive number here.
- In Python, `measure` also gives the frame where the sound starts (the first sample
  within 40 dB of the peak), the time until the level has fallen 20 dB, the length of
  the recording and its peak level.

A silent recording, and one shorter than about 0.3 s after the sound starts, is
refused.

## Build an instrument

The second part of step 1 (#270) turns the recordings of single notes for one player
into an instrument that any SFZ player loads, so it can play on the band's tracks:

```bash
uv run python -m mpc_iml.sounds.instrument bass bass-*.wav --out bass-set --low E1 --high G3
```

It writes `bass-set/bass.sfz` and the notes it uses in `bass-set/samples/`, and prints
one line for each region, for each file left out (with the reason) and for each stretch
of keys no note reaches:

```text
bass: samples/bass-E1.wav      keys   0-30  centre  28 (E1)  tune -4  level +1.2 dB  from bass-E1.wav
bass: left out bass-A1-take2.wav: another take of A1 is cleaner
bass: no note within 6 semitones of D3 to G3
```

The rules:

- Each file is measured as above. A file that cannot be read or measured is left out
  with the reason; the other files are still used.
- A note with **clean** under 98.5% is left out.
- One note is kept for each pitch: of several takes, the cleanest, or with
  `--prefer rich` the one with the highest **rich** (a bass that small speakers can
  still play).
- Each note plays the keys up to halfway to its neighbours; the lowest and the highest
  note reach to the ends of the keyboard.
- The silence before the note is cut: the sample starts 32 frames before the sound, and
  ends with a 10 ms fade.
- The levels are evened out: the level of the first 0.4 s of each note is brought to the
  median of the kept notes, by at most 9 dB up or down; after that no sample peaks above
  −1 dB full scale.
- Each note is written as a 24-bit WAV file with the sample rate and channels of its
  recording, named `<name>-<note>.wav` (`#` written as `s`, for example `keys-Fs4.wav`).
- The SFZ file has one `<global>` line (a 2 ms attack, the release from `--release`,
  0.25 s by default, and velocity changing the level) and one `<region>` for each note,
  with its keys, its note and the measured cents as `tune`.
- With `--low` and `--high` (the lowest and the highest note the part plays; give both
  or neither), the stretches of keys in that span that are more than 6 semitones from
  every kept note are listed.

When no recording can be used, the command prints the reason and ends with status 1.

### What an instrument plays

An instrument can play only its share of the band's notes (#274). Four options say
which, all in the notes the band sends, before any shift:

- `--part bass|melody`: the part of the band it plays. It is recorded in
  `sound-set.json` only; the SFZ file does not filter MIDI channels.
- `--keys <low> <high>`: the lowest and the highest note it plays, as note names
  (for example `--keys C5 G9`). Default: all keys.
- `--min-velocity <1-127>`: it plays only notes hit at least this hard. Default 1.
- `--octave <-4..4>`: it sounds this many octaves above the notes it is sent.
  Default 0.

The SFZ file does it with basic opcodes, so any SFZ player plays it:

- Octave: each note's `pitch_keycenter` is moved down by 12 semitones for each
  octave, and the keys are split halfway between the moved notes. With `--octave 1`,
  a note sent at A1 plays the sample of A2 at its own pitch. An octave that moves a
  note off the keyboard is refused before anything is written.
- Keys: each region's keys are cut to `--keys`. A note whose keys fall outside them
  gets no region and no sample, and is left out with the reason.
- Velocity: with `--min-velocity` above 1, the `<global>` line holds `lovel`.
- With the defaults, the SFZ file and the samples are what they were without these
  options.

`--low` and `--high` are in notes the band sends too, and only the keys inside both
the span and `--keys` are checked for a note within 6 semitones. When the options
are not the defaults, the first printed line says what the instrument plays:

```text
bell: plays the melody part, keys C5 to G9 (72-127)
```

For example, a melody part shared by three instruments, as in the sets played on
2026-11-25: the keys for the notes under C5, a bell from C5 up, and a pad only for
the notes hit hard:

```bash
uv run python -m mpc_iml.sounds.instrument keys keys-*.wav --out band-set --part melody --keys C-1 B4
uv run python -m mpc_iml.sounds.instrument bell bell-*.wav --out band-set --part melody --keys C5 G9
uv run python -m mpc_iml.sounds.instrument pad pad-*.wav --out band-set --part melody --min-velocity 86
```

A bass that should sound an octave above the notes it is sent takes `--part bass
--octave 1`. Put each instrument on its own track that receives its part (the three
melody instruments all receive the melody channel), with no key or velocity filter
and no octave shift in front of it.

### The players of a band

A band file (ADR 0014, `python -m mpc_iml.bands list`) gives each player its line:
its `plays` (part, keys, `min_velocity`, octave) and the defaults for building its
instrument (`release`, `prefer`). Build each player with `--part`, `--keys`,
`--min-velocity` and `--octave` from its `plays`, and `--release` and `--prefer` from
its line. Keys are written as note names: 0 is C-1, 71 is B4, 72 is C5 and 127 is G9.
For the `trap` band (`src/mpc_iml/bands/ensemble/trap.json`):

```bash
uv run python -m mpc_iml.sounds.instrument 808 808-*.wav --out trap-set --part bass --keys C-1 G9 --min-velocity 1 --octave 0 --release 0.08 --prefer rich
uv run python -m mpc_iml.sounds.instrument keys keys-*.wav --out trap-set --part melody --keys C-1 B4 --min-velocity 1 --octave 0 --release 0.25 --prefer clean
uv run python -m mpc_iml.sounds.instrument bell bell-*.wav --out trap-set --part melody --keys C5 G9 --min-velocity 1 --octave 0 --release 0.3 --prefer clean
uv run python -m mpc_iml.sounds.instrument pad pad-*.wav --out trap-set --part melody --keys C-1 B4 --min-velocity 86 --octave 0 --release 0.5 --prefer clean
```

The `lofi` band's `bass` takes `--octave 1`: it sounds an octave above the notes the
band sends.

## Sound sets

The last part of step 1 (#272, [ADR 0013](adr/0013-sound-set-folders.md)): a folder
that holds the instruments and drum hits made for one band is a **sound set**:

```text
<folder>/
  sound-set.json
  <instrument>.sfz
  samples/<instrument>-<note>.wav
  hits/<hit>.wav
  takes/<take>.wav
```

`sound-set.json` records what the set holds. For each instrument: its SFZ file, the
settings it was built with (`prefer`, `release`, `clean`), what it plays (`plays`:
`part`, `keys`, `min_velocity`, `octave`), the span and the keys no note reaches, and for every source recording what was measured in it and its region,
or why it was left out. For each hit: its sample, the recording it was cut from, its
length and how much its level was moved. Source recordings are named by file name
only and are not copied into the set, so the folder can be moved or shared. Takes a
model generated for the set are the exception: they are kept in `takes/`
([Generating notes](#generating-notes)).

Building an instrument into a folder adds it to `sound-set.json` (or replaces the
entry of an instrument with the same name) and keeps the other instruments and the
hits. Building it again removes the samples it no longer uses; nothing else is
deleted. Names are lower case letters, digits and hyphens.

### Drum hits

Each drum hit is one WAV file, cut from one recording:

```bash
uv run python -m mpc_iml.sounds.hits kick kick-take-2.wav --out band-set --seconds 0.6
```

It writes `band-set/hits/kick.wav`, records the hit and prints one line:

```text
kick: hits/kick.wav  0.60 s  level -2.1 dB  from kick-take-2.wav
```

The hit starts 32 frames before the sound (the first sample within 40 dB of the
peak), lasts `--seconds` (0.5 s by default), ends with a 30 ms fade and peaks 3 dB
under full scale. It is written as 24-bit WAV with the sample rate and channels of
its recording. A silent recording is refused. The set does not map hits to pads: put
them on your own pads.

### Check a set

```bash
uv run python -m mpc_iml.sounds.soundset check band-set
```

It reports every problem it finds, in the format and in each SFZ file, sample and hit
the file names but the folder lacks, and ends with status 1 when there is one. When
`sound-set.json` cannot be accepted, the instrument and the hit commands stop with
status 1 before they write anything.

## Audition

Step 2 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#278): hear what a band
sounds like with a sound set without opening the DAW.

```bash
uv run python -m mpc_iml.sounds.audition lofi lofi-set --out lofi-audition
```

The band is a built-in band (`python -m mpc_iml.bands list`). Its audition pattern
plays through `ensemble` offline, as in the web demo, with the band's content and
tempo; `--bars 8` plays only the first 8 bars. The command writes 24-bit WAV files
into `--out`: `<instrument>.wav` for each instrument of the set that plays a part,
`drums.wav` and `band.wav`. Each file lasts the song (the bars and one more, the band's
answer to the last bar) plus the longest release. It prints one line for each file,
and says which players of the band have no instrument of their name in the set, which
instruments play no part (`part` is `null`) and are skipped, how many notes of each
part no instrument played, and which drums have no hit.

What it does:

- Which instrument plays which note comes from the set, not from the band: an
  instrument plays a note of its part when the note is inside one of its regions and
  hit at least at its `min_velocity`, as its SFZ file says. The band's `bass` notes are
  the bass part and its `keys` notes the melody part; several instruments may play one
  note.
- A note plays its region's sample moved by the note minus `pitch_keycenter` in
  semitones plus `tune` in cents, by resampling with linear interpolation. It has a
  2 ms attack, plays until the note ends and then fades over the instrument's
  release; a sample that ends earlier just ends (no looping). A new note of the same
  pitch in the same instrument ends the one before.
- A note's level is full at velocity 127 and 16 dB lower at 0, in a straight line in
  dB. The `kick`, `snare` and `hat` of the band play the set's hits of those names with
  the same law, on the step; a drum without a hit is silent.
- Nothing is mixed: every instrument and the drums are added as they are, and one gain
  for all of them brings `band.wav` to a peak of 1 dB under full scale. The single
  files keep that gain, so they add up to `band.wav`. The files are stereo; a mono
  sample plays in both channels.
- All samples of the set must have one sample rate, which is the rate of the files; a
  set with two rates is refused.

It is close to what an SFZ player plays on the band's tracks, but not the same. The
velocity law is the one of the renders heard on 2026-11-25; an SFZ player's law for
`amp_veltrack=85` is close to it but not the same. There are no effects, no brightness
control (CC 74), no levels or panning for each player, and the drums are straight on
the step, without swing. Nothing it writes belongs in the repository.

The functions behind the command take the notes and the loaded set and return arrays,
so the web demo can call them without writing files: `play(band, bars)` runs the
audition, `played(song)` gives its notes in seconds, `audition(song, set)` renders
everything, and `render_notes(instrument, notes, rate, frames)` renders a list of
notes with one instrument.

## The band tab of the web demo

The first part of step 3 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#280): the
same audition in the web demo, with sound sets you already made, and a button that
sets the engine to the band. Put each sound set in its own subfolder of one folder,
then start the demo with it:

```bash
uv sync --extra demo
uv run python -m mpc_iml.webdemo --sounds my-sound-sets
```

The **band** tab has four parts, top to bottom:

1. **Choose a band**: a built-in band, with its title, description, tempo and
   content, and a table of its players (name, part and what it plays).
2. **Choose a sound set**: the subfolders of `--sounds` that hold a `sound-set.json`.
   A set the checks of `soundset check` refuse is listed with the reason and cannot be
   chosen; **Read the folder again** reads the folder after you build or change a
   set. For the chosen set, one line for each player of the band: the instrument of
   its name (how many regions, and what it plays when that differs from the player) or
   that the set has none; then the instruments of the set that are not players of the
   band, and the drum hits. When the page opens and when you choose another band, the
   tab chooses the set in which the most players of the band have an instrument of
   their name that plays their part (#282); the chosen set stays when it is among the
   best or when no set has a player of the band. **Read the folder again** keeps the
   chosen set while it is there and chooses again when it is gone. You can still
   choose any set by hand.
3. **Listen**: renders the band's audition with the set, as the audition command does,
   and plays the band, each instrument and the drums, with the lines the command
   prints. The **bars** slider plays only the first bars; the default is all of them.
4. **Play with it**: sends the band's `bass-loop`, `loop` and `progression` to the
   engine's control port on this machine (6450), as the preset messages of
   [docs/ensemble.md](ensemble.md#ensemble-controls), then lists what is left to do by
   hand: the tempo to set in the DAW, the SFZ file of each instrument and the part its
   track receives (bass or melody), and the paths of the drum hits. A UDP message gets
   no answer, so the page cannot tell whether an engine is running: check that the
   band changes.

A set that is gone or changed on disk, or one with two sample rates, gives a message
on the page. Without `--sounds` the tab shows the bands and part 4 still sends the
controls. The tab reads folders on your machine and sends to the engine, so it is not
on the page under `--share`. The settings above the tabs and the outputs below them
belong to the other tabs and are hidden while the band tab is open (#282).

It does not yet describe the sound of a player, generate notes or hits, build
instruments, or keep or try again: generating is on the command line for now
([Generating notes](#generating-notes)); the tab gets it in a later step. It does not set levels,
effects or the tempo of the DAW, and it uploads nothing.

## Generating notes

The first part of step 4 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#284,
[ADR 0015](adr/0015-generator-files.md)): describe a sound in words and get a playable
instrument or a drum hit in a sound set, made by a model **you** installed. The toolkit
holds no model, downloads nothing and sends nothing anywhere: it runs the command you
give it and reads the WAV file the command wrote. Agents and CI never run these
commands; a person who installed a model does.

### A generator file

A generator file says how to run your model. It lives on your machine, not in the
repository. Its name is the file name (`stable-audio.json` holds `"name":
"stable-audio"`). This example is for the open weights of Stable Audio 3, run through
its `stable-audio` command from the folder where you installed it. It is the command
that was run on 2026-11-25 with the repository `Stability-AI/stable-audio-3` at
`4007b6f`, and the flags are those of that version; check them against
`stable-audio --help` of your version:

```json
{
  "format": "mpc-iml-generator",
  "format_version": 1,
  "name": "stable-audio",
  "title": "Stable Audio 3 (open weights)",
  "model": "stable-audio-3-small-sfx",
  "folder": "~/models/stable-audio",
  "command": ["uv", "run", "stable-audio", "--model", "small-sfx", "-p", "{prompt}",
              "--seed", "{seed}", "--duration", "{seconds}", "-o", "{out}"],
  "note_prompt": "TrackType: Instrument. {words}, one single note, {note}, dry, no reverb",
  "hit_prompt": "TrackType: SFX. {words}, one-shot drum hit, dry, no reverb",
  "timeout": 300
}
```

- `command` is a list of arguments and runs without a shell, with `folder` as its
  working directory: your words reach the model as one argument, whatever they hold.
  `{prompt}` and `{out}` are required; `{seed}` and `{seconds}` are optional; any
  other `{...}` is an error.
- `note_prompt` must hold `{words}` and `{note}` (a note name such as `E2` or `F#2`);
  `hit_prompt` must hold `{words}`.
- `model` is what each take records as its model. `timeout` is the seconds one take
  may run (120 by default); a take that runs longer is stopped.
- Keep `--model`: without it `stable-audio` chooses its own default model, which was
  not tried with these commands.

Run the model once on its own, outside these commands, before you use them: the first
run of a model downloads its weights (about ten minutes on 2026-11-25) and may ask you
to log in, and a take that runs past `timeout` is stopped.

Check the file:

```bash
uv run python -m mpc_iml.sounds.generate check stable-audio.json
```

### An instrument

```bash
uv run python -m mpc_iml.sounds.generate notes bass --generator stable-audio.json --words "warm round electric bass" --notes E1 A1 D2 G2 --out lofi-set --part bass --octave 1
```

`--notes` takes note names or MIDI numbers. It also takes the options of
`instrument` that say how the instrument is built and what it plays (`--prefer`,
`--release`, `--low`, `--high`, `--part`, `--keys`, `--min-velocity`, `--octave`), and:

- `--duration`: the seconds asked of each take (4 by default).
- `--takes`: takes of each note in the first round (1 by default).
- `--seed`: the first seed (1 by default); each further take of a note uses the next.
- `--rounds`: rounds of asking (3 by default).

A model often plays the note name it is asked for one octave away, and now and then a
note is not clean, so every take is measured before it is trusted. A note is
**answered** when a clean take (the threshold of `instrument`) was measured within 2
semitones of it. In each later round, a note that is not answered is asked again with
the next seed: when its closest clean take came out a whole number of octaves away, it
is asked that many octaves the other way (asked E2, measured E3: ask E1); otherwise the
same note again. A note name that would leave the keyboard is not asked.

Then the instrument is built from all the takes, as `instrument` builds it, and the
command prints one line for each take (the round, the note asked, the seed, what was
measured, and whether it was kept or why not), the notes no take answered, and the
lines `instrument` prints. A take that fails (the command ends with an error, runs past
the timeout, writes no file, or writes a file that is silent or cannot be read) is
reported with the last lines the command printed, and the other takes go on. When no
take can be used, the command ends with status 1 and the set is unchanged. Before
anything is asked of the model, the generator file, the options and the set's
`sound-set.json` are checked; a problem stops the command with status 1.

### A drum hit

```bash
uv run python -m mpc_iml.sounds.generate hit kick --generator stable-audio.json --words "dusty lo-fi kick" --out lofi-set --seconds 0.6
```

It asks for one take (`--duration`, 1 second by default; `--seed`, 1 by default) with
the generator's `hit_prompt`, and makes the hit from it as `hits` does (`--seconds` as
there).

### Takes

Takes are kept in the set, under `takes/`: `takes/<instrument>-<asked note>-s<seed>.wav`
(`#` written as `s`) and `takes/<hit>-s<seed>.wav`. In `sound-set.json` each one's
`file` names its take and its `origin` records the model, the prompt that was sent,
the seed and the settings (`generator`, the note `asked`, `seconds` and the `round`).
Generating an instrument or a hit again replaces its entry and removes the takes and
samples its earlier entry listed that no entry uses now; other instruments, the hits
and their takes are untouched. You may delete `takes/` to save space: the set still
loads, `soundset check` says how many takes are missing, but the instrument can then
not be built again from them.

A measurement catches a wrong pitch, noise and silence, not everything: **listen** to
an instrument in an SFZ player, or with the audition, before you keep a set. Nothing
generated belongs in the repository.

## Known gap

Next to a low note (under about E2), a side lobe of the analysis window can count as a
weak peak off the harmonics, about 30 dB under the strongest. It costs a clean low note
up to half a percent of `clean`, and `other` names that side lobe. The method is kept as
it is, so results stay comparable with the sound sets already played.
