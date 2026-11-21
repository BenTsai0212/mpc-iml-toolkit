"""Loop files for `ensemble`: the format, its validation and loading (#173, ADR 0010).

A loop file holds one bass or melody loop with all its variations, so musicians can
write lines as data instead of Python. Notes are written as in `melody.LoopNote`:
a chord `tone` 0-3, the chord of its own or the next bar (`chord`), a chromatic
offset (`semitones`) and a timing `offset` (a fraction of a 16th):

    {"format": "mpc-iml-loop", "format_version": 1, "name": "boom",
     "preset": "ensemble", "part": "bass", "bars": 1,
     "variations": {"home": [{"bar": 0, "step": 0, "tone": 0, "length": 3,
                              "skeleton": true}]}}

The variation names are fixed per part (`VARIATIONS`), because the #158 rules
choose by them; `home` is required and a missing variation plays `home`. Notes
marked `skeleton` (in `home` only) are what `no-drums thin` plays; without any,
`thin` plays `home`'s level 1. Bass notes may not overlap (the bass is monophonic).

Loop files are a content kind next to kits and modules (ADR 0007): packages declare
them through the `mpc_iml.content` entry point group, under
`<root>/loops/ensemble/<name>.json`. `load_loops` reads every entry, built-in
content (the `mpc_iml` package) first. Musicians' own loops live in the engine's
data folder, `<data folder>/loops/*.json`; `load_user_loops` adds them after the
installed ones and skips a bad file instead of failing.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from mpc_iml.bass import BASS_VARIATIONS
from mpc_iml.content import (
    CONTENT_GROUP,
    Content,
    ContentError,
    UnknownContentError,
    _fail,
    _header,
    _load_entry,
    _number,
    _read,
)
from mpc_iml.melody import MELODY_VARIATIONS, ORNAMENTS, Loop, LoopNote

__all__ = [
    "BARS",
    "HOME",
    "KIND",
    "LOOP_FORMAT",
    "OFFSET",
    "PARTS",
    "PRESET",
    "STEPS",
    "VARIATIONS",
    "LoopFile",
    "LoopLibrary",
    "USER_FOLDER",
    "load_loops",
    "load_user_loops",
    "parse_loop",
]

LOOP_FORMAT = "mpc-iml-loop"
PRESET = "ensemble"
"""The preset loop files belong to."""
KIND = "loops"
"""The content folder of loop files: `<root>/loops/ensemble/`."""
USER_FOLDER = "loops"
"""The folder of user loop files in the engine's data folder."""
PARTS = ("bass", "melody")
VARIATIONS: Mapping[str, tuple[str, ...]] = {"bass": BASS_VARIATIONS, "melody": MELODY_VARIATIONS}
"""The variation names each part allows, in order."""
HOME = "home"
BARS = (1, 2, 4)
STEPS = 16
"""16ths in a bar."""
OFFSET = 0.5
"""The largest timing offset, in 16ths, either way."""

_TOP = {"format", "format_version", "name", "title", "description", "preset", "part"}
_TOP |= {"bars", "variations"}
_NOTE: tuple[str, ...] = ("bar", "step", "tone", "length", "level", "octave", "velocity")
_NOTE += ("chord", "semitones", "offset", "skeleton")
_REQUIRED = ("bar", "step", "tone", "length")


@dataclass(frozen=True)
class LoopFile:
    """A parsed loop file: the variations it writes (`home` first, in `VARIATIONS`
    order) and the notes of `home` marked `skeleton`."""

    name: str
    part: str
    bars: int
    variations: Mapping[str, tuple[LoopNote, ...]]
    skeleton: tuple[LoopNote, ...] = ()
    title: str = ""
    description: str = ""
    origin: str = ""

    def loop(self) -> Loop:
        """As a `melody.Loop`: every variation of the part (a missing one plays
        `home`), and as its own notes the skeleton at level 1 (`no-drums thin`)."""
        home = self.variations[HOME]
        skeleton = self.skeleton or tuple(n for n in home if n.level == 1)
        variations = tuple(
            Loop(name, self.bars, self.variations.get(name, home)) for name in VARIATIONS[self.part]
        )
        notes = tuple(replace(n, level=1) for n in skeleton)
        return Loop(self.name, self.bars, notes, variations)


def _integer(value: Any, origin: str, what: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _fail(origin, f"{what} must be a whole number, got {value!r}")
    if not low <= value <= high:
        raise _fail(origin, f"{what} must be {low}-{high}, got {value!r}")
    return value


def _note(data: Any, origin: str, where: str, bars: int, home: bool) -> tuple[LoopNote, bool]:
    """A note and whether it is marked `skeleton`."""
    if not isinstance(data, dict):
        raise _fail(origin, f"{where}: a note is an object, got {data!r}")
    unknown = sorted(set(data) - set(_NOTE))
    if unknown:
        raise _fail(origin, f"{where}: unknown field {unknown[0]!r}; fields: {', '.join(_NOTE)}")
    missing = [f for f in _REQUIRED if f not in data]
    if missing:
        raise _fail(origin, f"{where}: {missing[0]} is required")
    skeleton = data.get("skeleton", False)
    if not isinstance(skeleton, bool):
        raise _fail(origin, f"{where}: skeleton must be true or false")
    if skeleton and not home:
        raise _fail(origin, f"{where}: only notes of {HOME!r} can be skeleton")
    note = LoopNote(
        bar=_integer(data["bar"], origin, f"{where}: bar", 0, bars - 1),
        step=_integer(data["step"], origin, f"{where}: step", 0, STEPS - 1),
        tone=_integer(data["tone"], origin, f"{where}: tone", 0, 3),
        length=_integer(data["length"], origin, f"{where}: length", 1, 4 * STEPS),
        level=_integer(data.get("level", 1), origin, f"{where}: level", 1, ORNAMENTS),
        octave=_integer(data.get("octave", 0), origin, f"{where}: octave", -2, 3),
        velocity=_number(data.get("velocity", 1.0), origin, f"{where}: velocity", 0.05, 1.0),
        chord=_integer(data.get("chord", 0), origin, f"{where}: chord", 0, 1),
        semitones=_integer(data.get("semitones", 0), origin, f"{where}: semitones", -11, 11),
        offset=_number(data.get("offset", 0.0), origin, f"{where}: offset", -OFFSET, OFFSET),
    )
    return note, skeleton


def _start(note: LoopNote) -> int:
    return note.bar * STEPS + note.step


def _monophonic(notes: tuple[LoopNote, ...], bars: int, origin: str, where: str) -> None:
    """Raise when two notes of a bass variation overlap, also across the loop's end."""
    ordered = sorted(range(len(notes)), key=lambda i: _start(notes[i]))
    for i, j in zip(ordered, ordered[1:], strict=False):
        if _start(notes[i]) + notes[i].length > _start(notes[j]):
            raise _fail(
                origin,
                f"{where}[{j}]: overlaps {where}[{i}] (the bass plays one note at a time)",
            )
    first, last = notes[ordered[0]], notes[ordered[-1]]
    if _start(last) + last.length > bars * STEPS + _start(first):
        raise _fail(
            origin,
            f"{where}[{ordered[-1]}]: overlaps {where}[{ordered[0]}] when the loop repeats",
        )


def parse_loop(data: Any, origin: str = "loop") -> LoopFile:
    """Validate a loop file's JSON object; raises `ContentError` naming `origin`
    and the note, for example `boom.json: variations.push[3]: step must be 0-15`."""
    name, title, description = _header(data, LOOP_FORMAT, origin, PRESET)
    unknown = sorted(set(data) - _TOP)
    if unknown:
        raise _fail(origin, f"unknown field {unknown[0]!r}")
    part = data.get("part")
    if part not in PARTS:
        raise _fail(origin, f"part must be 'bass' or 'melody', got {part!r}")
    bars = data.get("bars")
    if isinstance(bars, bool) or bars not in BARS:
        raise _fail(origin, f"bars must be 1, 2 or 4, got {bars!r}")
    written = data.get("variations")
    if not isinstance(written, dict):
        raise _fail(origin, "variations must map variation names to lists of notes")
    allowed = VARIATIONS[part]
    for variation in written:
        if variation not in allowed:
            raise _fail(
                origin,
                f"unknown variation {variation!r} for the {part}; variations: {', '.join(allowed)}",
            )
    if HOME not in written:
        raise _fail(origin, f"variations must include {HOME!r}")
    variations: dict[str, tuple[LoopNote, ...]] = {}
    skeleton: list[LoopNote] = []
    for variation in allowed:
        if variation not in written:
            continue
        where = f"variations.{variation}"
        entries = written[variation]
        if not isinstance(entries, list) or not entries:
            raise _fail(
                origin, f"{where} must be a non-empty list of notes; leave it out to play home"
            )
        notes: list[LoopNote] = []
        for i, entry in enumerate(entries):
            note, marked = _note(entry, origin, f"{where}[{i}]", bars, variation == HOME)
            notes.append(note)
            if marked:
                skeleton.append(note)
        if part == "bass":
            _monophonic(tuple(notes), bars, origin, where)
        variations[variation] = tuple(notes)
    return LoopFile(name, part, bars, variations, tuple(skeleton), title, description, origin)


@dataclass(frozen=True)
class LoopLibrary:
    """The loop files installed for `ensemble`, built-in first, then installed,
    each group by name."""

    loops: Mapping[str, LoopFile]

    def names(self, part: str) -> list[str]:
        """The names of the loops of `part`, in library order."""
        return [name for name, loop in self.loops.items() if loop.part == part]

    def played(self, part: str) -> dict[str, Loop]:
        """The loops of `part` as `ensemble` plays them (`LoopFile.loop`), by name in
        library order."""
        return {name: self.loops[name].loop() for name in self.names(part)}

    def get(self, name: str, part: str) -> LoopFile:
        """The `part` loop `name`; raises `UnknownContentError` when none is installed."""
        loop = self.loops.get(name)
        if loop is None or loop.part != part:
            raise UnknownContentError(f"unknown {part} loop {name!r}")
        return loop


def _built_in(content: Content) -> bool:
    return content.root.partition(":")[0] == "mpc_iml"


def load_loops(group: str = CONTENT_GROUP) -> LoopLibrary:
    """Read the loop files every `group` entry declares for `ensemble`.

    Raises `ContentError` when an entry or file is invalid, when a file's name
    differs from its `name`, or when two files define the same loop.
    """
    contents = [c for c in map(_load_entry, entry_points(group=group)) if c.preset == PRESET]
    loops: dict[str, LoopFile] = {}
    for built_in in (True, False):
        found = [c for c in contents if _built_in(c) == built_in]
        parsed = [parse_loop(data, origin) for _, data, origin in _read(found, KIND, PRESET)]
        for loop in sorted(parsed, key=lambda loop: loop.name):
            if loop.name in loops:
                raise ContentError(
                    f"two loops named {loop.name!r}: {loops[loop.name].origin} and {loop.origin}"
                )
            loops[loop.name] = loop
    return LoopLibrary(loops)


def load_user_loops(folder: Path, library: LoopLibrary) -> tuple[LoopLibrary, list[str]]:
    """`library` with the user loop files in `folder` (`*.json`) after its own loops,
    by name, and one error message per skipped file.

    A file that cannot be read, is invalid, has a file name other than its `name` or
    reuses a name already in `library` (built-in, installed or another user file) is
    skipped, so one bad export never stops playing. A missing folder has no loops.
    """
    loops = dict(library.loops)
    errors: list[str] = []
    files = sorted(folder.glob("*.json")) if folder.is_dir() else []
    for path in files:
        origin = str(path)
        try:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise ContentError(f"{origin}: cannot read: {error}") from error
            loop = parse_loop(data, origin)
            if loop.name != path.stem:
                raise ContentError(f"{origin}: the file name must equal the name {loop.name!r}")
            if loop.name in loops:
                raise ContentError(
                    f"{origin}: a loop named {loop.name!r} already exists"
                    f" ({loops[loop.name].origin}); rename it"
                )
        except ContentError as error:
            errors.append(str(error))
            continue
        loops[loop.name] = loop
    return LoopLibrary(loops), errors
