"""The built-in preset `pressure` and its MIDI CC output (#65).

Training and the outputs are checked on replayed recordings: the hand-written
`tests/data/pressure_*.jsonl` and the recorded `hold-pressure.jsonl` fixture.
MIDI goes to a fake backend, never to a real port.
"""

import threading
import time
from collections.abc import Iterator, Sequence
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from test_engine import (
    DROPS,
    HOLD,
    TIMEOUT,
    Front,
    LoopingReplay,
    Receiver,
    SteppedReplay,
    record_steps,
)

from mpc_iml.engine import Engine
from mpc_iml.examples import ExampleSet, default_features, played_features
from mpc_iml.frames import Frame
from mpc_iml.loop import FanOut, IMLLoop
from mpc_iml.midi_out import MidiCcSender
from mpc_iml.presets import (
    PRESET_GROUP,
    MidiCcOutput,
    OscOutput,
    Preset,
    PresetError,
    available_presets,
)
from mpc_iml.recording import read_recording
from mpc_iml.sklearn_backend import Regressor
from mpc_iml.sources import PortNotFoundError, ReplaySource

DATA = Path(__file__).parent / "data"
EXAMPLES = DATA / "pressure_examples.jsonl"
PERFORMANCE = DATA / "pressure_performance.jsonl"
REST, LIGHT, HARD = [0.0] * 8, [0.5] * 4 + [0.0] * 4, [1.0] * 8


class FakeMidiOut:
    """A MIDI output backend that records what is sent."""

    def __init__(self, names: Sequence[str] = ("IAC Driver Bus 1",), fail: bool = False) -> None:
        self.names = list(names)
        self.fail = fail
        self.opened: str | int | None = None
        self.sent: list[bytes] = []
        self.closed = False

    def port_names(self) -> list[str]:
        return self.names

    def open(self, index: int) -> None:
        self.opened = index

    def open_virtual(self, name: str) -> None:
        if self.fail:
            raise RuntimeError("virtual ports are not supported here")
        self.opened = name

    def send(self, message: bytes) -> None:
        self.sent.append(message)

    def close(self) -> None:
        self.closed = True


class Collect:
    """A values sender that keeps every prediction."""

    def __init__(self) -> None:
        self.values: list[list[float]] = []
        self.closed = False

    def send(self, values: Sequence[float]) -> None:
        self.values.append(list(values))

    def close(self) -> None:
        self.closed = True


def preset() -> Preset:
    return available_presets()["pressure"]


# Registration


def test_registered_through_the_entry_point_group_only() -> None:
    entry = {e.name: e for e in entry_points(group=PRESET_GROUP)}["pressure"]
    assert entry.value == "mpc_iml.pressure:PRESET"
    found = preset()
    assert found.name == "pressure"
    assert found.targets == 8
    assert found.features is played_features
    assert found.model_factory is Regressor
    assert found.controls == {}
    osc, midi = found.outputs
    assert osc == OscOutput()
    assert midi == MidiCcOutput(controllers=tuple(range(20, 28)), channel=1, port_name="mpc-iml")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"targets": 0}, "at least 1"),
        ({"targets": 2, "classes": {"a": 1}}, "not both"),
        ({"targets": 2, "outputs": (MidiCcOutput(controllers=(1, 2, 3)),)}, "3 MIDI"),
    ],
)
def test_preset_targets_are_checked(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(PresetError, match=message):
        Preset(name="x", version="1", **kwargs)


# The front-end patch


def test_the_patch_is_inside_the_package() -> None:
    patch = preset().patch_path()
    assert patch is not None and patch.is_file()
    lines = [line.rstrip(";") for line in patch.read_text().splitlines()]
    assert lines[0].startswith("#N canvas")
    boxes = [line for line in lines[1:] if not line.startswith("#X connect")]
    for line in lines:
        if line.startswith("#X connect"):
            source, _, sink, _ = (int(n) for n in line.split()[2:])
            assert source < len(boxes) and sink < len(boxes)
    # It drives the engine with core messages only (ADR 0004) and shows the outputs.
    for box in [
        "netsend -u -b",
        "netreceive -u -b 6451",
        "netreceive -u -b 12000",
        "connect 127.0.0.1 6450",
        "oscformat mpciml hello",
        "oscformat mpciml preset load",
        "oscformat mpciml targets",
        "pack 0 0 0 0 0 0 0 0",
        "oscformat mpciml record start",
        "oscformat mpciml record stop",
        "oscformat mpciml train",
        "oscformat mpciml run",
        "oscformat mpciml stop",
        "unpack f f f f f f f f",
    ]:
        assert any(line.endswith(box) for line in boxes), box
    assert "mpciml preset pressure" not in patch.read_text()


# Training and playing on replays


def frame(velocity: int, pressure: int, held: bool = True) -> Frame:
    """Pad 1 only."""
    rest = (0,) * 15
    return Frame(
        0.0, (pressure, *rest), (velocity if held else 0, *rest), (held, *(False,) * 15), 0
    )


def trained_loop(outputs: Collect) -> IMLLoop:
    examples = preset().example_set()
    assert examples.add_recording(EXAMPLES) == 90
    loop = preset().build_loop(examples, outputs=outputs)
    loop.train()
    return loop


def test_training_and_playing_a_pressure_sweep() -> None:
    outputs = Collect()
    loop = trained_loop(outputs)
    assert loop.model is not None
    assert loop.model.predict(played_features(frame(110, 120))) == pytest.approx(HARD, abs=0.1)
    assert loop.model.predict(played_features(frame(40, 30))) == pytest.approx(LIGHT, abs=0.1)

    count = loop.run(ReplaySource(PERFORMANCE, realtime=False))
    assert count == len(outputs.values) == 161
    assert all(len(v) == 8 for v in outputs.values)
    rest, sweep_start, sweep_end, released = (
        outputs.values[10],
        outputs.values[52],
        outputs.values[110],
        outputs.values[150],
    )
    assert rest == pytest.approx(REST, abs=0.1)
    assert sum(sweep_end) > sum(sweep_start) + 1.0
    assert sum(sweep_start) > sum(rest) + 1.0
    # #43: rest right after playing is rest, exactly as before playing.
    assert released == rest


def test_rest_after_playing_differs_with_the_default_features() -> None:
    """Why the preset uses `played_features` (#43)."""
    hit_then_released = Frame(0.0, (0,) * 16, (110,) + (0,) * 15, (False,) * 16, 0)
    assert played_features(hit_then_released) == played_features(frame(0, 0, held=False))
    assert default_features(hit_then_released) != default_features(frame(0, 0, held=False))


def test_the_recorded_hold_fixture_plays_without_errors() -> None:
    outputs = Collect()
    loop = trained_loop(outputs)
    count = loop.run(ReplaySource(HOLD, realtime=False))
    assert count > 100 and len(outputs.values) == count
    assert all(len(v) == 8 for v in outputs.values)


# The MIDI CC sender


def test_midi_cc_sender_sends_changes_only_clamped() -> None:
    backend = FakeMidiOut()
    sender = MidiCcSender(preset().outputs[1], backend=lambda: backend)  # type: ignore[arg-type]
    sender.open()
    assert backend.opened == "mpc-iml" and sender.port_name == "mpc-iml"
    sender.send([0.0, 0.5, 1.0, 1.5, -0.2, 0.0, 0.0, 0.0])
    assert backend.sent == [
        bytes([0xB0, 20, 0]),
        bytes([0xB0, 21, 64]),
        bytes([0xB0, 22, 127]),
        bytes([0xB0, 23, 127]),
        bytes([0xB0, 24, 0]),
        bytes([0xB0, 25, 0]),
        bytes([0xB0, 26, 0]),
        bytes([0xB0, 27, 0]),
    ]
    backend.sent.clear()
    sender.send([0.001, 0.5, 1.0, 1.0, 0.0, 0.0, 0.0, 0.2])
    assert backend.sent == [bytes([0xB0, 27, 25])]
    with pytest.raises(ValueError, match="expected 8 values"):
        sender.send([0.0])
    sender.close()
    assert backend.closed
    with pytest.raises(RuntimeError, match="not open"):
        sender.send([0.0] * 8)


def test_midi_cc_sender_opens_an_existing_port() -> None:
    backend = FakeMidiOut(["Network", "IAC Driver Bus 1"])
    output = MidiCcOutput(controllers=(20,), channel=3)
    sender = MidiCcSender(output, "iac", backend=lambda: backend)
    sender.open()
    assert backend.opened == 1 and sender.port_name == "IAC Driver Bus 1"
    sender.send([1.0])
    assert backend.sent == [bytes([0xB2, 20, 127])]

    missing = FakeMidiOut(["Network"])
    with pytest.raises(PortNotFoundError, match="'Network'"):
        MidiCcSender(output, "IAC", backend=lambda: missing).open()
    assert missing.closed


def test_fan_out_sends_to_every_sender_and_closes_them() -> None:
    first, second = Collect(), Collect()
    fan = FanOut([first, second])
    fan.send([1.0, 2.0])
    fan.close()
    assert first.values == second.values == [[1.0, 2.0]]
    assert first.closed and second.closed


# The engine with the preset


@pytest.fixture
def engines(tmp_path: Path) -> Iterator[Any]:
    made: list[tuple[Engine, threading.Thread, list[Receiver]]] = []

    def _start(source: Any = None, backend: FakeMidiOut | None = None) -> tuple[Front, Receiver]:
        replies, outputs = Receiver(), Receiver()
        engine = Engine(
            tmp_path / "data",
            source,
            preset="pressure",
            control_port=0,
            reply_port=replies.port,
            outputs_port=outputs.port,
            midi_backend=lambda: backend or FakeMidiOut(),  # type: ignore[arg-type,return-value]
            log=lambda line: None,
        )
        engine.start()
        thread = threading.Thread(target=engine.serve_forever, daemon=True)
        thread.start()
        made.append((engine, thread, [replies, outputs]))
        return Front(engine, replies), outputs

    yield _start
    for engine, thread, receivers in made:
        engine.close()
        thread.join(TIMEOUT)
        for receiver in receivers:
            receiver.close()


def load_examples(front: Front) -> None:
    (front.engine.data_dir / "seed.jsonl").write_bytes(EXAMPLES.read_bytes())
    front.send("/mpciml/examples/load", "seed")
    assert front.expect("/mpciml/counts") == ["", 90]


def test_engine_trains_and_sends_osc_and_midi_while_running(engines: Any) -> None:
    backend = FakeMidiOut()
    front, outputs = engines(LoopingReplay(HOLD), backend)
    load_examples(front)
    front.send("/mpciml/train")
    front.expect("/mpciml/train/done")
    assert front.expect("/mpciml/state") == ["idle"]
    time.sleep(0.1)
    assert backend.opened == "mpc-iml" and backend.sent == []

    front.send("/mpciml/run")
    assert front.expect("/mpciml/state") == ["running"]
    address, values = outputs.receive()
    assert address == "/wek/outputs" and len(values) == 8
    deadline = time.monotonic() + TIMEOUT
    while len(backend.sent) < 8 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert {m[1] for m in backend.sent[:8]} == set(range(20, 28))
    assert all(m[0] == 0xB0 and 0 <= m[2] <= 127 for m in backend.sent)

    front.send("/mpciml/stop")
    assert front.expect("/mpciml/state") == ["idle"]
    sent = len(backend.sent)
    time.sleep(0.2)
    assert len(backend.sent) == sent

    front.send("/mpciml/preset/load", "demo")
    front.expect("/mpciml/preset")
    assert backend.closed


def test_engine_keeps_osc_when_the_midi_port_cannot_open(engines: Any) -> None:
    front, outputs = engines(LoopingReplay(HOLD), FakeMidiOut(fail=True))
    load_examples(front)
    front.send("/mpciml/train")
    front.expect("/mpciml/train/done")
    assert front.expect("/mpciml/state") == ["idle"]
    front.send("/mpciml/run")
    address, values = outputs.receive()
    assert address == "/wek/outputs" and len(values) == 8


def test_engine_checks_targets_against_the_preset(engines: Any) -> None:
    front, _ = engines()
    assert front.error("/mpciml/targets", 0.5, 0.5) == ("bad_arguments", "/mpciml/targets")
    assert front.error("/mpciml/class", "soft") == ("bad_arguments", "/mpciml/class")
    assert front.ask("/mpciml/targets", *HARD) == []

    (front.engine.data_dir / "two.jsonl").write_bytes((DATA / "regression.jsonl").read_bytes())
    assert front.error("/mpciml/examples/load", "two") == ("bad_arguments", "/mpciml/examples/load")


def test_engine_save_and_load_give_the_same_examples(engines: Any) -> None:
    """Also when the frame loop drops frames during a take (#73)."""
    source = SteppedReplay(HOLD)
    front, _ = engines(source)
    source.advance(180)
    for targets in (LIGHT, HARD):
        front.send("/mpciml/targets", *targets)
        record_steps(front, source)
    before = list(front.engine.examples.examples)
    assert len(before) == 2 * len(DROPS)
    assert len({e.features for e in before}) > 10

    assert front.ask("/mpciml/examples/save", "take") == []
    front.send("/mpciml/examples/clear")
    front.expect("/mpciml/counts")
    front.send("/mpciml/examples/load", "take")
    assert front.expect("/mpciml/counts") == ["", len(before)]
    assert front.engine.examples.examples == before

    saved = ExampleSet(features=played_features)
    saved.add_events(read_recording(front.engine.data_dir / "take.jsonl").events)
    assert saved.examples == before
