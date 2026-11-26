"""Band files for `ensemble`: content, tempo, players and an audition pattern (#276,
ADR 0014).

A band is the content `ensemble` plays (a bass loop, a melody loop and a progression,
each a built-in file), the tempo it is written for, its players and what each of them
plays (the `plays` of ADR 0013), and named bars of drums with the bars of an audition:

    {"format": "mpc-iml-band", "format_version": 1, "name": "lofi", "preset": "ensemble",
     "tempo": 76,
     "content": {"bass_loop": "haze-bass", "loop": "haze-keys", "progression": "haze"},
     "players": [{"name": "bass", "title": "Bass", "description": "…",
                  "plays": {"part": "bass", "keys": [0, 127], "min_velocity": 1,
                            "octave": 1},
                  "release": 0.12, "prefer": "clean",
                  "sound": {"words": "Upright bass, plucked", "seconds": 3, "takes": 2}}],
     "hits": {"kick": {"words": "Dusty kick drum", "seconds": 0.6}, "snare": {…},
              "hat": {…}},
     "patterns": {"groove-1": {"kick": [70, 0, …], "snare": […], "hat": […]}},
     "audition": ["groove-1", "groove-1"]}

`sound` and `hits` are the default words a model is asked with for each player and
each drum hit (#286): they say what a player sounds like, never what it plays
(RFC 0006), and the musician can replace them. A band is
chosen with the existing controls `bass-loop`, `loop` and `progression` and the tempo
of the DAW (`Band.controls`): no engine control, no protocol change. Only the built-in
bands are read (`<mpc_iml>/bands/ensemble/<name>.json`).

    python -m mpc_iml.bands check <file>…
    python -m mpc_iml.bands list
"""

import argparse
import functools
import json
import math
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mpc_iml.content import _NAME, Content, ContentError, _fail, _header, _read
from mpc_iml.loops import KIND as LOOPS
from mpc_iml.loops import parse_loop
from mpc_iml.plays import PARTS, Plays
from mpc_iml.plays import problems as plays_problems
from mpc_iml.progressions import KIND as PROGRESSIONS

__all__ = [
    "BAND_FORMAT",
    "CONTENT",
    "DRUMS",
    "KIND",
    "MAX_BARS",
    "PREFER",
    "PRESET",
    "RELEASE",
    "STEPS",
    "TEMPO_RANGE",
    "HIT_DRUMS",
    "Band",
    "Hit",
    "Player",
    "Sound",
    "load_bands",
    "main",
    "parse_band",
]

BAND_FORMAT = "mpc-iml-band"
PRESET = "ensemble"
"""The preset band files belong to."""
KIND = "bands"
"""The content folder of band files: `<mpc_iml>/bands/ensemble/`."""
CONTENT = {"bass_loop": "bass-loop", "loop": "loop", "progression": "progression"}
"""Each field of `content` and the `ensemble` control that chooses it."""
DRUMS = ("kick", "snare", "hat")
"""The rows of a pattern, as in the web demo's grid (`webdemo.sim.DRUMS`)."""
STEPS = 16
TEMPO_RANGE = (60, 160)
"""The tempos the web demo's simulation accepts (`webdemo.sim.TEMPO_RANGE`)."""
MAX_BARS = 64
"""The most bars the simulation accepts (`webdemo.sim.MAX_BARS`)."""
PREFER = ("clean", "rich")
"""What `sounds.instrument --prefer` takes."""
RELEASE = (0.0, 10.0)
"""The release times a player may give, in seconds."""

_TOP = {"format", "format_version", "name", "title", "description", "preset", "tempo"}
_TOP |= {"content", "players", "hits", "patterns", "audition"}
_PLAYER = ("name", "title", "description", "plays", "release", "prefer", "sound")
_SOUND = ("words", "seconds", "takes")
_HIT = ("words", "seconds")
HIT_DRUMS = DRUMS
"""The hits every band has: the audition plays them."""
_BUILT_IN = Content(PRESET, "mpc_iml")


@dataclass(frozen=True)
class Sound:
    """What a player sounds like by default (#286): the words a model is asked with,
    how long a note is asked for, in seconds, and how many takes of each note round 1
    asks for."""

    words: str
    seconds: float
    takes: int


@dataclass(frozen=True)
class Hit:
    """A drum hit of a band (#286): the words a model is asked with and the length of
    the hit that is kept, in seconds (`sounds.hits --seconds`)."""

    name: str
    words: str
    seconds: float


@dataclass(frozen=True)
class Player:
    """A player of a band: what it plays and the defaults for building its instrument
    (`sounds.instrument --release`, `--prefer`)."""

    name: str
    title: str
    description: str
    plays: Plays
    release: float
    prefer: str
    sound: Sound


@dataclass(frozen=True)
class Band:
    """A parsed band file."""

    name: str
    title: str
    description: str
    tempo: int
    content: Mapping[str, str]
    """`bass_loop`, `loop` and `progression`: names of built-in files."""
    players: tuple[Player, ...]
    hits: Mapping[str, Hit]
    """The drum hits, by name, in file order; `kick`, `snare` and `hat` are always there."""
    patterns: Mapping[str, Mapping[str, tuple[int, ...]]]
    audition: tuple[str, ...]
    origin: str = ""

    def grid(self) -> list[dict[str, list[int]]]:
        """The audition as the grid `webdemo.sim.simulate` takes: one bar per name."""
        return [{d: list(self.patterns[p][d]) for d in DRUMS} for p in self.audition]

    def controls(self) -> dict[str, str]:
        """What `ensemble` is set to for this band, by control name; the tempo is
        the DAW's (`tempo`)."""
        return {control: self.content[field] for field, control in CONTENT.items()}

    def part(self, part: str) -> tuple[Player, ...]:
        """The players of `part`, in file order."""
        return tuple(p for p in self.players if p.plays.part == part)


@functools.cache
def _built_in() -> dict[str, frozenset[str]]:
    """The names of the built-in files by kind: `bass`, `melody` and `progression`."""
    names: dict[str, set[str]] = {"bass": set(), "melody": set(), "progression": set()}
    for stem, data, origin in _read([_BUILT_IN], LOOPS, PRESET):
        names[parse_loop(data, origin).part].add(stem)
    names["progression"] = {stem for stem, _, _ in _read([_BUILT_IN], PROGRESSIONS, PRESET)}
    return {kind: frozenset(found) for kind, found in names.items()}


def _object(value: Any, origin: str, where: str, allowed: Sequence[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _fail(origin, f"{where} must be an object")
    for key in value:
        if key not in allowed:
            raise _fail(origin, f"{where}: unknown field {key!r}; fields: {', '.join(allowed)}")
    for key in allowed:
        if key not in value:
            raise _fail(origin, f"{where}: {key} is required")
    return value


def _text(value: Any, origin: str, where: str) -> str:
    if not isinstance(value, str):
        raise _fail(origin, f"{where} must be text, got {value!r}")
    return value


def _seconds(value: Any, origin: str, where: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, int | float)
        or not math.isfinite(value)
        or value <= 0
    ):
        raise _fail(origin, f"{where} must be a number of seconds above 0, got {value!r}")
    return float(value)


def _words(value: Any, origin: str, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail(origin, f"{where} must be words that are not empty, got {value!r}")
    return value


def _sound(value: Any, origin: str, where: str) -> Sound:
    data = _object(value, origin, where, _SOUND)
    takes = data["takes"]
    if isinstance(takes, bool) or not isinstance(takes, int) or takes < 1:
        raise _fail(origin, f"{where}.takes must be a whole number, 1 or more, got {takes!r}")
    return Sound(
        _words(data["words"], origin, f"{where}.words"),
        _seconds(data["seconds"], origin, f"{where}.seconds"),
        takes,
    )


def _hits(value: Any, origin: str) -> dict[str, Hit]:
    if not isinstance(value, dict):
        raise _fail(origin, "hits must map hit names to their words and seconds")
    hits: dict[str, Hit] = {}
    for name, entry in value.items():
        if not _NAME.fullmatch(name):
            raise _fail(
                origin,
                f"hits: {name!r} is not a name: use lower case letters, digits and hyphens",
            )
        data = _object(entry, origin, f"hits.{name}", _HIT)
        hits[name] = Hit(
            name,
            _words(data["words"], origin, f"hits.{name}.words"),
            _seconds(data["seconds"], origin, f"hits.{name}.seconds"),
        )
    for drum in HIT_DRUMS:
        if drum not in hits:
            raise _fail(origin, f"hits: {drum} is required: the audition plays it")
    return hits


def _tempo(value: Any, origin: str) -> int:
    low, high = TEMPO_RANGE
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise _fail(origin, f"tempo must be a whole number of BPM, {low}-{high}, got {value!r}")
    return value


def _content(value: Any, origin: str) -> dict[str, str]:
    data = _object(value, origin, "content", tuple(CONTENT))
    built_in = _built_in()
    kinds = {"bass_loop": "bass", "loop": "melody", "progression": "progression"}
    for field, kind in kinds.items():
        name = data[field]
        known = built_in[kind]
        what = "progression" if kind == "progression" else f"{kind} loop"
        if name not in known:
            raise _fail(
                origin,
                f"content.{field}: {name!r} is not a built-in {what}; {what}s: "
                + ", ".join(sorted(known)),
            )
    return {field: data[field] for field in CONTENT}


def _player(value: Any, origin: str, where: str) -> Player:
    data = _object(value, origin, where, _PLAYER)
    name = data["name"]
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise _fail(
            origin,
            f"{where}.name: {name!r} is not a name: use lower case letters, digits and hyphens",
        )
    found = plays_problems(data["plays"], f"{where}.plays", part_required=True)
    if found:
        raise _fail(origin, "; ".join(found))
    release = data["release"]
    low, high = RELEASE
    if (
        isinstance(release, bool)
        or not isinstance(release, int | float)
        or not math.isfinite(release)
        or not low <= release <= high
    ):
        raise _fail(origin, f"{where}.release must be {low:g}-{high:g} seconds, got {release!r}")
    if data["prefer"] not in PREFER:
        raise _fail(origin, f"{where}.prefer must be 'clean' or 'rich', got {data['prefer']!r}")
    return Player(
        name,
        _text(data["title"], origin, f"{where}.title"),
        _text(data["description"], origin, f"{where}.description"),
        Plays.from_json(data["plays"]),
        float(release),
        data["prefer"],
        _sound(data["sound"], origin, f"{where}.sound"),
    )


def _players(value: Any, origin: str) -> tuple[Player, ...]:
    if not isinstance(value, list):
        raise _fail(origin, "players must be a list of players")
    players: list[Player] = []
    for i, entry in enumerate(value):
        player = _player(entry, origin, f"players[{i}]")
        if any(p.name == player.name for p in players):
            raise _fail(origin, f"players[{i}]: two players are named {player.name!r}")
        players.append(player)
    for part in PARTS:
        if not any(p.plays.part == part for p in players):
            raise _fail(origin, f"players: no player plays the {part} part")
    return tuple(players)


def _patterns(value: Any, origin: str) -> dict[str, dict[str, tuple[int, ...]]]:
    if not isinstance(value, dict) or not value:
        raise _fail(origin, "patterns must map pattern names to bars of drums")
    patterns: dict[str, dict[str, tuple[int, ...]]] = {}
    for name, entry in value.items():
        if not _NAME.fullmatch(name):
            raise _fail(
                origin,
                f"patterns: {name!r} is not a name: use lower case letters, digits and hyphens",
            )
        data = _object(entry, origin, f"patterns.{name}", DRUMS)
        rows: dict[str, tuple[int, ...]] = {}
        for drum in DRUMS:
            steps = data[drum]
            if (
                not isinstance(steps, list)
                or len(steps) != STEPS
                or any(isinstance(s, bool) or not isinstance(s, int) for s in steps)
                or any(not 0 <= s <= 127 for s in steps)
            ):
                raise _fail(
                    origin,
                    f"patterns.{name}.{drum} must be {STEPS} steps of 0 (no hit) or a"
                    " velocity 1-127",
                )
            rows[drum] = tuple(steps)
        patterns[name] = rows
    return patterns


def _audition(value: Any, origin: str, patterns: Mapping[str, Any]) -> tuple[str, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_BARS:
        raise _fail(origin, f"audition must be a list of 1-{MAX_BARS} pattern names")
    for i, name in enumerate(value):
        if not isinstance(name, str) or name not in patterns:
            raise _fail(
                origin,
                f"audition[{i}]: {name!r} names no pattern; patterns: {', '.join(patterns)}",
            )
    return tuple(value)


def parse_band(data: Any, origin: str = "band") -> Band:
    """Validate a band file's JSON object; raises `ContentError` naming `origin` and
    the field, for example `lofi.json: players[1]: two players are named 'keys'`."""
    name, title, description = _header(data, BAND_FORMAT, origin, PRESET)
    unknown = sorted(set(data) - _TOP)
    if unknown:
        raise _fail(origin, f"unknown field {unknown[0]!r}")
    for field in ("tempo", "content", "players", "hits", "patterns", "audition"):
        if field not in data:
            raise _fail(origin, f"{field} is required")
    tempo = _tempo(data["tempo"], origin)
    content = _content(data["content"], origin)
    players = _players(data["players"], origin)
    hits = _hits(data["hits"], origin)
    patterns = _patterns(data["patterns"], origin)
    audition = _audition(data["audition"], origin, patterns)
    return Band(name, title, description, tempo, content, players, hits, patterns, audition, origin)


def _read_file(path: Path) -> Band:
    origin = str(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ContentError(f"{origin}: cannot read: {error}") from error
    band = parse_band(data, origin)
    if band.name != path.stem:
        raise ContentError(f"{origin}: the file name must equal the name {band.name!r}")
    return band


def load_bands() -> dict[str, Band]:
    """The built-in bands, by name. Raises `ContentError` when a file is invalid or its
    file name differs from its `name`."""
    return {
        stem: parse_band(data, origin) for stem, data, origin in _read([_BUILT_IN], KIND, PRESET)
    }


def _check(paths: Sequence[str]) -> int:
    failed = 0
    for path in paths:
        try:
            band = _read_file(Path(path))
        except ContentError as error:
            print(f"error: {error}", file=sys.stderr)
            failed += 1
            continue
        print(
            f"{path}: ok, band {band.name!r}, {len(band.players)} player(s),"
            f" {len(band.hits)} hit(s), {len(band.patterns)} pattern(s),"
            f" an audition of {len(band.audition)} bar(s)"
        )
    return 1 if failed else 0


def _line(band: Band) -> str:
    content = " ".join(f"{control} {name}" for control, name in band.controls().items())
    players = ", ".join(f"{p.name} ({p.plays.part})" for p in band.players)
    return f"{band.name}: {band.tempo} BPM, {content}; players {players}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.bands", description="Check and list band files."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chk = commands.add_parser("check", help="validate band files")
    chk.add_argument("files", nargs="+")
    commands.add_parser("list", help="list the built-in bands")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.files)
    try:
        bands = load_bands()
    except ContentError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for band in bands.values():
        print(_line(band))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
