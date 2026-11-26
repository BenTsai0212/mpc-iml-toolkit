"""Sound set folders: the file that records what a set holds (#272, ADR 0013).

A sound set is a folder with the instruments and drum hits made for one band:

    <folder>/sound-set.json
    <folder>/<instrument>.sfz
    <folder>/samples/<instrument>-<note>.wav
    <folder>/hits/<hit>.wav

`sound-set.json` records each instrument (its SFZ file, the settings it was built
with, and for every source recording what was measured in it and its region or why it
was left out) and each hit. Source recordings are named by file name only and are not
copied into the set; the files the set holds are named by a path relative to the
folder.

`python -m mpc_iml.sounds.soundset check <folder>` reports every problem and ends with
status 1 when there is one.
"""

import argparse
import json
import math
import os
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

FILE = "sound-set.json"
FORMAT = "mpc-iml-sound-set"
VERSION = 1

NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
"""Instrument and hit names: lower case letters, digits and hyphens (as in ADR 0010)."""

MEASURED = (
    "start",
    "frequency",
    "note",
    "cents",
    "clean",
    "rich",
    "other",
    "attack_cents",
    "length",
    "seconds",
    "peak_db",
)
"""The fields of `notes.Measurement`, in its order."""


class SoundSetError(ValueError):
    """A `sound-set.json` that cannot be accepted."""


def check_name(name: str) -> str:
    """`name`, or `ValueError` when it is not lower case letters, digits and hyphens."""
    if not NAME.fullmatch(name):
        raise ValueError(f"{name!r} is not a name: use lower case letters, digits and hyphens")
    return name


@dataclass(frozen=True)
class Origin:
    """Where a recording came from: `recorded`, or `generated` by a model."""

    kind: Literal["recorded", "generated"] = "recorded"
    model: str | None = None
    prompt: str | None = None
    seed: int | None = None
    settings: Mapping[str, Any] | None = None
    """Free settings of the model; only for `generated`."""

    def to_json(self) -> dict[str, Any]:
        if self.kind == "recorded":
            return {"kind": "recorded"}
        if self.model is None or self.prompt is None or self.seed is None:
            raise ValueError("a generated origin needs a model, a prompt and a seed")
        out: dict[str, Any] = {
            "kind": "generated",
            "model": self.model,
            "prompt": self.prompt,
            "seed": self.seed,
        }
        if self.settings is not None:
            out["settings"] = dict(self.settings)
        return out

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Origin":
        if data["kind"] == "recorded":
            return cls()
        return cls("generated", data["model"], data["prompt"], data["seed"], data.get("settings"))


@dataclass(frozen=True)
class SetRegion:
    """One region of an instrument in a loaded set."""

    sample: Path
    low: int
    high: int
    centre: int
    tune: int
    gain_db: float
    file: str
    """The source recording's file name."""
    origin: Origin | None = None


@dataclass(frozen=True)
class SetInstrument:
    name: str
    sfz: Path
    regions: tuple[SetRegion, ...]
    settings: Mapping[str, Any] = field(default_factory=dict)
    span: tuple[int, int] | None = None
    uncovered: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class SetHit:
    name: str
    sample: Path
    file: str
    seconds: float
    gain_db: float
    origin: Origin | None = None


@dataclass(frozen=True)
class SoundSet:
    folder: Path
    instruments: Mapping[str, SetInstrument]
    hits: Mapping[str, SetHit]


def empty() -> dict[str, Any]:
    """The document of a set with nothing in it."""
    return {"format": FORMAT, "format_version": VERSION, "instruments": {}, "hits": {}}


class _Checker:
    """Collects every problem of a document; with `folder`, also the files it names that
    the folder lacks."""

    def __init__(self, folder: Path | None) -> None:
        self.folder = folder
        self.problems: list[str] = []

    def say(self, where: str, problem: str) -> None:
        self.problems.append(f"{where}: {problem}" if where else problem)

    def fields(
        self, value: object, where: str, required: Sequence[str], optional: Sequence[str] = ()
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            self.say(where, "must be an object")
            return None
        for key in value:
            if key not in required and key not in optional:
                self.say(f"{where}.{key}" if where else key, "unknown field")
        for key in required:
            if key not in value:
                self.say(f"{where}.{key}" if where else key, "missing")
        return value

    def integer(
        self, value: object, where: str, low: int | None = None, high: int | None = None
    ) -> bool:
        if isinstance(value, bool) or not isinstance(value, int):
            self.say(where, "must be a whole number")
            return False
        if (low is not None and value < low) or (high is not None and value > high):
            self.say(where, f"must be from {low} to {high}")
            return False
        return True

    def number(self, value: object, where: str) -> bool:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            self.say(where, "must be a number")
            return False
        return True

    def text(self, value: object, where: str) -> bool:
        if not isinstance(value, str):
            self.say(where, "must be text")
            return False
        return True

    def file_name(self, value: object, where: str) -> None:
        if not self.text(value, where):
            return
        assert isinstance(value, str)
        if "/" in value or "\\" in value:
            self.say(where, f"{value} holds a path separator: give the file name only")
        elif value in ("", ".", ".."):
            self.say(where, f"{value!r} is not a file name")

    def path(self, value: object, where: str) -> None:
        """A path relative to the folder, inside it, of a file the folder holds."""
        if not self.text(value, where):
            return
        assert isinstance(value, str)
        posix = PurePosixPath(value)
        if value == "" or "\\" in value or posix.is_absolute() or re.match(r"[A-Za-z]:", value):
            self.say(where, f"{value!r} must be a path relative to the folder")
        elif ".." in posix.parts:
            self.say(where, f"{value} leaves the folder")
        elif self.folder is not None and not (self.folder / value).is_file():
            self.say(where, f"{value} is missing")

    def origin(self, value: object, where: str) -> None:
        data = self.fields(value, where, ["kind"], ["model", "prompt", "seed", "settings"])
        if data is None:
            return
        kind = data.get("kind")
        if kind == "recorded":
            for key in ("model", "prompt", "seed", "settings"):
                if key in data:
                    self.say(f"{where}.{key}", "only for a generated origin")
        elif kind == "generated":
            for key in ("model", "prompt", "seed"):
                if key not in data:
                    self.say(f"{where}.{key}", "missing")
            if "model" in data:
                self.text(data["model"], f"{where}.model")
            if "prompt" in data:
                self.text(data["prompt"], f"{where}.prompt")
            if "seed" in data:
                self.integer(data["seed"], f"{where}.seed")
            if "settings" in data and not isinstance(data["settings"], dict):
                self.say(f"{where}.settings", "must be an object")
        elif "kind" in data:
            self.say(f"{where}.kind", f"must be 'recorded' or 'generated', not {kind!r}")

    def measured(self, value: object, where: str) -> None:
        data = self.fields(value, where, MEASURED)
        if data is None:
            return
        for key in MEASURED:
            if key not in data:
                continue
            here = f"{where}.{key}"
            if key in ("start", "note"):
                self.integer(data[key], here, 0 if key == "start" else None)
            elif key == "other":
                other = data[key]
                if other is not None and not (
                    isinstance(other, list)
                    and len(other) == 2
                    and all(self.number(x, here) for x in other)
                ):
                    self.say(here, "must be null or [frequency, dB]")
            else:
                self.number(data[key], here)

    def key_pair(self, value: object, where: str) -> None:
        if not (isinstance(value, list) and len(value) == 2):
            self.say(where, "must be [low, high]")
            return
        if self.integer(value[0], where, 0, 127) and self.integer(value[1], where, 0, 127):
            if value[0] > value[1]:
                self.say(where, "low is above high")

    def region(self, value: object, where: str) -> None:
        data = self.fields(value, where, ["sample", "low", "high", "centre", "tune", "gain_db"])
        if data is None:
            return
        if "sample" in data:
            self.path(data["sample"], f"{where}.sample")
        for key in ("low", "high", "centre"):
            if key in data:
                self.integer(data[key], f"{where}.{key}", 0, 127)
        if "tune" in data:
            self.integer(data["tune"], f"{where}.tune")
        if "gain_db" in data:
            self.number(data["gain_db"], f"{where}.gain_db")

    def source(self, value: object, where: str) -> None:
        data = self.fields(value, where, ["file"], ["measured", "region", "left_out", "origin"])
        if data is None:
            return
        if "file" in data:
            self.file_name(data["file"], f"{where}.file")
        if "measured" in data:
            self.measured(data["measured"], f"{where}.measured")
        has_region, has_reason = "region" in data, "left_out" in data
        if has_region and has_reason:
            self.say(where, "has both region and left_out: give one")
        elif not has_region and not has_reason:
            self.say(where, "has neither region nor left_out: give one")
        if has_region:
            self.region(data["region"], f"{where}.region")
        if has_reason:
            self.text(data["left_out"], f"{where}.left_out")
        if "origin" in data:
            self.origin(data["origin"], f"{where}.origin")

    def instrument(self, value: object, where: str) -> None:
        data = self.fields(value, where, ["sfz", "settings", "span", "uncovered", "files"])
        if data is None:
            return
        if "sfz" in data:
            self.path(data["sfz"], f"{where}.sfz")
        if "settings" in data:
            settings = self.fields(
                data["settings"], f"{where}.settings", ["prefer", "release", "clean"]
            )
            if settings is not None:
                if "prefer" in settings and settings["prefer"] not in ("clean", "rich"):
                    self.say(f"{where}.settings.prefer", "must be 'clean' or 'rich'")
                for key in ("release", "clean"):
                    if key in settings:
                        self.number(settings[key], f"{where}.settings.{key}")
        if data.get("span") is not None:
            self.key_pair(data["span"], f"{where}.span")
        if "uncovered" in data:
            if isinstance(data["uncovered"], list):
                for i, gap in enumerate(data["uncovered"]):
                    self.key_pair(gap, f"{where}.uncovered[{i}]")
            else:
                self.say(f"{where}.uncovered", "must be a list")
        if "files" in data:
            if isinstance(data["files"], list):
                for i, entry in enumerate(data["files"]):
                    self.source(entry, f"{where}.files[{i}]")
            else:
                self.say(f"{where}.files", "must be a list")

    def hit(self, value: object, where: str) -> None:
        data = self.fields(value, where, ["sample", "file", "seconds", "gain_db"], ["origin"])
        if data is None:
            return
        if "sample" in data:
            self.path(data["sample"], f"{where}.sample")
        if "file" in data:
            self.file_name(data["file"], f"{where}.file")
        for key in ("seconds", "gain_db"):
            if key in data:
                self.number(data[key], f"{where}.{key}")
        if "origin" in data:
            self.origin(data["origin"], f"{where}.origin")

    def named(self, value: object, where: str, each: str) -> None:
        if not isinstance(value, dict):
            self.say(where, "must be an object")
            return
        for name, entry in value.items():
            if not NAME.fullmatch(name):
                self.say(
                    f"{where}.{name}", "not a name: use lower case letters, digits and hyphens"
                )
            (self.instrument if each == "instrument" else self.hit)(entry, f"{where}.{name}")

    def document(self, value: object) -> None:
        data = self.fields(value, "", ["format", "format_version", "instruments", "hits"])
        if data is None:
            return
        if "format" in data and data["format"] != FORMAT:
            self.say("format", f"must be {FORMAT!r}, not {data['format']!r}")
        if "format_version" in data and (
            isinstance(data["format_version"], bool) or data["format_version"] != VERSION
        ):
            self.say("format_version", f"must be {VERSION}, not {data['format_version']!r}")
        if "instruments" in data:
            self.named(data["instruments"], "instruments", "instrument")
        if "hits" in data:
            self.named(data["hits"], "hits", "hit")


def validate(data: object, folder: Path | None = None) -> list[str]:
    """Every problem of the document `data`; with `folder`, also each SFZ file and sample
    it names that `folder` lacks."""
    checker = _Checker(folder)
    checker.document(data)
    return checker.problems


def _parse(folder: Path) -> tuple[object, list[str]]:
    path = folder / FILE
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, [f"no {FILE} in {folder}"]
    except OSError as error:
        return None, [f"cannot read {FILE}: {error}"]
    try:
        return json.loads(text), []
    except json.JSONDecodeError as error:
        return None, [f"not JSON: {error}"]


def problems(folder: Path) -> list[str]:
    """Every problem of the set in `folder`: its format, and each file it names that the
    folder lacks."""
    data, found = _parse(folder)
    return found or validate(data, folder)


def _raise(problems: Sequence[str]) -> None:
    raise SoundSetError(f"{FILE} cannot be accepted: " + "; ".join(problems))


def read_document(folder: Path) -> dict[str, Any]:
    """The document in `folder`, checked for its format (not for the files it names), or
    an empty one when the folder has none. Raises `SoundSetError`."""
    if not (folder / FILE).exists():
        return empty()
    data, found = _parse(folder)
    found = found or validate(data)
    if found:
        _raise(found)
    assert isinstance(data, dict)
    return data


def write_document(folder: Path, data: Mapping[str, Any]) -> None:
    """Check `data` and write it as `folder/sound-set.json`, replacing the file whole."""
    found = validate(data)
    if found:
        raise SoundSetError("cannot write: " + "; ".join(found))
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{FILE}.tmp"
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, folder / FILE)


def _origin(data: Mapping[str, Any]) -> Origin | None:
    return Origin.from_json(data["origin"]) if "origin" in data else None


def load(folder: Path) -> SoundSet:
    """The set in `folder`. Raises `SoundSetError` naming every problem, also each SFZ
    file and sample the file names that the folder lacks."""
    data, found = _parse(folder)
    found = found or validate(data, folder)
    if found:
        _raise(found)
    assert isinstance(data, dict)
    instruments = {}
    for name, entry in data["instruments"].items():
        regions = tuple(
            SetRegion(
                sample=folder / f["region"]["sample"],
                low=f["region"]["low"],
                high=f["region"]["high"],
                centre=f["region"]["centre"],
                tune=f["region"]["tune"],
                gain_db=float(f["region"]["gain_db"]),
                file=f["file"],
                origin=_origin(f),
            )
            for f in entry["files"]
            if "region" in f
        )
        span = entry["span"]
        instruments[name] = SetInstrument(
            name=name,
            sfz=folder / entry["sfz"],
            regions=regions,
            settings=entry["settings"],
            span=(span[0], span[1]) if span is not None else None,
            uncovered=tuple((a, b) for a, b in entry["uncovered"]),
        )
    hits = {
        name: SetHit(
            name=name,
            sample=folder / entry["sample"],
            file=entry["file"],
            seconds=float(entry["seconds"]),
            gain_db=float(entry["gain_db"]),
            origin=_origin(entry),
        )
        for name, entry in data["hits"].items()
    }
    return SoundSet(folder, instruments, hits)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.sounds.soundset", description="Check a sound set folder."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    chk = commands.add_parser("check", help=f"check {FILE} and the files it names")
    chk.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    found = problems(args.folder)
    if found:
        for problem in found:
            print(f"error: {args.folder / FILE}: {problem}", file=sys.stderr)
        return 1
    loaded = load(args.folder)
    regions = sum(len(i.regions) for i in loaded.instruments.values())
    print(
        f"{args.folder}: ok, {len(loaded.instruments)} instrument(s) with {regions} "
        f"region(s), {len(loaded.hits)} hit(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
