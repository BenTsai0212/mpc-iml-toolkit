"""MIDI clock parsing, position, tempo, timeout and grid tags, with simulated clock."""

import random

import pytest

from mpc_iml.clock import (
    EIGHTHS,
    SIXTEENTH_TRIPLETS,
    TICKS_PER_BEAT,
    ClockAccess,
    GridHit,
    MidiClock,
    PadHit,
    off_state,
)
from mpc_iml.events import MidiEvent, RawMidiEvent

TICK, START, CONTINUE, STOP = b"\xf8", b"\xfa", b"\xfb", b"\xfc"


def song_position(sixteenths: int) -> bytes:
    return bytes([0xF2, sixteenths & 0x7F, sixteenths >> 7])


class Daw:
    """Sends ideal ticks at a tempo, each delivered with clipped Gaussian jitter."""

    def __init__(self, bpm: float, jitter: float = 0.001, seed: int = 1) -> None:
        self.bpm = bpm
        self.t = 0.0
        self.jitter = jitter
        self.rng = random.Random(seed)

    @property
    def interval(self) -> float:
        return 60.0 / (self.bpm * TICKS_PER_BEAT)

    def ticks(self, clock: MidiClock, count: int) -> None:
        """Send `count` ticks; the first one at the current ideal time."""
        for _ in range(count):
            noise = max(-0.003, min(0.003, self.rng.gauss(0.0, self.jitter)))
            clock.feed(TICK, self.t + noise)
            self.t += self.interval

    def send(self, clock: MidiClock, data: bytes) -> None:
        clock.feed(data, self.t - self.interval / 2)


def test_starts_waiting_and_off_state() -> None:
    clock = MidiClock()
    assert clock.state().status == "waiting"
    assert clock.position(0.0) is None
    off = off_state()
    assert (off.status, off.bpm, off.bar, off.beat, off.beats_per_bar) == ("off", None, 0, 0, 4)


@pytest.mark.parametrize("bpm", [60.0, 120.0, 180.0])
def test_bar_beat_and_step_are_exact_under_jitter(bpm: float) -> None:
    clock, daw = MidiClock(), Daw(bpm)
    daw.send(clock, START)
    for tick in range(64 * 4 * TICKS_PER_BEAT):
        daw.ticks(clock, 1)
        state = clock.state()
        assert state.tick == tick
        assert state.bar == tick // 96
        assert state.beat == (tick // 24) % 4
        assert state.step == (tick // 6) % 16
    state = clock.state()
    assert state.status == "running"
    assert state.bpm == pytest.approx(bpm, abs=0.5)


def test_tempo_is_known_after_one_beat_and_follows_a_change() -> None:
    clock, daw = MidiClock(), Daw(120.0)
    daw.send(clock, START)
    daw.ticks(clock, TICKS_PER_BEAT - 1)
    assert clock.state().bpm is None
    daw.ticks(clock, 1)
    assert clock.state().bpm == pytest.approx(120.0, abs=0.5)
    daw.bpm = 90.0
    daw.ticks(clock, 2 * TICKS_PER_BEAT)
    assert clock.state().bpm == pytest.approx(90.0, abs=0.5)


def test_ticks_without_start_only_set_the_tempo() -> None:
    clock, daw = MidiClock(), Daw(100.0)
    daw.ticks(clock, 30)
    state = clock.state()
    assert (state.status, state.tick) == ("stopped", -1)
    assert state.bpm == pytest.approx(100.0, abs=0.5)
    assert clock.position(daw.t) is None


def test_stop_keeps_position_and_song_position_continue_resumes() -> None:
    clock, daw = MidiClock(), Daw(120.0)
    daw.send(clock, START)
    daw.ticks(clock, 100)
    daw.send(clock, STOP)
    daw.ticks(clock, 10)
    state = clock.state()
    assert (state.status, state.tick) == ("stopped", 99)
    assert clock.position(daw.t) is None
    daw.send(clock, CONTINUE)
    daw.ticks(clock, 1)
    assert clock.state().tick == 100
    daw.send(clock, STOP)
    daw.send(clock, song_position(8 * 16))
    daw.send(clock, CONTINUE)
    daw.ticks(clock, 1)
    state = clock.state()
    assert (state.status, state.tick, state.bar, state.beat, state.step) == (
        "running",
        8 * 96,
        8,
        0,
        0,
    )


def test_start_returns_to_zero() -> None:
    clock, daw = MidiClock(), Daw(120.0)
    daw.send(clock, START)
    daw.ticks(clock, 500)
    daw.send(clock, START)
    assert clock.state().tick == -1
    daw.ticks(clock, 1)
    assert clock.state().tick == 0


def test_other_messages_are_ignored() -> None:
    clock = MidiClock()
    for data in (b"", b"\xfe", b"\xf2\x01", bytes([0x90, 36, 100]), b"\xf0\x47\xf7"):
        assert clock.feed(data, 0.0) == clock.state()
    assert clock.state().status == "waiting"


def test_lost_when_ticks_stop_and_running_when_they_return() -> None:
    clock, daw = MidiClock(), Daw(120.0)
    assert clock.check(10.0).status == "waiting"
    daw.send(clock, START)
    daw.ticks(clock, 48)
    last = daw.t - daw.interval
    assert clock.check(last + 0.4).status == "running"
    assert clock.check(last + 0.6).status == "lost"
    assert clock.position(last + 0.6) is None
    daw.t = last + 0.7
    daw.ticks(clock, 1)
    state = clock.state()
    assert (state.status, state.tick) == ("running", 48)


def test_start_without_ticks_is_lost() -> None:
    clock = MidiClock()
    clock.feed(START, 1.0)
    assert clock.check(1.6).status == "lost"


def test_stop_while_waiting_stays_waiting() -> None:
    clock = MidiClock()
    clock.feed(STOP, 0.0)
    assert clock.state().status == "waiting"


def note_on(t: float, note: int = 37, velocity: int = 90) -> MidiEvent:
    return MidiEvent(t=t, kind="note_on", channel=1, note=note, value=velocity)


@pytest.mark.parametrize("offset_ms", [-40.0, -12.0, 0.0, 7.5, 40.0])
def test_hits_get_their_step_and_offset_under_jitter(offset_ms: float) -> None:
    clock, daw = MidiClock(), Daw(120.0, seed=7)
    daw.send(clock, START)
    daw.ticks(clock, 4 * 96 + 6 * 5 + 1)
    true_time = (4 * 96 + 6 * 5) * daw.interval
    hit = clock.tag(note_on(true_time + offset_ms / 1000, note=53, velocity=110))
    assert hit is not None
    assert (hit.bar, hit.step, hit.bank, hit.pad, hit.velocity) == (4, 5, 1, 1, 110)
    assert hit.offset_ms == pytest.approx(offset_ms, abs=3.0)
    assert hit.offset == pytest.approx(offset_ms / 125.0, abs=0.03)


def test_a_late_hit_on_the_last_step_rounds_into_the_next_bar() -> None:
    clock, daw = MidiClock(), Daw(120.0, jitter=0.0)
    daw.send(clock, START)
    daw.ticks(clock, 96)
    hit = clock.tag(note_on(95.5 * daw.interval))
    assert hit is not None
    assert (hit.bar, hit.step) == (1, 0)
    assert hit.offset == pytest.approx(-0.5 / 6)


def test_halfway_goes_to_the_later_step() -> None:
    clock, daw = MidiClock(), Daw(120.0, jitter=0.0)
    daw.send(clock, START)
    daw.ticks(clock, 30)
    hit = clock.tag(note_on(3 * daw.interval))
    assert hit is not None
    assert (hit.step, hit.offset) == (1, pytest.approx(-0.5))


@pytest.mark.parametrize(("ticks_per_step", "step"), [(EIGHTHS, 3), (SIXTEENTH_TRIPLETS, 9)])
def test_other_resolutions(ticks_per_step: int, step: int) -> None:
    clock, daw = MidiClock(), Daw(120.0, jitter=0.0)
    daw.send(clock, START)
    daw.ticks(clock, 96 + 37)
    hit = clock.tag(note_on((96 + 36) * daw.interval), ticks_per_step=ticks_per_step)
    assert hit is not None
    assert (hit.bar, hit.step) == (1, step)
    with pytest.raises(ValueError):
        clock.tag(note_on(0.0), ticks_per_step=5)


def test_only_running_pad_hits_are_tagged() -> None:
    clock, daw = MidiClock(), Daw(120.0)
    assert clock.tag(note_on(0.0)) is None
    daw.send(clock, START)
    daw.ticks(clock, 30)
    t = daw.t
    assert clock.tag(note_on(t, velocity=0)) is None
    assert clock.tag(MidiEvent(t=t, kind="poly_pressure", channel=1, note=36, value=9)) is None
    assert clock.tag(RawMidiEvent(t=t, data=TICK)) is None
    assert clock.tag(note_on(t)) is not None


def test_three_beats_per_bar() -> None:
    clock, daw = MidiClock(beats_per_bar=3), Daw(120.0)
    daw.send(clock, START)
    daw.ticks(clock, 3 * 24 + 25)
    state = clock.state()
    assert (state.bar, state.beat, state.step, state.beats_per_bar) == (1, 1, 4, 3)
    with pytest.raises(ValueError):
        MidiClock(beats_per_bar=0)


# ClockAccess (#138)


def test_access_without_sync_gives_pad_hits_and_sends_at_once() -> None:
    sent: list[bytes] = []
    pads: list[PadHit] = []
    grid: list[GridHit] = []
    access = ClockAccess(None, send=sent.append, beats_per_bar=3)
    access.on_pad(pads.append)
    access.on_hit(grid.append)
    assert access.state() == off_state(3)
    assert access.position(1.0) is None
    assert access.scheduler is None
    access.deliver(note_on(1.0, note=53, velocity=110))
    access.deliver(note_on(1.1, velocity=0))
    access.deliver(MidiEvent(t=1.2, kind="poly_pressure", channel=1, note=36, value=9))
    assert pads == [PadHit(1.0, 1, 1, 110, None)]
    assert grid == []
    access.send_now([b"\x91\x21\x40", b"\x81\x21\x00"])
    assert sent == [b"\x91\x21\x40", b"\x81\x21\x00"]


def test_on_pad_has_the_grid_only_while_running() -> None:
    clock, daw = MidiClock(), Daw(120.0, jitter=0.0)
    pads: list[PadHit] = []
    grid: list[GridHit] = []
    access = ClockAccess(clock)
    access.on_pad(pads.append)
    access.on_pad(pads.append, ticks_per_step=EIGHTHS)
    access.on_hit(grid.append)
    access.deliver(note_on(0.0))
    daw.send(clock, START)
    daw.ticks(clock, 30)
    access.deliver(note_on(12 * daw.interval))
    first, eighths, second, second_eighths = pads
    assert first.grid is None and eighths.grid is None
    assert second.grid is not None and second.grid.step == 2
    assert second_eighths.grid is not None and second_eighths.grid.step == 1
    assert grid == [second.grid]
    access.send_now([b"\x90\x21\x40"])


def test_a_failing_pad_callback_is_logged_and_others_still_run() -> None:
    lines: list[str] = []
    pads: list[PadHit] = []

    def fail(hit: PadHit) -> None:
        raise RuntimeError("broken")

    access = ClockAccess(None, log=lines.append)
    access.on_pad(fail)
    access.on_pad(pads.append)
    access.deliver(note_on(0.0))
    access.send_now([b"\x90\x21\x40"])
    assert len(pads) == 1
    assert "broken" in lines[0]
    with pytest.raises(ValueError):
        access.on_pad(pads.append, ticks_per_step=5)
