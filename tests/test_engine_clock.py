"""Engine protocol 1.4: MIDI clock sync (ADR 0008, #130).

As in `test_engine.py`, each test starts an engine on free ports and talks OSC to
it. MIDI clock never comes from a DAW: a fake clock backend lets the test send
messages as the DAW would, and replays carry clock bytes as raw MIDI events.
"""

import dataclasses
import threading
from collections.abc import Callable, Mapping
from typing import Any

import pytest
import test_engine
from test_engine import TIMEOUT, Front

from mpc_iml.clock import TICKS_PER_BEAT, ClockAccess, GridHit
from mpc_iml.demo import PRESET as DEMO
from mpc_iml.engine import Engine, build_parser
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.presets import Preset
from mpc_iml.sources import CLOCK_PORT_NAME, PortNotFoundError

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

TICK, START, STOP = b"\xf8", b"\xfa", b"\xfc"
INTERVAL = 60 / 120 / TICKS_PER_BEAT
"""Seconds per tick at 120 BPM."""


class FakeClockBackend:
    """A `ClockInputBackend` the test drives: `send` plays the DAW."""

    made: list["FakeClockBackend"] = []

    def __init__(self) -> None:
        self.opened: str | None = None
        self.callback: Callable[[bytes], None] | None = None
        self.closed = False
        FakeClockBackend.made.append(self)

    def port_names(self) -> list[str]:
        return ["MPC Sample", "IAC Driver Bus 1"]

    def open(self, index: int) -> None:
        self.opened = self.port_names()[index]

    def open_virtual(self, name: str) -> None:
        self.opened = name

    def set_callback(self, callback: Callable[[bytes], None]) -> None:
        self.callback = callback

    def close(self) -> None:
        self.closed = True

    def send(self, data: bytes) -> None:
        assert self.callback is not None
        self.callback(data)


@pytest.fixture(autouse=True)
def _fresh_backends() -> None:
    FakeClockBackend.made = []


def clocked(start: Any, source: Any = None, **kwargs: Any) -> Front:
    front: Front = start(source, clock=True, clock_backend=FakeClockBackend, **kwargs)
    return front


def daw() -> FakeClockBackend:
    return FakeClockBackend.made[-1]


def clock_replies(front: Front) -> list[list[Any]]:
    """The `/mpciml/clock` replies so far (read up to a `pong`)."""
    front.send("/mpciml/ping")
    replies = front.replies.until("/mpciml/pong")
    return [args for address, args in replies if address == "/mpciml/clock"]


def bars(beats: int, t0: float = 0.0) -> list[Event]:
    """Start at `t0`, then `beats` beats of ticks at 120 BPM, as raw MIDI events."""
    events: list[Event] = [RawMidiEvent(t0, START)]
    events += [RawMidiEvent(t0 + i * INTERVAL, TICK) for i in range(beats * TICKS_PER_BEAT)]
    return events


def hit(t: float, note: int = 37, velocity: int = 100) -> MidiEvent:
    return MidiEvent(t, "note_on", 1, velocity, note=note)


def with_hook(hook: Callable[[ClockAccess], None]) -> Callable[[], Mapping[str, Preset]]:
    preset = dataclasses.replace(DEMO, name="synced", clock=hook)
    return lambda: {"demo": DEMO, "synced": preset}


# Sync off


def test_without_clock_no_port_opens_and_the_hook_is_not_called(start: Any) -> None:
    called: list[ClockAccess] = []
    front = start(preset="synced", presets=with_hook(called.append))
    assert front.ask("/mpciml/state/get")[-1] == ("/mpciml/clock", ["off", 0.0, 0, 0])
    assert FakeClockBackend.made == []
    assert called == []


# Clock input and replies


def test_clock_opens_the_virtual_input_and_waits(start: Any) -> None:
    front = clocked(start)
    assert daw().opened == CLOCK_PORT_NAME
    assert front.ask("/mpciml/state/get")[-1] == ("/mpciml/clock", ["waiting", 0.0, 0, 0])
    front.engine.close()
    assert daw().closed


def test_clock_port_opens_an_existing_port(start: Any) -> None:
    clocked(start, clock_port="iac")
    assert daw().opened == "IAC Driver Bus 1"


def test_unknown_clock_port_fails_on_start(tmp_path: Any) -> None:
    engine = Engine(
        tmp_path, clock=True, clock_port="nope", clock_backend=FakeClockBackend, control_port=0
    )
    with pytest.raises(PortNotFoundError, match="IAC Driver Bus 1"):
        engine.start()
    engine.close()


def test_reports_status_changes_and_each_beat(start: Any) -> None:
    front = clocked(start)
    clock = daw()
    clock.send(START)
    for _ in range(2 * 4 * TICKS_PER_BEAT):
        clock.send(TICK)
    clock.send(STOP)
    replies = clock_replies(front)
    assert [r[0] for r in replies] == ["running"] * 9 + ["stopped"]
    assert [(r[2], r[3]) for r in replies[:9]] == [(0, 0)] + [
        (b, k) for b in (1, 2) for k in (1, 2, 3, 4)
    ]
    assert replies[-1][1] > 0
    assert front.ask("/mpciml/state/get")[-1][1][:1] == ["stopped"]


def test_replayed_clock_bytes_drive_the_clock_and_lost(start: Any) -> None:
    """Clock in the gesture source feeds the clock; a gap of 1 s marks it `lost`."""
    events = [*bars(4, t0=0.0), hit(3.0)]
    front = clocked(start, events)
    statuses: list[str] = []
    while "lost" not in statuses:
        statuses.append(front.expect("/mpciml/clock")[0])
    assert statuses[:5] == ["running"] * 5
    assert statuses[-1] == "lost"


def test_beats_per_bar(start: Any) -> None:
    front = clocked(start, beats_per_bar=3)
    clock = daw()
    clock.send(START)
    for _ in range(4 * TICKS_PER_BEAT):
        clock.send(TICK)
    replies = clock_replies(front)
    assert [(r[2], r[3]) for r in replies] == [(0, 0), (1, 1), (1, 2), (1, 3), (2, 1)]


# Preset.clock


def test_preset_hook_gets_pad_hits_on_the_grid(start: Any) -> None:
    hits: list[GridHit] = []
    done = threading.Event()

    def hook(access: ClockAccess) -> None:
        def on_hit(grid_hit: GridHit) -> None:
            hits.append(grid_hit)
            if len(hits) == 2:
                done.set()

        access.on_hit(on_hit)

    sixteenth = 6 * INTERVAL
    events = bars(8)
    events.insert(4 * TICKS_PER_BEAT + 2, hit(4 * TICKS_PER_BEAT * INTERVAL + 0.004))
    events.insert(-10, hit((6 * TICKS_PER_BEAT + 12) * INTERVAL - 0.005, note=40))
    clocked(start, sorted(events, key=lambda e: e.t), preset="synced", presets=with_hook(hook))
    assert done.wait(TIMEOUT)
    first, second = hits
    assert (first.bar, first.step, first.pad, first.velocity) == (1, 0, 1, 100)
    assert first.offset_ms == pytest.approx(4.0, abs=0.01)
    assert (second.bar, second.step, second.pad) == (1, 10, 4)
    assert second.offset == pytest.approx(-0.005 / sixteenth, abs=1e-6)


def test_preset_load_gives_the_new_preset_a_new_access(start: Any) -> None:
    called: list[ClockAccess] = []
    front = clocked(start, presets=with_hook(called.append))
    assert called == []
    front.ask("/mpciml/preset/load", "synced")
    assert len(called) == 1
    assert called[0].state().status == "waiting"


def test_a_failing_hook_is_logged_and_the_preset_loads(start: Any) -> None:
    lines: list[str] = []

    def hook(access: ClockAccess) -> None:
        raise RuntimeError("broken")

    front = clocked(start, preset="synced", presets=with_hook(hook), log=lines.append)
    assert front.state() == "idle"
    assert any("broken" in line for line in lines)


# Command line


def test_clock_options() -> None:
    args = build_parser().parse_args(["data"])
    assert (args.clock, args.clock_port, args.beats_per_bar) == (False, None, 4)
    args = build_parser().parse_args(["data", "--clock-port", "IAC", "--beats-per-bar", "3"])
    assert (args.clock_port, args.beats_per_bar) == ("IAC", 3)


def test_beats_per_bar_must_be_positive() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["data", "--clock", "--beats-per-bar", "0"])
