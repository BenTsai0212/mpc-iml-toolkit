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
"""

import math
import threading
from collections import deque
from dataclasses import dataclass
from typing import Literal

from mpc_iml.events import Event, MidiEvent
from mpc_iml.frames import note_to_bank_pad

__all__ = [
    "EIGHTHS",
    "LOST_AFTER",
    "SIXTEENTH_TRIPLETS",
    "SIXTEENTHS",
    "TICKS_PER_BEAT",
    "ClockState",
    "ClockStatus",
    "GridHit",
    "MidiClock",
    "off_state",
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
