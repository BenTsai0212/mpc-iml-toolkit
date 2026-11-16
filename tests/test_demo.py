"""Reference example (`python -m mpc_iml.demo`): guided recording, run, receiver."""

import threading
import time
from pathlib import Path

import pytest

from mpc_iml.demo import (
    CLASSES,
    describe,
    guided_record,
    main,
    make_server,
    played_features,
)
from mpc_iml.events import ExampleEnd, ExampleStart, MidiEvent
from mpc_iml.examples import ExampleSet
from mpc_iml.frames import Frame
from mpc_iml.recording import read_recording
from mpc_iml.sources import LiveSource

DATA = Path(__file__).parent / "data"
EXAMPLES = DATA / "demo_examples.jsonl"
PERFORMANCE = DATA / "demo_performance.jsonl"


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeBackend:
    """One MPC-like port; each scripted message arrives at its clock time."""

    def __init__(self, clock: FakeClock, script: list[tuple[float, bytes]]) -> None:
        self.clock = clock
        self.script = list(script)
        self.closed = False

    def port_names(self) -> list[str]:
        return ["MPC Sample MIDI"]

    def open(self, index: int) -> None:
        pass

    def poll(self) -> bytes | None:
        if not self.script or self.script[0][0] > self.clock.now:
            return None
        return self.script.pop(0)[1]

    def close(self) -> None:
        self.closed = True


# Countdown 1 s and 1 s per class: rest 1-2, soft 3-4, hard 5-6.
SCRIPT = [
    (3.1, bytes([0x90, 36, 30])),
    (3.2, bytes([0xA0, 36, 25])),
    (4.5, bytes([0x80, 36, 0])),
    (5.1, bytes([0x90, 36, 110])),
    (5.2, bytes([0xA0, 36, 100])),
    (6.5, bytes([0x80, 36, 0])),
]


def frame(velocity: int, pressure: int, held: bool) -> Frame:
    return Frame(
        t=0.0,
        pressure=(pressure,) + (0,) * 15,
        velocity=(velocity,) + (0,) * 15,
        held=(held,) + (False,) * 15,
        bank=0,
    )


def test_played_features_drop_velocity_after_release() -> None:
    assert len(played_features(frame(100, 0, True))) == 32
    assert played_features(frame(127, 127, True))[0] == 1.0
    assert played_features(frame(127, 127, True))[16] == 1.0
    assert played_features(frame(100, 0, False)) == [0.0] * 32


def test_guided_record_puts_markers_around_each_class() -> None:
    clock = FakeClock()
    source = LiveSource(backend=FakeBackend(clock, SCRIPT), clock=clock, sleep=clock.sleep)
    lines: list[str] = []
    events = guided_record(source, seconds=1.0, countdown=1.0, say=lines.append)

    markers = [e for e in events if isinstance(e, ExampleStart | ExampleEnd)]
    assert [(type(m).__name__, getattr(m, "label", None)) for m in markers] == [
        ("ExampleStart", "rest"),
        ("ExampleEnd", None),
        ("ExampleStart", "soft"),
        ("ExampleEnd", None),
        ("ExampleStart", "hard"),
        ("ExampleEnd", None),
    ]
    assert [round(m.t, 6) for m in markers] == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    assert [e.t for e in events] == sorted(e.t for e in events)
    assert sum(isinstance(e, MidiEvent) for e in events) == 5
    assert lines == [
        "Next: rest. Do not touch any pad. Recording starts in 1 s...",
        "Recording rest for 1 s...",
        "Next: soft. Press and hold pad 1 lightly, for example a light fingertip touch."
        " Recording starts in 1 s...",
        "Recording soft for 1 s...",
        "Release pad 1 now.",
        "Next: hard. Press and hold pad 1 firmly, for example a firm press with the whole"
        " finger; make it clearly different from soft. Recording starts in 1 s...",
        "Recording hard for 1 s...",
        "Release pad 1 now.",
        "Done.",
    ]

    examples = ExampleSet(features=played_features, classes=CLASSES)
    examples.add_events(events)
    assert {e.label for e in examples.examples} == {"rest", "soft", "hard"}


def test_record_command_writes_a_recording(tmp_path: Path) -> None:
    clock = FakeClock()
    backend = FakeBackend(clock, SCRIPT)
    out = tmp_path / "examples.jsonl"

    code = main(
        ["record", str(out), "--seconds", "1", "--countdown", "1", "--no-full-level"],
        backend=backend,
        clock=clock,
        sleep=clock.sleep,
    )
    assert code == 0
    assert backend.closed
    recording = read_recording(out)
    assert recording.header.settings == {"full_level": False}
    labels = [e.label for e in recording.events if isinstance(e, ExampleStart)]
    assert labels == ["rest", "soft", "hard"]


def test_describe() -> None:
    assert describe([1.0]) == "1 rest"
    assert describe([3.0]) == "3 hard  ████████"
    assert describe([9.0]).startswith("9 ?")


class Receiver:
    """The demo's receiver on a free local port, collecting `/wek/outputs` values."""

    def __init__(self) -> None:
        self.values: list[float] = []
        self.server = make_server(lambda v: self.values.append(v[0]), port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "Receiver":
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.server.shutdown()
        self.server.server_close()

    def wait_until_quiet(self, timeout: float = 5.0) -> list[float]:
        deadline = time.monotonic() + timeout
        seen = -1
        while time.monotonic() < deadline and seen != len(self.values):
            seen = len(self.values)
            time.sleep(0.2)
        return self.values


def changes(values: list[float]) -> list[int]:
    out: list[int] = []
    for v in values:
        if not out or out[-1] != round(v):
            out.append(round(v))
    return out


def test_replay_sends_the_classes_in_order(capsys: pytest.CaptureFixture[str]) -> None:
    with Receiver() as receiver:
        code = main(
            ["run", str(EXAMPLES), "--replay", str(PERFORMANCE), "--fast"]
            + ["--osc-port", str(receiver.port)]
        )
        values = receiver.wait_until_quiet()
    assert code == 0
    rest, soft, hard = CLASSES["rest"], CLASSES["soft"], CLASSES["hard"]
    assert changes(values) == [rest, soft, rest, hard, rest]
    assert len(values) == 251
    assert "Ran 251 frames." in capsys.readouterr().out


def test_live_run_sends_classes() -> None:
    clock = FakeClock()
    script = [(0.5, bytes([0x90, 36, 105])), (0.5, bytes([0xA0, 36, 100]))]
    backend = FakeBackend(clock, script)
    with Receiver() as receiver:
        code = main(
            ["run", str(EXAMPLES), "--duration", "1", "--osc-port", str(receiver.port)],
            backend=backend,
            clock=clock,
            sleep=clock.sleep,
        )
        values = receiver.wait_until_quiet()
    assert code == 0
    assert backend.closed
    assert changes(values) == [CLASSES["rest"], CLASSES["hard"]]


def test_live_run_without_mpc_fails_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    class NoMpc(FakeBackend):
        def port_names(self) -> list[str]:
            return ["IAC Bus 1"]

    code = main(["run", str(EXAMPLES), "--duration", "1"], backend=NoMpc(FakeClock(), []))
    assert code == 1
    assert "no MIDI input port" in capsys.readouterr().err
