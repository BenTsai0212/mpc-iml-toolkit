# Measuring notes

English | [繁體中文](sounds.zh-TW.md)

The first part of step 1 of [RFC 0006](rfcs/0006-sounds-for-the-band.md) (#268):
find out what a recording of a single note really holds before it becomes part of a
kit. A model that generates single notes cannot be trusted to play the pitch it was
asked for: the note name is usually right, but the octave is often wrong, and some
notes are not clean. Building an instrument from the measured notes is a later Issue.

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

## Known gap

Next to a low note (under about E2), a side lobe of the analysis window can count as a
weak peak off the harmonics, about 30 dB under the strongest. It costs a clean low note
up to half a percent of `clean`, and `other` names that side lobe. The method is kept as
it is, so results stay comparable with the kits already played.

## Notes

RFC 0006 names `soundfile` as an optional dependency for reading audio. This step reads
WAV files without it, so no dependency is added.
