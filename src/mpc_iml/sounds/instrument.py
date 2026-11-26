"""Turn recordings of single notes into one playable instrument: an SFZ file (#270).

Each recording is measured (`mpc_iml.sounds.notes`), one recording is kept for each
pitch, the silence before the note is cut, the levels are evened out, and one region is
written for each note with its measured pitch. Key ranges split halfway between
neighbouring notes. Any SFZ player can load the result.

An instrument can play only some of the notes the band sends (#274): the notes of a
range of keys, the notes hit at least so hard, and it can sound some octaves above the
notes it is sent (`soundset.Plays`). The SFZ file does that with basic opcodes only, so
it plays its share of the part without key or velocity filters in front of it.

`python -m mpc_iml.sounds.instrument <name> <file>... --out <folder>` writes
`<folder>/<name>.sfz` and the notes it uses in `<folder>/samples/`, and records the
instrument in `<folder>/sound-set.json` (#272, `mpc_iml.sounds.soundset`).
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from mpc_iml.sounds import soundset, wav
from mpc_iml.sounds.notes import Measurement, measure, note_name, note_number
from mpc_iml.sounds.soundset import Origin, Plays
from mpc_iml.sounds.wav import Samples

CLEAN = 0.985
"""A note is kept when at least this share of its energy lies on its harmonics."""
REACH = 6
"""How many semitones a note may be moved before it starts to sound wrong."""
LEAD = 32
"""Frames kept before the start of a note."""
BODY = 0.4
"""Seconds at the start of a trimmed note whose level is evened out."""
MAX_GAIN_DB = 9.0
"""The most a note's level is moved up or down."""
CEILING_DB = -1.0
"""No sample of a written note peaks above this, in dB full scale."""
FADE = 0.01
"""Seconds of fade at the end of a trimmed note."""

Prefer = Literal["clean", "rich"]


@dataclass(frozen=True)
class Note:
    """One recording and what was measured in it."""

    path: Path
    measured: Measurement


@dataclass(frozen=True)
class Region:
    """One note of the instrument: its sample and the keys it plays."""

    sample: str
    """The sample's path, relative to the SFZ file."""
    low: int
    high: int
    centre: int
    """The MIDI note the sample plays unchanged (`pitch_keycenter`)."""
    tune: int
    """Cents that bring the measured pitch onto `centre`."""
    source: Path
    """The recording the sample was made from."""
    gain_db: float
    """How much the level was moved to even it out (before the peak limit)."""


@dataclass(frozen=True)
class Instrument:
    """What `build` wrote."""

    name: str
    path: Path
    """The SFZ file."""
    regions: tuple[Region, ...]
    dropped: tuple[tuple[Path, str], ...]
    """The files left out, each with the reason."""
    uncovered: tuple[tuple[int, int], ...]
    """The stretches of keys in the span that no kept note reaches."""
    notes: tuple[Note, ...]
    """What was measured in each file that could be measured."""
    plays: Plays = Plays()
    """Which notes of the band it plays."""


def choose(
    notes: Sequence[Note], prefer: Prefer = "clean", clean: float = CLEAN
) -> tuple[list[Note], list[tuple[Note, str]]]:
    """One note for each pitch, lowest first, and the notes left out with the reason.

    A note under `clean` is left out. Of several notes at one pitch, `prefer` keeps the
    cleanest, or with `rich` the one with the most energy around harmonics 2 to 4 (a bass
    that small speakers can still play)."""
    best: dict[int, Note] = {}
    dropped: list[tuple[Note, str]] = []

    def score(note: Note) -> float:
        return note.measured.rich if prefer == "rich" else note.measured.clean

    for note in notes:
        m = note.measured
        if m.clean < clean:
            dropped.append((note, f"not clean: {100 * m.clean:.1f}% of the energy on harmonics"))
            continue
        other = best.get(m.note)
        if other is None:
            best[m.note] = note
            continue
        winner, loser = (note, other) if score(note) > score(other) else (other, note)
        best[m.note] = winner
        better = "richer" if prefer == "rich" else "cleaner"
        dropped.append((loser, f"another take of {m.name} is {better}"))
    return [best[key] for key in sorted(best)], dropped


def key_ranges(centres: Sequence[int]) -> list[tuple[int, int]]:
    """The keys each note plays: the ranges split halfway between neighbouring notes, and
    the lowest and highest notes reach to the ends of the keyboard. `centres` is sorted."""
    ranges = []
    for i, centre in enumerate(centres):
        low = 0 if i == 0 else (centres[i - 1] + centre) // 2 + 1
        high = 127 if i == len(centres) - 1 else (centre + centres[i + 1]) // 2
        ranges.append((low, high))
    return ranges


def uncovered(
    centres: Sequence[int], low: int, high: int, reach: int = REACH
) -> list[tuple[int, int]]:
    """The stretches of keys between `low` and `high` that are more than `reach` semitones
    from every note in `centres`."""
    gaps: list[tuple[int, int]] = []
    for key in range(low, high + 1):
        if any(abs(key - centre) <= reach for centre in centres):
            continue
        if gaps and gaps[-1][1] == key - 1:
            gaps[-1] = (gaps[-1][0], key)
        else:
            gaps.append((key, key))
    return gaps


def _body_level(samples: Samples, rate: int) -> float:
    body = samples[: int(BODY * rate)].mean(axis=1)
    return float(np.sqrt((body**2).mean()))


def trim(samples: Samples, rate: int, start: int) -> Samples:
    """`samples` from `LEAD` frames before `start`, with a 10 ms fade at the end."""
    cut = samples[max(0, start - LEAD) :].copy()
    fade = min(int(FADE * rate), len(cut))
    cut[len(cut) - fade :] *= np.linspace(1, 0, fade, dtype=np.float32)[:, None]
    return cut


def describe(plays: Plays) -> str:
    """What an instrument plays, in words; empty with the defaults."""
    said = []
    if plays.part is not None:
        said.append(f"the {plays.part} part")
    if plays.keys != (0, 127):
        low, high = plays.keys
        said.append(f"keys {note_name(low)} to {note_name(high)} ({low}-{high})")
    if plays.min_velocity > 1:
        said.append(f"notes hit at velocity {plays.min_velocity} or more")
    if plays.octave:
        count = abs(plays.octave)
        way = "above" if plays.octave > 0 else "below"
        said.append(f"{count} octave{'s' if count > 1 else ''} {way} the notes it is sent")
    return ", ".join(said)


def sfz_text(
    name: str, regions: Sequence[Region], release: float, plays: Plays | None = None
) -> str:
    """The SFZ file for `regions`. With `plays.min_velocity` above 1 the `<global>` line
    holds `lovel`; the keys and the octave are already in `regions`."""
    plays = plays or Plays()
    lovel = f" lovel={plays.min_velocity}" if plays.min_velocity > 1 else ""
    said = describe(plays)
    lines = [
        f"// {name}: one region for each recorded note.",
        "// pitch_keycenter and tune come from the measured pitch of each note.",
        *([f"// plays {said}."] if said else []),
        f"<global> ampeg_attack=0.002 ampeg_release={release:.2f} amp_veltrack=85{lovel}",
        "",
    ]
    lines += [
        f"<region> sample={r.sample} lokey={r.low} hikey={r.high} "
        f"pitch_keycenter={r.centre} tune={r.tune}"
        for r in regions
    ]
    return "\n".join(lines) + "\n"


def build(
    name: str,
    files: Sequence[Path],
    out: Path,
    *,
    prefer: Prefer = "clean",
    release: float = 0.25,
    clean: float = CLEAN,
    span: tuple[int, int] | None = None,
    origins: Mapping[Path, Origin] | None = None,
    part: Literal["bass", "melody"] | None = None,
    keys: tuple[int, int] = (0, 127),
    min_velocity: int = 1,
    octave: int = 0,
) -> Instrument:
    """Write the instrument `name` from the recordings in `files` into the folder `out`,
    and record it in `out/sound-set.json`.

    `part`, `keys`, `min_velocity` and `octave` say which notes of the band it plays
    (`soundset.Plays`). Each kept note's centre is moved down by `octave` octaves, the
    key ranges are split between the moved centres and then cut to `keys`; a note whose
    range falls outside `keys` is left out with the reason. `span` is the lowest and
    highest key the part plays, in notes the band sends; the result lists the keys in
    both `span` and `keys` that no note with a region reaches. `origins` gives where a
    recording came from, by its path in `files`. The entry of an instrument built before
    under `name` is replaced, and the samples it listed that the new one does not use
    are removed. Raises `ValueError` when `name` is not a name, a value of what it plays
    is out of range, `octave` moves a kept note off the keyboard or no recording can be
    used, and `SoundSetError` when the folder's `sound-set.json` cannot be accepted;
    nothing is written then."""
    soundset.check_name(name)
    plays = Plays(part, keys, min_velocity, octave).check()
    document = soundset.read_document(out)
    notes: list[Note] = []
    unreadable: list[tuple[Path, str]] = []
    audio: dict[Path, tuple[Samples, int]] = {}
    for path in files:
        try:
            audio[path] = wav.read(path)
            notes.append(Note(path, measure(*audio[path])))
        except (OSError, ValueError) as error:
            unreadable.append((path, str(error)))
    kept, dropped = choose(notes, prefer, clean)
    if not kept:
        raise ValueError(f"{name}: none of the {len(files)} recordings can be used")
    shift = 12 * octave
    for note in kept:
        if not 0 <= note.measured.note - shift <= 127:
            raise ValueError(
                f"{name}: octave {octave:+d} moves {note.measured.name} "
                f"({note.measured.note}) to {note.measured.note - shift}, off the keyboard"
            )
    lowest, highest = keys
    ranges: list[tuple[int, int]] = []
    playing: list[Note] = []
    cut: list[tuple[Note, str]] = []
    for note, (low, high) in zip(
        kept, key_ranges([n.measured.note - shift for n in kept]), strict=True
    ):
        if high < lowest or low > highest:
            cut.append(
                (
                    note,
                    f"it would play keys {low} to {high}, outside the keys the "
                    f"instrument plays, {note_name(lowest)} to {note_name(highest)} "
                    f"({lowest}-{highest})",
                )
            )
            continue
        playing.append(note)
        ranges.append((max(low, lowest), min(high, highest)))
    dropped += cut
    kept = playing  # never empty: the ranges together cover every key

    trimmed = [trim(audio[n.path][0], audio[n.path][1], n.measured.start) for n in kept]
    rates = [audio[n.path][1] for n in kept]
    levels = [_body_level(x, rate) for x, rate in zip(trimmed, rates, strict=True)]
    target = float(np.median(levels))
    centres = [n.measured.note - shift for n in kept]
    samples_dir = out / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    most = 10 ** (MAX_GAIN_DB / 20)
    ceiling = 10 ** (CEILING_DB / 20)
    regions = []
    for note, x, rate, level, (low, high) in zip(kept, trimmed, rates, levels, ranges, strict=True):
        gain = float(np.clip(target / max(level, 1e-9), 1 / most, most))
        x = x * np.float32(gain)
        peak = float(np.abs(x).max())
        if peak > ceiling:
            x = x * np.float32(ceiling / peak)
        file_name = f"{name}-{note.measured.name.replace('#', 's')}.wav"
        wav.write(samples_dir / file_name, x, rate)
        regions.append(
            Region(
                sample=f"samples/{file_name}",
                low=low,
                high=high,
                centre=note.measured.note - shift,
                tune=-round(note.measured.cents),
                source=note.path,
                gain_db=20 * float(np.log10(gain)),
            )
        )
    path = out / f"{name}.sfz"
    path.write_text(sfz_text(name, regions, release, plays), encoding="utf-8")
    reach = (max(span[0], lowest), min(span[1], highest)) if span else None
    instrument = Instrument(
        name=name,
        path=path,
        regions=tuple(regions),
        dropped=tuple([(n.path, why) for n, why in dropped] + unreadable),
        uncovered=tuple(uncovered(centres, *reach) if reach and reach[0] <= reach[1] else []),
        notes=tuple(notes),
        plays=plays,
    )
    settings = {"prefer": prefer, "release": release, "clean": clean}
    _record(out, document, instrument, files, settings, span, origins or {})
    return instrument


def set_entry(
    instrument: Instrument,
    files: Sequence[Path],
    settings: Mapping[str, float | str],
    span: tuple[int, int] | None,
    origins: Mapping[Path, Origin],
) -> dict[str, object]:
    """The entry of `instrument` in `sound-set.json`: one entry for each of `files`, with
    what was measured in it and its region or why it was left out."""
    measured = {n.path: n.measured for n in instrument.notes}
    used = {r.source: r for r in instrument.regions}
    why = dict(instrument.dropped)
    entries: list[dict[str, object]] = []
    for path in files:
        entry: dict[str, object] = {"file": path.name}
        if path in measured:
            values = asdict(measured[path])
            if values["other"] is not None:
                values["other"] = list(values["other"])
            entry["measured"] = values
        if path in used:
            region = used[path]
            entry["region"] = {
                "sample": region.sample,
                "low": region.low,
                "high": region.high,
                "centre": region.centre,
                "tune": region.tune,
                "gain_db": region.gain_db,
            }
        else:
            entry["left_out"] = why[path]
        if path in origins:
            entry["origin"] = origins[path].to_json()
        entries.append(entry)
    return {
        "sfz": instrument.path.name,
        "settings": dict(settings),
        "plays": instrument.plays.to_json(),
        "span": list(span) if span else None,
        "uncovered": [list(gap) for gap in instrument.uncovered],
        "files": entries,
    }


def _samples_of(entry: Mapping[str, object]) -> set[str]:
    files = entry.get("files", [])
    assert isinstance(files, list)
    return {f["region"]["sample"] for f in files if "region" in f}


def _record(
    out: Path,
    document: dict[str, object],
    instrument: Instrument,
    files: Sequence[Path],
    settings: Mapping[str, float | str],
    span: tuple[int, int] | None,
    origins: Mapping[Path, Origin],
) -> None:
    """Add or replace the entry of `instrument` in `document`, write it, and remove the
    samples the earlier entry listed that no entry uses now."""
    instruments = document["instruments"]
    assert isinstance(instruments, dict)
    before = _samples_of(instruments.get(instrument.name, {}))
    instruments[instrument.name] = set_entry(instrument, files, settings, span, origins)
    soundset.write_document(out, document)
    hits = document["hits"]
    assert isinstance(hits, dict)
    still = {h["sample"] for h in hits.values()}
    for entry in instruments.values():
        still |= _samples_of(entry)
    for sample in sorted(before - still):
        (out / sample).unlink(missing_ok=True)


def report(instrument: Instrument) -> str:
    """What `build` did: what it plays when that is not every note, then one line for
    each region, file left out and stretch of keys."""
    said = describe(instrument.plays)
    lines = [f"{instrument.name}: plays {said}"] if said else []
    lines += [
        f"{instrument.name}: {r.sample:<24} keys {r.low:>3}-{r.high:<3} centre {r.centre:>3} "
        f"({note_name(r.centre)})  tune {r.tune:+d}  level {r.gain_db:+.1f} dB  "
        f"from {r.source.name}"
        for r in instrument.regions
    ]
    lines += [f"{instrument.name}: left out {p.name}: {why}" for p, why in instrument.dropped]
    lines += [
        f"{instrument.name}: no note within {REACH} semitones of "
        f"{note_name(low)} to {note_name(high)}"
        for low, high in instrument.uncovered
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.sounds.instrument",
        description=(__doc__ or "").split("\n\n")[0],
    )
    parser.add_argument("name", help="the instrument's name, used for the file names")
    parser.add_argument("files", nargs="+", type=Path, help="WAV recordings of single notes")
    parser.add_argument("--out", type=Path, required=True, help="the folder to write into")
    parser.add_argument(
        "--prefer",
        choices=["clean", "rich"],
        default="clean",
        help="of several takes of one pitch, keep the cleanest (default) or the richest",
    )
    parser.add_argument("--release", type=float, default=0.25, help="release time in seconds")
    parser.add_argument("--low", help="the lowest note the part plays, for example E1")
    parser.add_argument("--high", help="the highest note the part plays, for example G3")
    parser.add_argument(
        "--part", choices=["bass", "melody"], help="the part of the band the instrument plays"
    )
    parser.add_argument(
        "--keys",
        nargs=2,
        metavar=("LOW", "HIGH"),
        help="play only the notes from LOW to HIGH, for example C5 G9 (default: all keys)",
    )
    parser.add_argument(
        "--min-velocity",
        type=int,
        default=1,
        help="play only the notes hit at least this hard, 1 to 127 (default 1)",
    )
    parser.add_argument(
        "--octave",
        type=int,
        default=0,
        help="sound this many octaves above the notes sent, -4 to 4 (default 0)",
    )
    args = parser.parse_args(argv)
    if (args.low is None) != (args.high is None):
        parser.error("give both --low and --high, or neither")
    try:
        span = (note_number(args.low), note_number(args.high)) if args.low else None
        keys = (note_number(args.keys[0]), note_number(args.keys[1])) if args.keys else (0, 127)
        Plays(args.part, keys, args.min_velocity, args.octave).check()
    except ValueError as error:
        parser.error(str(error))
    try:
        instrument = build(
            args.name,
            args.files,
            args.out,
            prefer=args.prefer,
            release=args.release,
            span=span,
            part=args.part,
            keys=keys,
            min_velocity=args.min_velocity,
            octave=args.octave,
        )
    except ValueError as error:
        print(error)
        return 1
    print(report(instrument))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
