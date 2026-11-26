"""Generate the notes of an instrument and a drum hit with a model the musician
installed (#284, RFC 0006 step 4, ADR 0015).

The toolkit holds no model. A **generator file** on the musician's machine says how
to run one: a command (a list of arguments, run without a shell) with `{prompt}`,
`{seed}`, `{seconds}` and `{out}` in its arguments, and how a prompt for a single note
and for a drum hit is written for that model. The toolkit runs the command, reads the
WAV file it wrote and measures it; it sends nothing anywhere.

    python -m mpc_iml.sounds.generate check <file>...
    python -m mpc_iml.sounds.generate notes <name> --generator <file> --words "<words>"
        --notes <note>... --out <sound set folder> [--duration <s>] [--takes <n>]
        [--seed <n>] [--rounds <n>] [the options of `instrument`]
    python -m mpc_iml.sounds.generate hit <name> --generator <file> --words "<words>"
        --out <sound set folder> [--duration <s>] [--seed <n>] [--seconds <s>]
    python -m mpc_iml.sounds.generate band <band> --generator <file>
        --out <sound set folder> [--words <name>=<words>]... [--only <name>...]
        [--seed <n>] [--rounds <n>] [--plan]

`band` makes every player and drum hit of a built-in band with the words the band
brings (`mpc_iml.sounds.bandset`, #286).

A model often plays the note name it is asked for one octave away, so nothing is
trusted before it is measured: a note that no clean take answered is asked again in
the next round, an octave the other way when its closest clean take came out a whole
number of octaves away. Takes are kept in the set's `takes/` folder, and each records
the model, prompt, seed and settings that made it.

Uses `numpy` through `mpc_iml.sounds`; nothing in the core install imports it.
"""

import argparse
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from mpc_iml.plays import Plays
from mpc_iml.sounds import hits as hits_module
from mpc_iml.sounds import instrument as instrument_module
from mpc_iml.sounds import soundset, wav
from mpc_iml.sounds.instrument import CLEAN, Instrument, Prefer
from mpc_iml.sounds.notes import Measurement, measure, note_name, note_number
from mpc_iml.sounds.soundset import TAKES, Origin, SetHit

FORMAT = "mpc-iml-generator"
VERSION = 1
TIMEOUT = 120.0
"""Seconds one take may run when the generator file gives no `timeout`."""
NOTE_SECONDS = 4.0
"""How long a note take is asked to be when no `--duration` is given."""
HIT_SECONDS = 1.0
"""How long a hit take is asked to be when no `--duration` is given."""
ROUNDS = 3
"""How many rounds `notes` runs when no `--rounds` is given."""
NEAR = 2
"""A clean take answers an asked note when it is measured within this many semitones."""
LAST_LINES = 5
"""How many lines of what a failed command printed are reported."""

COMMAND_FIELDS = ("prompt", "seed", "seconds", "out")
"""The placeholders of `command`; `prompt` and `out` are required."""
NOTE_FIELDS = ("words", "note")
HIT_FIELDS = ("words",)
_REQUIRED = ("format", "format_version", "name", "model", "command", "note_prompt", "hit_prompt")
_OPTIONAL = ("title", "description", "folder", "timeout")
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")


class GeneratorError(ValueError):
    """A generator file that cannot be accepted."""


@dataclass(frozen=True)
class Generator:
    """A loaded generator file: how to run one model on this machine."""

    name: str
    model: str
    """Recorded as the `model` of each origin."""
    command: tuple[str, ...]
    note_prompt: str
    hit_prompt: str
    title: str = ""
    description: str = ""
    folder: Path | None = None
    """The working directory of the command; `None` is the current one."""
    timeout: float = TIMEOUT

    def note(self, words: str, note: int) -> str:
        """The prompt for a single note: `note_prompt` with the words and the note name."""
        return fill(self.note_prompt, {"words": words, "note": note_name(note)})

    def hit(self, words: str) -> str:
        """The prompt for a drum hit: `hit_prompt` with the words."""
        return fill(self.hit_prompt, {"words": words})

    def arguments(self, prompt: str, seed: int, seconds: float, out: Path) -> list[str]:
        """The command with its placeholders replaced, one argument for each item."""
        values = {"prompt": prompt, "seed": str(seed), "seconds": f"{seconds:g}", "out": str(out)}
        return [fill(argument, values) for argument in self.command]


def fill(template: str, values: Mapping[str, str]) -> str:
    """`template` with each `{field}` replaced by its value, in one pass: a value that
    holds braces is not read again."""
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def _placeholders(value: str) -> list[str]:
    return _PLACEHOLDER.findall(value)


def problems(data: object) -> list[str]:
    """Every problem of a generator file's JSON object."""
    if not isinstance(data, dict):
        return ["not a JSON object"]
    found: list[str] = []
    for key in data:
        if key not in _REQUIRED and key not in _OPTIONAL:
            found.append(f"{key}: unknown field")
    for key in _REQUIRED:
        if key not in data:
            found.append(f"{key}: missing")
    if "format" in data and data["format"] != FORMAT:
        found.append(f"format: must be {FORMAT!r}, not {data['format']!r}")
    if "format_version" in data and (
        isinstance(data["format_version"], bool) or data["format_version"] != VERSION
    ):
        found.append(f"format_version: must be {VERSION}, not {data['format_version']!r}")
    if "name" in data and not (
        isinstance(data["name"], str) and soundset.NAME.fullmatch(data["name"])
    ):
        found.append(
            f"name: {data['name']!r} is not a name: use lower case letters, digits and hyphens"
        )
    for key in ("model", "title", "description", "folder", "note_prompt", "hit_prompt"):
        if key in data and not isinstance(data[key], str):
            found.append(f"{key}: must be text")
    if isinstance(data.get("model"), str) and not data["model"].strip():
        found.append("model: must not be empty")
    found += _command_problems(data.get("command")) if "command" in data else []
    for key, fields in (("note_prompt", NOTE_FIELDS), ("hit_prompt", HIT_FIELDS)):
        if isinstance(data.get(key), str):
            found += _prompt_problems(key, data[key], fields)
    if "timeout" in data:
        timeout = data["timeout"]
        if (
            isinstance(timeout, bool)
            or not isinstance(timeout, int | float)
            or not math.isfinite(timeout)
            or timeout <= 0
        ):
            found.append(f"timeout: must be a number of seconds above 0, not {timeout!r}")
    return found


def _command_problems(command: object) -> list[str]:
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(argument, str) for argument in command)
    ):
        return ["command: must be a list of at least one text argument"]
    if not command[0]:
        return ["command: the first argument, the program, must not be empty"]
    found: list[str] = []
    used: set[str] = set()
    for i, argument in enumerate(command):
        for field in _placeholders(argument):
            if field in COMMAND_FIELDS:
                used.add(field)
            else:
                found.append(
                    f"command[{i}]: unknown placeholder {{{field}}}; placeholders: "
                    + ", ".join(f"{{{f}}}" for f in COMMAND_FIELDS)
                )
    for field in ("prompt", "out"):
        if field not in used:
            found.append(f"command: has no {{{field}}}")
    return found


def _prompt_problems(key: str, prompt: str, fields: Sequence[str]) -> list[str]:
    found: list[str] = []
    used = _placeholders(prompt)
    for field in used:
        if field not in fields:
            found.append(
                f"{key}: unknown placeholder {{{field}}}; placeholders: "
                + ", ".join(f"{{{f}}}" for f in fields)
            )
    for field in fields:
        if field not in used:
            found.append(f"{key}: has no {{{field}}}")
    return found


def parse_generator(data: object, origin: str = "generator") -> Generator:
    """A generator from its JSON object; raises `GeneratorError` naming every problem."""
    found = problems(data)
    if found:
        raise GeneratorError(f"{origin}: " + "; ".join(found))
    assert isinstance(data, dict)
    folder = data.get("folder")
    return Generator(
        name=data["name"],
        model=data["model"],
        command=tuple(data["command"]),
        note_prompt=data["note_prompt"],
        hit_prompt=data["hit_prompt"],
        title=data.get("title", ""),
        description=data.get("description", ""),
        folder=Path(folder).expanduser() if folder else None,
        timeout=float(data.get("timeout", TIMEOUT)),
    )


def load_generator(path: Path) -> Generator:
    """The generator file at `path`. Raises `GeneratorError` when it cannot be read, a
    field is wrong or the file name differs from its `name`."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise GeneratorError(f"{path}: cannot read: {error}") from error
    generator = parse_generator(data, str(path))
    if generator.name != path.stem:
        raise GeneratorError(f"{path}: the file name must equal the name {generator.name!r}")
    return generator


class TakeError(Exception):
    """A take that failed: the reason, and the last lines the command printed."""

    def __init__(self, reason: str, output: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.output = output


RunTake = Callable[[Generator, str, int, float, Path], None]
"""Runs one take: the generator, the prompt, the seed, the seconds and the file to write.
Raises `TakeError` when no usable file was written."""


def _last_lines(output: bytes) -> str:
    lines = output.decode("utf-8", "replace").strip().splitlines()
    return "\n".join(lines[-LAST_LINES:])


def run_take(generator: Generator, prompt: str, seed: int, seconds: float, out: Path) -> None:
    """Run the generator's command once, without a shell, and check that it wrote `out`.

    Raises `TakeError` when the command cannot start, ends with a status other than 0,
    runs past the generator's timeout or writes no file."""
    arguments = generator.arguments(prompt, seed, seconds, out)
    try:
        process = subprocess.Popen(
            arguments,
            cwd=generator.folder,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        raise TakeError(f"the command cannot start: {error}") from error
    try:
        output, _ = process.communicate(timeout=generator.timeout)
    except subprocess.TimeoutExpired:
        _stop(process)
        output, _ = process.communicate()
        raise TakeError(
            f"ran past the timeout of {generator.timeout:g} s", _last_lines(output)
        ) from None
    if process.returncode != 0:
        raise TakeError(f"the command ended with status {process.returncode}", _last_lines(output))
    if not out.is_file():
        raise TakeError("the command wrote no file", _last_lines(output))


def _stop(process: "subprocess.Popen[bytes]") -> None:
    """Stop `process` and what it started (it runs in a session of its own)."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - Windows
            process.kill()
    except ProcessLookupError:  # pragma: no cover - it ended just now
        pass


def take_file(name: str, seed: int, note: int | None = None) -> str:
    """The file name of a take: `<name>-<asked note>-s<seed>.wav` (`#` written as `s`),
    or `<name>-s<seed>.wav` for a hit."""
    asked = f"-{note_name(note).replace('#', 's')}" if note is not None else ""
    return f"{name}{asked}-s{seed}.wav"


@dataclass(frozen=True)
class Take:
    """One take: what was asked and sent, and what came back."""

    file: str
    """The file name in `takes/`."""
    prompt: str
    seed: int
    seconds: float
    asked: int | None = None
    """The note asked for; `None` for a hit."""
    target: int | None = None
    """The note of `--notes` this take is for; `None` for a hit."""
    round: int = 1
    measured: Measurement | None = None
    """What `notes.measure` found; `None` for a hit or a take that failed."""
    error: str | None = None
    """Why the take failed: the command, or the file it wrote."""
    output: str = ""
    """The last lines the command printed, when it failed."""

    @property
    def path(self) -> Path:
        return Path(TAKES) / self.file

    def origin(self, generator: Generator) -> Origin:
        settings: dict[str, Any] = {"generator": generator.name}
        if self.asked is not None:
            settings["asked"] = note_name(self.asked)
        settings["seconds"] = self.seconds
        if self.asked is not None:
            settings["round"] = self.round
        return Origin("generated", generator.model, self.prompt, self.seed, settings)

    def answers(self, note: int, clean: float = CLEAN) -> bool:
        """Whether this take is clean and measured within `NEAR` semitones of `note`."""
        m = self.measured
        return m is not None and m.clean >= clean and abs(m.note - note) <= NEAR


@dataclass(frozen=True)
class GeneratedInstrument:
    """What `generate_notes` did."""

    name: str
    takes: tuple[Take, ...]
    unanswered: tuple[int, ...]
    """The notes of `--notes` that no clean take answered."""
    instrument: Instrument | None
    """The instrument built, with the paths of its sources in `takes/`; `None` when no
    take could be used."""
    error: str | None = None


@dataclass(frozen=True)
class GeneratedHit:
    """What `generate_hit` did."""

    name: str
    take: Take
    hit: SetHit | None
    error: str | None = None


def _run(
    run: RunTake,
    generator: Generator,
    staging: Path,
    file: str,
    prompt: str,
    seed: int,
    seconds: float,
    *,
    note: bool,
) -> tuple[Measurement | None, str | None, str]:
    """Run one take into `staging/file`, and measure it when it is a note."""
    path = staging / file
    try:
        run(generator, prompt, seed, seconds, path)
        if not path.is_file():
            raise TakeError("the command wrote no file")
        samples, rate = wav.read(path)
        if note:
            return measure(samples, rate), None, ""
        hits_module.prepare_hit(samples, rate, hits_module.SECONDS)
        return None, None, ""
    except TakeError as error:
        return None, error.reason, error.output
    except (OSError, ValueError) as error:
        return None, f"the file cannot be used: {error}", ""


def next_note(target: int, takes: Sequence[Take], clean: float = CLEAN) -> int:
    """The note to ask for next for `target`: when its closest clean take came out a whole
    number of octaves from the note asked for, that many octaves the other way;
    otherwise `target` again."""
    measured = [
        (t.measured.note, t.asked)
        for t in takes
        if t.measured is not None and t.asked is not None and t.measured.clean >= clean
    ]
    if not measured:
        return target
    came, asked = min(measured, key=lambda pair: abs(pair[0] - target))
    away = came - asked
    if away != 0 and away % 12 == 0:
        return target - away
    return target


def _staging(out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=".takes-", dir=out))


def _keep(staging: Path, out: Path, files: Sequence[str]) -> None:
    """Move `files` from `staging` into `out/takes/`."""
    (out / TAKES).mkdir(parents=True, exist_ok=True)
    for file in files:
        os.replace(staging / file, out / TAKES / file)


def _remove_takes(out: Path, before: set[str], document_after: Mapping[str, Any]) -> None:
    for take in sorted(before - soundset.all_takes(document_after)):
        (out / take).unlink(missing_ok=True)


def _moved(instrument: Instrument, staging: Path, out: Path) -> Instrument:
    """`instrument` with the paths of its sources in `out/takes/`."""

    def at(path: Path) -> Path:
        return out / TAKES / path.name if path.parent == staging else path

    return replace(
        instrument,
        regions=tuple(replace(r, source=at(r.source)) for r in instrument.regions),
        dropped=tuple((at(p), why) for p, why in instrument.dropped),
        notes=tuple(replace(n, path=at(n.path)) for n in instrument.notes),
    )


def generate_notes(
    name: str,
    generator: Generator,
    words: str,
    notes: Sequence[int],
    out: Path,
    *,
    seconds: float = NOTE_SECONDS,
    takes: int = 1,
    seed: int = 1,
    rounds: int = ROUNDS,
    prefer: Prefer = "clean",
    release: float = 0.25,
    span: tuple[int, int] | None = None,
    part: Literal["bass", "melody"] | None = None,
    keys: tuple[int, int] = (0, 127),
    min_velocity: int = 1,
    octave: int = 0,
    run: RunTake = run_take,
) -> GeneratedInstrument:
    """Ask `generator` for each of `notes`, measure the takes, ask again for the notes no
    clean take answered, and build the instrument `name` from all takes into the sound
    set `out` (`instrument.build`).

    Raises `ValueError` (a `SoundSetError` for the folder) before the generator is run
    when a value is out of range or the folder's `sound-set.json` cannot be accepted.
    When no take can be used, nothing in the set changes and the result has no
    instrument."""
    soundset.check_name(name)
    Plays(part, keys, min_velocity, octave).check()
    _check_options(notes, seconds, takes, rounds, prefer, release, span)
    document = soundset.read_document(out)
    before = soundset.generated_takes(document["instruments"].get(name, {}))
    asked_notes = list(dict.fromkeys(notes))
    used: set[str] = set()
    next_seed = {note: seed for note in asked_notes}
    done: list[Take] = []
    staging = _staging(out)
    try:
        for number in range(1, rounds + 1):
            if number == 1:
                asks = [(note, note) for note in asked_notes for _ in range(takes)]
            else:
                asks = []
                for note in asked_notes:
                    mine = [t for t in done if t.target == note]
                    if any(t.answers(note) for t in mine):
                        continue
                    ask = next_note(note, mine)
                    if 0 <= ask <= 127:
                        asks.append((note, ask))
            for target, ask in asks:
                take_seed = next_seed[target]
                while take_file(name, take_seed, ask) in used:
                    take_seed += 1
                next_seed[target] = take_seed + 1
                file = take_file(name, take_seed, ask)
                used.add(file)
                prompt = generator.note(words, ask)
                measured, error, output = _run(
                    run, generator, staging, file, prompt, take_seed, seconds, note=True
                )
                done.append(
                    Take(
                        file,
                        prompt,
                        take_seed,
                        seconds,
                        ask,
                        target,
                        number,
                        measured,
                        error,
                        output,
                    )
                )
        unanswered = tuple(
            n for n in asked_notes if not any(t.answers(n) for t in done if t.target == n)
        )
        usable = [t for t in done if t.error is None]
        if not usable:
            return GeneratedInstrument(name, tuple(done), unanswered, None, "no take can be used")
        files = [staging / t.file for t in usable]
        origins = {staging / t.file: t.origin(generator) for t in usable}
        try:
            built = instrument_module.build(
                name,
                files,
                out,
                prefer=prefer,
                release=release,
                span=span,
                origins=origins,
                part=part,
                keys=keys,
                min_velocity=min_velocity,
                octave=octave,
            )
        except ValueError as error:
            return GeneratedInstrument(name, tuple(done), unanswered, None, str(error))
        _keep(staging, out, [t.file for t in usable])
        _remove_takes(out, before, soundset.read_document(out))
        return GeneratedInstrument(name, tuple(done), unanswered, _moved(built, staging, out), None)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _check_options(
    notes: Sequence[int],
    seconds: float,
    takes: int,
    rounds: int,
    prefer: str,
    release: float,
    span: tuple[int, int] | None,
) -> None:
    if not notes:
        raise ValueError("give at least one note to ask for")
    for note in notes:
        if not 0 <= note <= 127:
            raise ValueError(f"note {note} is off the keyboard: 0 to 127")
    _positive("duration", seconds)
    if takes < 1:
        raise ValueError(f"takes must be 1 or more, not {takes}")
    if rounds < 1:
        raise ValueError(f"rounds must be 1 or more, not {rounds}")
    if prefer not in ("clean", "rich"):
        raise ValueError(f"prefer must be 'clean' or 'rich', not {prefer!r}")
    if not math.isfinite(release) or release < 0:
        raise ValueError(f"release must be 0 seconds or more, not {release}")
    if span is not None and not (0 <= span[0] <= span[1] <= 127):
        raise ValueError(f"the low and high notes must be from 0 to 127, low first, not {span}")


def _positive(what: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{what} must be more than 0 seconds, not {value}")


def generate_hit(
    name: str,
    generator: Generator,
    words: str,
    out: Path,
    *,
    duration: float = HIT_SECONDS,
    seed: int = 1,
    seconds: float = hits_module.SECONDS,
    run: RunTake = run_take,
) -> GeneratedHit:
    """Ask `generator` for one drum hit and make the hit `name` from it in the sound set
    `out` (`hits.make_hit`, `seconds` long).

    Raises `ValueError` (a `SoundSetError` for the folder) before the generator is run
    when a value is out of range or the folder's `sound-set.json` cannot be accepted.
    When the take cannot be used, nothing in the set changes and the result has no hit."""
    soundset.check_name(name)
    _positive("duration", duration)
    _positive("seconds", seconds)
    document = soundset.read_document(out)
    before = soundset.generated_takes(document["hits"].get(name, {}))
    file = take_file(name, seed)
    prompt = generator.hit(words)
    staging = _staging(out)
    try:
        _, error, output = _run(run, generator, staging, file, prompt, seed, duration, note=False)
        take = Take(file, prompt, seed, duration, error=error, output=output)
        if error is not None:
            return GeneratedHit(name, take, None, error)
        try:
            hit = hits_module.make_hit(
                name, staging / file, out, seconds=seconds, origin=take.origin(generator)
            )
        except ValueError as error:
            return GeneratedHit(name, take, None, str(error))
        _keep(staging, out, [file])
        _remove_takes(out, before, soundset.read_document(out))
        return GeneratedHit(name, take, hit)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def take_lines(result: GeneratedInstrument) -> list[str]:
    """One line for each take: asked, measured, clean, and kept or why not; then the
    notes no take answered."""
    kept: dict[str, str] = {}
    why: dict[str, str] = {}
    if result.instrument is not None:
        for region in result.instrument.regions:
            kept[region.source.name] = region.sample
        why = {path.name: reason for path, reason in result.instrument.dropped}
    lines = []
    for take in result.takes:
        assert take.asked is not None
        head = (
            f"{result.name}: round {take.round} asked {note_name(take.asked):<4} seed {take.seed}"
        )
        m = take.measured
        if take.error is not None:
            line = f"{head}  failed: {take.error}"
            if take.output:
                line += "\n" + "\n".join(f"    | {x}" for x in take.output.splitlines())
            lines.append(line)
            continue
        assert m is not None
        said = f"{head}  measured {m.name:<4} {m.cents:+4.0f}c  clean {100 * m.clean:5.1f}%"
        if take.file in kept:
            said += f"  kept as {kept[take.file]}"
        elif take.file in why:
            said += f"  left out: {why[take.file]}"
        elif result.instrument is None:
            said += "  not built"
        lines.append(said)
    lines += [
        f"{result.name}: {note_name(n)} ({n}) was not answered by a clean take"
        for n in result.unanswered
    ]
    return lines


def _check(paths: Sequence[str]) -> int:
    failed = 0
    for path in paths:
        try:
            generator = load_generator(Path(path))
        except GeneratorError as error:
            print(f"error: {error}", file=sys.stderr)
            failed += 1
            continue
        print(f"{path}: ok, generator {generator.name!r} for model {generator.model!r}")
    return 1 if failed else 0


def _note_list(values: Sequence[str]) -> list[int]:
    found = []
    for value in values:
        found.append(int(value) if re.fullmatch(r"\d+", value) else note_number(value))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.sounds.generate",
        description=(__doc__ or "").split("\n\n")[0],
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chk = commands.add_parser("check", help="check generator files")
    chk.add_argument("files", nargs="+")

    notes = commands.add_parser("notes", help="generate the notes of an instrument")
    notes.add_argument("name", help="the instrument's name")
    _common(notes)
    notes.add_argument(
        "--notes", nargs="+", required=True, help="the notes to ask for, for example E1 A1 D2"
    )
    notes.add_argument(
        "--duration",
        type=float,
        default=NOTE_SECONDS,
        help=f"seconds of each take ({NOTE_SECONDS:g} by default)",
    )
    notes.add_argument("--takes", type=int, default=1, help="takes of each note in round 1")
    notes.add_argument(
        "--rounds", type=int, default=ROUNDS, help=f"rounds of asking ({ROUNDS} by default)"
    )
    notes.add_argument("--prefer", choices=["clean", "rich"], default="clean")
    notes.add_argument("--release", type=float, default=0.25, help="release time in seconds")
    notes.add_argument("--low", help="the lowest note the part plays, for example E1")
    notes.add_argument("--high", help="the highest note the part plays, for example G3")
    notes.add_argument("--part", choices=["bass", "melody"])
    notes.add_argument("--keys", nargs=2, metavar=("LOW", "HIGH"))
    notes.add_argument("--min-velocity", type=int, default=1)
    notes.add_argument("--octave", type=int, default=0)

    hit = commands.add_parser("hit", help="generate a drum hit")
    hit.add_argument("name", help="the hit's name")
    _common(hit)
    hit.add_argument(
        "--duration",
        type=float,
        default=HIT_SECONDS,
        help=f"seconds of the take ({HIT_SECONDS:g} by default)",
    )
    hit.add_argument(
        "--seconds",
        type=float,
        default=hits_module.SECONDS,
        help=f"length of the hit ({hits_module.SECONDS} by default)",
    )
    band = commands.add_parser("band", help="make a whole sound set for a built-in band")
    band.add_argument("band", help="the name of a built-in band (python -m mpc_iml.bands list)")
    band.add_argument("--generator", type=Path, required=True, help="a generator file")
    band.add_argument("--out", type=Path, required=True, help="the sound set folder")
    band.add_argument(
        "--words",
        action="append",
        default=[],
        metavar="NAME=WORDS",
        help="replace the words of one player or hit; can be given several times",
    )
    band.add_argument("--only", nargs="+", metavar="NAME", help="make only these players and hits")
    band.add_argument("--seed", type=int, default=1, help="the first seed (1 by default)")
    band.add_argument(
        "--rounds", type=int, default=ROUNDS, help=f"rounds of asking ({ROUNDS} by default)"
    )
    band.add_argument("--plan", action="store_true", help="print what would be asked for and stop")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.files)
    if args.command == "band":
        return _band(args)
    try:
        generator = load_generator(args.generator)
        if args.command == "notes":
            return _notes(args, generator)
        return _hit(args, generator)
    except ValueError as error:
        print(f"error: {error}")
        return 1


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--generator", type=Path, required=True, help="a generator file")
    parser.add_argument("--words", required=True, help="the sound, in words")
    parser.add_argument("--out", type=Path, required=True, help="the sound set folder")
    parser.add_argument("--seed", type=int, default=1, help="the first seed (1 by default)")


def _notes(args: argparse.Namespace, generator: Generator) -> int:
    if (args.low is None) != (args.high is None):
        raise ValueError("give both --low and --high, or neither")
    span = (note_number(args.low), note_number(args.high)) if args.low else None
    keys = (note_number(args.keys[0]), note_number(args.keys[1])) if args.keys else (0, 127)
    result = generate_notes(
        args.name,
        generator,
        args.words,
        _note_list(args.notes),
        args.out,
        seconds=args.duration,
        takes=args.takes,
        seed=args.seed,
        rounds=args.rounds,
        prefer=args.prefer,
        release=args.release,
        span=span,
        part=args.part,
        keys=keys,
        min_velocity=args.min_velocity,
        octave=args.octave,
    )
    for line in take_lines(result):
        print(line)
    if result.instrument is None:
        print(f"{args.name}: {result.error}; the sound set is unchanged")
        return 1
    print(instrument_module.report(result.instrument))
    return 0


def _hit(args: argparse.Namespace, generator: Generator) -> int:
    result = generate_hit(
        args.name,
        generator,
        args.words,
        args.out,
        duration=args.duration,
        seed=args.seed,
        seconds=args.seconds,
    )
    take = result.take
    if result.hit is None:
        print(f"{args.name}: seed {take.seed}  failed: {result.error}; the sound set is unchanged")
        for line in take.output.splitlines():
            print(f"    | {line}")
        return 1
    hit = result.hit
    print(
        f"{hit.name}: hits/{hit.name}.wav  {hit.seconds:.2f} s  level {hit.gain_db:+.1f} dB  "
        f"from {TAKES}/{hit.file}"
    )
    return 0


def _band(args: argparse.Namespace) -> int:
    from mpc_iml.bands import load_bands
    from mpc_iml.content import ContentError
    from mpc_iml.sounds import bandset

    try:
        bands = load_bands()
        if args.band not in bands:
            raise ValueError(f"no built-in band {args.band!r}; bands: {', '.join(bands)}")
        band = bands[args.band]
        words: dict[str, str] = {}
        for given in args.words:
            name, sep, said = given.partition("=")
            if not sep:
                raise ValueError(f"--words {given!r}: write it as <name>=<words>")
            words[name] = said
        planned = bandset.plan(band, words, args.only)
        if args.rounds < 1:
            raise ValueError(f"rounds must be 1 or more, not {args.rounds}")
        for line in bandset.plan_lines(planned):
            print(line)
        if args.plan:
            return 0
        generator = load_generator(args.generator)

        def done(made: bandset.Made) -> None:
            if made.instrument is not None:
                for line in take_lines(made.instrument):
                    print(line)
                if made.instrument.instrument is not None:
                    print(instrument_module.report(made.instrument.instrument))
            elif made.hit is not None:
                take = made.hit.take
                if made.hit.hit is None:
                    print(f"{made.name}: seed {take.seed}  failed: {made.hit.error}")
                    for line in take.output.splitlines():
                        print(f"    | {line}")
                else:
                    hit = made.hit.hit
                    print(
                        f"{hit.name}: hits/{hit.name}.wav  {hit.seconds:.2f} s  "
                        f"level {hit.gain_db:+.1f} dB  from {TAKES}/{hit.file}"
                    )

        results = bandset.generate_band(
            band,
            generator,
            args.out,
            words=words,
            only=args.only,
            seed=args.seed,
            rounds=args.rounds,
            done=done,
        )
    except (ValueError, ContentError) as error:
        print(f"error: {error}")
        return 1
    for made in results:
        print(bandset.made_line(made))
    for line in bandset.next_lines(band, args.out):
        print(line)
    return 0 if all(made.made for made in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
