"""The cards of the grooves tab: grooves, audio and export, without Gradio (#249, PR 2).

`find_recordings` reads the path box: one folder or recording per line, relative to
the data folder when there is one, else absolute. A folder means every `*.jsonl` in
it whose first line is an `mpc-iml-recording` header; its other files (a trial's
`session.jsonl`, `engine.log`) are listed as skipped. `load` tracks them with one
tracker (`offline.track_many`) and starts a sort (`groups.start`), with the paths as
given; `blind` shuffles the cards with a seed and names them "card A", "card B"...

`cards` builds a `Card` per groove: its prototype as a 16-step grid per role, its
counts, its features in plain words (`groups.describe`), the bars of up to two of
its sections as played (`played`), and two bars of its prototype on the grid
(`prototype_loop`). A section clip is the longest section, plus the longest from
another recording, else the second longest; at most `CLIP_BARS` bars of each. Each
hit sounds at its recorded time from the section's first bar line (`LEAD` seconds
in) with its recorded velocity, through `synth.render_hits`. Blind cards show no
groove id, no counts and no bar numbers. Without the recordings (`many` is `None`),
cards have the prototype loop only.

`summary` and `export_text` are the page's count line and the plain text export of
a sort, for an interview transcript.
"""

import json
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
import numpy.typing as npt

from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.grooves import CONTROL_PADS, PART_ROLES, STEPS, Pattern
from mpc_iml.grooves.__main__ import grid
from mpc_iml.grooves.groups import GrooveEntry, GrooveGroups, describe, start
from mpc_iml.grooves.offline import Bar, Many, Section, Source, track_many
from mpc_iml.recording import FORMAT as RECORDING_FORMAT
from mpc_iml.webdemo.synth import RATE, Hit, render_hits

__all__ = [
    "CLIP_BARS",
    "DEFAULT_BPM",
    "LEAD",
    "LOOP_BARS",
    "LOOP_VELOCITY",
    "Card",
    "Clip",
    "Found",
    "Loaded",
    "audio",
    "cards",
    "choose_sections",
    "export_text",
    "find_recordings",
    "letter",
    "load",
    "played",
    "prototype_loop",
    "shuffle",
    "summary",
]

CLIP_BARS = 8
"""At most this many bars of a section are played."""

LEAD = 0.15
"""Seconds before a section's first bar line, so a hit played early still sounds."""

LOOP_BARS = 2
LOOP_VELOCITY = 100
DEFAULT_BPM = 100.0
"""The prototype loop's tempo when no section was played."""


@dataclass(frozen=True)
class Clip:
    """Audio to play: a `label`, drum `hits` and the clip's length in `seconds`."""

    label: str
    hits: tuple[Hit, ...]
    seconds: float


@dataclass(frozen=True)
class Card:
    """A groove's card: `title` ("groove 3", or "card B" in blind mode), its prototype
    `grid` (one line per role), `counts` (empty in blind mode), `words` (its features),
    `played` clips and the prototype `loop`."""

    groove: int
    title: str
    grid: str
    counts: str
    words: str
    played: tuple[Clip, ...]
    loop: Clip


@dataclass(frozen=True)
class Found:
    """The recordings of the path box: `paths` as (as given, real path) in the order
    found, and the `skipped` files of folders, each with why."""

    paths: tuple[tuple[str, Path], ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class Loaded:
    """What `load` found: the tracked recordings (paths as given), the new sort and
    the skipped files."""

    many: Many
    groups: GrooveGroups
    skipped: tuple[str, ...]


def find_recordings(text: str, data: Path | None) -> Found:
    """The recordings named in `text` (module docstring). Raises `ValueError` for no
    lines, a missing path, a relative path without a data folder, or a folder with
    no recording."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("enter a folder or recording paths, one per line")
    paths: list[tuple[str, Path]] = []
    skipped: list[str] = []
    for line in lines:
        given = Path(line)
        if not given.is_absolute() and data is None:
            raise ValueError(f"{line}: give an absolute path, or start the demo with --data")
        real = given if given.is_absolute() or data is None else data / given
        if real.is_dir():
            found = 0
            for child in sorted(real.iterdir()):
                if not child.is_file():
                    continue
                why = _not_a_recording(child)
                if why:
                    skipped.append(f"{given / child.name}: {why}")
                else:
                    paths.append((str(given / child.name), child))
                    found += 1
            if not found:
                raise ValueError(f"{line}: no mpc-iml-recording in this folder")
        elif real.is_file():
            paths.append((line, real))
        else:
            raise ValueError(f"{line}: no such file or folder")
    return Found(tuple(paths), tuple(skipped))


def _not_a_recording(path: Path) -> str:
    """Why `path` is not a recording, or "" when its first line is the header."""
    if path.suffix != ".jsonl":
        return "not a .jsonl file"
    try:
        with path.open(encoding="utf-8") as f:
            first = next((line for line in f if line.strip()), "")
        header = json.loads(first) if first else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "not a recording"
    if not isinstance(header, dict) or header.get("format") != RECORDING_FORMAT:
        return "not a recording"
    return ""


def load(found: Found, created: str, blind: bool = False, seed: int = 0) -> Loaded:
    """Track `found` and start a sort; `blind` shuffles it with `seed`. Raises the
    errors of `offline.track_many`, naming the file as given."""
    given = {str(real): name for name, real in found.paths}
    try:
        many = track_many([real for _, real in found.paths])
    except ValueError as error:
        message = str(error)
        for real, name in given.items():
            message = message.replace(real, name)
        raise type(error)(message) from error
    many = replace(many, sources=tuple(replace(s, path=given[s.path]) for s in many.sources))
    groups = start(many, created)
    return Loaded(many, shuffle(groups, seed) if blind else groups, found.skipped)


def letter(i: int) -> str:
    """The card letter of index `i` from 0: A to Z, then AA, AB..."""
    out = ""
    i += 1
    while i:
        i, rest = divmod(i - 1, 26)
        out = chr(ord("A") + rest) + out
    return out


def shuffle(groups: GrooveGroups, seed: int) -> GrooveGroups:
    """`groups` as a blind sort: its grooves in a random order from `seed`, lettered
    in that order."""
    order = list(groups.grooves)
    random.Random(seed).shuffle(order)
    lettered = [replace(e, card=letter(i)) for i, e in enumerate(order)]
    return replace(groups, grooves=tuple(lettered), blind=True, seed=seed)


def _ordered(groups: GrooveGroups) -> list[GrooveEntry]:
    """Cards in page order: by letter when blind, else by groove id."""
    if groups.blind:
        return sorted(groups.grooves, key=lambda e: (len(e.card or ""), e.card or ""))
    return sorted(groups.grooves, key=lambda e: e.id)


def _title(e: GrooveEntry, blind: bool) -> str:
    return f"card {e.card}" if blind else f"groove {e.id}"


def choose_sections(many: Many, groove: int) -> list[tuple[Source, Section]]:
    """Up to two sections of `groove` to play (module docstring)."""
    found = [
        (s, section)
        for s in many.sources
        for section in s.result.sections
        if section.kind == "groove" and section.groove == groove
    ]
    found.sort(key=lambda x: -x[1].length)
    if not found:
        return []
    first = found[0]
    other = [x for x in found[1:] if x[0] is not first[0]]
    second = other[:1] or found[1:2]
    return [first, *second]


def played(source: Source, section: Section, label: str) -> Clip:
    """The first `CLIP_BARS` bars of `section` as played (module docstring). Only
    the kick, snare and hat pads of `ensemble.DEFAULT_ROLES` sound."""
    bars: Sequence[Bar] = source.result.bars[
        section.first : min(section.last, section.first + CLIP_BARS - 1) + 1
    ]
    zero = bars[0].line - LEAD
    hits = []
    for b in bars:
        for h in b.hits:
            role = DEFAULT_ROLES[h.pad] if 0 <= h.pad < len(DEFAULT_ROLES) else "other"
            if h.pad not in CONTROL_PADS and role in PART_ROLES:
                hits.append(Hit(h.t - zero, role, h.velocity))
    return Clip(label, tuple(hits), bars[-1].end - zero)


def prototype_loop(prototype: Pattern, bpm: float, bars: int = LOOP_BARS) -> Clip:
    """`bars` bars of `prototype` on the grid at `bpm`, at `LOOP_VELOCITY`."""
    step = 60.0 / bpm / 4
    hits = [
        Hit(LEAD + (bar * STEPS + s) * step, role, LOOP_VELOCITY)
        for bar in range(bars)
        for s in range(STEPS)
        for role in PART_ROLES
        if s in prototype.role(role)
    ]
    return Clip("prototype", tuple(hits), LEAD + bars * STEPS * step)


def _bpm(source: Source, section: Section) -> float:
    b = source.result.bars[section.first]
    return 4 * 60.0 / (b.end - b.line) if b.end > b.line else DEFAULT_BPM


def _counts(e: GrooveEntry, recordings: int) -> str:
    bars = f"{e.bars} bar{'s' * (e.bars != 1)}"
    sections = f"{e.sections} section{'s' * (e.sections != 1)}"
    where = f", in {recordings} recordings" if recordings > 1 else ""
    return f"{bars} in {sections}{where}"


def cards(groups: GrooveGroups, many: Many | None) -> list[Card]:
    """The cards of a sort in page order; `many` gives the played clips (module
    docstring)."""
    out = []
    for e in _ordered(groups):
        chosen = choose_sections(many, e.id) if many is not None else []
        clips = []
        for i, (source, section) in enumerate(chosen, start=1):
            first = source.result.bars[section.first]
            label = (
                f"played {i}"
                if groups.blind
                else f"{Path(source.path).name}, take {first.take}, from bar {first.bar}"
            )
            clips.append(played(source, section, label))
        recordings = sum(
            any(x.groove == e.id and x.kind == "groove" for x in s.result.sections)
            for s in (many.sources if many is not None else ())
        )
        bpm = _bpm(*chosen[0]) if chosen else DEFAULT_BPM
        out.append(
            Card(
                groove=e.id,
                title=_title(e, groups.blind),
                grid="\n".join(f"{r:<5} {grid(e.prototype.role(r))}" for r in PART_ROLES),
                counts="" if groups.blind else _counts(e, recordings),
                words=describe(e.features),
                played=tuple(clips),
                loop=prototype_loop(e.prototype, bpm),
            )
        )
    return out


def audio(clip: Clip) -> tuple[int, npt.NDArray[np.int16]]:
    """The clip as `(RATE, samples)` for `gr.Audio`."""
    return RATE, render_hits(clip.hits, clip.seconds)


_KIND_WORDS = (
    ("fill", "fill bar", "fill bars"),
    ("free", "free bar", "free bars"),
    ("none", "bar with no groove yet", "bars with no groove yet"),
    ("silent", "bar with no drums", "bars with no drums"),
)


def summary(groups: GrooveGroups) -> str:
    """The count line: grooves and bars of each kind; in blind mode only the number
    of cards."""
    n = len(groups.grooves)
    if groups.blind:
        return f"{n} card{'s' * (n != 1)}"
    c = groups.counts
    parts = [f"{n} groove{'s' * (n != 1)} ({c['groove'] + c['fill']} bars)"]
    for kind, one, many in _KIND_WORDS:
        parts.append(f"{c[kind]} {one if c[kind] == 1 else many}")
    r = len(groups.sources)
    return ", ".join(parts) + f", in {r} recording{'s' * (r != 1)}"


def export_text(groups: GrooveGroups) -> str:
    """The sort as plain text: each group (name, what it is for) with its cards and
    their notes, then "not sure"."""

    def lines_for(members: list[GrooveEntry]) -> list[str]:
        if not members:
            return ["  (none)"]
        out = []
        for e in members:
            title = _title(e, groups.blind)
            out.append(f"  - {title}: {e.note}" if e.note else f"  - {title}")
        return out

    ordered = _ordered(groups)
    lines = [f"Groove groups ({'blind' if groups.blind else 'with groove ids'})"]
    for g in groups.groups:
        lines += ["", f"{g.name or '(no name)'}"]
        if g.purpose:
            lines.append(f"  for: {g.purpose}")
        lines += lines_for([e for e in ordered if e.group == g.id])
    lines += ["", "not sure", *lines_for([e for e in ordered if e.group is None])]
    return "\n".join(lines) + "\n"
