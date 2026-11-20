"""Built-in preset `ensemble`: a rule-based bass that follows the kick (#138, RFC 0005).

No model: each pad has a role (`kick`, `snare`, `hat`, `other`; `DEFAULT_ROLES` is a
boom-bap layout, any bank) and only `kick` drives the bass. The bass plays the root
of the current chord of a fixed progression (`PROGRESSIONS`), monophonic, on the
`mpc-iml` port, channel 2 by default. Two layers can be switched on and off on their
own, to compare them:

- **immediate**: a kick sounds a bass note at once, with the chord of the hit's bar
  (the first chord when the clock is not running or the bar is negative), velocity
  1-127 mapped to 50-120, ending `length` 16ths later on the grid (or after
  `NOTE_SECONDS` without a running clock);
- **bar** (needs `--clock`): each kick at step `s` of bar `b` schedules a note at
  step `s` of bar `b + 1`, with that bar's chord: last bar's kicks echoed. Hits with
  a negative bar are ignored.

With both on there is one note per step slot and the first one wins: a live kick
within one step of a pending echo cancels it and plays; when the echo has already
sounded, the kick plays no bass.

Controls (provisional preset controls, ADR 0004; no replies, defaults return when
the preset is built again): `immediate 0|1`, `bar 0|1`, `progression <name>`,
`octave 0-3`, `length 1-16`, `channel 1-16`, `role <pad 1-16> <role>` and
`layer-pad 0-16` (default 16: that pad cycles immediate, bar, both, and plays no
bass; 0 turns it off).
"""

import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from mpc_iml import __version__
from mpc_iml.clock import SIXTEENTHS, ClockAccess, PadHit, Scheduled
from mpc_iml.frames import PADS
from mpc_iml.presets import ControlHandler, Preset

__all__ = [
    "DEFAULT_ROLES",
    "NOTE_SECONDS",
    "PROGRESSIONS",
    "ROLES",
    "Chord",
    "Ensemble",
    "Progression",
    "bass_velocity",
    "make_preset",
]

ROLES = ("kick", "snare", "hat", "other")

DEFAULT_ROLES = ("kick", "snare", "hat", "hat") + ("kick", "snare", "hat", "other") + ("other",) * 8
"""Roles of pads 1-16 (pad 1 bottom left): kick on 1 and 5, snare on 2 and 6."""

NOTE_SECONDS = 0.25
"""Length of an immediate note without a running clock."""

STEPS_PER_BEAT = 4
"""The bass works on 16ths."""


@dataclass(frozen=True)
class Chord:
    """`root` in semitones above the progression's tonic; `quality` for later layers."""

    root: int
    quality: str


@dataclass(frozen=True)
class Progression:
    """A fixed chord progression: `tonic` is a pitch class (0 is C)."""

    name: str
    tonic: int
    chords: tuple[Chord, ...]
    bars_per_chord: int

    def chord(self, bar: int) -> Chord:
        """The chord of `bar` (0-based from song start); bar 0 for a negative bar."""
        return self.chords[(max(bar, 0) // self.bars_per_chord) % len(self.chords)]

    def root_note(self, bar: int, octave: int) -> int:
        """The MIDI note of the chord root of `bar` in `octave` (A1 is 33)."""
        return 12 * (octave + 1) + (self.tonic + self.chord(bar).root) % 12


PROGRESSIONS = {
    p.name: p
    for p in (
        Progression("minor-two", 9, (Chord(0, "m7"), Chord(8, "maj7")), 2),
        Progression(
            "minor-four", 2, (Chord(0, "m7"), Chord(5, "m7"), Chord(8, "maj7"), Chord(7, "7")), 1
        ),
    )
}
"""`minor-two` (default): Am7 and Fmaj7, 2 bars each. `minor-four`: Dm7, Gm7,
Bbmaj7, A7, one bar each."""


def bass_velocity(velocity: int) -> int:
    """A kick velocity 1-127 mapped linearly to 50-120."""
    return round(50 + (min(max(velocity, 1), 127) - 1) * 70 / 126)


class _Timer(Protocol):
    def start(self) -> None: ...
    def cancel(self) -> None: ...


TimerFactory = Callable[[float, Callable[[], None]], _Timer]


@dataclass
class _Echo:
    tick: int
    note: int
    off_tick: int
    on: Scheduled
    off: Scheduled


class Ensemble:
    """The settings and bass state of one build of `ensemble`.

    `attach` is the preset's clock hook and `controls` its controls. Pad hits arrive
    on the engine's input thread, controls on the OSC thread and timers on their
    own, so the state is guarded by a lock.
    """

    def __init__(
        self,
        log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
        timer: TimerFactory = threading.Timer,
    ) -> None:
        self.immediate = True
        self.bar = True
        self.progression = PROGRESSIONS["minor-two"]
        self.octave = 1
        self.length = 2
        self.channel = 2
        self.roles = list(DEFAULT_ROLES)
        self.layer_pad = 16
        self._log = log
        self._timer = timer
        self._lock = threading.RLock()
        self._access: ClockAccess | None = None
        self._off: bytes | None = None
        self._off_handle: Scheduled | _Timer | None = None
        self._echoes: list[_Echo] = []

    def attach(self, access: ClockAccess) -> None:
        """The `Preset.clock` hook: listen to every pad hit."""
        self._access = access
        access.on_pad(self.on_pad)
        if access.scheduler is None:
            self._log("ensemble: no MIDI clock (start with --clock); bar layer off")

    def on_pad(self, hit: PadHit) -> None:
        with self._lock:
            if self.layer_pad and hit.pad == self.layer_pad - 1:
                self._cycle()
                return
            if self.roles[hit.pad] != "kick" or self._access is None:
                return
            grid = hit.grid if hit.grid is not None and hit.grid.bar >= 0 else None
            velocity = bass_velocity(hit.velocity)
            if grid is not None and self.bar and self._access.scheduler is not None:
                self._echo(grid.bar + 1, grid.step, velocity)
            if self.immediate:
                bar, step = (grid.bar, grid.step) if grid is not None else (0, None)
                self._play(bar, step, velocity)

    def _ticks(self, bar: int, step: int) -> int:
        return (bar * self._steps_per_bar() + step) * SIXTEENTHS

    def _steps_per_bar(self) -> int:
        assert self._access is not None
        return self._access.state().beats_per_bar * STEPS_PER_BEAT

    def _echo(self, bar: int, step: int, velocity: int) -> None:
        """Schedule last bar's kick in `bar`, ending the previous echo there."""
        scheduler = self._access.scheduler if self._access else None
        assert scheduler is not None
        tick = self._ticks(bar, step)
        note = self.progression.root_note(bar, self.octave)
        for echo in self._echoes:
            if echo.tick < tick < echo.off_tick:
                scheduler.cancel(echo.off)
                echo.off = scheduler.at(bar, step, [self._message(0x80, echo.note, 0)])
                echo.off_tick = tick
        on = scheduler.at(bar, step, [self._message(0x90, note, velocity)])
        off = scheduler.at(bar, step + self.length, [self._message(0x80, note, 0)])
        self._echoes.append(_Echo(tick, note, tick + self.length * SIXTEENTHS, on, off))

    def _play(self, bar: int, step: int | None, velocity: int) -> None:
        """Sound an immediate note now; `step` is `None` without a running clock."""
        assert self._access is not None
        scheduler = self._access.scheduler
        now = self._access.state().tick
        self._echoes = [e for e in self._echoes if e.off_tick > now]
        if step is not None and scheduler is not None:
            slot = self._ticks(bar, step)
            near = [e for e in self._echoes if abs(e.tick - slot) <= SIXTEENTHS]
            if any(e.tick <= now for e in near):
                return
            for echo in near:
                scheduler.cancel(echo.on)
                scheduler.cancel(echo.off)
                self._echoes.remove(echo)
        self._end()
        note = self.progression.root_note(bar, self.octave)
        self._off = self._message(0x80, note, 0)
        self._access.send_now([self._message(0x90, note, velocity)])
        if step is not None and scheduler is not None:
            self._off_handle = scheduler.at(bar, step + self.length, [self._off])
        else:
            holder: list[_Timer] = []
            timer = self._timer(NOTE_SECONDS, lambda: self._timed_off(holder[0]))
            holder.append(timer)
            self._off_handle = timer
            timer.start()

    def _timed_off(self, timer: _Timer) -> None:
        with self._lock:
            if self._off_handle is timer:
                self._end()

    def _end(self) -> None:
        """End the sounding immediate note, if any (the line stays monophonic)."""
        handle, off = self._off_handle, self._off
        self._off_handle = self._off = None
        if handle is None or off is None or self._access is None:
            return
        if isinstance(handle, Scheduled):
            if self._access.scheduler is not None:
                self._access.scheduler.cancel(handle)
        else:
            handle.cancel()
            self._access.send_now([off])

    def _message(self, status: int, note: int, velocity: int) -> bytes:
        return bytes([status | (self.channel - 1), note, velocity])

    def _cycle(self) -> None:
        """immediate -> bar -> both -> immediate."""
        modes = {(True, False): (False, True), (False, True): (True, True)}
        immediate, bar = modes.get((self.immediate, self.bar), (True, False))
        self.immediate = immediate
        self._set_bar(bar)
        name = "both" if immediate and bar else "immediate" if immediate else "bar"
        self._log(f"ensemble: {name}")

    def _set_bar(self, on: bool) -> None:
        scheduler = self._access.scheduler if self._access else None
        if not on and scheduler is not None:
            for echo in self._echoes:
                scheduler.cancel(echo.on)
                scheduler.cancel(echo.off)
            self._echoes = []
        self.bar = on

    def controls(self) -> dict[str, ControlHandler]:
        """The preset controls (`/mpciml/preset/ensemble/<name>`)."""
        return {
            "immediate": lambda a: self._set(lambda: setattr(self, "immediate", _flag(a))),
            "bar": lambda a: self._set(lambda: self._set_bar(_flag(a))),
            "progression": self._set_progression,
            "octave": lambda a: self._set(lambda: setattr(self, "octave", _whole(a, 0, 3))),
            "length": lambda a: self._set(lambda: setattr(self, "length", _whole(a, 1, 16))),
            "channel": self._set_channel,
            "role": self._set_role,
            "layer-pad": lambda a: self._set(
                lambda: setattr(self, "layer_pad", _whole(a, 0, PADS))
            ),
        }

    def _set(self, change: Callable[[], None]) -> None:
        with self._lock:
            change()

    def _set_progression(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in PROGRESSIONS:
            raise ValueError(f"expected one of {', '.join(PROGRESSIONS)}, got {list(args)}")
        with self._lock:
            self.progression = PROGRESSIONS[str(args[0])]

    def _set_channel(self, args: Sequence[float | int | str]) -> None:
        channel = _whole(args, 1, 16)
        with self._lock:
            self._end()
            self.channel = channel

    def _set_role(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 2 or args[1] not in ROLES:
            raise ValueError(f"expected a pad 1-16 and one of {', '.join(ROLES)}")
        pad = _whole(args[:1], 1, PADS)
        with self._lock:
            self.roles[pad - 1] = str(args[1])


def _whole(args: Sequence[float | int | str], low: int, high: int) -> int:
    if len(args) != 1:
        raise ValueError(f"expected one value, got {len(args)}")
    (value,) = args
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ValueError(f"expected a whole number, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"must be {low}-{high}, got {value}")
    return int(value)


def _flag(args: Sequence[float | int | str]) -> bool:
    return bool(_whole(args, 0, 1))


def make_preset(log: Callable[[str], None] | None = None) -> Preset:
    """The built-in preset `ensemble`, with fresh settings and bass state."""
    ensemble = Ensemble(log) if log is not None else Ensemble()
    return Preset(
        name="ensemble",
        version=__version__,
        description="Rule-based bass that follows the kick (MIDI notes, channel 2)",
        outputs=(),
        controls=ensemble.controls(),
        patch="mpc_iml:patches/mpc-iml.pd",
        clock=ensemble.attach,
    )
