"""The clock scheduler and test pattern (ADR 0008), driven by simulated MIDI clock."""

import pytest

from mpc_iml.clock import TEST_NOTES, TICKS_PER_BEAT, MidiClock, Scheduler

TICK, START, CONTINUE, STOP = b"\xf8", b"\xfa", b"\xfb", b"\xfc"
INTERVAL = 60 / 120 / TICKS_PER_BEAT
BAR = 4 * TICKS_PER_BEAT
NOTE_ON, NOTE_OFF = 0x90, 0x80


class Daw:
    """Plays a DAW: clock messages at 120 BPM into a clock and its scheduler."""

    def __init__(self, lead: float = 0.0, beats_per_bar: int = 4) -> None:
        self.clock = MidiClock(beats_per_bar)
        self.sent: list[tuple[int, bytes]] = []
        self.log: list[str] = []
        self.scheduler = Scheduler(self.clock, self.record, lead, self.log.append)
        self.next_tick = 0
        self.t = 0.0

    def record(self, message: bytes) -> None:
        self.sent.append((self.clock.state().tick, message))

    def send(self, data: bytes) -> None:
        self.clock.feed(data, self.t)
        self.scheduler.update(self.t)

    def ticks(self, count: int) -> None:
        for _ in range(count):
            self.send(TICK)
            self.t += INTERVAL
            self.next_tick += 1

    def until(self, tick: int) -> None:
        self.ticks(tick - self.next_tick)


def on(note: int, velocity: int = 100) -> bytes:
    return bytes([NOTE_ON, note, velocity])


def off(note: int) -> bytes:
    return bytes([NOTE_OFF, note, 0])


def test_messages_go_out_on_their_tick_never_before() -> None:
    daw = Daw()
    daw.scheduler.at(1, 2, [on(40), bytes([0xB0, 7, 1])])
    daw.send(START)
    daw.until(BAR + 12)
    assert daw.sent == []
    daw.ticks(1)
    assert daw.sent == [(BAR + 12, on(40)), (BAR + 12, bytes([0xB0, 7, 1]))]


def test_next_bar_and_every_n_bars() -> None:
    daw = Daw()
    assert daw.scheduler.next_bar() == 0
    daw.send(START)
    daw.until(1)
    assert daw.scheduler.next_bar() == 1
    assert daw.scheduler.next_bar(4) == 4
    daw.until(BAR)
    assert daw.scheduler.next_bar() == 1
    daw.ticks(1)
    assert daw.scheduler.next_bar() == 2
    assert daw.scheduler.at_next_bar([on(1)], n=2, step=4).tick == 2 * BAR + 24
    with pytest.raises(ValueError):
        daw.scheduler.next_bar(0)


def test_a_note_and_its_note_off() -> None:
    daw = Daw()
    daw.scheduler.note(0, 4, 36, velocity=90, length_steps=2, channel=10)
    daw.send(START)
    daw.until(4 * BAR)
    assert daw.sent == [(24, bytes([0x99, 36, 90])), (36, bytes([0x89, 36, 0]))]
    with pytest.raises(ValueError):
        daw.scheduler.note(0, 0, 128)
    with pytest.raises(ValueError):
        daw.scheduler.at(0, 0, [on(1)], ticks_per_step=5)


def test_cancel_drops_pending_and_ends_a_started_note() -> None:
    daw = Daw()
    dropped = daw.scheduler.at(0, 8, [on(50)])
    started = daw.scheduler.note(0, 1, 60, length_steps=8)
    daw.scheduler.cancel(dropped)
    daw.send(START)
    daw.until(12)
    daw.scheduler.cancel(started)
    assert daw.sent == [(6, on(60)), (11, off(60))]
    daw.until(BAR)
    assert len(daw.sent) == 2


@pytest.mark.parametrize("ending", ["stop", "lost", "start"])
def test_stop_lost_and_a_jump_end_notes_and_drop_pending(ending: str) -> None:
    daw = Daw()
    daw.scheduler.note(0, 1, 60, length_steps=8)
    daw.scheduler.at(1, 0, [on(70)])
    daw.send(START)
    daw.until(12)
    if ending == "stop":
        daw.send(STOP)
    elif ending == "lost":
        daw.clock.check(daw.t + 1)
        daw.scheduler.update(daw.t + 1)
    else:
        daw.send(START)
    assert daw.sent[-1][1] == off(60)
    daw.send(START)
    daw.until(2 * BAR)
    assert [m for _, m in daw.sent] == [on(60), off(60)]


def test_scheduled_while_stopped_plays_after_continue() -> None:
    daw = Daw()
    daw.send(START)
    daw.until(BAR + 30)
    daw.send(STOP)
    daw.scheduler.at_next_bar([on(1)])
    daw.send(CONTINUE)
    daw.until(3 * BAR)
    assert daw.sent == [(2 * BAR, on(1))]


def test_lead_sends_early_by_the_tempo() -> None:
    """At 120 BPM a tick is 20.8 ms: a 50 ms lead sends 2 ticks early."""
    daw = Daw(lead=0.05)
    daw.scheduler.at(1, 0, [on(1)])
    daw.send(START)
    daw.until(BAR + 1)
    assert daw.sent == [(BAR - 2, on(1))]


def test_lead_between_ticks_uses_the_position_at_t() -> None:
    daw = Daw(lead=0.01)
    daw.scheduler.at(1, 0, [on(1)])
    daw.send(START)
    daw.until(BAR)
    assert daw.sent == []
    daw.scheduler.update(daw.t - INTERVAL + 0.012)
    assert daw.sent == [(BAR - 1, on(1))]


def test_a_failing_send_is_logged() -> None:
    clock = MidiClock()
    lines: list[str] = []

    def fail(message: bytes) -> None:
        raise RuntimeError("port closed")

    scheduler = Scheduler(clock, fail, log=lines.append)
    scheduler.at(0, 0, [on(1)])
    clock.feed(START, 0.0)
    clock.feed(TICK, 0.0)
    scheduler.update(0.0)
    assert "port closed" in lines[0]


# Test pattern


def notes(daw: Daw) -> list[tuple[int, int]]:
    return [(tick, m[1]) for tick, m in daw.sent if m[0] == NOTE_ON]


def test_pattern_starts_on_the_next_bar_and_accents_beat_one() -> None:
    daw = Daw()
    daw.send(START)
    daw.until(30)
    daw.scheduler.test_pattern(True)
    daw.until(3 * BAR + 1)
    accent, other = TEST_NOTES
    assert notes(daw) == [
        (bar * BAR + beat * 24, accent if beat == 0 else other)
        for bar in (1, 2, 3)
        for beat in range(4)
        if bar * BAR + beat * 24 <= 3 * BAR
    ]
    assert (BAR + 6, off(accent)) in daw.sent


def test_pattern_from_start_and_three_beats_per_bar() -> None:
    daw = Daw(beats_per_bar=3)
    daw.scheduler.test_pattern(True)
    daw.send(START)
    daw.until(73)
    assert notes(daw) == [(0, 72), (24, 60), (48, 60), (72, 72)]


def test_pattern_stops_at_once_and_resumes_on_a_bar_after_stop() -> None:
    daw = Daw()
    daw.scheduler.test_pattern(True)
    daw.send(START)
    daw.until(BAR + 3)
    daw.scheduler.test_pattern(False)
    assert daw.sent[-1] == (BAR + 2, off(72))
    daw.until(2 * BAR)
    assert notes(daw)[-1] == (BAR, 72)
    daw.scheduler.test_pattern(True)
    daw.until(2 * BAR + 30)
    daw.send(STOP)
    daw.send(CONTINUE)
    daw.until(3 * BAR + 1)
    assert notes(daw)[-3:] == [(2 * BAR, 72), (2 * BAR + 24, 60), (3 * BAR, 72)]


def test_clear_stops_everything() -> None:
    daw = Daw()
    daw.scheduler.test_pattern(True)
    daw.send(START)
    daw.until(2)
    daw.scheduler.clear()
    assert daw.sent[-1][1] == off(72)
    daw.until(2 * BAR)
    assert len(notes(daw)) == 1
