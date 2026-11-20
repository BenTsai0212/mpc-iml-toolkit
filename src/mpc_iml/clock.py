"""MIDI clock: tempo, bar and beat position, and grid tags for pad hits (ADR 0008).

`MidiClock` reads MIDI clock messages from a DAW (24 ticks per quarter note, Start,
Stop, Continue and Song Position Pointer) and tracks the transport status, the
tempo and the position. It only uses the standard library and has no I/O: whoever
reads the clock port calls `feed(data, t)` with each message and the time it
arrived, in the same time base as the gesture source. Tests feed simulated clock.

Positions count from 0 in this API (protocol replies and front ends show them from
1). A bar is `beats_per_bar` quarter notes (4/4 assumed; MIDI clock carries no
meter). `step` is a grid step within the bar; the grid is 16ths unless a caller
asks for another resolution.

`feed` and `check` may run on the clock input thread while other threads read
`state()`, `position(t)` or `tag(event)`, so the clock guards its state with a lock.

`Scheduler` sends raw MIDI messages (notes, control changes) at grid positions, and
plays the engine's test pattern (`/mpciml/clock/test`).

`ClockAccess` is what a preset's provisional `Preset.clock` hook receives from the
engine: read-only access to the clock, every pad hit (placed on the grid while the
clock runs), the scheduler, and a path for notes sent at once. The engine calls the
hook with sync off too, with no clock and no scheduler (#138).

`tag_recording` places the pad hits of a recording made with `record --clock` on
the grid after the fact, with the same `MidiClock` the engine uses live (#139).
"""

import math
import threading
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, TypeVar

from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.frames import note_to_bank_pad

__all__ = [
    "EIGHTHS",
    "LOST_AFTER",
    "SIXTEENTH_TRIPLETS",
    "SIXTEENTHS",
    "TEST_NOTES",
    "TICKS_PER_BEAT",
    "ClockAccess",
    "ClockState",
    "ClockStatus",
    "GridHit",
    "HitCallback",
    "MidiClock",
    "PadCallback",
    "PadHit",
    "Scheduled",
    "Scheduler",
    "off_state",
    "tag_recording",
]

ClockStatus = Literal["off", "waiting", "running", "stopped", "lost"]

TICKS_PER_BEAT = 24
"""MIDI clock ticks per quarter note."""

SIXTEENTHS = 6
EIGHTHS = 12
SIXTEENTH_TRIPLETS = 4
"""Ticks per grid step for the supported resolutions (16ths is the default)."""

LOST_AFTER = 0.5
"""Seconds without a tick while `running` before the status becomes `lost`."""

_H = TypeVar("_H", "GridHit", "PadHit")

_TICK, _START, _CONTINUE, _STOP, _SONG_POSITION = 0xF8, 0xFA, 0xFB, 0xFC, 0xF2


@dataclass(frozen=True)
class ClockState:
    """A snapshot of the clock.

    `tick` is the position of the last tick since song start (-1 before the first
    tick after Start). `bar` counts from song start; `beat` is the quarter note in
    the bar and `step` the 16th in the bar. `bpm` is `None` until 24 ticks have
    arrived; `t_tick` is the time of the last tick (`None` before any).
    """

    status: ClockStatus
    bpm: float | None
    tick: int
    bar: int
    beat: int
    step: int
    t_tick: float | None
    beats_per_bar: int


def off_state(beats_per_bar: int = 4) -> ClockState:
    """The state reported when sync is not enabled."""
    return ClockState("off", None, -1, 0, 0, 0, None, beats_per_bar)


@dataclass(frozen=True)
class GridHit:
    """A pad hit placed on the grid.

    `pad` and `bank` count from 0, as in `frames`. `bar` counts from song start and
    `step` is the step within that bar (a hit just before a bar line rounds to step
    0 of the next bar). `offset` is how far the hit is from its step, in steps
    (-0.5 to 0.5, negative is early); `offset_ms` is the same in milliseconds.
    """

    t: float
    pad: int
    bank: int
    velocity: int
    bar: int
    step: int
    offset: float
    offset_ms: float


class MidiClock:
    """Parses MIDI clock messages and tracks status, tempo and position."""

    def __init__(self, beats_per_bar: int = 4, lost_after: float = LOST_AFTER) -> None:
        if beats_per_bar < 1:
            raise ValueError(f"beats_per_bar must be at least 1: {beats_per_bar}")
        self.beats_per_bar = beats_per_bar
        self.lost_after = lost_after
        self._lock = threading.Lock()
        self._status: ClockStatus = "waiting"
        self._next_tick = 0
        self._tick = -1
        self._t_tick: float | None = None
        self._t_last: float | None = None
        self._tick_times: deque[float] = deque(maxlen=TICKS_PER_BEAT + 1)
        self._run_times: deque[float] = deque(maxlen=TICKS_PER_BEAT + 1)

    def feed(self, data: bytes, t: float) -> ClockState:
        """Handle one MIDI message received at time `t`; ignore non-clock messages.

        Start sets the position to 0 and Continue resumes from the current position
        (moved by Song Position Pointer); the first tick after either is at that
        position. Ticks without a Start or Continue (the DAW was already playing, or
        sends clock while stopped) only update the tempo, and the status becomes
        `stopped` until the transport starts.
        """
        with self._lock:
            if not data:
                return self._snapshot()
            kind = data[0]
            if kind == _TICK:
                self._on_tick(t)
            elif kind == _START:
                self._next_tick = 0
                self._tick = -1
                self._run(t)
            elif kind == _CONTINUE:
                self._tick = self._next_tick - 1
                self._run(t)
            elif kind == _STOP:
                if self._status != "waiting":
                    self._status = "stopped"
            elif kind == _SONG_POSITION and len(data) == 3:
                sixteenths = data[1] | (data[2] << 7)
                self._next_tick = sixteenths * SIXTEENTHS
                self._tick = self._next_tick - 1
            return self._snapshot()

    def check(self, t: float) -> ClockState:
        """Mark the clock `lost` if no tick arrived for `lost_after` seconds."""
        with self._lock:
            if (
                self._status == "running"
                and self._t_last is not None
                and t - self._t_last > self.lost_after
            ):
                self._status = "lost"
            return self._snapshot()

    def state(self) -> ClockState:
        """The current snapshot."""
        with self._lock:
            return self._snapshot()

    def position(self, t: float) -> float | None:
        """The position of time `t` in ticks since song start, or `None`.

        `None` unless the clock is `running` and a tick has arrived since Start or
        Continue. Between ticks the position is interpolated with the tempo, from
        the last tick's time fitted over up to one beat of ticks.
        """
        with self._lock:
            return self._position(t)

    def tag(self, event: Event, ticks_per_step: int = SIXTEENTHS) -> GridHit | None:
        """Place a pad hit (`note_on` with velocity above 0) on the grid.

        Returns `None` for other events and when `position` is `None`. A hit exactly
        halfway between two steps goes to the later one.
        """
        if TICKS_PER_BEAT % ticks_per_step:
            raise ValueError(f"ticks_per_step must divide {TICKS_PER_BEAT}: {ticks_per_step}")
        if not (
            isinstance(event, MidiEvent)
            and event.kind == "note_on"
            and event.note is not None
            and event.value > 0
        ):
            return None
        with self._lock:
            position = self._position(event.t)
            interval = self._interval()
        if position is None:
            return None
        steps = position / ticks_per_step
        step = math.floor(steps + 0.5)
        offset = steps - step
        steps_per_bar = self.beats_per_bar * TICKS_PER_BEAT // ticks_per_step
        bank, pad = note_to_bank_pad(event.note)
        offset_ms = offset * ticks_per_step * interval * 1000 if interval else 0.0
        return GridHit(
            t=event.t,
            pad=pad,
            bank=bank,
            velocity=event.value,
            bar=step // steps_per_bar,
            step=step % steps_per_bar,
            offset=offset,
            offset_ms=offset_ms,
        )

    def _run(self, t: float) -> None:
        self._status = "running"
        self._t_last = t
        self._t_tick = None
        self._run_times.clear()

    def _on_tick(self, t: float) -> None:
        times = self._tick_times
        if times and t - times[-1] > self.lost_after:
            times.clear()
            self._run_times.clear()
        times.append(t)
        self._t_last = t
        if self._status in ("running", "lost"):
            self._status = "running"
            self._run_times.append(t)
            self._tick = self._next_tick
            self._next_tick += 1
            self._t_tick = t
        elif self._status == "waiting":
            self._status = "stopped"

    def _interval(self) -> float | None:
        """Seconds per tick, averaged over the last beat (None before two ticks)."""
        times = self._tick_times
        if len(times) < 2:
            return None
        return (times[-1] - times[0]) / (len(times) - 1)

    def _bpm(self) -> float | None:
        interval = self._interval()
        if len(self._tick_times) < TICKS_PER_BEAT or not interval:
            return None
        return 60.0 / (interval * TICKS_PER_BEAT)

    def _position(self, t: float) -> float | None:
        if self._status != "running" or self._tick < 0 or not self._run_times:
            return None
        interval = self._interval()
        if not interval:
            return float(self._tick)
        # The last tick's time, fitted over the ticks since Start or Continue (up to
        # one beat), so the jitter of a single tick does not move the grid.
        runs = self._run_times
        anchor = sum(runs) / len(runs) + (len(runs) - 1) / 2 * interval
        return self._tick + (t - anchor) / interval

    def _snapshot(self) -> ClockState:
        tick = max(self._tick, 0)
        beat = tick // TICKS_PER_BEAT
        return ClockState(
            status=self._status,
            bpm=self._bpm(),
            tick=self._tick,
            bar=beat // self.beats_per_bar,
            beat=beat % self.beats_per_bar,
            step=(tick // SIXTEENTHS) % (self.beats_per_bar * TICKS_PER_BEAT // SIXTEENTHS),
            t_tick=self._t_tick,
            beats_per_bar=self.beats_per_bar,
        )


HitCallback = Callable[[GridHit], None]
"""Receives each pad hit placed on the grid (`ClockAccess.on_hit`)."""


@dataclass(frozen=True)
class PadHit:
    """A pad hit in any clock status (`ClockAccess.on_pad`).

    `pad` and `bank` count from 0, as in `GridHit`. `grid` is the hit placed on the
    grid while the clock is `running`, otherwise `None` (sync off, `waiting`,
    `stopped` or `lost`).
    """

    t: float
    pad: int
    bank: int
    velocity: int
    grid: GridHit | None


PadCallback = Callable[[PadHit], None]
"""Receives every pad hit (`ClockAccess.on_pad`)."""


class ClockAccess:
    """Access to the engine's clock and note output for one loaded preset (ADR 0008).

    **Provisional**, like `Preset.controls`. The engine makes a new one each time a
    preset loads and passes it to the preset's `clock` hook, so callbacks registered
    by an earlier preset stop when another one loads. With sync off, `clock` and
    `scheduler` are `None`: `state()` is `off`, `position` is `None`, `on_hit` never
    fires, and `on_pad` and `send_now` still work.
    """

    def __init__(
        self,
        clock: MidiClock | None,
        log: Callable[[str], None] = lambda line: None,
        scheduler: "Scheduler | None" = None,
        send: Callable[[bytes], None] | None = None,
        beats_per_bar: int = 4,
    ) -> None:
        self._clock = clock
        self._log = log
        self.scheduler = scheduler
        """The engine's `Scheduler` for notes at grid positions (`None` without sync)."""
        self._send = send
        self._beats_per_bar = clock.beats_per_bar if clock is not None else beats_per_bar
        self._hits: list[tuple[HitCallback, int]] = []
        self._pads: list[tuple[PadCallback, int]] = []

    def state(self) -> ClockState:
        """The clock's current snapshot (`off` without sync)."""
        if self._clock is None:
            return off_state(self._beats_per_bar)
        return self._clock.state()

    def position(self, t: float) -> float | None:
        """The position of time `t` in ticks since song start (`MidiClock.position`)."""
        return self._clock.position(t) if self._clock is not None else None

    def on_hit(self, callback: HitCallback, ticks_per_step: int = SIXTEENTHS) -> None:
        """Call `callback` with every pad hit while the clock is `running`.

        `ticks_per_step` is the grid: `SIXTEENTHS` (default), `EIGHTHS` or
        `SIXTEENTH_TRIPLETS`. The callback runs on the engine's input thread, so it
        must return quickly; an exception is logged and the hit is dropped.
        """
        _check_step(ticks_per_step)
        self._hits.append((callback, ticks_per_step))

    def on_pad(self, callback: PadCallback, ticks_per_step: int = SIXTEENTHS) -> None:
        """Call `callback` with every pad hit (velocity above 0), in any clock status.

        `PadHit.grid` is placed on the `ticks_per_step` grid while the clock is
        `running`, otherwise `None`. Same thread and error rules as `on_hit`.
        """
        _check_step(ticks_per_step)
        self._pads.append((callback, ticks_per_step))

    def send_now(self, messages: Sequence[bytes]) -> None:
        """Send raw MIDI `messages` at once, in order, on the engine's note path.

        With sync on they go through the scheduler, so the notes they start count as
        sounding and are ended on Stop, `lost`, `clear` and a preset switch. Without
        sync the preset ends its own notes. A failed send is logged.
        """
        if self.scheduler is not None:
            self.scheduler.send_now(messages)
            return
        for message in messages:
            if self._send is None:
                return
            try:
                self._send(bytes(message))
            except Exception as error:
                self._log(f"MIDI message not sent: {error!r}")

    def deliver(self, event: Event) -> None:
        """Pass a pad hit to every `on_pad` and `on_hit` callback (called by the engine)."""
        if not (
            isinstance(event, MidiEvent)
            and event.kind == "note_on"
            and event.note is not None
            and event.value > 0
        ):
            return
        tags: dict[int, GridHit | None] = {}

        def tag(ticks_per_step: int) -> GridHit | None:
            if ticks_per_step not in tags:
                clock = self._clock
                tags[ticks_per_step] = clock.tag(event, ticks_per_step) if clock else None
            return tags[ticks_per_step]

        bank, pad = note_to_bank_pad(event.note)
        for pad_callback, ticks_per_step in list(self._pads):
            self._call(pad_callback, PadHit(event.t, pad, bank, event.value, tag(ticks_per_step)))
        for hit_callback, ticks_per_step in list(self._hits):
            hit = tag(ticks_per_step)
            if hit is not None:
                self._call(hit_callback, hit)

    def _call(self, callback: Callable[[_H], None], hit: _H) -> None:
        try:
            callback(hit)
        except Exception as error:
            self._log(f"clock hit callback failed: {error!r}")


def tag_recording(
    events: Iterable[Event], beats_per_bar: int = 4, ticks_per_step: int = SIXTEENTHS
) -> list[PadHit]:
    """Every pad hit of a recording, placed on the grid by the clock recorded with it.

    Replays the recording's raw clock messages through a new `MidiClock` in time
    order, as the engine does live: positions are interpolated from the ticks up to
    each hit, and a hit more than `LOST_AFTER` seconds after the last tick is not
    placed. Hits while the clock is not `running` (before Start, after Stop, lost)
    keep `grid=None`; they are returned, not dropped.
    """
    _check_step(ticks_per_step)
    clock = MidiClock(beats_per_bar)
    hits: list[PadHit] = []
    for event in events:
        if isinstance(event, RawMidiEvent):
            clock.feed(event.data, event.t)
        elif (
            isinstance(event, MidiEvent)
            and event.kind == "note_on"
            and event.note is not None
            and event.value > 0
        ):
            clock.check(event.t)
            bank, pad = note_to_bank_pad(event.note)
            grid = clock.tag(event, ticks_per_step)
            hits.append(PadHit(event.t, pad, bank, event.value, grid))
    return hits


def _check_step(ticks_per_step: int) -> None:
    if TICKS_PER_BEAT % ticks_per_step:
        raise ValueError(f"ticks_per_step must divide {TICKS_PER_BEAT}: {ticks_per_step}")


TEST_NOTES = (72, 60)
"""The test pattern's notes: on beat 1 of each bar, and on the other beats."""

_TEST_VELOCITY = 100


class Scheduled:
    """A handle for messages queued on a `Scheduler`; pass it to `cancel`."""

    def __init__(self, tick: int) -> None:
        self.tick = tick
        """When the first message is due, in ticks since song start."""


class Scheduler:
    """Sends raw MIDI messages at grid positions of a `MidiClock` (ADR 0008).

    Positions are absolute: `bar` counts from song start (0-based) and `step` is a
    16th within the bar, unless `ticks_per_step` says otherwise. Nothing is sent by a
    timer: whoever feeds the clock calls `update(t)` after each clock message (and
    may call it more often, for example on every frame), and every message due by
    then goes to `send` on that thread. With `lead` (seconds), messages go out that
    much early, judged from the clock's interpolated position at `t`; without it,
    a message never goes out before the tick it is due on. A message for a position
    already passed goes out at the next update.

    When the clock stops, is lost or jumps (Start, Song Position Pointer), pending
    messages are dropped and a Note Off is sent for every note still sounding, so no
    note hangs. Every method may be called from any thread.
    """

    def __init__(
        self,
        clock: MidiClock,
        send: Callable[[bytes], None],
        lead: float = 0.0,
        log: Callable[[str], None] = lambda line: None,
    ) -> None:
        if lead < 0:
            raise ValueError(f"lead must be 0 or more: {lead}")
        self._clock = clock
        self._send = send
        self.lead = lead
        self._log = log
        self._lock = threading.Lock()
        self._pending: list[tuple[int, int, bytes, Scheduled]] = []
        self._seq = 0
        self._sounding: dict[tuple[int, int], int] = {}
        self._tick = -1
        self._running = False
        self._done = -1
        self._test = False
        self._test_next: int | None = None
        self._test_handles: list[Scheduled] = []

    @property
    def ticks_per_bar(self) -> int:
        return self._clock.beats_per_bar * TICKS_PER_BEAT

    def at(
        self, bar: int, step: int, messages: Sequence[bytes], ticks_per_step: int = SIXTEENTHS
    ) -> Scheduled:
        """Send `messages` at `step` of `bar`, in order."""
        tick = self._tick_of(bar, step, ticks_per_step)
        handle = Scheduled(tick)
        with self._lock:
            for message in messages:
                self._push(tick, bytes(message), handle)
        return handle

    def next_bar(self, n: int = 1) -> int:
        """The first bar that starts after the current position, with `bar % n == 0`."""
        if n < 1:
            raise ValueError(f"n must be at least 1: {n}")
        tick = self._clock.state().tick
        bar = tick // self.ticks_per_bar + 1 if tick >= 0 else 0
        return bar + (-bar) % n

    def at_next_bar(
        self,
        messages: Sequence[bytes],
        n: int = 1,
        step: int = 0,
        ticks_per_step: int = SIXTEENTHS,
    ) -> Scheduled:
        """Send `messages` at `step` of the next bar where `bar % n == 0`."""
        return self.at(self.next_bar(n), step, messages, ticks_per_step)

    def note(
        self,
        bar: int,
        step: int,
        note: int,
        velocity: int = 100,
        length_steps: int = 1,
        channel: int = 1,
        ticks_per_step: int = SIXTEENTHS,
    ) -> Scheduled:
        """A Note On at `step` of `bar` and its Note Off `length_steps` steps later."""
        if not (0 <= note <= 127 and 1 <= velocity <= 127 and 1 <= channel <= 16):
            raise ValueError(f"bad note: note {note}, velocity {velocity}, channel {channel}")
        if length_steps < 1:
            raise ValueError(f"length_steps must be at least 1: {length_steps}")
        tick = self._tick_of(bar, step, ticks_per_step)
        handle = Scheduled(tick)
        with self._lock:
            self._push_note(tick, note, velocity, length_steps * ticks_per_step, channel, handle)
        return handle

    def cancel(self, handle: Scheduled) -> None:
        """Drop the handle's pending messages; a note it started is ended now."""
        with self._lock:
            self._cancel([handle])

    def send_now(self, messages: Sequence[bytes]) -> None:
        """Send `messages` at once, in order; the notes they start count as sounding,
        so Stop, `lost`, a jump and `clear` end them."""
        with self._lock:
            for message in messages:
                self._emit(bytes(message))

    def clear(self, keep_test: bool = False) -> None:
        """Drop every pending message and end sounding notes. The test pattern stops,
        unless `keep_test`: then it starts again from the next bar."""
        with self._lock:
            self._test = self._test and keep_test
            self._test_handles = []
            self._panic()

    def test_pattern(self, on: bool) -> None:
        """Start the test pattern from the next bar, or stop it now (ADR 0008).

        Note `TEST_NOTES[0]` on beat 1 and `TEST_NOTES[1]` on the other beats,
        velocity 100, one 16th long, on channel 1, until stopped.
        """
        with self._lock:
            if on and not self._test:
                self._test_next = None
            elif not on:
                self._cancel(self._test_handles)
                self._test_handles = []
            self._test = on

    def update(self, t: float | None = None) -> None:
        """Send every message due at the clock's current position (see the class)."""
        with self._lock:
            state = self._clock.state()
            running = state.status == "running"
            moved = state.tick < self._tick or not running and state.tick != self._tick
            if moved or self._running and not running:
                self._panic()
                self._done = state.tick
            self._tick, self._running = state.tick, running
            if not running or state.tick < 0:
                return
            horizon = state.tick
            if self.lead and state.bpm and t is not None:
                position = self._clock.position(t)
                ahead = self.lead * state.bpm * TICKS_PER_BEAT / 60.0
                horizon = max(horizon, math.floor((position or state.tick) + ahead))
            if self._test:
                self._schedule_test(horizon)
            while self._pending and self._pending[0][0] <= horizon:
                self._emit(self._pending.pop(0)[2])
            self._done = max(self._done, horizon)

    def _tick_of(self, bar: int, step: int, ticks_per_step: int) -> int:
        if TICKS_PER_BEAT % ticks_per_step:
            raise ValueError(f"ticks_per_step must divide {TICKS_PER_BEAT}: {ticks_per_step}")
        if bar < 0 or step < 0:
            raise ValueError(f"bar and step must be 0 or more: {bar}, {step}")
        return bar * self.ticks_per_bar + step * ticks_per_step

    def _push(self, tick: int, message: bytes, handle: Scheduled) -> None:
        self._seq += 1
        entry = (tick, self._seq, message, handle)
        index = len(self._pending)
        while index and self._pending[index - 1][:2] > entry[:2]:
            index -= 1
        self._pending.insert(index, entry)

    def _push_note(
        self, tick: int, note: int, velocity: int, length: int, channel: int, handle: Scheduled
    ) -> None:
        self._push(tick, bytes([0x90 | (channel - 1), note, velocity]), handle)
        self._push(tick + length, bytes([0x80 | (channel - 1), note, 0]), handle)

    def _schedule_test(self, horizon: int) -> None:
        """Queue the test pattern's beats up to one beat past `horizon`."""
        if self._test_next is None:
            self._test_next = -(-(self._done + 1) // self.ticks_per_bar) * self.ticks_per_bar
        self._test_handles = [h for h in self._test_handles if self._is_pending(h)]
        while self._test_next <= horizon + TICKS_PER_BEAT:
            tick = self._test_next
            note = TEST_NOTES[0] if tick % self.ticks_per_bar == 0 else TEST_NOTES[1]
            handle = Scheduled(tick)
            self._push_note(tick, note, _TEST_VELOCITY, SIXTEENTHS, 1, handle)
            self._test_handles.append(handle)
            self._test_next += TICKS_PER_BEAT

    def _is_pending(self, handle: Scheduled) -> bool:
        return any(entry[3] is handle for entry in self._pending)

    def _cancel(self, handles: Sequence[Scheduled]) -> None:
        dropped = [e for e in self._pending if any(e[3] is h for h in handles)]
        self._pending = [e for e in self._pending if not any(e[3] is h for h in handles)]
        for _, _, message, _ in dropped:
            if message[0] & 0xF0 == 0x80 and (message[0] & 0x0F, message[1]) in self._sounding:
                self._emit(message)

    def _panic(self) -> None:
        self._pending = []
        self._test_next = None
        self._test_handles = []
        for channel, note in list(self._sounding):
            self._emit(bytes([0x80 | channel, note, 0]))
        self._sounding = {}

    def _emit(self, message: bytes) -> None:
        """Send one message and keep track of the notes it starts and ends."""
        kind = message[0] & 0xF0
        if kind in (0x80, 0x90) and len(message) == 3:
            key = (message[0] & 0x0F, message[1])
            if kind == 0x90 and message[2] > 0:
                self._sounding[key] = self._sounding.get(key, 0) + 1
            elif key in self._sounding:
                self._sounding[key] -= 1
                if not self._sounding[key]:
                    del self._sounding[key]
        try:
            self._send(message)
        except Exception as error:
            self._log(f"scheduled MIDI message not sent: {error!r}")
