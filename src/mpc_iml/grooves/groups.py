"""The musician's own groups of grooves: the `mpc-iml-groove-groups` file (#249, ADR 0012).

After playing, the musician groups the grooves the tracker found (`offline.track_many`)
and names each group. `GrooveGroups` holds the result; `write_groups` saves it as JSON
in `<data folder>/grooves/` and `read_groups` reads it back, checking every field.
Each groove keeps its prototype and mean features, so a later reader (`ensemble`,
#250) can match bars or grooves to the groups by `grooves.similarity` without the
recordings. `describe` puts a groove's features into plain words for its card.
"""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, NoReturn

from mpc_iml.grooves import PART_ROLES, STEPS, Features, Pattern
from mpc_iml.grooves.offline import KINDS, Many

FORMAT = "mpc-iml-groove-groups"
VERSION = 1
FOLDER = "grooves"
"""The folder in the data folder that holds the files."""

SETTINGS = ("similar", "return", "free_bars", "decay")
"""The tracker thresholds a file records (`offline.Result.settings`)."""

_FEATURES = tuple(f.name for f in fields(Features))


class GroupsFormatError(ValueError):
    """The file is not a valid `mpc-iml-groove-groups` file; the message names the
    file and the field."""


@dataclass(frozen=True)
class Group:
    """A group the musician made: an `id` from 1, a `name` and what it is for
    (`purpose`)."""

    id: int
    name: str
    purpose: str = ""


@dataclass(frozen=True)
class GrooveEntry:
    """One groove: its tracker `id`, `prototype`, mean `features`, number of `bars`
    that voted and of `sections`; the musician's `group` (a group id, `None` for
    "not sure") and `note`; and its `card` letter in blind mode (else `None`)."""

    id: int
    prototype: Pattern
    features: Features
    bars: int
    sections: int
    group: int | None = None
    note: str = ""
    card: str | None = None


@dataclass(frozen=True)
class SourceInfo:
    """A recording the grooves came from: its `path` as given, its file's
    modification time (`modified`) and its number of complete `bars`."""

    path: str
    modified: str
    bars: int


@dataclass(frozen=True)
class GrooveGroups:
    """A whole file (module docstring). `counts` holds the number of bars of each
    kind of `offline.KINDS`; `blind` and `seed` record a blind sort."""

    sources: tuple[SourceInfo, ...]
    settings: dict[str, float]
    groups: tuple[Group, ...]
    grooves: tuple[GrooveEntry, ...]
    counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys(KINDS, 0))
    blind: bool = False
    seed: int | None = None
    created: str = ""
    updated: str = ""


def start(many: Many, created: str) -> GrooveGroups:
    """A new sort of the grooves of `many`: no groups yet, every groove "not sure".
    A groove's `sections` counts its groove sections in all the recordings."""
    sections: dict[int, int] = {}
    counts = dict.fromkeys(KINDS, 0)
    for source in many.sources:
        for s in source.result.sections:
            if s.groove is not None:
                sections[s.groove] = sections.get(s.groove, 0) + 1
        for b in source.result.bars:
            counts[b.kind] += 1
    return GrooveGroups(
        sources=tuple(SourceInfo(s.path, s.modified, len(s.result.bars)) for s in many.sources),
        settings=dict(many.settings),
        groups=(),
        grooves=tuple(
            GrooveEntry(g.id, g.prototype, g.features, g.bars, sections.get(g.id, 0))
            for g in many.grooves
        ),
        counts=counts,
        created=created,
        updated=created,
    )


def steps(p: Pattern) -> dict[str, list[int]]:
    """A pattern as sorted steps per role, as in `mpc-iml-grooves`."""
    return {name: sorted(p.role(name)) for name in PART_ROLES}


def to_dict(groups: GrooveGroups) -> dict[str, Any]:
    """The JSON document of `groups`."""
    return {
        "format": FORMAT,
        "version": VERSION,
        "created": groups.created,
        "updated": groups.updated,
        "sources": [
            {"path": s.path, "modified": s.modified, "bars": s.bars} for s in groups.sources
        ],
        "settings": dict(groups.settings),
        "blind": groups.blind,
        "seed": groups.seed,
        "counts": dict(groups.counts),
        "groups": [{"id": g.id, "name": g.name, "purpose": g.purpose} for g in groups.groups],
        "grooves": [
            {
                "id": e.id,
                "group": e.group,
                "note": e.note,
                "card": e.card,
                "prototype": steps(e.prototype),
                "features": e.features.as_dict(),
                "bars": e.bars,
                "sections": e.sections,
            }
            for e in groups.grooves
        ],
    }


def write_groups(path: Path | str, groups: GrooveGroups) -> None:
    """Write `groups` to `path` as JSON, creating its folder. It is checked first, so
    a file that `read_groups` would refuse is never written."""
    document = to_dict(groups)
    from_dict(document, Path(path).name)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def read_groups(path: Path | str) -> GrooveGroups:
    """Read a file. Raises `GroupsFormatError` naming the file and the field, or
    `OSError` when it cannot be read."""
    name = Path(path).name
    text = Path(path).read_text(encoding="utf-8")
    try:
        document = json.loads(text)
    except json.JSONDecodeError as error:
        raise GroupsFormatError(f"{name}: not valid JSON: {error}") from error
    return from_dict(document, name)


def from_dict(document: object, name: str = "<document>") -> GrooveGroups:
    """Check and read a JSON document; `name` is used in errors."""
    c = _Check(name)
    d = c.mapping(document, "", _TOP)
    if d["format"] != FORMAT:
        c.fail("format", f"must be {FORMAT!r}, got {d['format']!r}")
    if d["version"] != VERSION:
        c.fail("version", f"this toolkit reads version {VERSION}, got {d['version']!r}")
    sources = tuple(_source(c, x, i) for i, x in enumerate(c.array(d["sources"], "sources")))
    settings_doc = c.mapping(d["settings"], "settings", SETTINGS)
    settings = {k: c.number(settings_doc[k], f"settings.{k}") for k in SETTINGS}
    counts_doc = c.mapping(d["counts"], "counts", KINDS)
    counts = {k: c.count(counts_doc[k], f"counts.{k}") for k in KINDS}
    groups = tuple(_group(c, x, i) for i, x in enumerate(c.array(d["groups"], "groups")))
    _unique(c, [g.id for g in groups], "groups")
    known = {g.id for g in groups}
    grooves = tuple(_groove(c, x, i, known) for i, x in enumerate(c.array(d["grooves"], "grooves")))
    _unique(c, [e.id for e in grooves], "grooves")
    if not isinstance(d["blind"], bool):
        c.fail("blind", f"must be true or false, got {d['blind']!r}")
    seed = d["seed"]
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        c.fail("seed", f"must be an integer or null, got {seed!r}")
    return GrooveGroups(
        sources,
        settings,
        groups,
        grooves,
        counts,
        d["blind"],
        seed,
        c.text(d["created"], "created"),
        c.text(d["updated"], "updated"),
    )


_TOP = (
    "format",
    "version",
    "created",
    "updated",
    "sources",
    "settings",
    "blind",
    "seed",
    "counts",
    "groups",
    "grooves",
)
_GROOVE = ("id", "group", "note", "card", "prototype", "features", "bars", "sections")


def _source(c: "_Check", value: object, i: int) -> SourceInfo:
    where = f"sources[{i}]"
    s = c.mapping(value, where, ("path", "modified", "bars"))
    return SourceInfo(
        c.text(s["path"], f"{where}.path"),
        c.text(s["modified"], f"{where}.modified"),
        c.count(s["bars"], f"{where}.bars"),
    )


def _group(c: "_Check", value: object, i: int) -> Group:
    where = f"groups[{i}]"
    g = c.mapping(value, where, ("id", "name", "purpose"))
    return Group(
        c.ident(g["id"], f"{where}.id"),
        c.text(g["name"], f"{where}.name"),
        c.text(g["purpose"], f"{where}.purpose"),
    )


def _groove(c: "_Check", value: object, i: int, known: set[int]) -> GrooveEntry:
    where = f"grooves[{i}]"
    e = c.mapping(value, where, _GROOVE)
    group = e["group"]
    if group is not None:
        group = c.ident(group, f"{where}.group")
        if group not in known:
            c.fail(f"{where}.group", f"no group has id {group}")
    card = e["card"]
    if card is not None:
        card = c.text(card, f"{where}.card")
    proto = c.mapping(e["prototype"], f"{where}.prototype", PART_ROLES)
    feats = c.mapping(e["features"], f"{where}.features", _FEATURES)
    return GrooveEntry(
        c.ident(e["id"], f"{where}.id"),
        Pattern(*(_steps(c, proto[r], f"{where}.prototype.{r}") for r in PART_ROLES)),
        Features(**{k: c.number(feats[k], f"{where}.features.{k}") for k in _FEATURES}),
        c.count(e["bars"], f"{where}.bars"),
        c.count(e["sections"], f"{where}.sections"),
        group,
        c.text(e["note"], f"{where}.note"),
        card,
    )


def _steps(c: "_Check", value: object, where: str) -> frozenset[int]:
    out = set()
    for i, s in enumerate(c.array(value, where)):
        if isinstance(s, bool) or not isinstance(s, int) or not 0 <= s < STEPS:
            c.fail(f"{where}[{i}]", f"must be a step from 0 to {STEPS - 1}, got {s!r}")
        out.add(s)
    return frozenset(out)


def _unique(c: "_Check", ids: list[int], where: str) -> None:
    seen: set[int] = set()
    for i, n in enumerate(ids):
        if n in seen:
            c.fail(f"{where}[{i}].id", f"id {n} is used twice")
        seen.add(n)


@dataclass(frozen=True)
class _Check:
    name: str

    def fail(self, where: str, message: str) -> NoReturn:
        prefix = f"{self.name}: {where}: " if where else f"{self.name}: "
        raise GroupsFormatError(prefix + message)

    def mapping(self, value: object, where: str, keys: tuple[str, ...]) -> Mapping[str, Any]:
        label = where or "the document"
        if not isinstance(value, dict):
            self.fail(where, f"{label} must be an object, got {type(value).__name__}")
        for key in keys:
            if key not in value:
                self.fail(f"{where}.{key}" if where else key, "missing")
        for key in value:
            if key not in keys:
                self.fail(f"{where}.{key}" if where else str(key), "unknown field")
        return value

    def array(self, value: object, where: str) -> list[Any]:
        if not isinstance(value, list):
            self.fail(where, f"must be a list, got {type(value).__name__}")
        return value

    def text(self, value: object, where: str) -> str:
        if not isinstance(value, str):
            self.fail(where, f"must be text, got {value!r}")
        return value

    def number(self, value: object, where: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, int | float)
            or not math.isfinite(value)
        ):
            self.fail(where, f"must be a number, got {value!r}")
        return float(value)

    def count(self, value: object, where: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            self.fail(where, f"must be a whole number from 0, got {value!r}")
        return value

    def ident(self, value: object, where: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            self.fail(where, f"must be a whole number from 1, got {value!r}")
        return value


def describe(f: Features) -> str:
    """A groove's mean features in plain words, with fixed wording per feature and
    range, for example "about 3 kicks a bar, a double kick, kicks mostly in the
    second half, no snare off the backbeat, about 8 hats a bar"."""
    kicks = round(f.kicks)
    words = ["no kick" if kicks == 0 else f"about {kicks} kick{'s' * (kicks != 1)} a bar"]
    doubles = round(f.double_kicks)
    if doubles == 1:
        words.append("a double kick")
    elif doubles > 1:
        words.append(f"{doubles} double kicks")
    if kicks:
        share = f.late_kicks / f.kicks
        if share >= 0.6:
            words.append("kicks mostly in the second half")
        elif share <= 0.4:
            words.append("kicks mostly in the first half")
        else:
            words.append("kicks in both halves")
    off = round(f.snare_off)
    words.append(
        "no snare off the backbeat"
        if off == 0
        else f"about {off} snare hit{'s' * (off != 1)} off the backbeat"
    )
    if f.hat_presence == 0:
        words.append("no hat")
    elif f.hat_presence < 0.5:
        words.append("a hat in a few bars")
    else:
        hats = round(f.hats)
        words.append(f"about {hats} hat{'s' * (hats != 1)} a bar")
    return ", ".join(words)
