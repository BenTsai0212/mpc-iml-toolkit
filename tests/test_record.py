"""`python -m mpc_iml.record --clock` (#139): pad and MIDI clock in one recording.

The MPC is the fake backend of `test_sources.py`; the DAW is a fake clock backend
whose messages arrive just before a scripted pad message is polled, so the order in
the file is known without real ports or threads.
"""

import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from test_sources import FakeBackend, FakeClock

from mpc_iml import record as record_cli
from mpc_iml.events import MidiEvent, RawMidiEvent
from mpc_iml.record import main as record_main
from mpc_iml.recording import read_recording
from mpc_iml.sources import CLOCK_PORT_NAME, LiveSource

PAD_ON, PAD_OFF = b"\x90\x24\x1e", b"\x80\x24\x00"
START, TICK, NOTE = b"\xfa", b"\xf8", b"\x90\x3c\x64"


class FakeDaw:
    """A `ClockInputBackend`; `pending` messages go to the callback when `deliver` runs."""

    made: list["FakeDaw"] = []

    def __init__(self) -> None:
        self.opened: str | None = None
        self.callback: Callable[[bytes], None] | None = None
        self.closed = False
        self.pending: list[list[bytes]] = []
        FakeDaw.made.append(self)

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

    def deliver(self) -> None:
        if self.callback is not None and self.pending:
            for data in self.pending.pop(0):
                self.callback(data)


class PadsWithDaw(FakeBackend):
    """The MPC; before each scripted pad message, the DAW sends its next batch."""

    def __init__(self, daw: FakeDaw, script: list[tuple[float, bytes]]) -> None:
        super().__init__(FakeClock(), script)
        self.daw = daw

    def poll(self) -> bytes | None:
        if self.script:
            self.daw.deliver()
        return super().poll()


@pytest.fixture(autouse=True)
def _fresh() -> None:
    FakeDaw.made = []


def run(
    path: Path, *flags: str, batches: list[list[bytes]] | None = None, duration: str = "0.3"
) -> tuple[int, FakeDaw]:
    daw = FakeDaw()
    daw.pending = list(batches or [])
    backend = PadsWithDaw(daw, [(0.0, PAD_ON), (0.0, PAD_OFF)])
    code = record_main([str(path), "--duration", duration, *flags], backend, lambda: daw)
    return code, daw


def test_clock_and_pads_are_merged_in_time_order(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "out.jsonl"
    code, daw = run(path, "--clock", batches=[[START, TICK, NOTE], [TICK]])
    assert code == 0
    assert daw.opened == CLOCK_PORT_NAME
    assert daw.closed
    events = read_recording(path).events
    kinds = [e.data if isinstance(e, RawMidiEvent) else e.kind for e in events]
    # The note from the DAW's port is dropped: frames would read it as a pad hit.
    assert kinds == [START, TICK, "note_on", TICK, "note_off"]
    times = [e.t for e in events]
    assert times == sorted(times)
    err = capsys.readouterr().err
    assert f"Recording MIDI clock from {CLOCK_PORT_NAME!r}" in err
    assert "Wrote 5 events (3 clock messages)" in err


def test_clock_port_opens_an_existing_port(tmp_path: Path) -> None:
    code, daw = run(tmp_path / "out.jsonl", "--clock-port", "iac", batches=[[TICK]])
    assert code == 0
    assert daw.opened == "IAC Driver Bus 1"


def test_clock_port_not_found(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "out.jsonl"
    code, _ = run(path, "--clock-port", "Nope")
    assert code == 1
    assert "no MIDI input port contains 'Nope'" in capsys.readouterr().err
    assert not path.exists()


def test_without_clock_nothing_changes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "out.jsonl"
    code, daw = run(path, batches=[[START, TICK]])
    assert code == 0
    assert daw.opened is None
    events = read_recording(path).events
    assert [e.kind for e in events if isinstance(e, MidiEvent)] == ["note_on", "note_off"]
    assert len(events) == 2
    err = capsys.readouterr().err
    assert "MIDI clock" not in err
    assert "clock messages" not in err
    assert f"Wrote 2 events to {path}" in err


def test_no_clock_records_pads_with_one_log_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(record_cli, "CLOCK_WAIT", 0.05)
    path = tmp_path / "out.jsonl"
    code, _ = run(path, "--clock", duration="0.2")
    assert code == 0
    assert len(read_recording(path).events) == 2
    err = capsys.readouterr().err
    assert err.count("MIDI clock: nothing received on 'mpc-iml clock' yet") == 1
    assert "turn on Sync" in err
    assert "Wrote 2 events (0 clock messages)" in err


def test_inject_from_another_thread_keeps_time_monotonic() -> None:
    clock = FakeClock()
    lock = threading.Lock()

    def now() -> float:
        with lock:
            clock.now += 0.0001
            return clock.now

    script = [(0.0, PAD_ON if i % 2 == 0 else PAD_OFF) for i in range(500)]
    backend = FakeBackend(clock, script)
    source = LiveSource(backend=backend, clock=now, sleep=lambda _: None)
    source.open()

    def daw() -> None:
        for _ in range(500):
            source.inject(TICK)

    thread = threading.Thread(target=daw)
    thread.start()
    received = []
    while thread.is_alive() or not backend.exhausted() or len(received) < 1000:
        event = source.poll()
        if event is not None:
            received.append(event)
    thread.join()
    source.close()
    assert len(received) == 1000
    assert sum(isinstance(e, RawMidiEvent) for e in received) == 500
    times = [e.t for e in received]
    assert times == sorted(times)


def test_inject_is_ignored_while_closed() -> None:
    source = LiveSource(backend=FakeBackend(FakeClock()))
    source.inject(TICK)
    source.open()
    assert source.poll() is None
    source.inject(TICK)
    source.close()
    assert source.poll() is None
