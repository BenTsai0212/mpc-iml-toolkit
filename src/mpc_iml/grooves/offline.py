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
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from mpc_iml.clock import BarStart, ClockAccess, MidiClock
from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.grooves import PART_ROLES, Decision, Groove, Pattern, Tracker, pattern

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
    `start` (`None` outside a groove)."""

    take: int
    bar: int
    pattern: Pattern
    decision: Decision
    kind: str = "none"
    groove: int | None = None
    start: int | None = None


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
    live: list[tuple[int, int, Pattern, Decision]] = []
    take = 0

    def on_bar(start: BarStart) -> None:
        if start.complete and start.bar >= 1:
            p = pattern(start.hits, roles)
            live.append((take, start.bar, p, tracker.observe(len(live), p)))

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


def _after_the_fact(live: Sequence[tuple[int, int, Pattern, Decision]]) -> list[Bar]:
    labels: list[tuple[str, int | None, int | None]] = []
    for _, _, p, d in live:
        if d.groove is None:
            labels.append(("silent" if p.empty else "free" if d.free else "none", None, None))
        else:
            labels.append(("fill" if d.fill else "groove", d.groove, d.start))
    for d in (row[3] for row in live):
        if d.new and d.start is not None:
            labels[d.start] = ("groove", d.groove, d.start)
    for i in range(len(labels) - 1, 0, -1):
        after, empty = labels[i][0], live[i - 1][2].empty
        if labels[i - 1][0] != "fill" or after not in ("free", "silent"):
            continue
        if after == "free" or empty:
            labels[i - 1] = ("silent" if empty else "free", None, None)
    return [
        Bar(take, number, p, d, *label)
        for (take, number, p, d), label in zip(live, labels, strict=True)
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
