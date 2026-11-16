"""Live source with a fake MIDI backend, replay source, swapping, and recording."""

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from mpc_iml.events import Event, ExampleEnd, ExampleStart, MidiEvent, RawMidiEvent
from mpc_iml.frames import frames
from mpc_iml.record import main as record_main
from mpc_iml.recording import FullLevelWarning, Header, Recording, read_recording
from mpc_iml.sources import LiveSource, PortNotFoundError, ReplaySource, record, tee

DATA = Path(__file__).parent / "data"
EVENT_TYPES = (MidiEvent, RawMidiEvent, ExampleStart, ExampleEnd)


class FakeClock:
    """A clock that only moves when something sleeps or sets it."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeBackend:
    """Scripted ports and messages; a message arrives at its scripted clock time."""

    def __init__(
        self,
        clock: FakeClock,
        script: list[tuple[float, bytes]] | None = None,
        ports: list[str] | None = None,
    ) -> None:
        self.clock = clock
        self.script = list(script or [])
        self.ports = ports if ports is not None else ["IAC Bus 1", "MPC Sample MIDI"]
        self.opened: int | None = None
        self.closed = False

    def port_names(self) -> list[str]:
        return self.ports

    def open(self, index: int) -> None:
        self.opened = index

    def poll(self) -> bytes | None:
        if not self.script:
            return None
        at, data = self.script[0]
        self.clock.now = max(self.clock.now, at)
        self.script.pop(0)
        return data

    def close(self) -> None:
        self.closed = True

    def exhausted(self) -> bool:
        return not self.script


def to_bytes(event: MidiEvent | RawMidiEvent) -> bytes:
    if isinstance(event, RawMidiEvent):
        return event.data
    status = {
        "note_off": 0x80,
        "note_on": 0x90,
        "poly_pressure": 0xA0,
        "control_change": 0xB0,
        "program_change": 0xC0,
        "channel_pressure": 0xD0,
        "pitch_bend": 0xE0,
    }[event.kind] | (event.channel - 1)
    if event.kind == "pitch_bend":
        return bytes([status, event.value & 0x7F, event.value >> 7])
    first = event.note if event.note is not None else event.control
    if first is None:
        return bytes([status, event.value])
    return bytes([status, first, event.value])


def midi_only(events: tuple[Event, ...]) -> list[MidiEvent | RawMidiEvent]:
    return [e for e in events if isinstance(e, MidiEvent | RawMidiEvent)]


def live_from(events: Sequence[MidiEvent | RawMidiEvent]) -> tuple[LiveSource, FakeBackend]:
    clock = FakeClock()
    backend = FakeBackend(clock, [(e.t, to_bytes(e)) for e in events])
    return LiveSource(backend=backend, clock=clock, sleep=clock.sleep), backend


# Live source


def test_live_opens_port_containing_mpc_by_default() -> None:
    clock = FakeClock()
    backend = FakeBackend(clock)
    with LiveSource(backend=backend, clock=clock, sleep=clock.sleep) as source:
        assert backend.opened == 1
        assert source.port_name == "MPC Sample MIDI"
    assert backend.closed


def test_live_port_match_is_configurable_and_case_insensitive() -> None:
    clock = FakeClock()
    backend = FakeBackend(clock)
    with LiveSource("iac", backend=backend, clock=clock, sleep=clock.sleep):
        assert backend.opened == 0


def test_live_port_not_found_lists_ports() -> None:
    backend = FakeBackend(FakeClock(), ports=["IAC Bus 1"])
    with pytest.raises(PortNotFoundError, match="'IAC Bus 1'"):
        LiveSource(backend=backend).open()


def test_live_t_is_receive_time_since_open() -> None:
    clock = FakeClock()
    clock.now = 50.0
    backend = FakeBackend(clock, [(50.25, b"\x90\x24\x1e"), (51.0, b"\xa0\x24\x3f")])
    source = LiveSource(backend=backend, clock=clock, sleep=clock.sleep)
    events = list(source.events(stop=backend.exhausted))
    assert events == [
        MidiEvent(t=0.25, kind="note_on", channel=1, note=36, value=30),
        MidiEvent(t=1.0, kind="poly_pressure", channel=1, note=36, value=63),
    ]


def test_live_sleeps_1ms_when_idle_and_stops_after_duration() -> None:
    clock = FakeClock()
    source = LiveSource(backend=FakeBackend(clock), clock=clock, sleep=clock.sleep)
    assert list(source.events(duration=0.01)) == []
    assert set(clock.sleeps) == {0.001}
    assert clock.now == pytest.approx(0.01)


def test_live_close_stops_iteration() -> None:
    events = [MidiEvent(t=i / 10, kind="note_on", channel=1, note=36, value=1) for i in range(5)]
    source, _ = live_from(events)
    received = []
    for event in source:
        received.append(event)
        if len(received) == 2:
            source.close()
    assert received == events[:2]


def test_live_now_requires_open() -> None:
    with pytest.raises(RuntimeError):
        LiveSource(backend=FakeBackend(FakeClock())).now()


# Replay source


def test_replay_fast_yields_recording_events() -> None:
    rec = read_recording(DATA / "basic.jsonl")
    source = ReplaySource(DATA / "basic.jsonl")
    assert list(source) == list(rec.events)
    assert source.header == rec.header


def test_replay_of_full_level_fixture() -> None:
    with pytest.warns(FullLevelWarning):
        rec = read_recording(DATA / "full_level.jsonl")
    assert list(ReplaySource(rec)) == list(rec.events)


def test_replay_realtime_sleeps_until_each_event() -> None:
    clock = FakeClock()
    rec = Recording(
        Header(),
        (
            MidiEvent(t=0.5, kind="note_on", channel=1, note=36, value=30),
            MidiEvent(t=0.5, kind="poly_pressure", channel=1, note=36, value=60),
            MidiEvent(t=1.25, kind="note_off", channel=1, note=36, value=0),
        ),
    )
    source = ReplaySource(rec, realtime=True, clock=clock, sleep=clock.sleep)
    assert list(source) == list(rec.events)
    assert clock.sleeps == [0.5, 0.75]


def test_replay_fast_does_not_sleep() -> None:
    clock = FakeClock()
    rec = read_recording(DATA / "basic.jsonl")
    assert list(ReplaySource(rec, clock=clock, sleep=clock.sleep)) == list(rec.events)
    assert clock.sleeps == []


# Swapping


def test_live_and_replay_are_interchangeable() -> None:
    rec = read_recording(DATA / "basic.jsonl")
    midi = midi_only(rec.events)
    replay = ReplaySource(Recording(rec.header, tuple(midi)))
    live, backend = live_from(midi)
    live_events = list(live.events(stop=backend.exhausted))
    replay_events = list(replay)
    assert live_events == replay_events
    assert all(isinstance(e, EVENT_TYPES) for e in live_events)
    assert list(frames(live_events)) == list(frames(replay_events))


# Recording live input


def test_record_live_input_round_trip(tmp_path: Path) -> None:
    rec = read_recording(DATA / "basic.jsonl")
    midi = midi_only(rec.events)
    live, backend = live_from(midi)
    header = Header(firmware="1.3.0", settings={"full_level": False})
    path = tmp_path / "live.jsonl"
    assert record(live.events(stop=backend.exhausted), path, header) == len(midi)
    again = read_recording(path)
    assert again.header == header
    assert list(again.events) == midi


def test_record_stops_on_keyboard_interrupt(tmp_path: Path) -> None:
    def interrupted() -> Iterator[Event]:
        yield MidiEvent(t=0.1, kind="note_on", channel=1, note=36, value=30)
        raise KeyboardInterrupt

    path = tmp_path / "rec.jsonl"
    assert record(interrupted(), path, Header()) == 1
    assert len(read_recording(path).events) == 1


def test_tee_passes_events_through_while_writing(tmp_path: Path) -> None:
    rec = read_recording(DATA / "basic.jsonl")
    path = tmp_path / "tee.jsonl"
    assert list(tee(ReplaySource(rec), path, rec.header)) == list(rec.events)
    assert read_recording(path) == rec


def test_record_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    clock = FakeClock()
    backend = FakeBackend(clock, [(0.1, b"\x90\x24\x1e"), (0.2, b"\x80\x24\x00")])
    path = tmp_path / "out.jsonl"
    argv = [str(path), "--duration", "0.5", "--firmware", "1.3.0", "--no-full-level"]
    # The CLI uses the real clock; the backend delivers its script immediately.
    assert record_main(argv, backend=backend) == 0
    rec = read_recording(path)
    assert rec.header.firmware == "1.3.0"
    assert rec.header.settings == {"full_level": False}
    assert [(e.kind, e.value) for e in rec.events if isinstance(e, MidiEvent)] == [
        ("note_on", 30),
        ("note_off", 0),
    ]
    assert "Wrote 2 events" in capsys.readouterr().err


def test_record_cli_port_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    backend = FakeBackend(FakeClock(), ports=["IAC Bus 1"])
    assert record_main([str(tmp_path / "out.jsonl"), "--duration", "1"], backend=backend) == 1
    assert "no MIDI input port" in capsys.readouterr().err
    assert not (tmp_path / "out.jsonl").exists()
