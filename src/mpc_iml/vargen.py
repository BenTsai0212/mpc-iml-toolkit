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

`generate` (#221 PR 2) makes candidates (`Candidate`) of one variation. Fixed, never
changed (principle 10): `home`'s `skeleton` notes (in the other variations, every
note on the step of one), every note on a bar line (step 0), every approach note
(`chord` 1), the bars, the grid, the octave range of the corpus and, for the bass,
one note at a time. One number, `novelty` 0-1 (default `DEFAULT_NOVELTY` 0.2),
caps the changed notes at `max(1, round(novelty x free notes))` and sets the
temperature `0.5 + novelty`; below 0.4 only pitches and velocity classes change,
from 0.4 onsets may move by one or two 16ths, from 0.7 ornaments may be added and
notes dropped. New pitches take `chord` 0 and new notes are level 2. A change that
would break a rule is skipped (bass lengths are cut to end by the next note); a
candidate equal to the source or an earlier one is tried again, up to `TRIES` times,
and every candidate passes `loops.parse_loop`. `novelty 0` returns the source.

`python -m mpc_iml.vargen <loop name or file>` prints candidates with their seed,
distance and changes (`--json` for all of it, `--midi` writes clips under
`<data folder>/vargen/`); `python -m mpc_iml.vargen show <loop>` prints the model.
Nothing here changes how `ensemble` plays.
"""

import argparse
import json
import random
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mpc_iml.content import ContentError
from mpc_iml.launch import DEFAULT_DATA
from mpc_iml.loop_midi import TICKS, dump, to_midi
from mpc_iml.loops import (
    HOME,
    STEPS,
    USER_FOLDER,
    LoopFile,
    LoopLibrary,
    load_loops,
    load_user_loops,
    parse_loop,
)
from mpc_iml.melody import LoopNote
from mpc_iml.progressions import DEFAULT, load_progressions

__all__ = [
    "CORPORA",
    "DEFAULT_CORPUS",
    "DEFAULT_NOVELTY",
    "GRAMMAR",
    "ORDER",
    "POSITIONS",
    "PRIOR",
    "TRIES",
    "Candidate",
    "Change",
    "Model",
    "Pitch",
    "Rhythm",
    "build_model",
    "corpus",
    "as_json",
    "describe",
    "find_loop",
    "fixed",
    "generate",
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


DEFAULT_NOVELTY = 0.2
TRIES = 50
"""Tries per candidate before the generator gives up on a new one."""
_VELOCITY = {"ghost": 0.7, "mid": 0.85, "full": 1.0}
"""The velocity a note gets when its velocity class changes."""
_KINDS: tuple[tuple[str, float, int], ...] = (
    ("pitch", 0.0, 2),
    ("velocity", 0.0, 1),
    ("moved", 0.4, 1),
)
_KINDS += (("added", 0.7, 1), ("dropped", 0.7, 1))
"""Each change kind, the novelty it starts at and its weight."""


@dataclass(frozen=True)
class Change:
    """One changed note: `kind` (`pitch`, `velocity`, `moved`, `added` or `dropped`),
    the note `before` (none when added) and `after` (none when dropped)."""

    kind: str
    before: LoopNote | None
    after: LoopNote | None


@dataclass(frozen=True)
class Candidate:
    """A generated variation with its provenance: the `source` loop and `variation`
    (`yours` when it is one of the musician's loops), the `seed` that makes it again
    with `generate`'s other settings, and the `changes` from the source. `fixed` are
    the notes the rules keep."""

    notes: tuple[LoopNote, ...]
    source: str
    variation: str
    yours: bool
    part: str
    bars: int
    seed: int
    novelty: float
    corpus: str
    changes: tuple[Change, ...]
    fixed: tuple[LoopNote, ...] = field(repr=False)
    size: int = field(repr=False)
    """The source variation's note count."""

    @property
    def distance(self) -> tuple[int, float]:
        """The number of changed notes, and that over the source's note count."""
        return len(self.changes), len(self.changes) / self.size

    def as_loop(self, name: str) -> LoopFile:
        """A loop file with the candidate as `home`, its fixed notes as `skeleton`
        (`home`'s level 1 when there are none)."""
        return LoopFile(name, self.part, self.bars, {HOME: self.notes}, self.fixed)


def fixed(loop: LoopFile, variation: str) -> list[bool]:
    """For each note of `variation`, whether the rules keep it: a skeleton note (a
    note on a skeleton note's step outside `home`), a bar-line note or an approach."""
    notes = loop.variations[variation]
    steps = {(n.bar, n.step) for n in loop.skeleton}
    if variation == HOME:
        marked = [n in loop.skeleton for n in notes]
    else:
        marked = [(n.bar, n.step) in steps for n in notes]
    return [m or n.step == 0 or n.chord == 1 for m, n in zip(marked, notes, strict=True)]


@dataclass
class _Slot:
    note: LoopNote
    fixed: bool
    change: Change | None = None


def _start(note: LoopNote) -> int:
    return note.bar * STEPS + note.step


def _pick[T](rng: random.Random, counts: Mapping[T, float], temperature: float) -> T | None:
    if not counts:
        return None
    tokens = sorted(counts, key=str)
    weights = [counts[t] ** (1 / temperature) for t in tokens]
    return rng.choices(tokens, weights)[0]


def _bass(slots: list[_Slot], bars: int) -> bool:
    """Cut changed bass notes to end by the next note, also across the loop's end;
    false when another note would have to be cut or two notes start together."""
    ordered = sorted(slots, key=lambda s: _start(s.note))
    for slot, after in zip(ordered, [*ordered[1:], ordered[0]], strict=True):
        gap = (_start(after.note) - _start(slot.note)) % (bars * STEPS) or bars * STEPS
        if slot is not after and _start(after.note) == _start(slot.note):
            return False
        if slot.note.length > gap:
            if slot.change is None:
                return False
            slot.note = replace(slot.note, length=gap)
            slot.change = replace(slot.change, after=slot.note)
    return True


class _Maker:
    """Makes one candidate's changes with one random generator."""

    def __init__(self, loop: LoopFile, variation: str, model: Model, novelty: float) -> None:
        self.loop, self.model, self.novelty = loop, model, novelty
        self.source = loop.variations[variation]
        self.keep = fixed(loop, variation)
        free = self.keep.count(False)
        self.cap = max(1, round(novelty * free))
        low = max(len(self.source) - self.cap, self.keep.count(True), 1)
        self.count = (low, len(self.source) + self.cap)
        octaves = [t[3] for t in model.pitch.get((), {})] + [0]
        self.octaves = (min(octaves), max(octaves))
        self.kinds = [(k, w) for k, start, w in _KINDS if novelty >= start]

    def make(self, rng: random.Random) -> list[_Slot]:
        slots = [_Slot(n, k) for n, k in zip(self.source, self.keep, strict=True)]
        self.dropped: list[Change] = []
        for _ in range(rng.randint(1, self.cap)):
            for _ in range(TRIES):
                kind = rng.choices([k for k, _ in self.kinds], [w for _, w in self.kinds])[0]
                trial = [_Slot(s.note, s.fixed, s.change) for s in slots]
                if self._change(kind, trial, rng):
                    if kind == "dropped":
                        self.dropped.append(Change("dropped", self.gone, None))
                    slots = trial
                    break
        return slots

    def _context(self, slots: list[_Slot], start: int) -> list[Pitch]:
        """The `ORDER` pitches before `start`, wrapping around the loop's end."""
        line = _line([s.note for s in slots])
        later = [n for n in line if _start(n) > start]
        return [pitch_token(n) for n in later + [n for n in line if _start(n) < start]][-ORDER:]

    def _pitch(self, slots: list[_Slot], start: int, rng: random.Random) -> Pitch | None:
        _, counts = self.model.continuations(self._context(slots, start))
        low, high = self.octaves
        legal = {t: c for t, c in counts.items() if t[1] == 0 and low <= t[3] <= high}
        return _pick(rng, legal, 0.5 + self.novelty)

    def _change(self, kind: str, slots: list[_Slot], rng: random.Random) -> bool:
        free = [s for s in slots if not s.fixed and s.change is None]
        taken = {_start(s.note) for s in slots}
        if kind == "added":
            if len(slots) >= self.count[1]:
                return False
            start = rng.randrange(self.loop.bars * STEPS)
            rhythm = _pick(rng, self.model.rhythms(start % STEPS), 0.5 + self.novelty)
            token = self._pitch(slots, start, rng)
            if start in taken or token is None or rhythm is None:
                return False
            length, velocity, offset = rhythm
            note = LoopNote(start // STEPS, start % STEPS, token[0], length, 2, token[3])
            note = replace(note, velocity=_VELOCITY[velocity], semitones=token[2])
            note = replace(note, offset=round(offset / TICKS, 2))
            slots.append(_Slot(note, False, Change("added", None, note)))
        elif not free:
            return False
        elif kind == "dropped":
            if len(slots) <= self.count[0]:
                return False
            slot = rng.choice(free)
            slots.remove(slot)
            self.gone = slot.note
            return self.loop.part != "bass" or _bass(slots, self.loop.bars)
        else:
            slot = rng.choice(free)
            note = slot.note
            if kind == "pitch":
                token = self._pitch(slots, _start(note), rng)
                if token is None or token == pitch_token(note):
                    return False
                note = replace(note, tone=token[0], semitones=token[2], octave=token[3])
            elif kind == "velocity":
                now = velocity_class(note.velocity)
                classes: dict[str, float] = {}
                for (_, cls, _), count in self.model.rhythms(note.step).items():
                    classes[cls] = classes.get(cls, 0.0) + count
                classes.pop(now, None)
                picked = _pick(rng, classes, 0.5 + self.novelty)
                if picked is None:
                    return False
                note = replace(note, velocity=_VELOCITY[picked])
            else:
                step = note.step + rng.choice((-2, -1, 1, 2))
                start = note.bar * STEPS + step
                if not 0 <= step < STEPS or start in taken:
                    return False
                if position(step) not in self.model.rhythm:
                    return False
                note = replace(note, step=step)
            slot.note, slot.change = note, Change(kind, slot.note, note)
        return self.loop.part != "bass" or _bass(slots, self.loop.bars)


def generate(
    loop: LoopFile,
    variation: str,
    model: Model,
    *,
    novelty: float = DEFAULT_NOVELTY,
    seed: int = 0,
    count: int = 4,
    setting: str = DEFAULT_CORPUS,
    yours: bool = False,
) -> list[Candidate]:
    """Up to `count` (1-100) different candidates of `loop`'s `variation` learned
    from `model` (the corpus `setting`); fewer when the line leaves no room for new
    ones. `novelty 0` returns the source itself. Try `t` uses the random seed
    `seed + t`, which becomes the candidate's `seed`: `generate` with that seed and
    `count` 1 makes the same candidate again."""
    if not 0 <= novelty <= 1:
        raise ValueError(f"novelty must be 0-1, got {novelty!r}")
    if not 1 <= count <= 100:
        raise ValueError(f"count must be 1-100, got {count!r}")
    if variation not in loop.variations:
        raise ValueError(f"{loop.name} has no variation {variation!r}")
    source = loop.variations[variation]
    keep = fixed(loop, variation)
    kept = tuple(n for n, k in zip(source, keep, strict=True) if k)
    info = (loop.name, variation, yours, loop.part, loop.bars)

    def candidate(notes: tuple[LoopNote, ...], used: int, changes: tuple[Change, ...]) -> Candidate:
        return Candidate(notes, *info, used, novelty, setting, changes, kept, len(source))

    if novelty == 0:
        return [candidate(tuple(_line(source)), seed, ())]
    maker = _Maker(loop, variation, model, novelty)
    seen = {tuple(_line(source))}
    found: list[Candidate] = []
    for attempt in range(count * TRIES):
        if len(found) == count:
            break
        used = seed + attempt
        slots = maker.make(random.Random(used))
        notes = tuple(_line([s.note for s in slots]))
        if notes in seen or not maker.count[0] <= len(notes) <= maker.count[1]:
            continue
        changes = tuple(s.change for s in slots if s.change) + tuple(maker.dropped)
        made = candidate(notes, used, changes)
        try:
            parse_loop(dump(made.as_loop(loop.name)), f"{loop.name} candidate")
        except ContentError:
            continue
        seen.add(notes)
        found.append(made)
    return found


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


def _where(note: LoopNote) -> str:
    return f"bar {note.bar} step {note.step}"


def describe(change: Change) -> str:
    """One change as text, for example `pitch bar 0 step 6 (0,0,0,1) -> (3,0,0,0)`."""
    before, after = change.before, change.after
    if before is None and after is not None:
        return f"added {_where(after)} {_pitch(pitch_token(after))} {_rhythm(rhythm_token(after))}"
    assert before is not None
    if after is None:
        return f"dropped {_where(before)} {_pitch(pitch_token(before))}"
    if change.kind == "moved":
        return f"moved {_where(before)} -> step {after.step}"
    if change.kind == "velocity":
        old, new = velocity_class(before.velocity), velocity_class(after.velocity)
        return f"velocity {_where(before)} {old} -> {new}"
    return f"pitch {_where(before)} {_pitch(pitch_token(before))} -> {_pitch(pitch_token(after))}"


def as_json(candidate: Candidate) -> dict[str, Any]:
    """A candidate with its provenance as JSON; notes as in a loop file."""
    changed, ratio = candidate.distance
    return {
        "source": candidate.source,
        "variation": candidate.variation,
        "yours": candidate.yours,
        "seed": candidate.seed,
        "novelty": candidate.novelty,
        "corpus": candidate.corpus,
        "distance": {"notes": changed, "ratio": round(ratio, 3)},
        "changes": [describe(c) for c in candidate.changes],
        "notes": dump(candidate.as_loop(candidate.source))["variations"][HOME],
    }


def _generate(args: argparse.Namespace) -> None:
    source, installed, user = find_loop(args.loop, Path(args.data))
    model = build_model(corpus(source, args.corpus, installed, user))
    yours = installed.loops.get(source.name) is not source
    found = generate(
        source,
        args.variation,
        model,
        novelty=args.novelty,
        seed=args.seed,
        count=args.count,
        setting=args.corpus,
        yours=yours,
    )
    if args.json:
        print(json.dumps([as_json(c) for c in found], indent=2))
    else:
        owner = "your" if yours else "the built-in"
        head = f"{len(found)} candidate(s) of {owner} {source.name}/{args.variation}"
        print(f"{head}, novelty {args.novelty}, corpus {args.corpus}:")
        for i, c in enumerate(found, 1):
            changed, ratio = c.distance
            print(f"  {i}. seed {c.seed}: {changed} change(s), {ratio:.0%} of the notes")
            print("".join(f"     {describe(change)}\n" for change in c.changes), end="")
    if args.midi is not None:
        folder = Path(args.midi or Path(args.data) / "vargen")
        folder.mkdir(parents=True, exist_ok=True)
        progression = load_progressions()[args.progression]
        clips = [(f"{source.name}-{args.variation}", source, args.variation)]
        clips += [
            (f"{source.name}-{args.variation}-{c.seed}", c.as_loop(source.name), HOME)
            for c in found
        ]
        for name, loop, variation in clips:
            (folder / f"{name}.mid").write_bytes(to_midi(loop, variation, progression))
        print(
            f"wrote {len(clips)} clip(s) to {folder}", file=sys.stderr if args.json else sys.stdout
        )


def _novelty(text: str) -> float:
    value = float(text)
    if not 0 <= value <= 1:
        raise argparse.ArgumentTypeError(f"novelty must be 0-1, got {text}")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.vargen",
        description="Variations that grow from your lines (#221); `show <loop>` prints the model.",
    )
    parser.add_argument("loop", help="a loop name or a loop file (.json)")
    parser.add_argument("--corpus", choices=CORPORA, default=DEFAULT_CORPUS)
    parser.add_argument("--data", default=DEFAULT_DATA, help="the data folder with user loops")
    showing = bool(argv) and argv[0] == "show"
    if showing:
        parser.prog += " show"
        argv = argv[1:]
    else:
        parser.add_argument("--variation", default=HOME)
        parser.add_argument("--count", type=int, default=4, help="candidates (1-100)")
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--novelty", type=_novelty, default=DEFAULT_NOVELTY, help="0-1")
        parser.add_argument("--json", action="store_true", help="print candidates as JSON")
        parser.add_argument(
            "--midi", nargs="?", const="", help="write clips (default <data>/vargen/)"
        )
        parser.add_argument("--progression", choices=list(load_progressions()), default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        if showing:
            source, installed, user = find_loop(args.loop, Path(args.data))
            print(show(build_model(corpus(source, args.corpus, installed, user)), args.corpus))
        else:
            _generate(args)
    except (ContentError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
