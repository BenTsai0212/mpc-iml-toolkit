"""Hear a band with a sound set, without the DAW (#278, RFC 0006 step 2).

The band's audition pattern goes through `ensemble` offline (`webdemo.sim.simulate`
with the band's grid, content and tempo), and what the band plays is rendered with the
instruments and drum hits of a sound set. Which instrument plays which note comes from
the set: an instrument plays a note of its part when the note is inside one of its
regions and hit at least at its `min_velocity` (what its SFZ file says). The song's
`bass` notes are the bass part and its `keys` notes the melody part; several
instruments may play one note.

A note plays its region's sample moved by the note minus `centre` in semitones plus
`tune` in cents, resampled with linear interpolation, with a 2 ms attack; it plays until
the note ends and then fades over the instrument's release, and a sample that ends
earlier just ends. A new note of the same pitch in the same instrument ends the one
before. Its level is full at velocity 127 and `VELOCITY_DB` lower at 0, in a straight
line in dB. The `kick`, `snare` and `hat` hits of the song play the set's hits of those
names with the same law. Nothing is mixed: one gain brings the whole band to a peak of
`PEAK_DB`, and each part keeps that gain, so the parts add up to the band.

    python -m mpc_iml.sounds.audition <band> <sound set folder> --out <folder> [--bars <n>]

writes 24-bit WAV files: `<instrument>.wav` for each instrument that plays a part,
`drums.wav` and `band.wav`.
"""

import argparse
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from mpc_iml.bands import DRUMS, Band, load_bands
from mpc_iml.plays import PARTS
from mpc_iml.sounds import soundset, wav
from mpc_iml.sounds.soundset import SetInstrument, SoundSet, SoundSetError
from mpc_iml.sounds.wav import Samples
from mpc_iml.webdemo import sim

__all__ = [
    "ATTACK",
    "PEAK_DB",
    "SONG_PARTS",
    "VELOCITY_DB",
    "Audition",
    "AuditionError",
    "Played",
    "audition",
    "level",
    "main",
    "play",
    "played",
    "rate_of",
    "render_hits",
    "release_of",
    "report",
    "render_notes",
]

ATTACK = 0.002
"""Seconds of the attack of every note."""
VELOCITY_DB = 16.0
"""How much lower a note at velocity 0 is than one at 127, in dB."""
PEAK_DB = -1.0
"""The peak of `band.wav`, in dB full scale."""
SONG_PARTS = {"bass": "bass", "keys": "melody"}
"""The part of the band each part of the song (`webdemo.sim.Note.part`) is."""
CHANNELS = 2
"""The files are stereo; a mono sample plays in both channels."""


Cache = dict[Path, tuple[Samples, int]]
"""Samples already read, by path, so a sample is read once in one audition."""


class AuditionError(ValueError):
    """A band or a set that cannot be auditioned."""


@dataclass(frozen=True)
class Played:
    """A note or a hit to render: when it starts and how long it is held, in seconds."""

    start: float
    seconds: float
    pitch: int
    velocity: int


@dataclass(frozen=True)
class Audition:
    """What `audition` rendered: one array for each instrument that plays a part, the
    drums and the band, all with the same `gain` and length."""

    rate: int
    gain: float
    instruments: Mapping[str, Samples]
    drums: Samples
    band: Samples
    skipped: tuple[str, ...] = ()
    """The instruments that play no part (`part` is `null`)."""
    unplayed: Mapping[str, int] = field(default_factory=dict)
    """For each part, how many of its notes no instrument played."""
    silent: tuple[str, ...] = ()
    """The drums the set has no hit for."""


def level(velocity: int) -> float:
    """The gain of a note at `velocity`: 1 at 127, `VELOCITY_DB` lower at 0."""
    return float(10 ** (-VELOCITY_DB * (127 - velocity) / 127 / 20))


def rate_of(sound_set: SoundSet, cache: Cache | None = None) -> int:
    """The sample rate every sample of the set has. Raises `AuditionError` naming the
    rates and a sample of each when they differ, or when the set has no sample."""
    cache = {} if cache is None else cache
    found: dict[int, str] = {}
    paths = [r.sample for i in sound_set.instruments.values() for r in i.regions]
    paths += [h.sample for h in sound_set.hits.values()]
    for path in paths:
        found.setdefault(_read(path, cache)[1], str(path.relative_to(sound_set.folder)))
    if not found:
        raise AuditionError(f"{sound_set.folder}: the set has no samples")
    if len(found) > 1:
        rates = " and ".join(f"{rate} Hz ({path})" for rate, path in sorted(found.items()))
        raise AuditionError(f"the samples of the set must share one sample rate, not {rates}")
    return next(iter(found))


def _read(path: Path, cache: Cache) -> tuple[Samples, int]:
    if path not in cache:
        cache[path] = wav.read(path)
    return cache[path]


def _stereo(samples: Samples) -> Samples:
    return np.repeat(samples, CHANNELS, axis=1) if samples.shape[1] == 1 else samples


def _plays(instrument: SetInstrument, pitch: int, velocity: int) -> list[soundset.SetRegion]:
    if velocity < instrument.plays.min_velocity:
        return []
    return [r for r in instrument.regions if r.low <= pitch <= r.high]


def release_of(instrument: SetInstrument) -> float:
    """The release of `instrument`, in seconds, from the settings it was built with."""
    return float(instrument.settings.get("release", 0.0))


def render_notes(
    instrument: SetInstrument,
    notes: Sequence[Played],
    rate: int,
    frames: int,
    cache: Cache | None = None,
) -> Samples:
    """`notes` played by `instrument` as `frames` stereo frames at `rate`, without a
    gain for the band. A note the instrument does not play is silent."""
    cache = {} if cache is None else cache
    out = np.zeros((frames, CHANNELS), dtype=np.float32)
    release = round(release_of(instrument) * rate)
    attack = max(round(ATTACK * rate), 1)
    ordered = sorted(notes, key=lambda n: n.start)
    for i, note in enumerate(ordered):
        start = round(note.start * rate)
        held = round((note.start + note.seconds) * rate) - start
        later = [n.start for n in ordered[i + 1 :] if n.pitch == note.pitch]
        if later:
            held = min(held, round(later[0] * rate) - start)
        held = max(held, 0)
        for region in _plays(instrument, note.pitch, note.velocity):
            sample = _stereo(_read(region.sample, cache)[0])
            ratio = 2 ** ((note.pitch - region.centre) / 12 + region.tune / 1200)
            count = min(
                held + release,
                frames - start,
                int((len(sample) - 1) / ratio) + 1 if len(sample) else 0,
            )
            if count <= 0:
                continue
            at = np.arange(count) * ratio
            moved = np.stack(
                [np.interp(at, np.arange(len(sample)), sample[:, c]) for c in range(CHANNELS)],
                axis=1,
            )
            n = np.arange(count)
            envelope = np.minimum(1.0, (n + 1) / attack)
            if release:
                envelope *= np.clip(1.0 - (n - held) / release, 0.0, 1.0)
            else:
                envelope = np.where(n < held, envelope, 0.0)
            gain = envelope * level(note.velocity)
            out[start : start + count] += (moved * gain[:, None]).astype(np.float32)
    return out


def render_hits(
    sound_set: SoundSet,
    hits: Mapping[str, Sequence[Played]],
    rate: int,
    frames: int,
    cache: Cache | None = None,
) -> Samples:
    """The hits of each drum (by name) played with the set's hit of that name, as
    `frames` stereo frames at `rate`. A drum without a hit in the set is silent."""
    cache = {} if cache is None else cache
    out = np.zeros((frames, CHANNELS), dtype=np.float32)
    for drum, played in hits.items():
        if drum not in sound_set.hits:
            continue
        sample = _stereo(_read(sound_set.hits[drum].sample, cache)[0])
        for hit in played:
            start = round(hit.start * rate)
            count = min(len(sample), frames - start)
            if count > 0:
                out[start : start + count] += sample[:count] * np.float32(level(hit.velocity))
    return out


def play(band: Band, bars: int | None = None) -> sim.Song:
    """What the band plays for its audition pattern, or its first `bars` bars."""
    grid = band.grid()[:bars] if bars is not None else band.grid()
    c = band.content
    settings = sim.Settings(
        tempo=band.tempo, progression=c["progression"], bass_loop=c["bass_loop"], loop=c["loop"]
    )
    return sim.simulate(grid, settings)


def played(song: sim.Song) -> dict[str, list[Played]]:
    """The notes of `song` in seconds, by part of the band (`bass`, `melody`) and by
    drum (`kick`, `snare`, `hat`)."""
    out: dict[str, list[Played]] = {name: [] for name in (*PARTS, *DRUMS)}
    tick = song.seconds_per_tick
    for note in song.notes:
        name = SONG_PARTS.get(note.part, note.part)
        if name in out:
            out[name].append(Played(note.tick * tick, note.ticks * tick, note.pitch, note.velocity))
    return out


def audition(song: sim.Song, sound_set: SoundSet) -> Audition:
    """`song` rendered with `sound_set`. Raises `AuditionError` when the samples of the
    set have two sample rates, or an instrument that plays a part is named `drums` or
    `band`."""
    cache: Cache = {}
    rate = rate_of(sound_set, cache)
    notes = played(song)
    playing = {n: i for n, i in sound_set.instruments.items() if i.plays.part is not None}
    for name in playing:
        if name in ("drums", "band"):
            raise AuditionError(f"an instrument is named {name!r}: {name}.wav is the {name}")
    longest = max((release_of(i) for i in playing.values()), default=0.0)
    frames = round(song.seconds * rate) + round(longest * rate)
    tracks = {
        name: render_notes(i, notes[str(i.plays.part)], rate, frames, cache)
        for name, i in playing.items()
    }
    drums = render_hits(sound_set, {d: notes[d] for d in DRUMS}, rate, frames, cache)
    band = drums.copy()
    for track in tracks.values():
        band += track
    peak = float(np.abs(band).max()) if band.size else 0.0
    gain = 10 ** (PEAK_DB / 20) / peak if peak > 0 else 1.0
    unplayed = {
        part: sum(
            1
            for n in notes[part]
            if not any(
                _plays(i, n.pitch, n.velocity) for i in playing.values() if i.plays.part == part
            )
        )
        for part in PARTS
    }
    scale = np.float32(gain)
    return Audition(
        rate=rate,
        gain=gain,
        instruments={name: track * scale for name, track in tracks.items()},
        drums=drums * scale,
        band=band * scale,
        skipped=tuple(n for n, i in sound_set.instruments.items() if i.plays.part is None),
        unplayed=unplayed,
        silent=tuple(d for d in DRUMS if d not in sound_set.hits),
    )


def report(band: Band, sound_set: SoundSet, result: Audition) -> list[str]:
    """What the command prints before the files: the players without an instrument
    of their name, the instruments skipped, the notes no instrument played and the drums
    without a hit."""
    lines = [
        f"{band.name}: player {p.name!r} has no instrument of its name in the set"
        for p in band.players
        if p.name not in sound_set.instruments
    ]
    lines += [f"{name}: plays no part (part is null), skipped" for name in result.skipped]
    lines += [
        f"{part}: {count} note(s) no instrument played" for part, count in result.unplayed.items()
    ]
    lines += [f"{drum}: no hit in the set, silent" for drum in result.silent]
    return lines


def _band(name: str) -> Band:
    bands = load_bands()
    if name not in bands:
        raise AuditionError(f"no built-in band {name!r}; bands: {', '.join(bands)}")
    return bands[name]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.sounds.audition",
        description="Render a built-in band's audition with a sound set.",
    )
    parser.add_argument("band", help="the name of a built-in band (python -m mpc_iml.bands list)")
    parser.add_argument("folder", type=Path, help="the sound set folder")
    parser.add_argument("--out", type=Path, required=True, help="the folder to write into")
    parser.add_argument("--bars", type=int, help="play only the first bars of the audition")
    args = parser.parse_args(argv)
    try:
        band = _band(args.band)
        if args.bars is not None and not 1 <= args.bars <= len(band.audition):
            raise AuditionError(f"--bars must be 1-{len(band.audition)}, got {args.bars}")
        sound_set = soundset.load(args.folder)
        result = audition(play(band, args.bars), sound_set)
    except (AuditionError, SoundSetError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for line in report(band, sound_set, result):
        print(line)
    args.out.mkdir(parents=True, exist_ok=True)
    files = {**result.instruments, "drums": result.drums, "band": result.band}
    seconds = len(result.band) / result.rate
    for name, samples in files.items():
        path = args.out / f"{name}.wav"
        wav.write(path, samples, result.rate)
        print(f"wrote {path} ({seconds:.2f} s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
