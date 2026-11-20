"""Built-in preset `ensemble`: a bass and a melody that follow the drums (RFC 0005).

No model: each pad has a role (`kick`, `snare`, `hat`, `other`; `DEFAULT_ROLES` is a
boom-bap layout, any bank) and only `kick` drives the bass. The bass is monophonic,
on the `mpc-iml` port, channel 2 by default, over a fixed progression
(`PROGRESSIONS`), in one of three modes (`bass`):

- `loop` (default, #148, needs `--clock`): a bass loop of chord tones (`bass`) that
  keeps playing; at each bar line the kicks of the bar that ended set the next bar:
  their number its density, their average velocity its loudness and their positions
  its accents (`bass.kick_density`, `bass.accent`, its own `melody.Follower`).
  Without a running clock it falls back to the immediate layer below;
- `rule` (#138): the root of the current chord, in two layers that can be switched
  on and off on their own, to compare them;
- `off`: no bass.

The two layers of `rule`:

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

A melody layer (#144, needs `--clock`) loops a few bars of chord tones (`melody`)
on channel 3 by default. At each bar line (`ClockAccess.on_bar`) the drums of the
bar that ended set the next bar: the number of hits its density, their average
velocity its loudness and the hat hits a brightness CC (`melody.Follower`). Hits on
the layer pad and the melody pad do not count.

Controls (provisional preset controls, ADR 0004; defaults return when the preset is
built again): `bass loop|rule|off`, `bass-loop <name>`,
`progression <name>`, `octave 0-3`, `channel 1-16`, `role <pad 1-16> <role>`,
`layer-pad 0-16` (default 16: that pad cycles the bass loop, rule, off, and plays
no bass; 0 turns it off), for `rule` only `immediate 0|1`, `bar 0|1` and
`length 1-16`, and for the melody `melody 0|1`, `loop <name>`, `follow 0|1` (both
loops), `melody-octave 2-6`, `melody-channel 1-16`, `filter-cc 0-127` (0 is off)
and `melody-pad 0-16` (default 15: that pad cycles follow, fixed, off; follow and
fixed apply to both loops, off only to the melody), and `melody-mode
follow|fixed|off` (#153: `melody` and `follow` in one message). Bass mode and melody
changes apply from the next bar line (at once while the clock is not running);
`melody 0` and `melody-mode off` also drop the pending notes.

State replies (`Preset.state`, ADR 0009, #153): `bass` and `melody-mode` give the
mode asked for (next) and the one playing, the other replies the current settings
(`Ensemble.state`). The preset asks the engine to send them again
(`ClockAccess.report()`) after a press of the layer pad or the melody pad, and at a
bar line where the playing bass or melody mode changes.
"""

import sys
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from mpc_iml import __version__
from mpc_iml.bass import BASS_LOOPS, bass_note_velocity, kick_density
from mpc_iml.clock import (
    SIXTEENTHS,
    TICKS_PER_BEAT,
    BarStart,
    ClockAccess,
    GridHit,
    PadHit,
    Scheduled,
)
from mpc_iml.frames import PADS
from mpc_iml.melody import LOOPS, Follower, chord_note, loop_pitch
from mpc_iml.presets import ControlHandler, Preset

__all__ = [
    "BASS_MODES",
    "DEFAULT_ROLES",
    "MELODY_MODES",
    "NO_CLOCK",
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

BASS_MODES = ("loop", "rule", "off")
"""The bass modes, in the order the layer pad cycles them; `loop` is the default."""

MELODY_MODES = ("follow", "fixed", "off")
"""The melody modes, in the order the melody pad cycles them; `follow` is the default."""

NO_CLOCK = (
    "ensemble: no MIDI clock (start with --clock); bass loop, bar layer and melody off,"
    " bass plays on each kick"
)

DEFAULT_ROLES = ("kick", "snare", "hat", "hat") + ("kick", "snare", "hat", "other") + ("other",) * 8
"""Roles of pads 1-16 (pad 1 bottom left): kick on 1 and 5, snare on 2 and 6."""

NOTE_SECONDS = 0.25
"""Length of an immediate note without a running clock."""

STEPS_PER_BEAT = 4
"""The bass works on 16ths."""


@dataclass(frozen=True)
class Chord:
    """`root` in semitones above the progression's tonic; `quality` (`m7`, `maj7` or
    `7`) for the melody's chord tones."""

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
        self.bass = "loop"
        self._bass_active = "loop"
        self.bass_loop = BASS_LOOPS["boom"]
        self._bass_follower = Follower(kick_density)
        self._bass_notes: list[Scheduled] = []
        self.immediate = True
        self.bar = True
        self.progression = PROGRESSIONS["minor-two"]
        self.octave = 1
        self.length = 2
        self.channel = 2
        self.roles = list(DEFAULT_ROLES)
        self.layer_pad = 16
        self.melody = True
        self.loop = LOOPS["keys"]
        self.follow = True
        self.melody_octave = 4
        self.melody_channel = 3
        self.filter_cc = 74
        self.melody_pad = 15
        self._melody_playing = "follow"
        self._follower = Follower()
        self._melody_notes: list[Scheduled] = []
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
        access.on_bar(self.on_bar)
        if access.scheduler is None:
            self._log(NO_CLOCK)

    def on_pad(self, hit: PadHit) -> None:
        if self._on_pad(hit):
            self._report()

    def _on_pad(self, hit: PadHit) -> bool:
        """Handle a pad hit; `True` when it changed a mode, to report."""
        with self._lock:
            if self.layer_pad and hit.pad == self.layer_pad - 1:
                self._cycle()
                return True
            if self.melody_pad and hit.pad == self.melody_pad - 1:
                self._cycle_melody()
                return True
            self._bass_hit(hit)
            return False

    def _bass_hit(self, hit: PadHit) -> None:
        """The bass of a pad hit (`rule`, or `loop` without a running clock)."""
        with self._lock:
            if self.roles[hit.pad] != "kick" or self._access is None:
                return
            scheduler = self._access.scheduler
            rule = self._bass_active == "rule"
            fallback = self._bass_active == "loop" and scheduler is None
            if not (rule or fallback):
                return
            grid = hit.grid if hit.grid is not None and hit.grid.bar >= 0 else None
            velocity = bass_velocity(hit.velocity)
            if grid is not None and rule and self.bar and scheduler is not None:
                self._echo(grid.bar + 1, grid.step, velocity)
            if self.immediate or fallback:
                bar, step = (grid.bar, grid.step) if grid is not None else (0, None)
                self._play(bar, step, velocity)

    def on_bar(self, start: BarStart) -> None:
        """Plan the bass loop and the melody of the bar that starts now from the drums
        of the last one; report when the playing bass or melody mode changes."""
        with self._lock:
            playing = (self._bass_active, self._melody_playing)
            self._plan(start)
            self._melody_playing = self._melody_mode()
            changed = playing != (self._bass_active, self._melody_playing)
        if changed:
            self._report()

    def _report(self) -> None:
        """Ask the engine to send the state again (outside the lock, ADR 0009)."""
        if self._access is not None:
            self._access.report()

    def _plan(self, start: BarStart) -> None:
        with self._lock:
            self._apply_bass()
            skip = {p - 1 for p in (self.layer_pad, self.melody_pad) if p}
            drums = [h for h in start.hits if h.pad not in skip]
            self._plan_bass(start, [h for h in drums if self.roles[h.pad] == "kick"])
            hats = sum(self.roles[h.pad] == "hat" for h in drums)
            velocities = [h.velocity for h in drums]
            plan = self._follower.plan_bar(velocities, hats, start.complete, self.follow)
            scheduler = self._access.scheduler if self._access else None
            if scheduler is None or not self.melody:
                return
            last_bar = start.state.tick - start.state.beats_per_bar * TICKS_PER_BEAT
            self._melody_notes = [h for h in self._melody_notes if h.tick >= last_bar]
            channel = self.melody_channel
            if plan.cc is not None and self.filter_cc:
                cc = bytes([0xB0 | (channel - 1), self.filter_cc, plan.cc])
                self._melody_notes.append(scheduler.at(start.bar, 0, [cc]))
            chord = self.progression.chord(start.bar)
            pitch_class = self.progression.tonic + chord.root
            steps = start.state.beats_per_bar * STEPS_PER_BEAT
            for note in self.loop.bar_notes(start.bar, plan.level):
                if note.step >= steps:
                    continue
                pitch = chord_note(pitch_class, chord.quality, note.tone, self.melody_octave)
                velocity = min(max(round(plan.velocity * note.velocity), 1), 127)
                self._melody_notes.append(
                    scheduler.note(
                        start.bar,
                        note.step,
                        pitch + 12 * note.octave,
                        velocity,
                        note.length,
                        channel,
                    )
                )

    def _plan_bass(self, start: BarStart, kicks: Sequence[GridHit]) -> None:
        """Schedule the bass loop's notes of the bar that starts now."""
        velocities = [h.velocity for h in kicks]
        plan = self._bass_follower.plan_bar(velocities, 0, start.complete, self.follow)
        scheduler = self._access.scheduler if self._access else None
        if scheduler is None or self._bass_active != "loop":
            return
        last_bar = start.state.tick - start.state.beats_per_bar * TICKS_PER_BEAT
        self._bass_notes = [h for h in self._bass_notes if h.tick >= last_bar]
        progression, bar = self.progression, start.bar
        now, following = progression.chord(bar), progression.chord(bar + 1)
        chords = (
            (progression.tonic + now.root, now.quality),
            (progression.tonic + following.root, following.quality),
        )
        accents = [h.step for h in kicks] if self.follow else None
        steps = start.state.beats_per_bar * STEPS_PER_BEAT
        for note in self.bass_loop.bar_notes(bar, plan.level):
            if note.step >= steps:
                continue
            pitch = loop_pitch(note, *chords, self.octave)
            velocity = bass_note_velocity(note, plan.velocity, accents)
            length = min(note.length, steps - note.step)
            self._bass_notes.append(
                scheduler.note(bar, note.step, pitch, velocity, length, self.channel)
            )

    def _set_bass(self, mode: str) -> None:
        """Ask for a bass mode: it starts at the next bar line, or at once while the
        clock is not running."""
        self.bass = mode
        if not self._running():
            self._apply_bass()

    def _running(self) -> bool:
        """Whether the clock runs, so mode changes wait for the next bar line."""
        return self._access is not None and self._access.state().status == "running"

    def _melody_mode(self) -> str:
        """The melody mode asked for: `follow`, `fixed` or `off`."""
        return "off" if not self.melody else "follow" if self.follow else "fixed"

    def _sync_melody(self) -> None:
        """A melody change plays at once while the clock is not running."""
        if not self._running():
            self._melody_playing = self._melody_mode()

    def _apply_bass(self) -> None:
        """Switch to the asked bass mode, ending what the old one plays."""
        if self.bass == self._bass_active:
            return
        self._stop_bass_loop()
        self._drop_echoes()
        self._end()
        self._bass_active = self.bass

    def _stop_bass_loop(self) -> None:
        """Drop the pending bass loop notes and end the sounding one."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for handle in self._bass_notes:
                scheduler.cancel(handle)
        self._bass_notes = []

    def _cycle_melody(self) -> None:
        """follow -> fixed -> off -> follow, from the next bar line."""
        if self.melody and self.follow:
            self.follow = False
        elif self.melody:
            self.melody = False
        else:
            self.melody = self.follow = True
        self._sync_melody()
        self._log(f"ensemble: melody {self._melody_mode()}")

    def _stop_melody(self) -> None:
        """Drop the pending melody notes and end the sounding ones."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for handle in self._melody_notes:
                scheduler.cancel(handle)
        self._melody_notes = []

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
        """Bass loop -> rule -> off -> loop."""
        mode = BASS_MODES[(BASS_MODES.index(self.bass) + 1) % len(BASS_MODES)]
        self._set_bass(mode)
        self._log(f"ensemble: bass {mode}")

    def _set_bar(self, on: bool) -> None:
        if not on:
            self._drop_echoes()
        self.bar = on

    def _drop_echoes(self) -> None:
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for echo in self._echoes:
                scheduler.cancel(echo.on)
                scheduler.cancel(echo.off)
        self._echoes = []

    def controls(self) -> dict[str, ControlHandler]:
        """The preset controls (`/mpciml/preset/ensemble/<name>`)."""
        return {
            "bass": self._set_bass_control,
            "bass-loop": self._set_bass_loop,
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
            "melody": self._set_melody,
            "loop": self._set_loop,
            "follow": self._set_follow,
            "melody-mode": self._set_melody_mode,
            "melody-octave": lambda a: self._set(
                lambda: setattr(self, "melody_octave", _whole(a, 2, 6))
            ),
            "melody-channel": self._set_melody_channel,
            "filter-cc": lambda a: self._set(lambda: setattr(self, "filter_cc", _whole(a, 0, 127))),
            "melody-pad": lambda a: self._set(
                lambda: setattr(self, "melody_pad", _whole(a, 0, PADS))
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

    def _set_bass_control(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in BASS_MODES:
            raise ValueError(f"expected one of {', '.join(BASS_MODES)}, got {list(args)}")
        with self._lock:
            self._set_bass(str(args[0]))

    def _set_bass_loop(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in BASS_LOOPS:
            raise ValueError(f"expected one of {', '.join(BASS_LOOPS)}, got {list(args)}")
        with self._lock:
            self.bass_loop = BASS_LOOPS[str(args[0])]

    def _set_melody(self, args: Sequence[float | int | str]) -> None:
        self._melody_to(_flag(args), None)

    def _set_follow(self, args: Sequence[float | int | str]) -> None:
        self._melody_to(None, _flag(args))

    def _set_melody_mode(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in MELODY_MODES:
            raise ValueError(f"expected one of {', '.join(MELODY_MODES)}, got {list(args)}")
        if args[0] == "off":
            self._melody_to(False, None)
        else:
            self._melody_to(True, args[0] == "follow")

    def _melody_to(self, on: bool | None, follow: bool | None) -> None:
        """Set `melody` and `follow` (`None` keeps one); off drops the pending notes,
        so the melody stops at once."""
        with self._lock:
            if follow is not None:
                self.follow = follow
            if on is not None:
                if not on:
                    self._stop_melody()
                    self._melody_playing = "off"
                self.melody = on
            self._sync_melody()

    def state(self) -> list[tuple[str, list[int | float | str]]]:
        """The `Preset.state` hook: the replies of ADR 0009, in its order. The melody's
        playing mode is `off` without `--clock` (it never plays)."""
        with self._lock:
            scheduler = self._access.scheduler if self._access else None
            melody = self._melody_playing if scheduler is not None else "off"
            return [
                ("bass", [self.bass, self._bass_active]),
                ("melody-mode", [self._melody_mode(), melody]),
                ("bass-loop", [self.bass_loop.name]),
                ("loop", [self.loop.name]),
                ("progression", [self.progression.name]),
                ("bass-loops", list(BASS_LOOPS)),
                ("loops", list(LOOPS)),
                ("progressions", list(PROGRESSIONS)),
                ("octave", [self.octave]),
                ("melody-octave", [self.melody_octave]),
                ("channel", [self.channel]),
                ("melody-channel", [self.melody_channel]),
                ("length", [self.length]),
                ("filter-cc", [self.filter_cc]),
                ("layer-pad", [self.layer_pad]),
                ("melody-pad", [self.melody_pad]),
                ("immediate", [int(self.immediate)]),
                ("bar", [int(self.bar)]),
                ("roles", list(self.roles)),
            ]

    def _set_loop(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in LOOPS:
            raise ValueError(f"expected one of {', '.join(LOOPS)}, got {list(args)}")
        with self._lock:
            self.loop = LOOPS[str(args[0])]

    def _set_melody_channel(self, args: Sequence[float | int | str]) -> None:
        channel = _whole(args, 1, 16)
        with self._lock:
            self._stop_melody()
            self.melody_channel = channel

    def _set_channel(self, args: Sequence[float | int | str]) -> None:
        channel = _whole(args, 1, 16)
        with self._lock:
            self._end()
            self._stop_bass_loop()
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
        description=(
            "A bass loop that follows the kick (or a rule-based bass) and a melody loop"
            " that follows the drums (MIDI notes, channels 2 and 3)"
        ),
        outputs=(),
        controls=ensemble.controls(),
        patch="mpc_iml:patches/mpc-iml.pd",
        clock=ensemble.attach,
        state=ensemble.state,
    )
