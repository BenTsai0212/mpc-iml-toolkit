"""Progression files for `ensemble`: the format, its validation and loading (#236,
ADR 0011).

A progression file holds one chord progression, so musicians can add chords as data
instead of Python. Roots are semitones above the tonic; a chord lasts `bars` bars:

    {"format": "mpc-iml-progression", "format_version": 1, "name": "minor-two",
     "preset": "ensemble", "tonic": "A",
     "chords": [{"root": 0, "quality": "m7", "bars": 2},
                {"root": 8, "quality": "maj7", "bars": 2}]}

Loop notes are chord tones (ADR 0010), so any loop plays on any progression. The
whole progression is 1, 2, 4 or 8 bars long, so it lines up with the 4-bar phrase.

Progression files are a content kind next to loops: packages declare them through
the `mpc_iml.content` entry point group, under `<root>/progressions/ensemble/<name>.json`.
`load_progressions` reads every entry, built-in content (the `mpc_iml` package) first.

    python -m mpc_iml.progressions check <file>…
    python -m mpc_iml.progressions list
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from mpc_iml.content import CONTENT_GROUP, Content, ContentError, _fail, _header, _load_entry, _read
from mpc_iml.melody import QUALITIES

__all__ = [
    "CHORD_BARS",
    "DEFAULT",
    "FIRST",
    "KIND",
    "LENGTHS",
    "MAX_CHORDS",
    "NAMES",
    "PRESET",
    "PROGRESSION_FORMAT",
    "Chord",
    "Progression",
    "chord_names",
    "load_progressions",
    "main",
    "parse_progression",
]

PROGRESSION_FORMAT = "mpc-iml-progression"
PRESET = "ensemble"
"""The preset progression files belong to."""
KIND = "progressions"
"""The content folder of progression files: `<root>/progressions/ensemble/`."""
DEFAULT = "minor-two"
"""The progression `ensemble` starts with."""
FIRST = ("minor-two", "minor-four")
"""The built-in progressions listed first, in this order; the others follow by name."""
MAX_CHORDS = 8
CHORD_BARS = (1, 4)
"""The shortest and longest chord, in bars."""
LENGTHS = (1, 2, 4, 8)
"""The lengths a whole progression may have, in bars."""
NAMES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
"""The name of each pitch class, as chords are printed."""
_LETTERS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTALS = {"": 0, "#": 1, "b": -1}
_TOP = {"format", "format_version", "name", "title", "description", "preset", "tonic", "chords"}
_CHORD = ("root", "quality", "bars")


@dataclass(frozen=True)
class Chord:
    """`root` in semitones above the progression's tonic; `quality` (a key of
    `melody.QUALITIES`) for the chord tones; `bars` how long it lasts."""

    root: int
    quality: str
    bars: int = 1


@dataclass(frozen=True)
class Progression:
    """A fixed chord progression: `tonic` is a pitch class (0 is C)."""

    name: str
    tonic: int
    chords: tuple[Chord, ...]
    title: str = ""
    description: str = ""
    origin: str = ""

    @property
    def bars(self) -> int:
        """The length of the whole progression, in bars."""
        return sum(chord.bars for chord in self.chords)

    def chord(self, bar: int) -> Chord:
        """The chord of `bar` (0-based from song start); bar 0 for a negative bar."""
        left = max(bar, 0) % self.bars
        for chord in self.chords:
            if left < chord.bars:
                return chord
            left -= chord.bars
        raise AssertionError("unreachable: the chords fill the progression")

    def root_note(self, bar: int, octave: int) -> int:
        """The MIDI note of the chord root of `bar` in `octave` (A1 is 33)."""
        return 12 * (octave + 1) + (self.tonic + self.chord(bar).root) % 12


def chord_names(progression: Progression) -> str:
    """The chords by name and length, for example `Am7 (2) Fmaj7 (2)`."""
    return " ".join(
        f"{NAMES[(progression.tonic + c.root) % 12]}{c.quality} ({c.bars})"
        for c in progression.chords
    )


def _whole(value: Any, origin: str, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(origin, f"{what} must be a whole number, got {value!r}")
    if not low <= value <= high:
        raise _fail(origin, f"{what} must be {low}-{high}, got {value!r}")
    return value


def _tonic(value: Any, origin: str) -> int:
    letter, accidental = (value[:1], value[1:]) if isinstance(value, str) else ("", "")
    if letter not in _LETTERS or accidental not in _ACCIDENTALS:
        raise _fail(origin, f"tonic must be a note name C-B with an optional # or b, got {value!r}")
    return (_LETTERS[letter] + _ACCIDENTALS[accidental]) % 12


def _chord(data: Any, origin: str, where: str) -> Chord:
    if not isinstance(data, dict):
        raise _fail(origin, f"{where}: a chord is an object, got {data!r}")
    unknown = sorted(set(data) - set(_CHORD))
    if unknown:
        raise _fail(origin, f"{where}: unknown field {unknown[0]!r}; fields: {', '.join(_CHORD)}")
    for field in ("root", "quality"):
        if field not in data:
            raise _fail(origin, f"{where}: {field} is required")
    quality = data["quality"]
    if quality not in QUALITIES:
        allowed = ", ".join(QUALITIES)
        raise _fail(origin, f"{where}: quality must be one of {allowed}, got {quality!r}")
    root = _whole(data["root"], origin, f"{where}: root", 0, 11)
    bars = _whole(data.get("bars", 1), origin, f"{where}: bars", *CHORD_BARS)
    return Chord(root, quality, bars)


def parse_progression(data: Any, origin: str = "progression") -> Progression:
    """Validate a progression file's JSON object; raises `ContentError` naming
    `origin` and the chord, for example `lofi.json: chords[2]: quality must be …`."""
    name, title, description = _header(data, PROGRESSION_FORMAT, origin, PRESET)
    unknown = sorted(set(data) - _TOP)
    if unknown:
        raise _fail(origin, f"unknown field {unknown[0]!r}")
    tonic = _tonic(data.get("tonic"), origin)
    entries = data.get("chords")
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_CHORDS:
        raise _fail(origin, f"chords must be a list of 1-{MAX_CHORDS} chords")
    chords = tuple(_chord(entry, origin, f"chords[{i}]") for i, entry in enumerate(entries))
    progression = Progression(name, tonic, chords, title, description, origin)
    if progression.bars not in LENGTHS:
        lengths = ", ".join(map(str, LENGTHS))
        raise _fail(origin, f"the chords must last {lengths} bars in all, got {progression.bars}")
    return progression


def _built_in(content: Content) -> bool:
    return content.root.partition(":")[0] == "mpc_iml"


def _order(progression: Progression) -> tuple[int, str]:
    name = progression.name
    return (FIRST.index(name) if name in FIRST else len(FIRST), name)


def load_progressions(group: str = CONTENT_GROUP) -> dict[str, Progression]:
    """The progression files every `group` entry declares for `ensemble`, by name:
    built-in ones first (`FIRST`, then by name), then installed ones by name.

    Raises `ContentError` when an entry or file is invalid, when a file's name
    differs from its `name`, or when two files define the same progression.
    """
    contents = [c for c in map(_load_entry, entry_points(group=group)) if c.preset == PRESET]
    progressions: dict[str, Progression] = {}
    for built_in in (True, False):
        found = [c for c in contents if _built_in(c) == built_in]
        parsed = [parse_progression(data, origin) for _, data, origin in _read(found, KIND, PRESET)]
        for progression in sorted(parsed, key=_order if built_in else lambda p: (0, p.name)):
            if progression.name in progressions:
                raise ContentError(
                    f"two progressions named {progression.name!r}:"
                    f" {progressions[progression.name].origin} and {progression.origin}"
                )
            progressions[progression.name] = progression
    return progressions


def _check(paths: Sequence[str]) -> int:
    failed = 0
    for path in paths:
        try:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ContentError(f"{path}: cannot read: {error}") from error
            progression = parse_progression(data, path)
            if progression.name != Path(path).stem:
                raise ContentError(
                    f"{path}: the file name must equal the name {progression.name!r}"
                )
        except ContentError as error:
            print(f"error: {error}", file=sys.stderr)
            failed += 1
            continue
        print(
            f"{path}: ok, progression {progression.name!r}, {progression.bars} bar(s):"
            f" {chord_names(progression)}"
        )
    return 1 if failed else 0


def _list(progressions: Mapping[str, Progression]) -> None:
    for name, progression in progressions.items():
        print(f"{name}: {chord_names(progression)}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.progressions", description="Check and list progression files."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chk = commands.add_parser("check", help="validate progression files")
    chk.add_argument("files", nargs="+")
    commands.add_parser("list", help="list the built-in and installed progressions")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.files)
    try:
        _list(load_progressions())
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
