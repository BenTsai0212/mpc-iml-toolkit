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

## Sound sets

The last part of step 1 (#272, [ADR 0013](adr/0013-sound-set-folders.md)): a folder
that holds the instruments and drum hits made for one band is a **sound set**:

```text
<folder>/
  sound-set.json
  <instrument>.sfz
  samples/<instrument>-<note>.wav
  hits/<hit>.wav
```

`sound-set.json` records what the set holds. For each instrument: its SFZ file, the
settings it was built with (`prefer`, `release`, `clean`), what it plays (`plays`:
`part`, `keys`, `min_velocity`, `octave`), the span and the keys no note reaches, and for every source recording what was measured in it and its region,
or why it was left out. For each hit: its sample, the recording it was cut from, its
length and how much its level was moved. Source recordings are named by file name
only and are not copied into the set, so the folder can be moved or shared.

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

## Known gap

Next to a low note (under about E2), a side lobe of the analysis window can count as a
weak peak off the harmonics, about 30 dB under the strongest. It costs a clean low note
up to half a percent of `clean`, and `other` names that side lobe. The method is kept as
it is, so results stay comparable with the sound sets already played.
