"""The model of the offline variation generator (#221, RFC 0005 step 8, line style).

A small model of how the musician's lines move, learned from loop files (ADR 0010)
in the Continuator family, with two viewpoints whose counts can be printed:

- **Pitch**: a chain over each variation's notes in start order. A token is
  `(tone, chord, semitones, octave)`, where the note sits in the harmony. Contexts
  have up to `ORDER` 2 earlier notes and wrap around the loop's end, because the
  loop repeats. `Model.continuations` uses the longest context seen at least once
  and backs off to order 1 and then order 0 (longest match, no interpolation).
  Order 0 is the corpus' token counts plus `PRIOR` 0.25 for each `GRAMMAR` token
  (chord tones 0-3, `chord` 0, `semitones` 0), so even a one-note corpus has
  something legal to choose.
- **Rhythm**: a table by metric position (`position`: `downbeat`, `beat`, `8th`,
  `16th`) of `(length, velocity class, offset)`; the velocity class is `ghost`
  below 0.8, `mid` below 0.95, else `full`, and the offset is in 1/6 of a 16th
  (`loop_midi.TICKS`).

The corpus (`corpus`, the setting `CORPORA`, default `own`) is the source loop
file (`source`), the source plus the musician's other loops of its part from
`<data folder>/loops/` (`own`), or every built-in, installed and user loop of the
part (`all`). All variations and both levels count; each file's notes are
weighted so that the file totals 1, so a loop with three variations does not
outweigh a one-variation line.

`python -m mpc_iml.vargen show <loop name or file>` prints the model. The generator
itself comes in a later PR of #221; nothing here changes how `ensemble` plays, and
nothing is written.
"""

import argparse
import json
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mpc_iml.content import ContentError
from mpc_iml.launch import DEFAULT_DATA
from mpc_iml.loop_midi import TICKS
from mpc_iml.loops import (
    STEPS,
    USER_FOLDER,
    LoopFile,
    LoopLibrary,
    load_loops,
    load_user_loops,
    parse_loop,
)
from mpc_iml.melody import LoopNote

__all__ = [
    "CORPORA",
    "DEFAULT_CORPUS",
    "GRAMMAR",
    "ORDER",
    "POSITIONS",
    "PRIOR",
    "Model",
    "Pitch",
    "Rhythm",
    "build_model",
    "corpus",
    "find_loop",
    "main",
    "pitch_token",
    "position",
    "rhythm_token",
    "show",
    "velocity_class",
]

Pitch = tuple[int, int, int, int]
"""`(tone, chord, semitones, octave)`."""
Rhythm = tuple[int, str, int]
"""`(length, velocity class, offset in 1/6 of a 16th)`."""

ORDER = 2
"""The longest pitch context, in notes."""
PRIOR = 0.25
"""The count each `GRAMMAR` token adds at order 0."""
GRAMMAR: tuple[Pitch, ...] = tuple((tone, 0, 0, 0) for tone in range(4))
"""The chord tones the prior allows at order 0."""
POSITIONS = ("downbeat", "beat", "8th", "16th")
CORPORA = ("source", "own", "all")
DEFAULT_CORPUS = "own"


def velocity_class(velocity: float) -> str:
    """`ghost` below 0.8, `mid` below 0.95, else `full`."""
    if velocity < 0.8:
        return "ghost"
    return "mid" if velocity < 0.95 else "full"


def position(step: int) -> str:
    """The metric position of a 16th `step` of the bar."""
    if step == 0:
        return "downbeat"
    if step % 4 == 0:
        return "beat"
    return "8th" if step % 2 == 0 else "16th"


def pitch_token(note: LoopNote) -> Pitch:
    return (note.tone, note.chord, note.semitones, note.octave)


def rhythm_token(note: LoopNote) -> Rhythm:
    return (note.length, velocity_class(note.velocity), round(note.offset * TICKS))


def _line(notes: Sequence[LoopNote]) -> list[LoopNote]:
    """A variation's notes in start order (level 1 before an ornament on the same step)."""
    return sorted(notes, key=lambda n: (n.bar * STEPS + n.step, n.level, pitch_token(n)))


@dataclass(frozen=True)
class Model:
    """Weighted counts of one part's corpus: `pitch` by context (a tuple of 0 to
    `ORDER` earlier tokens, the nearest last) and `rhythm` by metric position.
    `files` are the corpus' loop names with their note counts, source first."""

    part: str
    files: tuple[tuple[str, int], ...]
    pitch: Mapping[tuple[Pitch, ...], Mapping[Pitch, float]]
    rhythm: Mapping[str, Mapping[Rhythm, float]]

    def continuations(self, context: Sequence[Pitch]) -> tuple[int, dict[Pitch, float]]:
        """The order used and the counts of what follows `context` (earliest first):
        the longest suffix of up to `ORDER` tokens seen at least once, else order 0
        with the prior."""
        for order in range(min(ORDER, len(context)), 0, -1):
            seen = self.pitch.get(tuple(context[-order:]))
            if seen:
                return order, dict(seen)
        counts = dict(self.pitch.get((), {}))
        for token in GRAMMAR:
            counts[token] = counts.get(token, 0.0) + PRIOR
        return 0, counts

    def rhythms(self, step: int) -> dict[Rhythm, float]:
        """The rhythm counts at `step`'s metric position; all positions together
        when the corpus has no note there."""
        seen = self.rhythm.get(position(step))
        if seen:
            return dict(seen)
        merged: dict[Rhythm, float] = {}
        for counts in self.rhythm.values():
            for token, count in counts.items():
                merged[token] = merged.get(token, 0.0) + count
        return merged


def _add[K, T](table: dict[K, dict[T, float]], key: K, token: T, weight: float) -> None:
    counts = table.setdefault(key, {})
    counts[token] = counts.get(token, 0.0) + weight


def build_model(files: Sequence[LoopFile]) -> Model:
    """The model of `files`, all of one part; raises `ValueError` when there are
    none or their parts differ."""
    if not files:
        raise ValueError("the corpus has no loop files")
    part = files[0].part
    if any(f.part != part for f in files):
        raise ValueError("the corpus mixes bass and melody loops")
    pitch: dict[tuple[Pitch, ...], dict[Pitch, float]] = {}
    rhythm: dict[str, dict[Rhythm, float]] = {}
    sizes: list[tuple[str, int]] = []
    for loop in files:
        total = sum(len(notes) for notes in loop.variations.values())
        sizes.append((loop.name, total))
        weight = 1.0 / total
        for notes in loop.variations.values():
            line = _line(notes)
            tokens = [pitch_token(n) for n in line]
            for i, note in enumerate(line):
                for order in range(ORDER + 1):
                    context = tuple(tokens[(i - order + j) % len(tokens)] for j in range(order))
                    _add(pitch, context, tokens[i], weight)
                _add(rhythm, position(note.step), rhythm_token(note), weight)
    return Model(part, tuple(sizes), pitch, rhythm)


def corpus(
    source: LoopFile, setting: str, installed: LoopLibrary, user: Sequence[LoopFile]
) -> tuple[LoopFile, ...]:
    """The loop files to learn from for `source`, source first: `source` alone; `own`
    adds the `user` loops of its part; `all` adds every `installed` and `user` loop
    of its part. A loop with `source`'s name is the source itself."""
    if setting not in CORPORA:
        raise ValueError(f"corpus must be one of {', '.join(CORPORA)}, got {setting!r}")
    others: list[LoopFile] = []
    if setting == "all":
        others += [installed.loops[name] for name in installed.names(source.part)]
    if setting in ("own", "all"):
        others += [loop for loop in user if loop.part == source.part]
    rest = [loop for loop in others if loop.name != source.name]
    return (source, *rest)


def _read(path: Path) -> LoopFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContentError(f"{path}: cannot read: {error}") from error
    return parse_loop(data, str(path))


def find_loop(name: str, data: Path) -> tuple[LoopFile, LoopLibrary, list[LoopFile]]:
    """The loop `name` (a loop name, or a loop file ending in `.json`), the installed
    library and the user loops in `data`'s loop folder (bad files skipped)."""
    installed = load_loops()
    library, _ = load_user_loops(data / USER_FOLDER, installed)
    user = [loop for loop_name, loop in library.loops.items() if loop_name not in installed.loops]
    if name.endswith(".json"):
        return _read(Path(name)), installed, user
    if name not in library.loops:
        raise ContentError(f"unknown loop {name!r}; loops: {', '.join(library.loops)}")
    return library.loops[name], installed, user


def _pitch(token: Pitch) -> str:
    return "({},{},{},{})".format(*token)


def _rhythm(token: Rhythm) -> str:
    length, velocity, offset = token
    sixths = "0" if offset == 0 else f"{offset:+d}/{TICKS}"
    return f"({length},{velocity},{sixths})"


def _counts[T](counts: Mapping[T, float], name: Callable[[T], str]) -> str:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name(token)} {count:.2f}" for token, count in ordered)


def show(model: Model, setting: str) -> str:
    """The model as text: the corpus, every pitch context by order with its
    continuations and counts, the prior, and the rhythm table by position."""
    lines = [f"{model.part} model, corpus {setting}; each file's notes total 1:"]
    lines += [f"  {name}: {notes} notes, {1 / notes:.2f} each" for name, notes in model.files]
    lines.append(f"pitch (tone,chord,semitones,octave), contexts of up to {ORDER} notes:")
    for order in range(ORDER, -1, -1):
        lines.append(f"  order {order}:")
        contexts = sorted(c for c in model.pitch if len(c) == order)
        for context in contexts:
            before = "".join(f"{_pitch(t)} " for t in context)
            lines.append(f"    {before}-> {_counts(model.pitch[context], _pitch)}")
    grammar = ", ".join(_pitch(t) for t in GRAMMAR)
    lines.append(f"  prior at order 0: +{PRIOR:.2f} each for {grammar}")
    lines.append(f"rhythm (length,velocity,offset in 1/{TICKS} 16th) by position:")
    for where in POSITIONS:
        if where in model.rhythm:
            lines.append(f"  {where} -> {_counts(model.rhythm[where], _rhythm)}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.vargen",
        description="The variation generator's model of your lines (#221).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    shown = commands.add_parser("show", help="print the model learned for a loop")
    shown.add_argument("loop", help="a loop name or a loop file (.json)")
    shown.add_argument("--corpus", choices=CORPORA, default=DEFAULT_CORPUS)
    shown.add_argument("--data", default=DEFAULT_DATA, help="the data folder with user loops")
    args = parser.parse_args(argv)
    try:
        source, installed, user = find_loop(args.loop, Path(args.data))
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(show(build_model(corpus(source, args.corpus, installed, user)), args.corpus))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
