"""The grooves of a `record --clock` recording, after the fact (#245, PR 2).

`track` replays a recording's clock and pad hits as the engine plays them live: each
clock message to a new `MidiClock` and then to the bar lines (`ClockAccess.on_bar`),
each pad Note On through `ClockAccess.deliver`. Every complete bar, with its hits on
the 16th grid, goes to one `Tracker` in order, so the decisions are the ones a live
tracker would make. The library of grooves lasts the whole recording; whenever the
clock stops running (Stop, lost), the groove ends (`Tracker.stop`). A take starts at
each Start or Continue; bars are numbered from 1 from song start, as the clock does.

`sections` is the view after the fact, which differs from the live decisions in three
ways: the first of the two bars that started a groove belongs to the new groove (live
it was a fill of the old one, or no groove); fills at the end of a groove that led
to free bars are free; and bars with no drums at the end of a groove are gaps.

`document` is the `mpc-iml-grooves` JSON document (version 1) for the grouping page.
Steps in it count from 0, as in `Pattern`; bars and takes from 1.

`track_many` runs one tracker over several recordings (#249), so a groove played
again in a later recording takes its earlier id by the tracker's `RETURN` rule, as
across takes. Recordings go in the order of their file's modification time, then
path: the recording header has no date.

`descriptor_reach` (#250) lists, for each groove, the grooves within a
`grooves.descriptor_distance` of it, which a nod on it would reach, for `python -m
mpc_iml.grooves --group-distance`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mpc_iml.clock import BarStart, ClockAccess, GridHit, MidiClock
from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.grooves import (
    GROUP_DISTANCE,
    PART_ROLES,
    Decision,
    Groove,
    Pattern,
    Tracker,
    descriptor_distance,
    pattern,
    rhythm_descriptors,
)
from mpc_iml.recording import RecordingFormatError, read_recording

FORMAT = "mpc-iml-grooves"
VERSION = 1

KINDS = ("groove", "fill", "free", "none", "silent")
"""A bar after the fact: in a groove, a fill in it, free, no groove yet, no drums."""

_START, _CONTINUE = 0xFA, 0xFB


@dataclass(frozen=True)
class Bar:
    """A complete bar of the recording: `take` and `bar` (both from 1), its `pattern`,
    the live `decision` (its `bar` and `start` are indexes into the list of bars), and
    after the fact its `kind` (`KINDS`), `groove` and the index of its section's
    `start` (`None` outside a groove). `hits` are the bar's pad hits as played (with
    their recorded time and velocity, pads 15 and 16 and `other` pads included), and
    `line` and `end` the times of its bar line and of the next one, in the
    recording's time base. None of these three is in the `mpc-iml-grooves` document."""

    take: int
    bar: int
    pattern: Pattern
    decision: Decision
    kind: str = "none"
    groove: int | None = None
    start: int | None = None
    hits: tuple[GridHit, ...] = ()
    line: float = 0.0
    end: float = 0.0


@dataclass(frozen=True)
class Section:
    """Bars in a row of one kind (and one groove): the indexes of the `first` and
    `last` bars, and the indexes of the fills in it."""

    kind: str
    groove: int | None
    first: int
    last: int
    fills: tuple[int, ...] = ()

    @property
    def length(self) -> int:
        return self.last - self.first + 1


@dataclass(frozen=True)
class Result:
    """The bars, sections and grooves of a recording, and the tracker's settings."""

    bars: tuple[Bar, ...]
    sections: tuple[Section, ...]
    grooves: tuple[Groove, ...]
    settings: dict[str, float]


def track(
    events: Iterable[Event], tracker: Tracker | None = None, roles: Sequence[str] = DEFAULT_ROLES
) -> Result:
    """The grooves of a recording. Raises `ValueError` without a complete bar of clock
    (a recording made without `--clock`)."""
    tracker = tracker or Tracker()
    clock = MidiClock()
    access = ClockAccess(clock)
    live: list[_Live] = []
    take = 0
    previous: tuple[int, int, float] | None = None
    """The take, bar and time of the last bar line."""

    def on_bar(start: BarStart) -> None:
        nonlocal previous
        end = start.state.t_tick if start.state.t_tick is not None else 0.0
        if start.complete and start.bar >= 1:
            if previous is not None and previous[:2] == (take, start.bar - 1):
                line = previous[2]
            else:
                bpm = start.state.bpm or 120.0
                line = end - start.state.beats_per_bar * 60.0 / bpm
            p = pattern(start.hits, roles)
            decision = tracker.observe(len(live), p)
            live.append(_Live(take, start.bar, p, decision, start.hits, line, end))
        previous = (take, start.bar, end)

    access.on_bar(on_bar)
    running = False
    for event in events:
        if isinstance(event, RawMidiEvent) and event.data[:1]:
            take += event.data[0] in (_START, _CONTINUE)
            state = clock.feed(event.data, event.t)
            access.bar_line()
        elif isinstance(event, MidiEvent) and event.kind == "note_on":
            state = clock.check(event.t)
            access.deliver(event)
        else:
            continue
        if running and state.status != "running":
            tracker.stop()
        running = state.status == "running"
    if not live:
        raise ValueError(
            "the recording has no complete bar of MIDI clock: "
            "record it with `python -m mpc_iml.record --clock`"
        )
    bars = _after_the_fact(live)
    settings = {
        "similar": tracker.similar,
        "return": tracker.return_at,
        "free_bars": tracker.free_bars,
        "decay": tracker.decay,
    }
    return Result(tuple(bars), tuple(sections(bars)), tracker.grooves, settings)


@dataclass(frozen=True)
class _Live:
    take: int
    bar: int
    pattern: Pattern
    decision: Decision
    hits: tuple[GridHit, ...]
    line: float
    end: float


def _after_the_fact(live: Sequence[_Live]) -> list[Bar]:
    labels: list[tuple[str, int | None, int | None]] = []
    for row in live:
        p, d = row.pattern, row.decision
        if d.groove is None:
            labels.append(("silent" if p.empty else "free" if d.free else "none", None, None))
        else:
            labels.append(("fill" if d.fill else "groove", d.groove, d.start))
    for d in (row.decision for row in live):
        if d.new and d.start is not None:
            labels[d.start] = ("groove", d.groove, d.start)
    for i in range(len(labels) - 1, 0, -1):
        after, empty = labels[i][0], live[i - 1].pattern.empty
        if labels[i - 1][0] != "fill" or after not in ("free", "silent"):
            continue
        if after == "free" or empty:
            labels[i - 1] = ("silent" if empty else "free", None, None)
    return [
        Bar(r.take, r.bar, r.pattern, r.decision, *label, r.hits, r.line, r.end)
        for r, label in zip(live, labels, strict=True)
    ]


def sections(bars: Sequence[Bar]) -> list[Section]:
    """`bars` in sections: a groove section runs from the bar that started it to its
    last bar, fills included; other sections are runs of one kind. A section does not
    cross takes."""
    out: list[Section] = []
    previous: tuple[object, ...] | None = None
    for i, b in enumerate(bars):
        kind = "groove" if b.kind == "fill" else b.kind
        key = (b.take, kind, b.groove, b.start)
        fill = (i,) if b.kind == "fill" else ()
        if key == previous:
            last = out[-1]
            out[-1] = Section(last.kind, last.groove, last.first, i, last.fills + fill)
        else:
            out.append(Section(kind, b.groove, i, i, fill))
        previous = key
    return out


def steps(p: Pattern) -> dict[str, list[int]]:
    """A pattern as sorted steps per role."""
    return {name: sorted(p.role(name)) for name in PART_ROLES}


def document(result: Result, recording: str) -> dict[str, Any]:
    """The `mpc-iml-grooves` document of `result` (module docstring)."""
    bars = result.bars

    def where(i: int) -> dict[str, int]:
        return {"take": bars[i].take, "bar": bars[i].bar}

    return {
        "format": FORMAT,
        "version": VERSION,
        "recording": recording,
        "settings": result.settings,
        "bars": [
            {
                **where(i),
                "kind": b.kind,
                "groove": b.groove,
                "similarity": b.decision.similarity,
                "live": {
                    "groove": b.decision.groove,
                    "position": b.decision.position,
                    "fill": b.decision.fill,
                    "free": b.decision.free,
                },
                "pattern": steps(b.pattern),
            }
            for i, b in enumerate(bars)
        ],
        "sections": [
            {
                **where(s.first),
                "length": s.length,
                "kind": s.kind,
                "groove": s.groove,
                "fills": [bars[i].bar for i in s.fills],
            }
            for s in result.sections
        ],
        "grooves": [
            {
                "id": g.id,
                "bars": g.bars,
                "prototype": steps(g.prototype),
                "features": g.features.as_dict(),
            }
            for g in result.grooves
        ],
    }


@dataclass(frozen=True)
class Source:
    """One recording of `track_many`: its `path` as given, its file's modification
    time (`modified`, ISO 8601 in UTC) and its `result`. The result's `grooves` are
    the tracker's after this recording, so they include earlier recordings'."""

    path: str
    modified: str
    result: Result


@dataclass(frozen=True)
class Many:
    """The recordings of `track_many` in the order tracked, the grooves of all of
    them, and the tracker's settings."""

    sources: tuple[Source, ...]
    grooves: tuple[Groove, ...]
    settings: dict[str, float]


def track_many(
    paths: Iterable[Path | str],
    tracker: Tracker | None = None,
    roles: Sequence[str] = DEFAULT_ROLES,
) -> Many:
    """The grooves of several recordings with one tracker (module docstring). The
    groove ends between recordings (`Tracker.stop`). Raises `ValueError` (a
    `RecordingFormatError` for a file that is not a recording) naming the file, and
    `OSError` for a file that cannot be read; `ValueError` for no paths."""
    tracker = tracker or Tracker()
    found: list[tuple[float, str]] = []
    for path in paths:
        found.append((Path(path).stat().st_mtime, str(path)))
    if not found:
        raise ValueError("no recordings to track")
    sources: list[Source] = []
    for mtime, path in sorted(found):
        try:
            recording = read_recording(path)
        except RecordingFormatError as error:
            raise RecordingFormatError(f"{path}: {error}") from error
        try:
            result = track(recording.events, tracker, roles)
        except ValueError as error:
            raise ValueError(f"{path}: {error}") from error
        tracker.stop()
        modified = datetime.fromtimestamp(mtime, UTC).isoformat(timespec="seconds")
        sources.append(Source(path, modified, result))
    return Many(tuple(sources), tracker.grooves, sources[-1].result.settings)


def descriptor_reach(
    grooves: Sequence[Groove], distance: float = GROUP_DISTANCE
) -> dict[int, list[tuple[int, float]]]:
    """For each groove id (in order), the other grooves whose prototypes are at most
    `distance` from its own (`grooves.descriptor_distance`), as `(id, distance)`,
    nearest first. These are the grooves a nod on it would reach; grooves linked only
    through others are not. A groove near no other has an empty list."""
    found = {g.id: rhythm_descriptors(g.prototype) for g in grooves}
    reach: dict[int, list[tuple[int, float]]] = {}
    for i in sorted(found):
        near = [(descriptor_distance(found[i], d), j) for j, d in found.items() if j != i]
        reach[i] = [(j, d) for d, j in sorted(near) if d <= distance]
    return reach
