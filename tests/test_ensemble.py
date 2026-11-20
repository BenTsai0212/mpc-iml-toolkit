"""The built-in preset `ensemble`: pad roles and a rule-based bass (#138).

These tests run the bass in `rule` mode; the bass loop (#148) is in
`test_bass_loop.py`.

The bass is driven by simulated MIDI clock at 120 BPM (as in `test_scheduler.py`)
through a real `MidiClock`, `Scheduler` and `ClockAccess`; pad hits arrive as the
engine delivers them. Timers are fakes, so nothing waits on the wall clock.
"""

import threading
from collections.abc import Callable
from typing import Any

import pytest
import test_engine
from test_engine import TIMEOUT
from test_engine_clock import FakeMidiOut

from mpc_iml.clock import TICKS_PER_BEAT, ClockAccess, GridHit, MidiClock, PadHit, Scheduler
from mpc_iml.ensemble import (
    DEFAULT_ROLES,
    NO_CLOCK,
    NOTE_SECONDS,
    PROGRESSIONS,
    Ensemble,
    bass_velocity,
    make_preset,
)
from mpc_iml.events import MidiEvent
from mpc_iml.presets import available_presets

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

TICK, START, STOP = b"\xf8", b"\xfa", b"\xfc"
INTERVAL = 60 / 120 / TICKS_PER_BEAT
STEP = 6
BAR = 16 * STEP
KICK, SNARE, LAYER = 36, 37, 51
"""Notes of pad 1 (kick), pad 2 (snare) and pad 16 (the layer pad), bank A."""


class FakeTimer:
    def __init__(self, seconds: float, action: Callable[[], None]) -> None:
        self.seconds, self.action = seconds, action
        self.started = self.cancelled = False

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.action()


class Rig:
    """An `Ensemble` on a simulated DAW clock (or without one); the melody layer is
    off unless `melody` (its tests are in `test_melody.py`), the bass in mode `bass`.
    The surprises (#158) are off unless `surprise`, with the fixed seed `seed`."""

    def __init__(
        self,
        clock: bool = True,
        melody: bool = False,
        bass: str = "rule",
        surprise: bool = False,
        seed: int = 0,
    ) -> None:
        self.sent: list[tuple[int, bytes]] = []
        self.log: list[str] = []
        self.timers: list[FakeTimer] = []
        self.reports: list[dict[str, list[Any]]] = []
        """The state at each `ClockAccess.report()` (#153)."""
        self.clock = MidiClock() if clock else None
        self.scheduler = Scheduler(self.clock, self.record) if self.clock else None
        self.access = ClockAccess(
            self.clock, self.log.append, self.scheduler, self.record, report=self.report
        )
        self.ensemble = Ensemble(self.log.append, self.timer, seed=seed)
        self.ensemble.surprise = surprise
        self.ensemble.melody = melody
        self.ensemble.controls()["bass"]([bass])
        self.ensemble.attach(self.access)
        self.t = 0.0
        self.next_tick = 0

    def report(self, access: ClockAccess) -> None:
        self.reports.append({name: list(args) for name, args in self.ensemble.state()})

    def timer(self, seconds: float, action: Callable[[], None]) -> FakeTimer:
        self.timers.append(FakeTimer(seconds, action))
        return self.timers[-1]

    def record(self, message: bytes) -> None:
        self.sent.append((self.clock.state().tick if self.clock else -1, message))

    def send(self, data: bytes) -> None:
        assert self.clock is not None and self.scheduler is not None
        self.clock.feed(data, self.t)
        self.access.bar_line()
        self.scheduler.update(self.t)

    def until(self, tick: int) -> None:
        while self.next_tick < tick:
            self.send(TICK)
            self.t += INTERVAL
            self.next_tick += 1

    def hit(self, note: int = KICK, velocity: int = 127, ticks: float = 0.0) -> None:
        """A pad hit `ticks` after the tick about to arrive (negative is early)."""
        self.access.deliver(MidiEvent(self.t + ticks * INTERVAL, "note_on", 1, velocity, note))

    def on(self) -> list[tuple[int, int, int]]:
        """(tick, note, velocity) of every Note On."""
        return [(t, m[1], m[2]) for t, m in self.sent if m[0] & 0xF0 == 0x90]

    def off(self) -> list[tuple[int, int]]:
        return [(t, m[1]) for t, m in self.sent if m[0] & 0xF0 == 0x80]


def started(immediate: bool = True, bar: bool = True) -> Rig:
    rig = Rig()
    rig.ensemble.immediate, rig.ensemble.bar = immediate, bar
    rig.send(START)
    return rig


def test_progressions_and_velocity() -> None:
    two, four = PROGRESSIONS["minor-two"], PROGRESSIONS["minor-four"]
    assert [two.root_note(b, 1) for b in range(5)] == [33, 33, 29, 29, 33]
    assert [four.root_note(b, 1) for b in range(5)] == [26, 31, 34, 33, 26]
    assert two.root_note(-1, 2) == 45
    assert (bass_velocity(1), bass_velocity(127)) == (50, 120)
    assert DEFAULT_ROLES[0] == DEFAULT_ROLES[4] == "kick" and len(DEFAULT_ROLES) == 16


def test_immediate_plays_at_once_on_channel_2_and_ends_on_the_grid() -> None:
    rig = started(bar=False)
    rig.until(4 * STEP)
    rig.hit(ticks=-1.0)
    assert rig.sent == [(4 * STEP - 1, bytes([0x91, 33, 120]))]
    rig.until(BAR)
    assert rig.off() == [(6 * STEP, 33)]


def test_only_kick_pads_play_in_any_bank_and_roles_change() -> None:
    rig = started(bar=False)
    rig.until(STEP)
    rig.hit(SNARE)
    rig.hit(KICK + 16 + 4)
    assert [n for _, n, _ in rig.on()] == [33]
    rig.ensemble.controls()["role"]([2, "kick"])
    rig.hit(SNARE)
    assert len(rig.on()) == 2


def test_without_clock_first_chord_timed_note_off_and_one_log_line() -> None:
    rig = Rig(clock=False)
    assert rig.log == [NO_CLOCK]
    rig.ensemble.controls()["progression"](["minor-four"])
    rig.hit()
    rig.hit()
    first, second = rig.timers
    assert (first.seconds, first.cancelled, second.started) == (NOTE_SECONDS, True, True)
    second.fire()
    assert [m for _, m in rig.sent] == [
        bytes([0x91, 26, 120]),
        bytes([0x81, 26, 0]),
        bytes([0x91, 26, 120]),
        bytes([0x81, 26, 0]),
    ]


def test_bar_layer_echoes_last_bars_kicks_on_the_next_chord() -> None:
    rig = started(immediate=False)
    for step in (0, 6, 10):
        rig.until(BAR + step * STEP)
        rig.hit()
    rig.until(3 * BAR)
    assert rig.on() == [(2 * BAR + s * STEP, 29, 120) for s in (0, 6, 10)]
    assert rig.off() == [(2 * BAR + s * STEP, 29) for s in (2, 8, 12)]


def test_bar_layer_trims_an_echo_that_would_overlap_the_next() -> None:
    rig = started(immediate=False)
    rig.ensemble.controls()["length"]([4])
    rig.until(BAR)
    rig.hit()
    rig.until(BAR + 2 * STEP)
    rig.hit()
    rig.until(3 * BAR)
    assert rig.off() == [(2 * BAR + 2 * STEP, 29), (2 * BAR + 6 * STEP, 29)]


def test_bar_layer_ignores_negative_bars_and_the_immediate_layer_plays_them() -> None:
    rig = started()
    grid = GridHit(0.0, 0, 0, 100, -1, 15, 0.2, 10.0)
    rig.ensemble.on_pad(PadHit(0.0, 0, 0, 100, grid))
    assert (rig.on(), len(rig.timers)) == ([(-1, 33, bass_velocity(100))], 1)
    rig.until(2 * BAR)
    assert len(rig.on()) == 1


def test_both_layers_one_note_per_slot_first_one_wins() -> None:
    rig = started()
    for step in (0, 8):
        rig.until(BAR + step * STEP)
        rig.hit()
    rig.until(2 * BAR + 1)
    rig.hit(ticks=-1.5)
    rig.until(2 * BAR + 8 * STEP)
    rig.hit(ticks=-2.0)
    rig.until(3 * BAR)
    slots = [round(t / STEP) for t, _, _ in rig.on()]
    assert slots == [16, 24, 32, 40]


def test_stop_ends_every_note_and_drops_pending() -> None:
    rig = started()
    rig.until(BAR - STEP)
    rig.hit()
    rig.until(BAR - 1)
    rig.send(STOP)
    rig.until(3 * BAR)
    assert len(rig.on()) == len(rig.off()) == 1


def test_layer_pad_cycles_the_bass_mode_and_plays_no_bass() -> None:
    rig = started()
    rig.until(STEP)
    for _ in range(4):
        rig.hit(LAYER)
    assert rig.log == [
        "ensemble: bass off",
        "ensemble: bass loop",
        "ensemble: bass rule",
        "ensemble: bass off",
    ]
    rig.until(BAR + STEP)
    assert rig.sent == []
    rig.ensemble.controls()["layer-pad"]([0])
    rig.hit(LAYER)
    assert rig.log[-1] == "ensemble: bass off" and len(rig.log) == 4


@pytest.mark.parametrize(
    ("control", "args"),
    [
        ("immediate", [2]),
        ("bar", ["on"]),
        ("progression", ["major"]),
        ("octave", [4]),
        ("length", [0]),
        ("channel", [1.5]),
        ("role", [17, "kick"]),
        ("role", [1, "bass"]),
        ("layer-pad", [1, 2]),
        ("bass", ["walk"]),
        ("bass", []),
        ("bass-loop", ["rule"]),
    ],
)
def test_bad_control_arguments_are_rejected(control: str, args: list[Any]) -> None:
    with pytest.raises(ValueError):
        Ensemble().controls()[control](args)


def test_registered_and_plays_through_the_engine(start: Any) -> None:
    preset = available_presets()["ensemble"]
    assert (preset.outputs, preset.targets, preset.clock is not None) == ((), None, True)
    FakeMidiOut.made = []
    log: list[str] = []
    sent = threading.Event()
    found = {"ensemble": make_preset(log.append)}

    class Out(FakeMidiOut):
        def send(self, message: bytes) -> None:
            super().send(message)
            sent.set()

    start(
        [MidiEvent(0.1, "note_on", 1, 127, KICK)],
        preset="ensemble",
        presets=lambda: found,
        midi_backend=Out,
    )
    assert sent.wait(TIMEOUT)
    assert log == [NO_CLOCK]
    (port,) = FakeMidiOut.made
    assert (port.opened, port.sent[0]) == ("mpc-iml", bytes([0x91, 33, 120]))
