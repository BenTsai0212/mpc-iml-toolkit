# Measuring notes and building instruments

English | [繁體中文](sounds.zh-TW.md)

The first part of step 1 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#268):
find out what a recording of a single note really holds before it becomes part of a
sound set. A model that generates single notes cannot be trusted to play the pitch it
was asked for: in the first notes made this way the note name was always right, but
the octave was wrong for several of them, and two notes were not clean. The second part (#270) builds an instrument from the measured notes: see
[Build an instrument](#build-an-instrument).

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

## Known gap

Next to a low note (under about E2), a side lobe of the analysis window can count as a
weak peak off the harmonics, about 30 dB under the strongest. It costs a clean low note
up to half a percent of `clean`, and `other` names that side lobe. The method is kept as
it is, so results stay comparable with the sound sets already played.
