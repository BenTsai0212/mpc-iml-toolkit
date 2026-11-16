"""The built-in preset `pressure` and its MIDI CC output (#65).

Training and the outputs are checked on replayed recordings: the hand-written
`tests/data/pressure_*.jsonl` and the recorded `hold-pressure.jsonl` and
`two-pads.jsonl` fixtures, whose light holds retrigger on the hardware (#76).
MIDI goes to a fake backend, never to a real port.
"""

import textwrap
import threading
import time
from collections.abc import Iterator, Sequence
from dataclasses import replace
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
from test_fixtures import frame_at, load, midi, retriggers

from mpc_iml.engine import Engine
from mpc_iml.examples import (
    ExampleSet,
    FeatureFn,
    default_features,
    played_features,
    pressure_features,
)
from mpc_iml.frames import Frame, frames, note_to_bank_pad
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
    assert found.features is pressure_features
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
        "oscformat mpciml midi learn",
        "oscformat mpciml examples clear",
    ]:
        assert any(line.endswith(box) for line in boxes), box
    # Learn buttons l1-l8 send /mpciml/midi/learn 1-8 (ADR 0005).
    learn = next(i for i, b in enumerate(boxes) if b.endswith("oscformat mpciml midi learn"))
    edges = {
        tuple(int(n) for n in line.split()[2:]) for line in lines if line.startswith("#X connect")
    }
    sent = {boxes[s].split()[-1] for s, _, d, _ in edges if d == learn}
    assert sent == {str(n) for n in range(1, 9)}
    for n in range(1, 9):
        button = next(i for i, b in enumerate(boxes) if f" l{n} " in b and " bng " in b)
        message = next(d for s, _, d, _ in edges if s == button)
        assert boxes[message].startswith("#X msg") and boxes[message].endswith(f" {n}")
    assert "mpciml preset pressure" not in patch.read_text()
    # The clear button sends /mpciml/examples/clear (ADR 0004), with a comment.
    clear = next(i for i, b in enumerate(boxes) if " bng " in b and " clear " in b)
    sink = next(d for s, _, d, _ in edges if s == clear)
    assert boxes[sink].endswith("oscformat mpciml examples clear")
    assert any(b.startswith("#X text") and "clear deletes all examples" in b for b in boxes)
    # No two boxes, comments or GUI objects overlap (#82).
    rects = [(box, box_rect(box)) for box in boxes]
    for i, (a, ra) in enumerate(rects):
        for b, rb in rects[i + 1 :]:
            assert not overlap(ra, rb), (a, b)


FONT_WIDTH, FONT_HEIGHT, BOX_HEIGHT = 7, 16, 21
"""Pd's font metrics at the patch's font size 12, estimated."""

Rect = tuple[int, int, int, int]


def text_width(text: str) -> int:
    return len(text) * FONT_WIDTH


def box_rect(line: str) -> Rect:
    """An estimate of where a box is drawn: left, top, right, bottom."""
    words = line.replace("\\,", ",").split()
    kind, x, y, args = words[1], int(words[2]), int(words[3]), words[4:]
    if kind == "text":
        rows = textwrap.wrap(" ".join(args), 60)
        return x, y, x + max(map(text_width, rows)), y + FONT_HEIGHT * len(rows)
    if kind in ("symbolatom", "floatatom"):
        width, side, label = int(args[0]), args[3], args[4]
        right = x + text_width("0" * width) + 4
        if label == "-":
            return x, y, right, y + BOX_HEIGHT
        assert side == "0", "labels are drawn on the left"
        return x - text_width(label) - 4, y, right, y + BOX_HEIGHT
    if kind == "obj" and args[0] in ("bng", "hsl"):
        if args[0] == "bng":
            width = height = int(args[1])
            label, dx, dy = args[7], int(args[8]), int(args[9])
        else:
            width, height = int(args[1]), int(args[2])
            label, dx, dy = args[9], int(args[10]), int(args[11])
        label_left, label_right = x + dx, x + dx + text_width(label)
        label_top, label_bottom = y + dy - FONT_HEIGHT // 2, y + dy + FONT_HEIGHT // 2
        return (
            min(x, label_left),
            min(y, label_top),
            max(x + width, label_right),
            max(y + height, label_bottom),
        )
    return x, y, x + text_width(" ".join(args)) + 6, y + BOX_HEIGHT


def overlap(a: Rect, b: Rect) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


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
    assert loop.model.predict(pressure_features(frame(110, 120))) == pytest.approx(HARD, abs=0.1)
    assert loop.model.predict(pressure_features(frame(40, 30))) == pytest.approx(LIGHT, abs=0.1)

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


def test_pressure_features_are_pressure_only() -> None:
    assert len(pressure_features(frame(100, 0))) == 16
    assert pressure_features(frame(127, 127)) == [1.0] + [0.0] * 15
    # Velocity and the held flag do not reach the model.
    assert pressure_features(frame(100, 0)) == pressure_features(frame(0, 0, held=False))


def test_rest_after_playing_differs_with_the_default_features() -> None:
    """Why the preset does not use the default features (#43)."""
    hit_then_released = Frame(0.0, (0,) * 16, (110,) + (0,) * 15, (False,) * 16, 0)
    assert pressure_features(hit_then_released) == pressure_features(frame(0, 0, held=False))
    assert played_features(hit_then_released) == played_features(frame(0, 0, held=False))
    assert default_features(hit_then_released) != default_features(frame(0, 0, held=False))


def test_the_recorded_hold_fixture_plays_without_errors() -> None:
    outputs = Collect()
    loop = trained_loop(outputs)
    count = loop.run(ReplaySource(HOLD, realtime=False))
    assert count > 100 and len(outputs.values) == count
    assert all(len(v) == 8 for v in outputs.values)


# The light end on the recorded fixtures (#76)

LIGHT_HOLDS = ["hold-pressure", "two-pads"]
STEP = 3 / 127
"""The largest last pressure before a retrigger in the fixtures (1 or 3 of 127)."""
TOLERANCE = 0.08
"""How far an output may move while a light hold retriggers or a press starts.

A pressure step of `STEP` moves the outputs of the model trained on
`pressure_examples.jsonl` by about 0.06, as easing off by that much would.
"""


def put[T](values: tuple[T, ...], pad: int, value: T) -> tuple[T, ...]:
    return (*values[:pad], value, *values[pad + 1 :])


def with_pad(f: Frame, pad: int, like: Frame) -> Frame:
    """`f` with one pad's pressure, velocity and held flag taken from `like`."""
    return replace(
        f,
        pressure=put(f.pressure, pad, like.pressure[pad]),
        velocity=put(f.velocity, pad, like.velocity[pad]),
        held=put(f.held, pad, like.held[pad]),
    )


def windows(
    name: str,
) -> tuple[list[tuple[int, Frame, list[Frame]]], list[tuple[int, list[Frame]]]]:
    """The gaps and presses of a fixture, per pad.

    A gap runs from a retrigger's `note_off` until the first pressure after its new
    `note_on`, with the pad as it was just before the `note_off` as reference. A press runs
    from any `note_on` until its first pressure.
    """
    rec = load(name)
    fs = list(frames(rec.events))

    def first_pressure(start: int, pad: int) -> int:
        return next(i for i in range(start, len(fs)) if fs[i].pressure[pad] > 0)

    gaps = []
    for r in retriggers(rec.events):
        _, pad = note_to_bank_pad(r.note)
        off, on = frame_at(fs, r.off.t), frame_at(fs, r.on.t)
        # The last pressure before the `note_off` (1 or 3) can fall in the same frame
        # as the `note_off`, so the reference takes it from the MIDI.
        last = fs[off - 1]
        before = replace(last, pressure=put(last.pressure, pad, r.pressure_before))
        gaps.append((pad, before, fs[off : first_pressure(on, pad)]))
    presses = []
    for e in midi(rec.events):
        if e.kind == "note_on" and e.note is not None:
            _, pad = note_to_bank_pad(e.note)
            on = frame_at(fs, e.t)
            presses.append((pad, fs[on : first_pressure(on, pad)]))
    return gaps, presses


def released(f: Frame, pad: int) -> Frame:
    return with_pad(f, pad, Frame(f.t, (0,) * 16, (0,) * 16, (False,) * 16, f.bank))


def light_end_is_continuous(features: FeatureFn, name: str) -> bool:
    """Feature level: no drop in a light hold and no jump on a press.

    Each frame is compared with the same frame where only that pad is replaced:
    in a gap by the pad just before the `note_off` (at most `STEP` apart), on a
    press by the released pad (equal).
    """
    gaps, presses = windows(name)
    for pad, before, gap in gaps:
        for f in gap:
            steady = features(with_pad(f, pad, before))
            if max(abs(a - b) for a, b in zip(features(f), steady, strict=True)) > STEP + 1e-9:
                return False
    return all(features(f) == features(released(f, pad)) for pad, press in presses for f in press)


def outputs_are_continuous(loop: IMLLoop, features: FeatureFn, name: str) -> bool:
    """Model level: the same comparison on the model outputs, within `TOLERANCE`."""
    assert loop.model is not None
    model = loop.model

    def apart(f: Frame, other: Frame) -> float:
        a, b = model.predict(features(f)), model.predict(features(other))
        return max(abs(x - y) for x, y in zip(a, b, strict=True))

    gaps, presses = windows(name)
    return all(
        apart(f, with_pad(f, pad, before)) <= TOLERANCE for pad, before, gap in gaps for f in gap
    ) and all(apart(f, released(f, pad)) <= TOLERANCE for pad, press in presses for f in press)


@pytest.mark.parametrize("name", LIGHT_HOLDS)
def test_fixtures_have_light_holds_that_retrigger(name: str) -> None:
    gaps, presses = windows(name)
    assert len(gaps) == {"hold-pressure": 3, "two-pads": 21}[name]
    assert all(len(gap) >= 5 for _, _, gap in gaps)
    assert len(presses) > len(gaps)
    assert all(len(press) >= 5 for _, press in presses)


@pytest.mark.parametrize("name", LIGHT_HOLDS)
def test_pressure_features_stay_continuous_at_the_light_end(name: str) -> None:
    assert light_end_is_continuous(pressure_features, name)
    # The same check catches the old behaviour (#76): velocity and held jump.
    assert not light_end_is_continuous(played_features, name)


def test_preset_outputs_stay_continuous_at_the_light_end() -> None:
    loop = trained_loop(Collect())
    for name in LIGHT_HOLDS:
        assert outputs_are_continuous(loop, pressure_features, name), name


def test_played_features_outputs_jump_at_the_light_end() -> None:
    """The model-level check detects the old behaviour (#76)."""
    examples = ExampleSet(features=played_features)
    assert examples.add_recording(EXAMPLES) == 90
    loop = IMLLoop(Regressor, examples)
    loop.train()
    # In `hold-pressure` the retrigger velocities (1-21) are low, so the jumps are
    # small there; in `two-pads` they move the outputs by more than 0.4.
    assert not outputs_are_continuous(loop, played_features, "two-pads")


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


def test_midi_cc_sender_sends_one_controller() -> None:
    backend = FakeMidiOut()
    output = MidiCcOutput(controllers=(20, 21), channel=2)
    sender = MidiCcSender(output, backend=lambda: backend)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="not open"):
        sender.send_controller(0, 1)
    sender.open()
    assert sender.last_value(1) is None
    sender.send_controller(1, 64)
    sender.send_controller(1, 64)
    assert backend.sent == [bytes([0xB1, 21, 64])] * 2
    assert sender.last_value(1) == 64
    with pytest.raises(ValueError, match="0-127"):
        sender.send_controller(1, 128)
    backend.sent.clear()
    sender.send([0.0, 64 / 127])
    assert backend.sent == [bytes([0xB1, 20, 0])]


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

    saved = ExampleSet(features=pressure_features)
    saved.add_events(read_recording(front.engine.data_dir / "take.jsonl").events)
    assert saved.examples == before


# MIDI learn (#78, ADR 0005)

UP = [0, 32, 64, 96, 127]


def test_midi_learn_sends_only_the_chosen_controller(engines: Any) -> None:
    backend = FakeMidiOut()
    front, _ = engines(LoopingReplay(HOLD), backend)
    assert front.ask("/mpciml/midi/learn", 3) == [("/mpciml/midi/sent", [3, 22])]
    assert backend.sent == [bytes([0xB0, 22, v]) for v in UP]

    backend.sent.clear()
    assert front.ask("/mpciml/midi/learn", 3.0) == [("/mpciml/midi/sent", [3, 22])]
    assert backend.sent == [bytes([0xB0, 22, v]) for v in reversed(UP)]

    backend.sent.clear()
    for output in range(1, 9):
        front.ask("/mpciml/midi/learn", output)
    assert [m[1] for m in backend.sent] == [c for c in range(20, 28) for _ in UP]
    assert backend.sent[:5] == [bytes([0xB0, 20, v]) for v in UP]
    assert backend.sent[10:15] == [bytes([0xB0, 22, v]) for v in UP]


@pytest.mark.parametrize("args", [[0], [9], [], [1, 2], ["one"], [1.5]])
def test_midi_learn_rejects_bad_arguments(engines: Any, args: list[Any]) -> None:
    backend = FakeMidiOut()
    front, _ = engines(None, backend)
    assert front.error("/mpciml/midi/learn", *args) == ("bad_arguments", "/mpciml/midi/learn")
    assert backend.sent == []


def learn_error(front: Front) -> list[Any]:
    errors = [m[1] for m in front.ask("/mpciml/midi/learn", 1) if m[0] == "/mpciml/error"]
    assert len(errors) == 1
    return list(errors[0])


def test_midi_learn_without_a_midi_output(engines: Any) -> None:
    front, _ = engines(None, FakeMidiOut(fail=True))
    assert learn_error(front) == ["bad_arguments", "/mpciml/midi/learn", "MIDI output not open"]

    front.send("/mpciml/preset/load", "demo")
    front.expect("/mpciml/counts")
    code, address, message = learn_error(front)
    assert (code, address) == ("bad_arguments", "/mpciml/midi/learn")
    assert "no MIDI output" in message


def test_midi_learn_is_refused_while_running_and_run_still_sends(engines: Any) -> None:
    backend = FakeMidiOut()
    front, _ = engines(LoopingReplay(HOLD), backend)
    load_examples(front)
    front.send("/mpciml/train")
    front.expect("/mpciml/train/done")
    assert front.expect("/mpciml/state") == ["idle"]
    for output in range(1, 9):
        front.ask("/mpciml/midi/learn", output)
    assert len(backend.sent) == 40

    front.send("/mpciml/run")
    assert front.expect("/mpciml/state") == ["running"]
    assert front.error("/mpciml/midi/learn", 1) == ("wrong_state", "/mpciml/midi/learn")
    deadline = time.monotonic() + TIMEOUT
    while len(backend.sent) == 40 and time.monotonic() < deadline:
        time.sleep(0.01)
    played = backend.sent[40:]
    assert played and all(m[0] == 0xB0 and 20 <= m[1] <= 27 for m in played)
    front.send("/mpciml/stop")
    assert front.expect("/mpciml/state") == ["idle"]
