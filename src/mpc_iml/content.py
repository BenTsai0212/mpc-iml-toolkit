"""Modules and kits for presets with named outputs (ADR 0007).

A **module** describes how a pad's pressure moves some named outputs away from a
resting sound: per output, points `[pressure, offset]` with linear interpolation.
A **kit** is a resting sound (`rest`, a value for every named output) plus one
module on each of the 16 pads. `mpc_iml.generation` turns a kit into training
examples.

Modules and kits are JSON files in a package, `<root>/modules/<preset>/<name>.json`
and `<root>/kits/<preset>/<name>.json`, read with `importlib.resources`. A package
declares where they are with an entry point in the group `mpc_iml.content`, which
refers to a `Content` or to a zero-argument callable returning one:

    [project.entry-points."mpc_iml.content"]
    pressure-content = "mpc_iml.pressure:CONTENT"

So another package can add kits and modules to a preset it does not define.
`load_library(preset)` reads every entry for that preset; content for other
presets, installed or not, is not read. The module `none` is built in and has no
file: its takes stay at the resting values.
"""

import json
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import EntryPoint, entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import Any, Literal

from mpc_iml.presets import Preset

__all__ = [
    "COMBINE_MODES",
    "CONTENT_GROUP",
    "KIT_FORMAT",
    "MODULE_FORMAT",
    "NONE",
    "PADS",
    "Combine",
    "Content",
    "ContentError",
    "Kit",
    "Library",
    "Module",
    "PadAssignment",
    "UnknownContentError",
    "load_library",
    "parse_kit",
    "parse_module",
]

CONTENT_GROUP = "mpc_iml.content"
"""The entry point group kits and modules are registered in."""

MODULE_FORMAT = "mpc-iml-module"
KIT_FORMAT = "mpc-iml-kit"
NONE = "none"
"""The built-in module that changes nothing."""
PADS = 16

Combine = Literal["add", "none"]
COMBINE_MODES: tuple[Combine, ...] = ("add", "none")

_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


class ContentError(Exception):
    """A module, kit or content entry is invalid, duplicated or inconsistent."""


class UnknownContentError(ContentError):
    """No installed content defines the requested kit or module."""


@dataclass(frozen=True)
class Content:
    """Where a package keeps kits and modules for one preset.

    `root` is a package (`"my_package"`) or a folder inside one
    (`"my_package:content"`); the files are under `<root>/kits/<preset>/` and
    `<root>/modules/<preset>/`.
    """

    preset: str
    root: str

    def folder(self) -> Traversable:
        package, _, path = self.root.partition(":")
        folder = files(package)
        return folder.joinpath(path) if path else folder


@dataclass(frozen=True)
class Module:
    """Offsets of named outputs as a function of pressure (ADR 0007).

    `outputs` maps an output name to points `(pressure, offset)`: pressure strictly
    increasing from 0, offsets -1 to 1, the first point `(0, 0)`. Outputs not
    listed keep their resting value.
    """

    name: str
    preset: str
    outputs: Mapping[str, tuple[tuple[float, float], ...]]
    title: str = ""
    description: str = ""

    def offset(self, output: str, pressure: float) -> float:
        """The offset of `output` at `pressure`: interpolated, held after the last point."""
        points = self.outputs.get(output)
        if not points:
            return 0.0
        if pressure <= points[0][0]:
            return points[0][1]
        for (p0, o0), (p1, o1) in zip(points, points[1:], strict=False):
            if pressure <= p1:
                return o0 + (o1 - o0) * (pressure - p0) / (p1 - p0)
        return points[-1][1]


@dataclass(frozen=True)
class PadAssignment:
    """A module on a pad, scaled by `amount` (0-1)."""

    module: str
    amount: float = 1.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.amount <= 1.0:
            raise ContentError(f"amount must be 0-1: {self.amount}")


@dataclass(frozen=True)
class Kit:
    """A resting sound and a module on each of the 16 pads (pad 1 first)."""

    name: str
    preset: str
    rest: Mapping[str, float]
    pads: tuple[PadAssignment, ...]
    title: str = ""
    description: str = ""
    default: bool = False
    combine: Combine = "add"


def _fail(origin: str, message: str) -> ContentError:
    return ContentError(f"{origin}: {message}")


def _number(value: Any, origin: str, what: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _fail(origin, f"{what} must be a number, got {value!r}")
    if not low <= value <= high:
        raise _fail(origin, f"{what} must be {low:g}-{high:g}, got {value!r}")
    return float(value)


def _header(data: Any, fmt: str, origin: str, preset: str) -> tuple[str, str, str]:
    """Check the common fields for a file of `preset`; return (name, title, description)."""
    if not isinstance(data, dict):
        raise _fail(origin, "not a JSON object")
    if data.get("format") != fmt or data.get("format_version") != 1:
        raise _fail(origin, f"not an {fmt} file of format_version 1")
    name = data.get("name")
    if not isinstance(name, str) or not _NAME.fullmatch(name):
        raise _fail(origin, f"name must be lower case letters, digits and hyphens: {name!r}")
    if data.get("preset") != preset:
        raise _fail(origin, f"preset is {data.get('preset')!r}, expected {preset!r}")
    title = data.get("title", name.capitalize())
    description = data.get("description", "")
    if not isinstance(title, str) or not isinstance(description, str):
        raise _fail(origin, "title and description must be strings")
    return name, title, description


def _output_names(preset: Preset) -> tuple[str, ...]:
    if preset.output_names is None:
        raise ContentError(f"preset {preset.name!r} has no output_names")
    return preset.output_names


def parse_module(data: Any, preset: Preset, origin: str = "module") -> Module:
    """Validate a module's JSON object for `preset`; raises `ContentError`."""
    names = _output_names(preset)
    name, title, description = _header(data, MODULE_FORMAT, origin, preset.name)
    if name == NONE:
        raise _fail(origin, f"{NONE!r} is built in and cannot be defined")
    outputs = data.get("outputs")
    if not isinstance(outputs, dict) or not outputs:
        raise _fail(origin, "outputs must map output names to points")
    curves: dict[str, tuple[tuple[float, float], ...]] = {}
    for output, points in outputs.items():
        if output not in names:
            raise _fail(origin, f"unknown output {output!r}; outputs: {', '.join(names)}")
        if not isinstance(points, list) or not points:
            raise _fail(origin, f"{output}: points must be a list of [pressure, offset]")
        curve: list[tuple[float, float]] = []
        for point in points:
            if not isinstance(point, list) or len(point) != 2:
                raise _fail(origin, f"{output}: a point is [pressure, offset], got {point!r}")
            pressure = _number(point[0], origin, f"{output}: pressure", 0.0, 1.0)
            offset = _number(point[1], origin, f"{output}: offset", -1.0, 1.0)
            if curve and pressure <= curve[-1][0]:
                raise _fail(origin, f"{output}: pressures must be strictly increasing")
            curve.append((pressure, offset))
        if curve[0] != (0.0, 0.0):
            raise _fail(origin, f"{output}: the first point must be [0, 0]")
        curves[output] = tuple(curve)
    return Module(name, preset.name, curves, title, description)


def _assignment(entry: Any, origin: str, pad: int) -> PadAssignment:
    if isinstance(entry, str):
        return PadAssignment(entry)
    if isinstance(entry, dict) and isinstance(entry.get("module"), str):
        if set(entry) - {"module", "amount"}:
            raise _fail(origin, f"pad {pad}: only module and amount are allowed")
        amount = _number(entry.get("amount", 1.0), origin, f"pad {pad}: amount", 0.0, 1.0)
        return PadAssignment(entry["module"], amount)
    raise _fail(origin, f"pad {pad}: expected a module id or {{module, amount}}")


def parse_kit(data: Any, preset: Preset, origin: str = "kit") -> Kit:
    """Validate a kit's JSON object for `preset`; raises `ContentError`.

    Module ids are checked against the installed modules by `load_library`.
    """
    names = _output_names(preset)
    name, title, description = _header(data, KIT_FORMAT, origin, preset.name)
    rest = data.get("rest")
    if not isinstance(rest, dict) or set(rest) != set(names):
        raise _fail(origin, f"rest must give a value for every output: {', '.join(names)}")
    rest_values = {o: _number(rest[o], origin, f"rest {o}", 0.0, 1.0) for o in names}
    pads = data.get("pads")
    if not isinstance(pads, list) or len(pads) != PADS:
        raise _fail(origin, f"pads must have exactly {PADS} entries")
    combine = data.get("combine", "add")
    if combine not in COMBINE_MODES:
        raise _fail(origin, f"combine must be 'add' or 'none', got {combine!r}")
    default = data.get("default", False)
    if not isinstance(default, bool):
        raise _fail(origin, "default must be true or false")
    assignments = tuple(_assignment(entry, origin, i) for i, entry in enumerate(pads, start=1))
    return Kit(name, preset.name, rest_values, assignments, title, description, default, combine)


NONE_MODULE_TITLE = "None"


@dataclass(frozen=True)
class Library:
    """The modules (including `none`) and kits installed for one preset."""

    preset: Preset
    modules: Mapping[str, Module]
    kits: Mapping[str, Kit]

    @property
    def output_names(self) -> tuple[str, ...]:
        """The preset's output names; empty for a preset without them."""
        return self.preset.output_names or ()

    def module_ids(self) -> list[str]:
        """Module ids, `none` first, then by id; empty for a preset without names."""
        if not self.modules:
            return []
        return [NONE, *sorted(m for m in self.modules if m != NONE)]

    def kit_names(self) -> list[str]:
        """Kit names, the default kit first, then by name."""
        return sorted(self.kits, key=lambda k: (not self.kits[k].default, k))

    def module(self, module_id: str) -> Module:
        """The module `module_id`; raises `UnknownContentError` when none is installed."""
        if module_id not in self.modules:
            raise UnknownContentError(f"unknown module {module_id!r} for {self.preset.name!r}")
        return self.modules[module_id]

    def kit(self, name: str) -> Kit:
        """The kit `name`; raises `UnknownContentError` when none is installed."""
        if name not in self.kits:
            raise UnknownContentError(f"unknown kit {name!r} for {self.preset.name!r}")
        return self.kits[name]


def _origin(entry: EntryPoint) -> str:
    dist = entry.dist.name if entry.dist is not None else "unknown distribution"
    return f"entry point {entry.name!r} ({entry.value}) of {dist}"


def _load_entry(entry: EntryPoint) -> Content:
    try:
        obj = entry.load()
        if callable(obj) and not isinstance(obj, Content):
            obj = obj()
    except Exception as error:
        raise ContentError(f"cannot load {_origin(entry)}: {error}") from error
    if not isinstance(obj, Content):
        raise ContentError(f"{_origin(entry)} is not a Content: {type(obj).__name__}")
    return obj


def _json_files(folder: Traversable) -> Iterator[tuple[str, Any, str]]:
    """(file stem, parsed JSON, origin) for each `*.json` in `folder`, by name."""
    if not folder.is_dir():
        return
    for item in sorted(folder.iterdir(), key=lambda i: i.name):
        if not item.name.endswith(".json"):
            continue
        origin = str(item)
        try:
            data = json.loads(item.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ContentError(f"{origin}: cannot read: {error}") from error
        yield item.name.removesuffix(".json"), data, origin


def _read(contents: Sequence[Content], kind: str, preset: str) -> Iterator[tuple[str, Any, str]]:
    for content in contents:
        for stem, data, origin in _json_files(content.folder() / kind / preset):
            name = data.get("name") if isinstance(data, dict) else None
            if stem != name:
                raise ContentError(f"{origin}: the file name must equal the name {name!r}")
            yield stem, data, origin


def load_library(preset: Preset, group: str = CONTENT_GROUP) -> Library:
    """Read the kits and modules every `group` entry declares for `preset`.

    A preset without `output_names` gets an empty library (no kits, no modules,
    not even `none`). Raises `ContentError` when an entry or file is invalid, when
    two files define the same kit or module, when more than one kit is the default,
    or when a kit names a module no installed content defines.
    """
    if preset.output_names is None:
        return Library(preset, {}, {})
    contents = [c for c in map(_load_entry, entry_points(group=group)) if c.preset == preset.name]
    modules: dict[str, Module] = {NONE: Module(NONE, preset.name, {}, NONE_MODULE_TITLE)}
    origins: dict[str, str] = {}
    for name, data, origin in _read(contents, "modules", preset.name):
        if name in modules:
            raise ContentError(f"two modules named {name!r}: {origins.get(name)} and {origin}")
        modules[name] = parse_module(data, preset, origin)
        origins[name] = origin
    kits: dict[str, Kit] = {}
    for name, data, origin in _read(contents, "kits", preset.name):
        if name in kits:
            raise ContentError(f"two kits named {name!r}: {origins[f'kit:{name}']} and {origin}")
        kit = parse_kit(data, preset, origin)
        for pad, assignment in enumerate(kit.pads, start=1):
            if assignment.module not in modules:
                raise ContentError(f"{origin}: pad {pad}: unknown module {assignment.module!r}")
        kits[name] = kit
        origins[f"kit:{name}"] = origin
    defaults = [k for k in kits.values() if k.default]
    if len(defaults) > 1:
        raise ContentError(
            f"more than one default kit for {preset.name!r}: "
            + ", ".join(sorted(k.name for k in defaults))
        )
    return Library(preset, modules, kits)
