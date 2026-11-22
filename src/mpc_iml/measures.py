"""Objective measures of a `record --clock` recording (#197): `python -m mpc_iml.measures`.

A blind trial (`mpc_iml.trial`) records each condition; these numbers come from the
musician's pad hits, so a comparison does not rest only on scores. The pad hits are
placed on the 16th grid with `clock.tag_recording`, and each pad has its `ensemble`
role (`ensemble.DEFAULT_ROLES`, any bank). Only complete bars of the take count: the
take is the clock from its first Start up to the next Stop, Continue, Song Position
or Start, as in `webdemo.sim.replay`.

- `hits`, `kicks`, `hats`: hits per bar, all pads and the `kick` and `hat` pads.
- `syncopation`: the share of hits on odd 16th steps (off the 8th notes).
- `changes`: from the second bar, the Jaccard distance between the bar's set of
  (role, step) and the bar before's: 0 is the same pattern, 1 nothing in common.
- `response` (**exploratory**: it depends on `THRESHOLD` and on the offline replay):
  the recording is replayed into a new `Ensemble` (`webdemo.sim.replay`), and for
  each bar where the band's bass or melody variation changed, the bars until the
  musician's `changes` is above `THRESHOLD`, at most `CAP`. The replay chooses the
  same variations as the live run, but not the same surprises, and does not load
  user loops from the data folder.

Standard library only.
"""

import argparse
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mpc_iml.clock import TICKS_PER_BEAT, tag_recording
from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.events import Event, RawMidiEvent
from mpc_iml.recording import RecordingFormatError, read_recording
from mpc_iml.trial.spec import TrialError, load_trial
from mpc_iml.webdemo.sim import BEATS_PER_BAR, BarRow, Settings, replay

__all__ = [
    "CAP",
    "EXPLORATORY",
    "THRESHOLD",
    "Measures",
    "Response",
    "band_changes",
    "distance",
    "measure",
    "replay_settings",
    "response",
]

THRESHOLD = 0.5
"""A pattern change above this counts as the musician answering a band change."""
CAP = 4
"""Bars after a band change in which an answer is looked for."""

_START, _CLOCK = 0xFA, 0xF8
_TAKE_ENDS = frozenset((0xFA, 0xFB, 0xFC, 0xF2))
_FIELDS = {
    "progression": "progression",
    "bass-loop": "bass_loop",
    "loop": "loop",
    "melody-mode": "melody_mode",
    "no-drums": "no_drums",
    "fade-bars": "fade_bars",
    "surprise": "surprise",
    "rhythm": "rhythm",
}
"""`ensemble` controls the replay takes, and their `Settings` fields."""

Pattern = frozenset[tuple[str, int]]


@dataclass(frozen=True)
class Response:
    """Exploratory: `latencies` has one entry per band change with a full window,
    the bars until the musician answered (1 to `CAP`), or `None` for no answer."""

    latencies: tuple[int | None, ...]

    @property
    def answered(self) -> float | None:
        """The share of band changes the musician answered."""
        if not self.latencies:
            return None
        return sum(k is not None for k in self.latencies) / len(self.latencies)

    @property
    def mean(self) -> float | None:
        """The mean latency of the answered changes."""
        found = [k for k in self.latencies if k is not None]
        return sum(found) / len(found) if found else None


@dataclass(frozen=True)
class Measures:
    """The measures of one recording, per complete bar."""

    bars: int
    hits: tuple[int, ...]
    kicks: tuple[int, ...]
    hats: tuple[int, ...]
    syncopation: float | None
    changes: tuple[float, ...]
    response: Response | None = None

    def summary(self) -> dict[str, Any]:
        """The numbers a report shows (`None`: not measurable), in a fixed order."""
        r = self.response
        return {
            "bars": self.bars,
            "hits_per_bar": _mean(self.hits),
            "kicks_per_bar": _mean(self.kicks),
            "hats_per_bar": _mean(self.hats),
            "syncopation": self.syncopation,
            "pattern_change": _mean(self.changes),
            "band_changes": None if r is None else len(r.latencies),
            "answered": None if r is None else r.answered,
            "response_bars": None if r is None else r.mean,
        }


EXPLORATORY = frozenset(("band_changes", "answered", "response_bars"))
"""The `Measures.summary` keys of the exploratory response measure."""


def _mean(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def distance(a: Pattern, b: Pattern) -> float:
    """The Jaccard distance of two bars' (role, step) sets; two empty bars are 0."""
    union = a | b
    return 1 - len(a & b) / len(union) if union else 0.0


def _take(events: Iterable[Event]) -> tuple[list[Event], int]:
    """The events up to the end of the first take, and its clock ticks after Start."""
    kept: list[Event] = []
    started, ticks = False, 0
    for event in events:
        if isinstance(event, RawMidiEvent) and event.data[:1]:
            kind = event.data[0]
            if started and kind in _TAKE_ENDS:
                break
            started = started or kind == _START
            ticks += started and kind == _CLOCK
        kept.append(event)
    return kept, ticks


def measure(
    events: Iterable[Event],
    beats_per_bar: int = BEATS_PER_BAR,
    roles: Sequence[str] = DEFAULT_ROLES,
    settings: Settings | None = None,
) -> Measures:
    """The measures of a recording; with `settings` (and 4/4), also the exploratory
    `response`, replayed with those settings. A take the replay refuses (no clock,
    too long) has no `response`."""
    events = list(events)
    kept, ticks = _take(events)
    bars = ticks // (beats_per_bar * TICKS_PER_BEAT)
    patterns: list[set[tuple[str, int]]] = [set() for _ in range(bars)]
    hits, kicks, hats = [0] * bars, [0] * bars, [0] * bars
    off = total = 0
    for hit in tag_recording(kept, beats_per_bar):
        grid = hit.grid
        if grid is None or not 0 <= grid.bar < bars:
            continue
        role = roles[hit.pad] if hit.pad < len(roles) else "other"
        patterns[grid.bar].add((role, grid.step))
        hits[grid.bar] += 1
        kicks[grid.bar] += role == "kick"
        hats[grid.bar] += role == "hat"
        off += grid.step % 2
        total += 1
    frozen = [frozenset(p) for p in patterns]
    changes = tuple(distance(frozen[b - 1], frozen[b]) for b in range(1, bars))
    result = Measures(
        bars, tuple(hits), tuple(kicks), tuple(hats), off / total if total else None, changes
    )
    if settings is None or beats_per_bar != BEATS_PER_BAR:
        return result
    try:
        rows = replay(events, settings).rows
    except ValueError:
        return result
    return replace(result, response=response(changes, band_changes(rows)))


def band_changes(rows: Sequence[BarRow]) -> list[int]:
    """The song bars (0-based) whose bass or melody variation differs from the bar
    before. `rows[b]` holds the plans for bar `b + 1`."""

    def played(row: BarRow) -> tuple[str | None, ...]:
        return tuple(None if p is None else p.variation for p in (row.bass, row.melody))

    return [b + 1 for b in range(1, len(rows)) if played(rows[b]) != played(rows[b - 1])]


def response(changes: Sequence[float], bands: Sequence[int]) -> Response:
    """Exploratory: for each band change in song bar `c`, the first `k` (1 to `CAP`)
    whose `changes` from bar `c + k - 1` to `c + k` is above `THRESHOLD`. `changes[i]`
    is the change into bar `i + 1`. A change too near the end to see `CAP` bars, and
    not answered in the bars there are, is left out."""
    bars = len(changes) + 1
    latencies: list[int | None] = []
    for c in bands:
        found = next(
            (k for k in range(1, CAP + 1) if c + k < bars and changes[c + k - 1] > THRESHOLD),
            None,
        )
        if found is not None or c + CAP < bars:
            latencies.append(found)
    return Response(tuple(latencies))


def replay_settings(controls: Iterable[tuple[str, Sequence[Any]]]) -> Settings:
    """The replay `Settings` for `ensemble` controls in order (a trial's `messages`).
    Raises `ValueError` for a control the replay cannot play: `bass` other than
    `loop`, or a control it does not know."""
    values: dict[str, Any] = {}
    for control, args in controls:
        if control == "bass" and list(args) == ["loop"]:
            continue
        if control not in _FIELDS or len(args) != 1:
            raise ValueError(f"the replay cannot play {control} {' '.join(map(str, args))}")
        values[_FIELDS[control]] = args[0]
    return Settings(**values)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.measures",
        description="Objective measures of a recording made with `record --clock`.",
    )
    parser.add_argument("path", type=Path, help="a recording with MIDI clock")
    parser.add_argument(
        "--beats-per-bar", type=int, default=BEATS_PER_BAR, help="quarter notes per bar"
    )
    parser.add_argument("--trial", type=Path, help="a trial file, for the replay's settings")
    parser.add_argument("--condition", help="the condition of --trial the recording played")
    return parser


def _settings(trial: Path | None, condition: str | None) -> Settings:
    if trial is None:
        if condition is not None:
            raise ValueError("--condition needs --trial")
        return Settings()
    try:
        spec, _ = load_trial(trial)
    except TrialError as exc:
        raise ValueError(str(exc)) from exc
    chosen = [c for c in spec.conditions if c.name == condition]
    if not chosen:
        names = ", ".join(c.name for c in spec.conditions)
        raise ValueError(f"--condition must be one of {names}")
    return replay_settings(spec.messages(chosen[0]))


def format_value(value: float | None) -> str:
    if value is None:
        return "-"
    return str(value) if isinstance(value, int) else f"{value:.2f}"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.beats_per_bar < 1:
        print("error: --beats-per-bar must be at least 1", file=sys.stderr)
        return 2
    try:
        settings = _settings(args.trial, args.condition)
        events = read_recording(args.path).events
    except (OSError, RecordingFormatError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    result = measure(events, args.beats_per_bar, settings=settings)
    for key, value in result.summary().items():
        note = "\t(exploratory)" if key in EXPLORATORY else ""
        print(f"{key}\t{format_value(value)}{note}")
    if result.bars == 0:
        print("no complete bar with MIDI clock: record with --clock", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
