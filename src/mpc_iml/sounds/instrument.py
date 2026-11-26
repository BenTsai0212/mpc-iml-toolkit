"""Turn recordings of single notes into one playable instrument: an SFZ file (#270).

Each recording is measured (`mpc_iml.sounds.notes`), one recording is kept for each
pitch, the silence before the note is cut, the levels are evened out, and one region is
written for each note with its measured pitch. Key ranges split halfway between
neighbouring notes. Any SFZ player can load the result.

`python -m mpc_iml.sounds.instrument <name> <file>... --out <folder>` writes
`<folder>/<name>.sfz` and the notes it uses in `<folder>/samples/`.
"""

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from mpc_iml.sounds import wav
from mpc_iml.sounds.notes import Measurement, measure, note_name, note_number
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


def sfz_text(name: str, regions: Sequence[Region], release: float) -> str:
    """The SFZ file for `regions`."""
    lines = [
        f"// {name}: one region for each recorded note.",
        "// pitch_keycenter and tune come from the measured pitch of each note.",
        f"<global> ampeg_attack=0.002 ampeg_release={release:.2f} amp_veltrack=85",
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
) -> Instrument:
    """Write the instrument `name` from the recordings in `files` into the folder `out`.

    `span` is the lowest and highest key the part plays; the result lists the keys in it
    that no kept note reaches. Raises `ValueError` when no recording can be used."""
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

    trimmed = [trim(audio[n.path][0], audio[n.path][1], n.measured.start) for n in kept]
    rates = [audio[n.path][1] for n in kept]
    levels = [_body_level(x, rate) for x, rate in zip(trimmed, rates, strict=True)]
    target = float(np.median(levels))
    centres = [n.measured.note for n in kept]
    samples_dir = out / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    most = 10 ** (MAX_GAIN_DB / 20)
    ceiling = 10 ** (CEILING_DB / 20)
    regions = []
    for note, x, rate, level, (low, high) in zip(
        kept, trimmed, rates, levels, key_ranges(centres), strict=True
    ):
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
                centre=note.measured.note,
                tune=-round(note.measured.cents),
                source=note.path,
                gain_db=20 * float(np.log10(gain)),
            )
        )
    path = out / f"{name}.sfz"
    path.write_text(sfz_text(name, regions, release), encoding="utf-8")
    return Instrument(
        name=name,
        path=path,
        regions=tuple(regions),
        dropped=tuple([(n.path, why) for n, why in dropped] + unreadable),
        uncovered=tuple(uncovered(centres, *span) if span else []),
        notes=tuple(notes),
    )


def report(instrument: Instrument) -> str:
    """What `build` did, one line for each region, file left out and stretch of keys."""
    lines = [
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
    args = parser.parse_args(argv)
    if (args.low is None) != (args.high is None):
        parser.error("give both --low and --high, or neither")
    try:
        span = (note_number(args.low), note_number(args.high)) if args.low else None
    except ValueError as error:
        parser.error(str(error))
    try:
        instrument = build(
            args.name, args.files, args.out, prefer=args.prefer, release=args.release, span=span
        )
    except ValueError as error:
        print(error)
        return 1
    print(report(instrument))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
