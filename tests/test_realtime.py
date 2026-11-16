"""Real-time frames (#39): a fake clock and a fake MIDI backend; no hardware, no waiting."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from mpc_iml.events import Event, MidiEvent
from mpc_iml.frames import Frame, frames, realtime_frames
from mpc_iml.loop import IMLLoop
from mpc_iml.osc import OscSender
from mpc_iml.recording import Header, Recording, read_recording
from mpc_iml.sources import LiveSource, ReplaySource

DATA = Path(__file__).parent / "data"


class FakeClock:
    """A clock that only moves when something sleeps or advances it.

    Times are rounded to nanoseconds so that sleeping until k / rate lands exactly on it.
    """

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.advance(seconds)

    def advance(self, seconds: float) -> None:
        self.now = round(self.now + seconds, 9)


class TimedBackend:
    """Fake MIDI input: each scripted message becomes pending at its clock time."""

    def __init__(self, clock: FakeClock, script: Sequence[tuple[float, bytes]] = ()) -> None:
        self.clock = clock
        self.script = list(script)

    def port_names(self) -> list[str]:
        return ["MPC Sample MIDI"]

    def open(self, index: int) -> None:
        pass

    def poll(self) -> bytes | None:
        if self.script and self.script[0][0] <= self.clock.now:
            return self.script.pop(0)[1]
        return None

    def close(self) -> None:
        pass


class FakeSender(OscSender):
    """Collects sent values instead of sending UDP."""

    def __init__(self) -> None:
        self.sent: list[list[float]] = []

    def send(self, values: Sequence[float]) -> None:
        self.sent.append(list(values))


def live(script: Sequence[tuple[float, bytes]] = ()) -> tuple[LiveSource, FakeClock]:
    clock = FakeClock()
    backend = TimedBackend(clock, script)
    return LiveSource(backend=backend, clock=clock, sleep=clock.sleep), clock


PRESS = b"\x90\x24\x64"  # note_on pad 1, velocity 100
SQUEEZE = b"\xa0\x24\x3f"  # poly_pressure pad 1, 63
RELEASE = b"\x80\x24\x00"


def test_live_frames_come_every_interval_without_midi() -> None:
    source, clock = live()
    stamps: list[tuple[float, float]] = []
    for frame in realtime_frames(source, duration=0.05):
        stamps.append((frame.t, clock.now))
    assert stamps == [(k / 100, k / 100) for k in range(5)]


def test_event_shows_from_the_first_frame_at_or_after_it() -> None:
    source, _ = live([(0.023, PRESS)])
    held = [f.held[0] for f in realtime_frames(source, duration=0.05)]
    assert held == [False, False, False, True, True]


def test_event_exactly_on_a_frame_time_is_in_that_frame() -> None:
    source, _ = live([(0.03, PRESS)])
    held = [f.held[0] for f in realtime_frames(source, duration=0.05)]
    assert held == [False, False, False, True, True]


@pytest.mark.parametrize(
    "script",
    [
        [(0.0, PRESS), (0.005, SQUEEZE), (0.04, RELEASE)],
        [(0.01, PRESS), (0.02, SQUEEZE), (0.02, RELEASE), (0.07, PRESS)],
        [(0.013, PRESS), (0.0131, SQUEEZE), (0.099, RELEASE)],
    ],
)
def test_live_frames_match_frames_on_the_same_events(script: list[tuple[float, bytes]]) -> None:
    source, _ = live(script)
    received: list[Event] = []
    original_poll = source.poll

    def recording_poll() -> Event | None:
        event = original_poll()
        if event is not None:
            received.append(event)
        return event

    source.poll = recording_poll  # type: ignore[method-assign]
    got = list(realtime_frames(source, duration=0.1))
    end: Event = MidiEvent(0.1, "control_change", 1, 0, control=7)
    expected = [f for f in frames([*received, end]) if f.t < 0.1]
    assert got == expected


def test_live_stops_when_stopped_or_closed() -> None:
    source, clock = live()
    assert len(list(realtime_frames(source, stop=lambda: clock.now >= 0.02))) == 2
    source, _ = live()
    stream = realtime_frames(source)
    next(stream)
    source.close()
    assert list(stream) == []


def recording() -> Recording:
    return read_recording(DATA / "basic.jsonl")


def test_realtime_replay_gives_frames_of_frames_on_schedule() -> None:
    clock = FakeClock()
    rec = recording()
    source = ReplaySource(rec, realtime=True, clock=clock, sleep=clock.sleep)
    stamps: list[tuple[Frame, float]] = [(f, clock.now) for f in realtime_frames(source)]
    assert [f for f, _ in stamps] == list(frames(rec.events))
    assert all(now == f.t for f, now in stamps)


def test_replay_can_be_started_again() -> None:
    clock = FakeClock()
    source = ReplaySource(recording(), realtime=True, clock=clock, sleep=clock.sleep)
    first = list(realtime_frames(source))
    clock.now = 0.0
    assert list(realtime_frames(source)) == first


def test_late_frames_are_dropped_and_events_kept() -> None:
    clock = FakeClock()
    events: tuple[Event, ...] = (
        MidiEvent(0.005, "note_on", 1, 100, note=36),
        MidiEvent(0.025, "poly_pressure", 1, 63, note=36),
        MidiEvent(0.05, "note_off", 1, 0, note=36),
    )
    source = ReplaySource(Recording(Header(), events), True, clock, clock.sleep)
    dropped: list[int] = []
    stream = realtime_frames(source, on_drop=dropped.append)
    first = next(stream)
    clock.advance(0.035)  # a slow step: frames 1 and 2 are late
    late = next(stream)
    rest = list(stream)
    assert (first.t, late.t) == (0.0, 0.03)
    assert dropped == [2]
    assert late.held[0] and late.pressure[0] == 63
    assert [f.t for f in rest] == [0.04, 0.05]
    assert rest[-1] == list(frames(events))[-1]


def test_live_message_waiting_during_a_slow_step_is_stamped_when_read() -> None:
    source, clock = live([(0.005, PRESS)])
    stream = realtime_frames(source)
    next(stream)
    clock.advance(0.035)
    assert [next(stream).held[0] for _ in range(2)] == [False, True]


def test_loop_steps_once_per_frame_with_a_live_source() -> None:
    source, _ = live([(0.012, PRESS)])
    inputs = FakeSender()
    loop = IMLLoop(None, inputs=inputs)
    assert loop.run(source, duration=0.05) == 5
    assert len(inputs.sent) == 5
    assert [values[32] for values in inputs.sent] == [0.0, 0.0, 1.0, 1.0, 1.0]
    assert loop.dropped_frames == 0


def test_loop_counts_dropped_frames() -> None:
    source, clock = live()

    class SlowSender(FakeSender):
        def send(self, values: Sequence[float]) -> None:
            super().send(values)
            clock.advance(0.025)

    loop = IMLLoop(None, inputs=SlowSender())
    sender = loop.inputs
    assert loop.run(source, duration=0.1) == 4
    assert isinstance(sender, FakeSender) and len(sender.sent) == 4
    assert loop.dropped_frames == 4  # frames at 0, 0.02, 0.05, 0.07


def test_loop_runs_iterables_fast_and_honours_duration() -> None:
    events: list[Event] = [MidiEvent(0.05, "note_on", 1, 100, note=36)]
    loop = IMLLoop(None, inputs=FakeSender())
    assert loop.run(events) == 6
    assert loop.run(events, duration=0.03) == 3
    assert loop.run(ReplaySource(Recording(Header(), tuple(events)))) == 6
