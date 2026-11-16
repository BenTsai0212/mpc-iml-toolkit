"""Replay tests against the recorded MPC Sample fixtures (#53).

The fixtures in `tests/fixtures/recordings/` were recorded on the hardware (#26);
their README describes each file and the hardware behaviour seen. These tests only
read them: to cover new behaviour, record a new file and describe it there.
"""

import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest

from mpc_iml.events import Event, MidiEvent
from mpc_iml.examples import ExampleSet
from mpc_iml.frames import Frame, frames, note_to_bank_pad, realtime_frames
from mpc_iml.loop import IMLLoop
from mpc_iml.recording import Recording, read_recording
from mpc_iml.sklearn_backend import Classifier
from mpc_iml.sources import ReplaySource

FIXTURES = Path(__file__).parent / "fixtures" / "recordings"
NAMES = ["strikes", "hold-pressure", "two-pads", "banks", "transport", "examples"]


def load(name: str) -> Recording:
    return read_recording(FIXTURES / f"{name}.jsonl")


def midi(events: tuple[Event, ...]) -> list[MidiEvent]:
    return [e for e in events if isinstance(e, MidiEvent)]


def frame_at(fs: list[Frame], t: float) -> int:
    """Index of the first frame at or after `t`: the first one that reflects an event at `t`."""
    return next(i for i, f in enumerate(fs) if f.t >= t)


class FakeClock:
    """A clock that only moves when something sleeps (as in test_realtime)."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now = round(self.now + seconds, 9)


def test_every_fixture_is_listed() -> None:
    assert sorted(p.stem for p in FIXTURES.glob("*.jsonl")) == sorted(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_fixture_reads_without_error_or_warning(name: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rec = load(name)
    assert rec.header.format_version == 1
    assert rec.header.firmware == "1.3.0"
    assert rec.header.settings["full_level"] is False
    assert rec.events
    times = [e.t for e in rec.events]
    assert times == sorted(times)


def test_banks_show_bank_0_1_and_7_on_physical_pad_1() -> None:
    rec = load("banks")
    fs = list(frames(rec.events))
    strikes = [e for e in midi(rec.events) if e.kind == "note_on"]
    assert [e.note for e in strikes] == [36, 52, 20]
    for strike, bank in zip(strikes, [0, 1, 7], strict=True):
        assert strike.note is not None
        assert note_to_bank_pad(strike.note) == (bank, 0)
        frame = fs[frame_at(fs, strike.t)]
        assert frame.bank == bank
        assert frame.held[0]
        assert frame.velocity[0] == strike.value
        assert not any(frame.held[1:])


def test_transport_messages_do_not_change_any_frame() -> None:
    rec = load("transport")
    controls = [e for e in midi(rec.events) if e.kind == "control_change"]
    assert [(e.control, e.value) for e in controls] == [(7, 90), (64, 0), (64, 0)]
    without = [e for e in rec.events if e not in controls]
    with_controls = list(frames(rec.events))
    without_controls = list(frames(without))
    # The control changes come after the last note, so only the frame count differs.
    assert with_controls[: len(without_controls)] == without_controls
    last = without_controls[-1]
    assert all(
        (f.pressure, f.velocity, f.held, f.bank)
        == (last.pressure, last.velocity, last.held, last.bank)
        for f in with_controls[len(without_controls) :]
    )


@dataclass(frozen=True)
class Retrigger:
    """`note_off` while the pad was still held, then a new `note_on` on the same note."""

    note: int
    off: MidiEvent
    on: MidiEvent
    pressure_before: int


def retriggers(events: tuple[Event, ...]) -> list[Retrigger]:
    """Every `note_off` followed by a `note_on` on the same note within 0.3 s."""
    ms = midi(events)
    found: list[Retrigger] = []
    for i, off in enumerate(ms):
        if off.kind != "note_off" or off.note is None:
            continue
        on = next((e for e in ms[i + 1 :] if e.note == off.note and e.kind == "note_on"), None)
        if on is None or on.t - off.t > 0.3:
            continue
        before = [e for e in ms[:i] if e.note == off.note and e.kind == "poly_pressure"]
        found.append(Retrigger(off.note, off, on, before[-1].value))
    return found


@pytest.mark.parametrize(("name", "count"), [("hold-pressure", 3), ("two-pads", 21)])
def test_retriggering_while_held_is_what_frames_currently_show(name: str, count: int) -> None:
    """Pins today's frames around each hardware retrigger (README; #43).

    The pad stays physically held, but frames follow the MIDI: from the `note_off`
    the held flag is off and pressure is 0 until the new `note_on`, whose frame has
    held on, the new low velocity and pressure still 0. If #43 changes how frames
    treat retriggering, this test changes with it on purpose.
    """
    rec = load(name)
    fs = list(frames(rec.events))
    found = retriggers(rec.events)
    assert len(found) == count
    for r in found:
        _, pad = note_to_bank_pad(r.note)
        # Hardware behaviour from the fixtures README.
        assert r.pressure_before in (1, 3)
        assert 0.069 <= r.on.t - r.off.t <= 0.274  # README: 70-273 ms, rounded (shortest 69.5 ms)
        assert 1 <= r.on.value <= 21
        off, on = frame_at(fs, r.off.t), frame_at(fs, r.on.t)
        assert fs[off - 1].held[pad]
        assert fs[off - 1].pressure[pad] > 0
        for f in fs[off:on]:
            assert not f.held[pad]
            assert f.pressure[pad] == 0
        assert fs[on].held[pad]
        assert fs[on].velocity[pad] == r.on.value
        assert fs[on].pressure[pad] == 0


def test_examples_fixture_trains_and_runs_the_loop() -> None:
    examples = ExampleSet()
    added = examples.add_recording(FIXTURES / "examples.jsonl")
    assert added > 0
    assert set(examples.classes) == {"rest", "soft", "hard"}
    assert {e.label for e in examples.examples} == {"rest", "soft", "hard"}
    loop = IMLLoop(Classifier, examples)
    loop.train()
    source = ReplaySource(FIXTURES / "examples.jsonl")
    predictions: list[list[float] | None] = []
    for frame in frames(source):
        predictions.append(loop.step(frame))
    assert loop.run(ReplaySource(FIXTURES / "examples.jsonl")) == len(predictions)
    numbers = {float(n) for n in examples.classes.values()}
    assert all(p is not None and len(p) == 1 and p[0] in numbers for p in predictions)


@pytest.mark.parametrize("name", ["two-pads", "examples"])
def test_realtime_replay_gives_the_same_frames(name: str) -> None:
    clock = FakeClock()
    rec = load(name)
    source = ReplaySource(rec, realtime=True, clock=clock, sleep=clock.sleep)
    dropped: list[int] = []
    realtime = list(realtime_frames(source, on_drop=dropped.append))
    assert realtime == list(frames(rec.events))
    assert dropped == []
