"""Run `ensemble` offline on a step grid of drums (#166).

The grid is played into the real `Ensemble` the way the engine plays a live MPC
into it: a `MidiClock` gets Start and 24 ticks per beat at the grid's tempo, each
tick goes through `ClockAccess.bar_line` and `Scheduler.update`, and each hit
arrives through `ClockAccess.deliver` on its step's tick. Nothing waits on the wall
clock, so the demo hears exactly what the instrument would play and cannot drift
from it.

The drums are pads 1 (kick), 2 (snare) and 3 (hat) of bank A, as in
`ensemble.DEFAULT_ROLES`. The song is the grid and one more bar, since the band
answers each bar in the bar after it (RFC 0005). The bass plays the bass loop
(`bass loop`); the other settings go through the preset's controls. The surprises
(#158) are drawn from `Settings.seed`, so the same grid and settings always give
the same song.

`Settings.learn` is the setting `learn` (`off` or `nod`, #250). Each row shows the
contexts of its bar and where each choice came from (`chose`), and the song keeps
the learning log lines and the final `learned` reply. With `nod`, `Settings.nods`
sends the control `nod` in the first beat of the bar after each listed
grid bar, so the nod counts for that bar, as pad 16 does live; a replayed recording's
pad 16 is the nod itself. The groove settings `follow-by`, `answer-after`,
`learn-group` and `new-groove` go through the controls of the same name. Nothing is
saved: the demo has no data folder, so there is no profile and no learn log.
"""

import functools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from mpc_iml.clock import SIXTEENTHS, TICKS_PER_BEAT, BarStart, ClockAccess, MidiClock, Scheduler
from mpc_iml.ensemble import DEFAULT_ROLES, LEARN_MODES, Ensemble
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.frames import bank_pad_to_note, note_to_bank_pad
from mpc_iml.learn import PARTS
from mpc_iml.learn import context as learn_context
from mpc_iml.melody import BarPlan
from mpc_iml.progressions import Progression, load_progressions
from mpc_iml.sources import CLOCK_BYTES

__all__ = [
    "BEATS_PER_BAR",
    "DRUMS",
    "DRUM_NOTES",
    "MAX_BARS",
    "STEPS",
    "TEMPO_RANGE",
    "BarRow",
    "Note",
    "Settings",
    "Song",
    "chord_name",
    "replay",
    "simulate",
]

DRUMS = ("kick", "snare", "hat")
"""The rows of the grid, played on pads 1, 2 and 3."""

DRUM_NOTES = {"kick": 36, "snare": 38, "hat": 42}
"""General MIDI notes of the drums in the song (for the piano roll and MIDI file)."""

STEPS = 16
BEATS_PER_BAR = 4
MAX_BARS = 64
"""At most this many bars, so a shared demo cannot be made to render minutes of audio."""

TEMPO_RANGE = (60.0, 160.0)

_PARTS = {2: "bass", 3: "keys"}
"""The `ensemble` channels in the song, by default setting."""

_START, _TICK = b"\xfa", b"\xf8"
_TAKE_ENDS = frozenset((0xFA, 0xFB, 0xFC, 0xF2))
"""Start, Continue, Stop and Song Position: after the first Start, the end of the take."""
_SURPRISE = re.compile(r"ensemble: surprise (\w+) in bar (\d+)")
"""The line `ensemble` logs for each surprise (#158): information, not a failure."""
_MOTIF = re.compile(r"ensemble: rhythm motif (kick|snare)[\w ]*")
"""The line `ensemble` logs for the motif at a phrase start (#189): information."""
_LEARNING = re.compile(r"ensemble: (nod|groove \d+) .*")
"""The lines `ensemble` logs while learning (the nods and the grooves they play in,
#250): kept in `Song.learning`."""


@functools.cache
def progressions() -> Mapping[str, Progression]:
    """The built-in and installed progressions (#236), read once: the demo has no
    data folder."""
    return MappingProxyType(load_progressions())


@dataclass(frozen=True)
class Settings:
    """The demo's settings: the tempo and the `ensemble` controls of the same name."""

    tempo: float = 90.0
    progression: str = "minor-two"
    bass_loop: str = "boom"
    loop: str = "keys"
    melody_mode: str = "follow"
    no_drums: str = "lead"
    fade_bars: int = 8
    surprise: int = 1
    """The phrase-end surprises (#158) as the control `surprise`: 0 off, 1 (the
    default, as in the instrument) the bass fill only, 2 also the melody surprises
    (#178)."""
    rhythm: int = 0
    """The rhythm transformation (#189) as the setting `rhythm`: 0 (the default, as
    in the instrument, #194) off, 1 the bass follows the kicks, 2 also the melody
    follows the snares and hats."""
    seed: int = 0
    """The seed of the surprises (`Ensemble(seed=…)`), fixed so a run is reproducible."""
    learn: str = "off"
    """The setting `learn`: `off` (the default, the rules) or `nod` (#250)."""
    mode_pads: int = 1
    """The setting `mode-pads` (#216): 1 (the default, as in the instrument) pads 15
    and 16 of a replayed recording switch the modes, 0 they do not."""
    follow_by: str = "bar"
    """The setting `follow-by` (#250): `bar` (the default, as in the instrument) or
    `groove`."""
    answer_after: int = 2
    """The setting `answer-after` (#250): 2 (the default) or 1."""
    learn_group: int = 0
    """The setting `learn-group` (#250): 0 (the default) or 1."""
    new_groove: str = "rules"
    """The setting `new-groove` (#250): `rules` (the default) or `invite`."""
    nods: tuple[int, ...] = ()
    """With `learn nod`: the grid bars (from 0) the musician nods to, with the control
    `nod` in the first beat of the bar after each (`learn.liked_bar`)."""


@dataclass(frozen=True)
class Note:
    """A note of the song: `part` is a drum (`DRUMS`), `bass` or `keys`; `tick` and
    `ticks` are its start and length in MIDI clock ticks from song start; `moved`
    says the rhythm transformation moved it to a drum hit (#189)."""

    part: str
    tick: int
    ticks: int
    pitch: int
    velocity: int
    moved: bool = False


@dataclass(frozen=True)
class BarRow:
    """The drums of grid bar `bar` (0-based) and what the band chose for the bar after
    it: `kicks` and `hats` are the steps of those hits, `hits` every drum hit,
    `velocity` their average (`None`: no hits); `chord` is the next bar's chord;
    `bass` and `melody` are the plans `ensemble` made (`None`: it does not play),
    `rule` says why: `drums`, `fixed`, `still` (the melody, #233), or the `no-drums`
    setting for a bar without drums (without kicks, for the bass); `surprise` is the
    surprise the band played in the bar after it (`fill`, `octave` or `passing`;
    `None`: none, #158)."""

    bar: int
    kicks: tuple[int, ...]
    hats: tuple[int, ...]
    hits: int
    velocity: float | None
    chord: str
    bass: BarPlan | None
    bass_rule: str
    melody: BarPlan | None
    melody_rule: str
    surprise: str | None = None
    context: tuple[str, str] = ("-", "-")
    """The bass and melody contexts of the bar's drums (`learn.context`, #196)."""
    chose: tuple[str, str] = ("-", "-")
    """Where the bass and melody choice for the bar after it came from, as the reply
    `chose`: `rule`, `still`, `nod`, `group`, `invite`, `fill`, or `-` when the loop
    is silent."""


@dataclass(frozen=True)
class Song:
    """The result of `simulate`: `bars` is the song length (the grid and one bar),
    `notes` in start order, `brightness` the `(tick, value)` of each brightness CC
    the melody sent, `rows` one per grid bar."""

    settings: Settings
    bars: int
    notes: tuple[Note, ...]
    brightness: tuple[tuple[int, int], ...]
    rows: tuple[BarRow, ...]
    learning: tuple[str, ...] = ()
    """The learning log lines (the nods and the grooves they play in)."""
    learned: tuple[str, ...] = ()
    """The reply `learned` at the end: up to 4 `bass:groove <id>><variation>` for the
    nodded grooves (empty: none)."""

    @property
    def seconds_per_tick(self) -> float:
        return 60.0 / self.settings.tempo / TICKS_PER_BEAT

    @property
    def ticks(self) -> int:
        return self.bars * BEATS_PER_BAR * TICKS_PER_BEAT

    @property
    def seconds(self) -> float:
        return self.ticks * self.seconds_per_tick


Grid = Sequence[Mapping[str, Sequence[int]]]
"""One mapping per bar from each drum to its 16 steps: 0 is no hit, 1-127 a velocity
(a missing drum has no hits)."""


def chord_name(progression: str, bar: int) -> str:
    """The name of the chord of `bar` in `progression`, for example `Am7`."""
    return progressions()[progression].chord_name(bar)


def simulate(
    grid: Grid,
    settings: Settings = Settings(),
    library: Mapping[str, Progression] | None = None,
) -> Song:
    """Play `grid` into a new `Ensemble` with `settings` and collect what it plays.

    Raises `ValueError` for a grid of no bars or more than `MAX_BARS`, a drum or step
    count other than `DRUMS` and `STEPS`, a velocity outside 0-127, a tempo outside
    `TEMPO_RANGE`, a nod outside the grid or the `learn` mode, or a setting the
    preset's controls refuse. `library` holds the progressions `settings.progression`
    names (default `progressions()`).
    """
    hits = _hits(grid)
    low, high = TEMPO_RANGE
    if not low <= settings.tempo <= high:
        raise ValueError(f"tempo must be {low:g}-{high:g}, got {settings.tempo:g}")
    _check_learning(settings, len(grid))
    run = _Run(settings, library)
    interval = 60.0 / settings.tempo / TICKS_PER_BEAT
    song_bars = len(grid) + 1
    run.feed(_START, 0.0)
    for tick in range(song_bars * BEATS_PER_BAR * TICKS_PER_BEAT):
        t = tick * interval
        run.feed(_TICK, t)
        for pad, velocity in hits.get(tick, ()):
            run.hit(MidiEvent(t, "note_on", 1, velocity, bank_pad_to_note(0, pad)))
    return run.song(len(grid), settings)


def replay(
    events: Iterable[Event],
    settings: Settings = Settings(),
    library: Mapping[str, Progression] | None = None,
) -> Song:
    """Play a recording made with `record --clock` (ADR 0002) into a new `Ensemble`.

    The events go in time order as the engine plays them live: each clock message to
    the clock (then the bar lines and the scheduler), each pad Note On through
    `ClockAccess.deliver`, at its recorded time. The take is the clock from its first
    Start up to the next Stop, Continue, Song Position or Start; later events are
    ignored. The band then plays one more bar at the last tempo, as for a grid.

    The drums of the song are the hits of `kick`, `snare` and `hat` pads
    (`DEFAULT_ROLES`, any bank) while the clock runs, at their clock position. The
    song's tempo (`Settings.tempo`) is the clock's at the end of the take, and the
    audio renders at that tempo. Raises `ValueError` for a recording without a Start
    and 24 ticks, or of more than `MAX_BARS` bars, and as `simulate` for the learning
    settings (a nod after the take does nothing). `library` as for
    `simulate` (`measures --data` adds the musician's own progressions, #236).
    """
    _check_learning(settings, MAX_BARS)
    run: _Run | None = None
    t = 0.0
    for event in events:
        if isinstance(event, RawMidiEvent) and event.data[:1] and event.data[0] in CLOCK_BYTES:
            if run is None:
                if event.data[0] != _START[0]:
                    continue
                run = _Run(settings, library)
            elif event.data[0] in _TAKE_ENDS:
                break
            t = event.t
            run.feed(event.data, t)
            if run.clock.state().bar >= MAX_BARS:
                raise ValueError(f"the recording must have at most {MAX_BARS} bars")
        elif run is not None and isinstance(event, MidiEvent) and event.kind == "note_on":
            run.clock.check(event.t)
            run.hit(event)
    state = run.clock.state() if run is not None else None
    if run is None or state is None or state.bpm is None:
        raise ValueError(
            "the recording has no MIDI clock: record it with `python -m mpc_iml.record --clock`"
        )
    interval = 60.0 / state.bpm / TICKS_PER_BEAT
    grid_bars = state.bar + 1
    for _ in range(state.tick + 1, (grid_bars + 1) * BEATS_PER_BAR * TICKS_PER_BEAT):
        t += interval
        run.feed(_TICK, t)
    return run.song(grid_bars, replace(settings, tempo=state.bpm))


def _check_learning(settings: Settings, bars: int) -> None:
    """Refuse a `learn` mode or nod `simulate` and `replay` cannot play."""
    if settings.learn not in LEARN_MODES:
        raise ValueError(f"learn must be one of {', '.join(LEARN_MODES)}, got {settings.learn!r}")
    if settings.nods and settings.learn != "nod":
        raise ValueError("nods need learn nod")
    for bar in settings.nods:
        if not 0 <= bar < bars:
            raise ValueError(f"a nod must be in bars 1-{bars}, got bar {bar + 1}")


class _Run:
    """A new `Ensemble` with `settings` on a simulated clock, collecting what it plays."""

    def __init__(
        self, settings: Settings, library: Mapping[str, Progression] | None = None
    ) -> None:
        self.log: list[str] = []
        self.learning: list[str] = []
        self.surprises: dict[int, str] = {}
        self.chose: dict[int, tuple[str, str]] = {}
        self._nods = {bar + 1 for bar in settings.nods}
        self._nodded: set[int] = set()
        self.clock = MidiClock(BEATS_PER_BAR)
        self.sent: list[tuple[int, bytes]] = []
        self.drums: list[Note] = []
        clock = self.clock
        self.scheduler = Scheduler(clock, lambda m: self.sent.append((clock.state().tick, m)))
        self.access = ClockAccess(clock, self.log.append, self.scheduler)
        library = progressions() if library is None else library
        ensemble = Ensemble(self._ensemble_log, seed=settings.seed, progressions=library)
        controls = ensemble.controls()
        controls["bass"](["loop"])
        controls["bass-loop"]([settings.bass_loop])
        controls["loop"]([settings.loop])
        controls["progression"]([settings.progression])
        controls["melody-mode"]([settings.melody_mode])
        controls["no-drums"]([settings.no_drums])
        controls["fade-bars"]([settings.fade_bars])
        controls["surprise"]([settings.surprise])
        controls["rhythm"]([settings.rhythm])
        controls["learn"]([settings.learn])
        controls["mode-pads"]([settings.mode_pads])
        controls["follow-by"]([settings.follow_by])
        controls["answer-after"]([settings.answer_after])
        controls["learn-group"]([settings.learn_group])
        controls["new-groove"]([settings.new_groove])
        controls["status"]([0])  # the page shows the bars in its table (#230)
        self.ensemble, self._nod = ensemble, controls["nod"]
        self.chords = ensemble.progression
        ensemble.attach(self.access)
        self.bars: dict[int, tuple[BarStart, dict[str, BarPlan | None]]] = {}
        self.access.on_bar(self._bar)

    def _bar(self, start: BarStart) -> None:
        """After `ensemble` planned the bar that starts now: keep its plans and `chose`."""
        self.bars[start.bar] = (start, self.ensemble.plans)
        state = dict(self.ensemble.state())
        bass, melody = state["chose"]
        self.chose[start.bar] = (str(bass), str(melody))

    def _ensemble_log(self, line: str) -> None:
        match = _SURPRISE.fullmatch(line)
        if match:
            self.surprises[int(match[2])] = match[1]
        elif _LEARNING.fullmatch(line):
            self.learning.append(line)
        elif not _MOTIF.fullmatch(line):
            self.log.append(line)

    def feed(self, data: bytes, t: float) -> None:
        """One clock message at `t`, then the bar lines, a nod due and the notes
        now due."""
        self.clock.feed(data, t)
        self.access.bar_line()
        state = self.clock.state()
        if state.status == "running" and state.bar in self._nods - self._nodded:
            self._nodded.add(state.bar)
            self._nod([])
        self.scheduler.update(t)

    def hit(self, event: MidiEvent) -> None:
        """A pad Note On; a drum while the clock runs is also a note of the song."""
        position = self.clock.position(event.t)
        if position is not None and event.note is not None and event.value > 0:
            drum = DEFAULT_ROLES[note_to_bank_pad(event.note)[1]]
            if drum in DRUMS:
                tick = max(round(position), 0)
                self.drums.append(Note(drum, tick, SIXTEENTHS, DRUM_NOTES[drum], event.value))
        self.access.deliver(event)

    def song(self, grid_bars: int, settings: Settings) -> Song:
        if self.log:
            raise RuntimeError(f"ensemble failed: {self.log}")
        song_bars = grid_bars + 1
        total = song_bars * BEATS_PER_BAR * TICKS_PER_BEAT
        sent = self.sent
        moves = _moves(self.bars, self.surprises)
        notes = self.drums + [
            replace(n, moved=True) if _moved(n, moves) else n for n in _band_notes(sent, total)
        ]
        brightness = tuple(
            (tick, m[2]) for tick, m in sent if m[0] & 0xF0 == 0xB0 and m[0] & 0x0F == 2
        )
        rows = tuple(
            replace(
                _row(b, *self.bars[b + 1], settings, self.surprises.get(b + 1), self.chords),
                chose=self.chose[b + 1],
            )
            for b in range(grid_bars)
        )
        learned = [str(c) for c in dict(self.ensemble.state())["learned"] if c != "-"]
        return Song(
            settings,
            song_bars,
            tuple(sorted(notes, key=lambda n: (n.tick, n.part))),
            brightness,
            rows,
            tuple(self.learning),
            tuple(learned),
        )


def _hits(grid: Grid) -> dict[int, list[tuple[int, int]]]:
    """The `(pad, velocity)` hits of `grid` by tick."""
    if not 1 <= len(grid) <= MAX_BARS:
        raise ValueError(f"the grid must have 1-{MAX_BARS} bars, got {len(grid)}")
    hits: dict[int, list[tuple[int, int]]] = {}
    for bar, rows in enumerate(grid):
        unknown = set(rows) - set(DRUMS)
        if unknown:
            raise ValueError(f"unknown drums {sorted(unknown)}; expected {', '.join(DRUMS)}")
        for pad, drum in enumerate(DRUMS):
            steps = rows.get(drum, [0] * STEPS)
            if len(steps) != STEPS:
                raise ValueError(f"bar {bar + 1} {drum}: expected {STEPS} steps, got {len(steps)}")
            for step, velocity in enumerate(steps):
                if not 0 <= velocity <= 127 or velocity != int(velocity):
                    raise ValueError(f"bar {bar + 1} {drum}: velocity must be 0-127")
                if velocity:
                    tick = (bar * STEPS + step) * SIXTEENTHS
                    hits.setdefault(tick, []).append((pad, int(velocity)))
    return hits


_PLAN_PARTS = {"bass": "bass", "melody": "keys"}
"""The part of the song each loop's plan plays."""
_NEAR = SIXTEENTHS // 3
"""A moved note starts within this many ticks of its step: it takes half of a hit's
offset (at most half a step), so at most a quarter step, 2 ticks once rounded."""


def _moves(
    bars: Mapping[int, tuple[BarStart, Mapping[str, BarPlan | None]]],
    surprises: Mapping[int, str],
) -> dict[str, set[int]]:
    """The ticks from song start that the rhythm transformation moved a note to, by
    part. A move that keeps its step is not counted, and the bass `fill` replaces
    the last beat, so moves into it do not sound."""
    moves: dict[str, set[int]] = {part: set() for part in _PLAN_PARTS.values()}
    for bar, (_, plans) in bars.items():
        for loop, part in _PLAN_PARTS.items():
            plan = plans.get(loop)
            if plan is None or plan.taken is None:
                continue
            for move in plan.taken.moves:
                if move.step == move.start:
                    continue
                if part == "bass" and surprises.get(bar) == "fill" and move.step >= STEPS - 4:
                    continue
                moves[part].add((bar * STEPS + move.step) * SIXTEENTHS)
    return moves


def _moved(note: Note, moves: Mapping[str, set[int]]) -> bool:
    ticks = moves.get(note.part, set())
    return any(abs(note.tick - tick) <= _NEAR for tick in ticks)


def _band_notes(sent: Sequence[tuple[int, bytes]], end: int) -> list[Note]:
    """Pair the Note On and Note Off messages `ensemble` sent; a note still sounding
    at the end of the song ends there."""
    notes: list[Note] = []
    sounding: dict[tuple[int, int], tuple[int, int]] = {}

    def close(key: tuple[int, int], tick: int) -> None:
        start, velocity = sounding.pop(key)
        notes.append(Note(_PARTS[key[0]], start, max(tick - start, 1), key[1], velocity))

    for tick, message in sent:
        kind, channel = message[0] & 0xF0, (message[0] & 0x0F) + 1
        if channel not in _PARTS or kind not in (0x80, 0x90):
            continue
        key = (channel, message[1])
        if key in sounding:
            close(key, tick)
        if kind == 0x90 and message[2] > 0:
            sounding[key] = (tick, message[2])
    for key in list(sounding):
        close(key, end)
    return notes


def _row(
    bar: int,
    start: BarStart,
    plans: Mapping[str, BarPlan | None],
    s: Settings,
    surprise: str | None,
    chords: Progression,
) -> BarRow:
    roles = [DEFAULT_ROLES[h.pad] for h in start.hits]
    kicks = tuple(h.step for h, r in zip(start.hits, roles, strict=True) if r == "kick")
    hats = tuple(h.step for h, r in zip(start.hits, roles, strict=True) if r == "hat")
    velocities = [h.velocity for h in start.hits]
    fixed = s.melody_mode == "fixed"

    def rule(drums: bool) -> str:
        return "fixed" if fixed else "drums" if drums else s.no_drums

    melody_rule = "still" if s.melody_mode == "still" else rule(bool(start.hits))

    return BarRow(
        bar,
        kicks,
        hats,
        len(start.hits),
        sum(velocities) / len(velocities) if velocities else None,
        chords.chord_name(bar + 1),
        plans["bass"],
        rule(bool(kicks)),
        plans["melody"],
        melody_rule,
        surprise,
        (
            learn_context(PARTS[0], start.hits, DEFAULT_ROLES),
            learn_context(PARTS[1], start.hits, DEFAULT_ROLES),
        ),
    )
