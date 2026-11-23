"""Loop files to and from MIDI clips, and `python -m mpc_iml.loops` (#173, ADR 0010).

`import` turns a Standard MIDI File (for example a clip exported from Live) into a
loop file, or one variation of an existing file with `--into`: each pitch becomes
the nearest chord tone over the progression and start bar the clip was written on,
steps are rounded to 16ths with the remainder kept as `offset`, and velocities
become weights. `export` writes a variation as a MIDI clip and `check` validates
a file.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mpc_iml import smf
from mpc_iml.content import ContentError
from mpc_iml.launch import DEFAULT_DATA
from mpc_iml.loops import (
    BARS,
    HOME,
    LOOP_FORMAT,
    PRESET,
    STEPS,
    USER_FOLDER,
    VARIATIONS,
    LoopFile,
    load_loops,
    load_user_loops,
    parse_loop,
)
from mpc_iml.melody import ORNAMENTS, QUALITIES, LoopNote, loop_pitch
from mpc_iml.progressions import DEFAULT, Progression, find_progression

__all__ = ["OCTAVES", "ORNAMENT_CHANNEL", "Imported", "dump", "from_midi", "main", "to_midi"]

OCTAVES = {"bass": 1, "melody": 4}
"""The base octave of each part (the `ensemble` defaults `octave`, `melody-octave`)."""
ORNAMENT_CHANNEL = 1
"""`export` writes level 2 notes on MIDI channel 2 (0-based 1); `import` reads them back."""
TICKS = 6
"""Offsets are rounded to 1/6 of a 16th, the 24 PPQN clock's resolution."""
_DEFAULTS = {"level": 1, "octave": 0, "velocity": 1.0, "chord": 0, "semitones": 0, "offset": 0.0}


def _chords(progression: Progression, bar: int) -> tuple[int, str]:
    chord = progression.chord(bar)
    return (progression.tonic + chord.root) % 12, chord.quality


def _nearest(
    pitch: int, chord: tuple[int, str], base: int, lower: bool = True
) -> tuple[int, int, int]:
    """(tone, octave, semitones) of the chord tone nearest `pitch`; ties go to the
    lower tone, or with `lower` false to the higher (an approach resolves upwards)."""
    pitch_class, quality = chord
    best: list[tuple[int, int, int, int]] = []
    for tone, above in enumerate(QUALITIES[quality]):
        root = 12 * (base + 1) + pitch_class + above
        octave = (pitch - root + 6) // 12
        for k in (octave - 1, octave, octave + 1):
            semitones = pitch - (root + 12 * k)
            best.append((abs(semitones), -semitones if lower else semitones, tone, k))
    found = min(best)
    return found[2], found[3], -found[1] if lower else found[1]


@dataclass
class Imported:
    """The notes of one variation and the messages for the musician."""

    bars: int
    notes: list[LoopNote]
    messages: list[str]


def from_midi(
    clip: smf.MidiFile,
    part: str,
    progression: Progression,
    start_bar: int = 0,
    bars: int | None = None,
    ornament_below: int = 0,
    octave: int | None = None,
) -> Imported:
    """The notes of `clip` as a variation; raises `ContentError` for a note the
    format cannot hold."""
    sixteenth = clip.division / 4
    if bars is None:
        whole = max(-(-round(clip.length / sixteenth) // STEPS), 1)
        bars = next((b for b in BARS if b >= whole), 0)
        if not bars:
            raise ContentError(f"the clip is {whole} bars long; a loop has 1, 2 or 4 bars")
    end, base = bars * STEPS, OCTAVES[part] if octave is None else octave
    loudest = max([n.velocity for n in clip.notes] + [1])
    notes: list[LoopNote] = []
    messages: list[str] = []
    counts = {"chord tones": 0, "approach notes": 0, "other notes": 0, "offsets": 0}
    for n in clip.notes:
        position = n.start / sixteenth
        start = round(position)
        offset = round((position - start) * TICKS) / TICKS
        where = f"note {n.pitch} at bar {start // STEPS} step {start % STEPS}"
        if start >= end:
            raise ContentError(f"{where} is after the loop's {bars} bar(s); use --bars")
        length = max(round(n.length / sixteenth), 1)
        if start + length > end:
            messages.append(f"{where} crosses the loop's end; shortened")
            length = end - start
        bar, step = divmod(start, STEPS)
        chord = 0
        tone, up, semitones = _nearest(n.pitch, _chords(progression, start_bar + bar), base)
        if semitones and step >= STEPS - 2:
            following = _nearest(n.pitch, _chords(progression, start_bar + bar + 1), base, False)
            if abs(following[2]) <= 2:
                chord, (tone, up, semitones) = 1, following
        kind = "approach notes" if chord else "other notes" if semitones else "chord tones"
        counts[kind] += 1
        if kind == "other notes":
            messages.append(f"{where} is not a chord tone: tone {tone} {semitones:+d}")
        counts["offsets"] += offset != 0
        level = ORNAMENTS if n.channel == ORNAMENT_CHANNEL or n.velocity < ornament_below else 1
        velocity = max(round(n.velocity / loudest * 20) / 20, 0.05)
        notes.append(
            LoopNote(bar, step, tone, length, level, up, velocity, chord, semitones, offset)
        )
    if part == "bass":
        notes = _monophonic(notes, messages)
    if not notes:
        raise ContentError("the clip has no notes")
    summary = ", ".join(f"{count} {kind}" for kind, count in counts.items())
    return Imported(bars, notes, [summary, *messages])


def _monophonic(notes: list[LoopNote], messages: list[str]) -> list[LoopNote]:
    """One note per step (the louder), each ending by the next one's start."""
    by_step: dict[int, LoopNote] = {}
    for n in notes:
        at = n.bar * STEPS + n.step
        if at in by_step:
            messages.append(f"two bass notes at bar {n.bar} step {n.step}; kept the louder")
            if n.velocity <= by_step[at].velocity:
                continue
        by_step[at] = n
    ordered = [by_step[at] for at in sorted(by_step)]
    out = []
    for n, after in zip(ordered, [*ordered[1:], None], strict=True):
        gap = (after.bar - n.bar) * STEPS + after.step - n.step if after else n.length
        if n.length > gap:
            messages.append(f"bass note at bar {n.bar} step {n.step} overlaps the next; shortened")
            n = replace(n, length=gap)
        out.append(n)
    return out


def to_midi(
    loop: LoopFile,
    variation: str,
    progression: Progression,
    start_bar: int = 0,
    octave: int | None = None,
) -> bytes:
    """`variation` of `loop` over `progression` as a format 0 file; ornaments
    (level 2) on channel 2 and velocities relative to 127."""
    sixteenth = smf.DIVISION // 4
    base = OCTAVES[loop.part] if octave is None else octave
    notes = []
    for n in loop.variations.get(variation, loop.variations[HOME]):
        bar = start_bar + n.bar
        chords = _chords(progression, bar), _chords(progression, bar + 1)
        start = round((n.bar * STEPS + n.step + n.offset) * sixteenth)
        channel = ORNAMENT_CHANNEL if n.level == ORNAMENTS else 0
        velocity = max(round(n.velocity * 127), 1)
        pitch = loop_pitch(n, *chords, base)
        notes.append(smf.Note(max(start, 0), n.length * sixteenth, pitch, velocity, channel))
    return smf.write(notes, length=loop.bars * STEPS * sixteenth)


def dump(loop: LoopFile) -> dict[str, Any]:
    """`loop` as a loop file's JSON object, with defaults left out."""
    variations: dict[str, list[dict[str, Any]]] = {}
    for name, notes in loop.variations.items():
        written = []
        for n in notes:
            entry: dict[str, Any] = {"bar": n.bar, "step": n.step, "tone": n.tone}
            entry["length"] = n.length
            for field, default in _DEFAULTS.items():
                value = getattr(n, field)
                if value != default:
                    entry[field] = round(value, 2) if isinstance(value, float) else value
            if name == HOME and n in loop.skeleton:
                entry["skeleton"] = True
            written.append(entry)
        variations[name] = written
    data: dict[str, Any] = {"format": LOOP_FORMAT, "format_version": 1, "name": loop.name}
    data |= {"title": loop.title} if loop.title else {}
    data |= {"description": loop.description} if loop.description else {}
    return data | {"preset": PRESET, "part": loop.part, "bars": loop.bars, "variations": variations}


def _write(loop: LoopFile, path: Path) -> None:
    """Write `loop` with one note per line, as the built-in files."""
    data = dump(loop)
    variations = data.pop("variations")
    rows = [
        f'    "{name}": [\n'
        + ",\n".join(f"      {json.dumps(n, separators=(', ', ': '))}" for n in notes)
        + "\n    ]"
        for name, notes in variations.items()
    ]
    head = json.dumps(data, indent=2, ensure_ascii=False)[:-2]
    path.parent.mkdir(parents=True, exist_ok=True)
    text = head + ',\n  "variations": {\n' + ",\n".join(rows) + "\n  }\n}\n"
    path.write_text(text, encoding="utf-8")


def _read(path: Path) -> LoopFile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContentError(f"{path}: cannot read: {error}") from error
    loop = parse_loop(data, str(path))
    if loop.name != path.stem:
        raise ContentError(f"{path}: the file name must equal the name {loop.name!r}")
    return loop


def _import(args: argparse.Namespace) -> None:
    try:
        clip = smf.read(Path(args.clip).read_bytes())
    except (OSError, smf.SmfError) as error:
        raise ContentError(f"{args.clip}: {error}") from error
    if args.into:
        path = Path(args.into)
        old = _read(path)
        part = old.part
    else:
        part = args.part
        if not part:
            raise ContentError("give --part bass or --part melody (or --into <loop file>)")
        if not args.name:
            raise ContentError("give --name <name> (or --into <loop file>)")
        path = Path(args.out) / f"{args.name}.json"
        if path.exists() and not args.force:
            raise ContentError(f"{path} exists; use --into to replace a variation, or --force")
    if args.variation not in VARIATIONS[part]:
        allowed = ", ".join(VARIATIONS[part])
        raise ContentError(f"unknown variation {args.variation!r} for the {part}; {allowed}")
    bars = args.bars or (old.bars if args.into else None)
    progression = find_progression(args.progression, Path(args.data))
    found = from_midi(clip, part, progression, args.start_bar, bars, args.ornament_below)
    for message in found.messages:
        print(message)
    notes = tuple(found.notes)
    if args.into:
        skeleton = old.skeleton
        if args.variation == HOME and skeleton:
            print("home was replaced, so its skeleton marks are gone (thin plays level 1)")
            skeleton = ()
        variations = dict(old.variations) | {args.variation: notes}
        loop = replace(old, variations=variations, skeleton=skeleton)
    else:
        if args.variation != HOME:
            raise ContentError(
                f"a new loop file starts with {HOME}; add {args.variation} with --into"
            )
        loop = LoopFile(args.name, part, found.bars, {HOME: notes}, origin=str(path))
    ordered = {v: loop.variations[v] for v in VARIATIONS[part] if v in loop.variations}
    loop = parse_loop(dump(replace(loop, variations=ordered)), str(path))
    _write(loop, path)
    print(f"wrote {args.variation} of {loop.name} ({loop.bars} bar(s)) to {path}")


def _find(name: str, data: str) -> LoopFile:
    if name.endswith(".json"):
        return _read(Path(name))
    library, _ = load_user_loops(Path(data) / USER_FOLDER, load_loops())
    if name not in library.loops:
        raise ContentError(f"unknown loop {name!r}; loops: {', '.join(library.loops)}")
    return library.loops[name]


def _export(args: argparse.Namespace) -> None:
    loop = _find(args.loop, args.data)
    if args.variation not in VARIATIONS[loop.part]:
        raise ContentError(f"unknown variation {args.variation!r} for the {loop.part}")
    progression = find_progression(args.progression, Path(args.data))
    Path(args.out).write_bytes(to_midi(loop, args.variation, progression, args.start_bar))
    print(f"wrote {args.variation} of {loop.name} over {args.progression} to {args.out}")


def _check(args: argparse.Namespace) -> None:
    loop = _read(Path(args.file))
    counts = ", ".join(f"{v} {len(n)} notes" for v, n in loop.variations.items())
    print(f"{args.file}: ok, {loop.part} loop {loop.name!r}, {loop.bars} bar(s): {counts}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.loops", description="Import, export and check loop files."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    imp = commands.add_parser("import", help="turn a MIDI clip into a loop file")
    imp.add_argument("clip", help="a Standard MIDI File, for example from Live's Export MIDI Clip")
    imp.add_argument("--part", choices=list(VARIATIONS))
    imp.add_argument("--name", help="the loop's name (lower case letters, digits, hyphens)")
    imp.add_argument("--variation", default=HOME, help="the variation the clip is (default home)")
    imp.add_argument("--into", help="add or replace the variation in this loop file")
    imp.add_argument("--progression", default=DEFAULT, help="the chords of the clip")
    imp.add_argument("--start-bar", type=int, default=0, help="the song bar the clip starts on")
    imp.add_argument("--bars", type=int, choices=BARS, help="default: from the clip's length")
    imp.add_argument(
        "--ornament-below", type=int, default=0, help="notes below this velocity are ornaments"
    )
    imp.add_argument("--out", default=str(Path(DEFAULT_DATA) / USER_FOLDER), help="folder")
    imp.add_argument("--force", action="store_true", help="overwrite an existing file")
    imp.add_argument("--data", default=DEFAULT_DATA, help="the data folder with user progressions")
    exp = commands.add_parser("export", help="write a loop's variation as a MIDI clip")
    exp.add_argument("loop", help="a loop name or a loop file (.json)")
    exp.add_argument("out", help="the MIDI file to write")
    exp.add_argument("--variation", default=HOME)
    exp.add_argument("--progression", default=DEFAULT, help="yours from --data too")
    exp.add_argument("--start-bar", type=int, default=0)
    exp.add_argument(
        "--data", default=DEFAULT_DATA, help="the data folder with user loops and progressions"
    )
    chk = commands.add_parser("check", help="validate a loop file")
    chk.add_argument("file")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = {"import": _import, "export": _export, "check": _check}[args.command]
    try:
        command(args)
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0
