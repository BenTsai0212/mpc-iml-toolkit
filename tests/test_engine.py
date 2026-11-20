"""The engine and its control protocol (ADR 0004, #64).

Each test starts an engine on free ports, sends OSC control messages and checks the
replies on a reply socket. Gestures come from the recorded MPC fixtures replayed in
real time (`LoopingReplay`), never from the MPC. Tests that compare recorded and
saved examples use `SteppedReplay` instead: the test moves its clock, so which frames
are recorded and which are dropped does not depend on machine load (#73).
"""

import dataclasses
import shutil
import socket
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from pythonosc.osc_message import OscMessage
from pythonosc.udp_client import SimpleUDPClient

from mpc_iml import __version__
from mpc_iml.demo import PRESET as DEMO
from mpc_iml.engine import ALLOWED, Engine, _transition, build_parser
from mpc_iml.events import Event
from mpc_iml.examples import labelled_frames
from mpc_iml.frames import DEFAULT_RATE, PADS, Frame, PadState
from mpc_iml.presets import Preset, PresetError, available_presets
from mpc_iml.recording import read_recording
from mpc_iml.sklearn_backend import Classifier, Regressor

TESTS = Path(__file__).parent
FIXTURES = TESTS / "fixtures" / "recordings"
HOLD = FIXTURES / "hold-pressure.jsonl"
SEED = FIXTURES / "examples.jsonl"
"""A `demo record` fixture: rest, soft and hard segments."""
PLUGINS = TESTS / "plugins"
TIMEOUT = 10.0
Message = tuple[str, list[Any]]


class LoopingReplay:
    """A fixture replayed in real time, over and over: stands in for the MPC."""

    realtime = True

    def __init__(self, path: Path, gap: float = 0.2) -> None:
        self._events = read_recording(path).events
        self._length = self._events[-1].t + gap
        self._start = 0.0
        self._next = 0

    def start(self) -> None:
        self._start = time.monotonic()

    def now(self) -> float:
        return time.monotonic() - self._start

    def poll(self) -> Event | None:
        lap, index = divmod(self._next, len(self._events))
        event = self._events[index]
        t = event.t + lap * self._length
        if t > self.now():
            return None
        self._next += 1
        return dataclasses.replace(event, t=t)

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def done(self) -> bool:
        return False


class SteppedReplay(LoopingReplay):
    """`LoopingReplay` on a clock that only the test moves, one `advance` at a time.

    The engine's frame loop yields one frame per `advance`, the latest one due, and
    drops the frames skipped in between, as when the machine is busy (#39).
    `advance` returns once that frame has been handled.
    """

    def __init__(self, path: Path, rate: float = DEFAULT_RATE) -> None:
        super().__init__(path)
        self.rate = rate
        self._k = 0
        self._seen = 0
        self._waiting_at: int | None = None
        self._changed = threading.Condition()

    def start(self) -> None:
        pass

    def now(self) -> float:
        with self._changed:
            self._seen = self._k
            return self._k / self.rate

    def sleep(self, seconds: float) -> None:
        with self._changed:
            if self._seen != self._k:
                return
            self._waiting_at = self._k
            self._changed.notify_all()
            self._changed.wait(0.05)

    def advance(self, frames: int = 1) -> None:
        """Move the clock by `frames` frame intervals; wait until the loop catches up."""
        with self._changed:
            self._k += frames
            target = self._k
            self._changed.notify_all()
            assert self._changed.wait_for(lambda: self._waiting_at == target, TIMEOUT)


DROPS = (1, 3, 1, 1, 5, 2, 1, 4, 1, 1) * 3
"""Clock steps for a take: a step of `n` frames drops `n - 1` of them."""


class Receiver:
    """A UDP socket that collects OSC messages."""

    def __init__(self) -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port: int = self.sock.getsockname()[1]

    def receive(self, timeout: float = TIMEOUT) -> Message:
        self.sock.settimeout(timeout)
        message = OscMessage(self.sock.recv(65536))
        return message.address, list(message.params)

    def until(self, address: str, timeout: float = TIMEOUT) -> list[Message]:
        """Every message up to and including the first one at `address`."""
        seen: list[Message] = []
        deadline = time.monotonic() + timeout
        while not seen or seen[-1][0] != address:
            seen.append(self.receive(max(deadline - time.monotonic(), 0.01)))
        return seen

    def close(self) -> None:
        self.sock.close()


class Front:
    """A front end: sends control messages, reads replies."""

    def __init__(self, engine: Engine, replies: Receiver) -> None:
        self.engine = engine
        self.replies = replies
        self.client = SimpleUDPClient("127.0.0.1", engine.control_port)

    def send(self, address: str, *args: Any) -> None:
        self.client.send_message(address, list(args))

    def ask(self, address: str, *args: Any) -> list[Message]:
        """Send a message, then `ping`; return the replies before the `pong`."""
        self.send(address, *args)
        self.send("/mpciml/ping")
        return self.replies.until("/mpciml/pong")[:-1]

    def expect(self, address: str, timeout: float = TIMEOUT) -> list[Any]:
        return self.replies.until(address, timeout)[-1][1]

    def error(self, address: str, *args: Any) -> tuple[str, str]:
        """Send a message that must fail; return its error code and the address."""
        replies = self.ask(address, *args)
        errors = [m for m in replies if m[0] == "/mpciml/error"]
        assert len(errors) == 1, replies
        code, received, _ = errors[0][1]
        return code, received

    def state(self) -> str:
        """The state from `state/get`; earlier replies are read and dropped."""
        replies = self.ask("/mpciml/state/get")
        return str([m for m in replies if m[0] == "/mpciml/state"][-1][1][0])


@pytest.fixture
def receivers() -> Iterator[list[Receiver]]:
    made: list[Receiver] = []
    yield made
    for receiver in made:
        receiver.close()


@pytest.fixture
def start(tmp_path: Path, receivers: list[Receiver]) -> Iterator[Any]:
    """Start an engine on free ports; returns a `Front` connected to it."""
    engines: list[tuple[Engine, threading.Thread]] = []

    def _start(source: Any = None, **kwargs: Any) -> Front:
        replies = Receiver()
        receivers.append(replies)
        engine = Engine(
            tmp_path / "data", source, control_port=0, reply_port=replies.port, **kwargs
        )
        engine.start()
        thread = threading.Thread(target=engine.serve_forever, daemon=True)
        thread.start()
        engines.append((engine, thread))
        return Front(engine, replies)

    yield _start
    for engine, thread in engines:
        engine.close()
        thread.join(TIMEOUT)


class Gate:
    """A classifier whose training waits until the gate is open."""

    opened = threading.Event()

    def __init__(self) -> None:
        self._model = Classifier()

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        assert Gate.opened.wait(TIMEOUT)
        self._model.fit(inputs, outputs)

    def predict(self, values: Sequence[float]) -> list[float]:
        return self._model.predict(values)


GATED = dataclasses.replace(DEMO, name="gated", model_factory=Gate)
REGRESSION = Preset(name="reg", version="2.0", model_factory=Regressor)


def presets(*extra: Preset) -> Mapping[str, Preset]:
    found = {"demo": DEMO, "gated": GATED, "reg": REGRESSION}
    found.update({p.name: p for p in extra})
    return found


@pytest.fixture(autouse=True)
def _open_gate() -> Iterator[None]:
    Gate.opened.set()
    yield
    Gate.opened.set()


def seed(front: Front) -> None:
    """Save the demo fixture in the data folder and load it as the example set."""
    shutil.copy(SEED, front.engine.data_dir / "seed.jsonl")
    front.send("/mpciml/examples/load", "seed")
    front.expect("/mpciml/counts")


def trained(front: Front) -> None:
    seed(front)
    front.send("/mpciml/train")
    front.expect("/mpciml/train/done")
    assert front.expect("/mpciml/state") == ["idle"]


def record(front: Front, seconds: float = 0.3) -> list[Any]:
    front.send("/mpciml/record/start")
    assert front.expect("/mpciml/state") == ["recording"]
    time.sleep(seconds)
    front.send("/mpciml/record/stop")
    return front.expect("/mpciml/counts")


def record_steps(front: Front, source: SteppedReplay, steps: Sequence[int] = DROPS) -> list[Any]:
    """Record one take while moving the clock by `steps`; one frame is kept per step."""
    front.send("/mpciml/record/start")
    assert front.expect("/mpciml/state") == ["recording"]
    for frames in steps:
        source.advance(frames)
    front.send("/mpciml/record/stop")
    return front.expect("/mpciml/counts")


# Handshake, ping and state


def test_hello_sends_version_then_full_state(start: Any) -> None:
    front = start()
    front.send("/mpciml/hello", 1)
    replies = front.replies.until("/mpciml/clock")
    assert replies == [
        ("/mpciml/version", [1, 5, __version__]),
        ("/mpciml/state", ["idle"]),
        ("/mpciml/preset", ["demo", DEMO.version]),
        ("/mpciml/layout", [0, 0]),
        ("/mpciml/names", []),
        ("/mpciml/kit", [""]),
        ("/mpciml/pads", ["", 1.0] * PADS),
        ("/mpciml/counts", ["rest", 0, "soft", 0, "hard", 0]),
        ("/mpciml/trained", [0]),
        ("/mpciml/clock", ["off", 0.0, 0, 0]),
    ]


def test_hello_changes_the_reply_port(start: Any, receivers: list[Receiver]) -> None:
    front = start()
    other = Receiver()
    receivers.append(other)
    front.send("/mpciml/hello", 1, other.port)
    assert other.until("/mpciml/version")[-1][1][0] == 1
    front.replies = other
    assert front.ask("/mpciml/state/get")[0] == ("/mpciml/state", ["idle"])


def test_hello_accepts_whole_number_floats(start: Any, receivers: list[Receiver]) -> None:
    front = start()
    other = Receiver()
    receivers.append(other)
    front.send("/mpciml/hello", 1.0, float(other.port))
    replies = other.until("/mpciml/clock")
    assert replies[0] == ("/mpciml/version", [1, 5, __version__])
    front.replies = other
    assert front.ask("/mpciml/state/get")[0] == ("/mpciml/state", ["idle"])


def test_hello_with_another_major_reports_mismatch_and_keeps_working(start: Any) -> None:
    front = start()
    front.send("/mpciml/hello", 2)
    replies = front.replies.until("/mpciml/clock")
    assert replies[0][0] == "/mpciml/error"
    assert replies[0][1][:2] == ["version_mismatch", "/mpciml/hello"]
    assert replies[1] == ("/mpciml/version", [1, 5, __version__])
    assert front.ask("/mpciml/state/get")[0] == ("/mpciml/state", ["idle"])


def test_ping_and_state_get(start: Any) -> None:
    front = start()
    front.send("/mpciml/ping")
    assert front.replies.receive() == ("/mpciml/pong", [])
    assert [m[0] for m in front.ask("/mpciml/state/get")] == [
        "/mpciml/state",
        "/mpciml/preset",
        "/mpciml/layout",
        "/mpciml/names",
        "/mpciml/kit",
        "/mpciml/pads",
        "/mpciml/counts",
        "/mpciml/trained",
        "/mpciml/clock",
    ]


# Errors


@pytest.mark.parametrize("address", ["/mpciml/nope", "/mpciml/record", "/wek/inputs"])
def test_unknown_message(start: Any, address: str) -> None:
    assert start().error(address) == ("unknown_message", address)


@pytest.mark.parametrize(
    ("address", "args"),
    [
        ("/mpciml/ping", [1]),
        ("/mpciml/hello", []),
        ("/mpciml/hello", ["1"]),
        ("/mpciml/hello", [1.5]),
        ("/mpciml/hello", [1, 6451.5]),
        ("/mpciml/hello", [1, 70000]),
        ("/mpciml/class", []),
        ("/mpciml/class", [3]),
        ("/mpciml/targets", []),
        ("/mpciml/targets", ["a"]),
        ("/mpciml/examples/save", ["../outside"]),
        ("/mpciml/examples/save", ["a b"]),
        ("/mpciml/examples/save", []),
        ("/mpciml/examples/load", ["/etc/passwd"]),
        ("/mpciml/examples/delete", [1]),
        ("/mpciml/preset/load", ["a/b"]),
        ("/mpciml/record/start", []),
    ],
)
def test_bad_arguments(start: Any, tmp_path: Path, address: str, args: list[Any]) -> None:
    front = start()
    assert front.error(address, *args) == ("bad_arguments", address)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["data"]
    assert list((tmp_path / "data").iterdir()) == []


def test_not_found(start: Any) -> None:
    front = start()
    assert front.error("/mpciml/examples/load", "missing")[0] == "not_found"
    assert front.error("/mpciml/preset/load", "missing")[0] == "not_found"


# Recording, training and running on recorded fixtures


def test_record_train_run_stop(start: Any, receivers: list[Receiver]) -> None:
    inputs, outputs = Receiver(), Receiver()
    receivers += [inputs, outputs]
    front = start(LoopingReplay(HOLD), inputs_port=inputs.port, outputs_port=outputs.port)
    assert front.ask("/mpciml/class", "soft") == []
    counts = record(front)
    assert counts[:2] == ["rest", 0] and counts[2] == "soft" and counts[3] > 10

    front.send("/mpciml/train")
    assert front.expect("/mpciml/state") == ["training"]
    assert front.expect("/mpciml/train/done")[0] >= 0
    assert front.expect("/mpciml/trained") == [1]
    assert front.expect("/mpciml/state") == ["idle"]

    front.send("/mpciml/run")
    assert front.expect("/mpciml/state") == ["running"]
    address, values = inputs.receive()
    assert address == "/wek/inputs" and len(values) == 32
    assert outputs.receive() == ("/wek/outputs", [2.0])

    front.send("/mpciml/stop")
    assert front.expect("/mpciml/state") == ["idle"]


def test_stop_while_recording_discards_the_example(start: Any) -> None:
    front = start(LoopingReplay(HOLD))
    front.send("/mpciml/class", "soft")
    front.send("/mpciml/record/start")
    assert front.expect("/mpciml/state") == ["recording"]
    time.sleep(0.2)
    assert front.ask("/mpciml/stop") == [("/mpciml/state", ["idle"])]
    front.send("/mpciml/state/get")
    assert front.expect("/mpciml/counts") == ["rest", 0, "soft", 0, "hard", 0]


def test_stop_in_idle_does_nothing(start: Any) -> None:
    assert start().ask("/mpciml/stop") == []


def test_regression_targets(start: Any) -> None:
    front = start(LoopingReplay(HOLD), preset="reg", presets=presets)
    front.send("/mpciml/targets", 0.25, 1)
    assert record(front, 0.2)[0] == ""
    assert front.error("/mpciml/targets", 0.5)[0] == "bad_arguments"
    assert front.error("/mpciml/class", "soft")[0] == "bad_arguments"
    front.send("/mpciml/train")
    front.expect("/mpciml/train/done")
    assert front.engine.examples.examples[0].targets == (0.25, 1.0)


def test_train_without_examples_fails_and_keeps_the_model(start: Any) -> None:
    front = start()
    replies = front.ask("/mpciml/train")
    assert [m[0] for m in replies] == ["/mpciml/train/failed"]
    assert front.state() == "idle"
    assert front.error("/mpciml/run") == ("wrong_state", "/mpciml/run")


def test_retrain_while_running(start: Any) -> None:
    front = start(preset="gated", presets=presets)
    trained(front)
    front.send("/mpciml/run")
    front.expect("/mpciml/state")
    Gate.opened.clear()
    assert front.ask("/mpciml/train") == []
    assert front.error("/mpciml/train") == ("wrong_state", "/mpciml/train")
    Gate.opened.set()
    assert front.expect("/mpciml/train/done")[0] >= 0
    assert front.state() == "running"


# Example sets


def test_delete_clear_save_list_load(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source)
    source.advance(180)
    front.send("/mpciml/class", "hard")
    record_steps(front, source)
    front.send("/mpciml/class", "soft")
    counts = record_steps(front, source, (2,) * 33)
    assert counts == ["rest", 0, "soft", 33, "hard", len(DROPS)]
    before = list(front.engine.examples.examples)

    assert front.ask("/mpciml/examples/save", "take-1") == []
    front.send("/mpciml/examples/list")
    assert front.expect("/mpciml/examples/names") == ["take-1"]

    front.send("/mpciml/examples/delete", "hard")
    assert front.expect("/mpciml/counts") == ["rest", 0, "soft", counts[3], "hard", 0]
    front.send("/mpciml/examples/clear")
    assert front.expect("/mpciml/counts") == ["rest", 0, "soft", 0, "hard", 0]

    front.send("/mpciml/examples/load", "take-1")
    assert front.expect("/mpciml/counts") == counts
    assert front.engine.examples.examples == before

    front.send("/mpciml/examples/delete", "hard")
    front.expect("/mpciml/counts")
    front.send("/mpciml/examples/save", "take-1")
    front.send("/mpciml/examples/load", "take-1")
    assert front.expect("/mpciml/counts") == ["rest", 0, "soft", counts[3], "hard", 0]


def test_save_and_load_give_the_recorded_examples_when_frames_are_dropped(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source)
    source.advance(180)
    for label in ("soft", "hard", "soft"):
        front.send("/mpciml/class", label)
        record_steps(front, source)
    before = list(front.engine.examples.examples)
    assert len(before) == 3 * len(DROPS) < 3 * sum(DROPS)
    assert len({e.features for e in before}) > 10

    assert front.ask("/mpciml/examples/save", "dropped") == []
    front.send("/mpciml/examples/clear")
    front.expect("/mpciml/counts")
    front.send("/mpciml/examples/load", "dropped")
    assert front.expect("/mpciml/counts") == ["rest", 0, "soft", 60, "hard", 30]
    assert front.engine.examples.examples == before

    saved = DEMO.example_set()
    saved.add_recording(front.engine.data_dir / "dropped.jsonl")
    assert saved.examples == before


def _frame(bank: int, pressure: dict[int, int], velocity: dict[int, int], held: set[int]) -> Frame:
    return Frame(
        t=0.0,
        pressure=tuple(pressure.get(p, 0) for p in range(PADS)),
        velocity=tuple(velocity.get(p, 0) for p in range(PADS)),
        held=tuple(p in held for p in range(PADS)),
        bank=bank,
    )


def test_transition_events_replay_to_every_frame() -> None:
    """Frames a real-time loop could give with frames dropped in between (#73)."""
    wanted = [
        _frame(0, {}, {}, set()),
        _frame(0, {3: 40}, {3: 90}, {3}),
        _frame(2, {3: 40, 5: 7}, {3: 90, 5: 20}, {3, 5}),
        _frame(2, {5: 9}, {3: 90, 5: 20}, {5}),
        _frame(4, {}, {3: 90, 5: 20}, set()),
        _frame(4, {}, {3: 64, 5: 20}, {3}),
        _frame(1, {}, {3: 64, 5: 20}, set()),
        _frame(1, {2: 5}, {3: 64, 5: 20}, set()),
    ]
    state, events = PadState(), []
    for k, frame in enumerate(wanted):
        events += _transition(state, frame, k / DEFAULT_RATE)
    replayed = [f for f, _ in labelled_frames(events)][: len(wanted)]
    assert [dataclasses.replace(f, t=0.0) for f in replayed] == wanted


def test_load_a_demo_recording(start: Any) -> None:
    front = start()
    seed(front)
    examples = DEMO.example_set()
    examples.add_recording(SEED)
    assert front.engine.examples.examples == examples.examples


# States


def enter(front: Front, state: str) -> None:
    """Bring a fresh engine with the `gated` preset into `state`."""
    if state == "recording":
        front.send("/mpciml/class", "soft")
        front.send("/mpciml/record/start")
    elif state == "training":
        seed(front)
        Gate.opened.clear()
        front.send("/mpciml/train")
    else:
        trained(front)
        if state == "running":
            front.send("/mpciml/run")
    assert front.state() == state


ARGS: dict[str, list[Any]] = {
    "hello": [1],
    "class": ["soft"],
    "targets": [0.5],
    "examples/delete": ["soft"],
    "examples/save": ["kept"],
    "examples/load": ["seed"],
    "preset/load": ["gated"],
    "midi/learn": [1],
    "kit/load": ["filter-play"],
    "pad/module": [1, "bite"],
    "clock/test": [0],
}

TABLE = {
    "hello": "✓✓✓✓",
    "ping": "✓✓✓✓",
    "state/get": "✓✓✓✓",
    "examples/list": "✓✓✓✓",
    "preset/list": "✓✓✓✓",
    "record/start": "✓✗✗✗",
    "record/stop": "✗✓✗✗",
    "class": "✓✗✓✓",
    "targets": "✓✗✓✓",
    "examples/delete": "✓✗✗✓",
    "examples/clear": "✓✗✗✓",
    "examples/load": "✓✗✗✓",
    "examples/save": "✓✗✓✓",
    "train": "✓✗✗✓",
    "run": "✓✗✗✗",
    "stop": "✓✓✗✓",
    "preset/load": "✓✗✗✗",
    "midi/learn": "✓✗✓✗",
    "kit/list": "✓✓✓✓",
    "module/list": "✓✓✓✓",
    "kit/load": "✓✗✗✓",
    "pad/module": "✓✗✗✓",
    "pad/select/start": "✓✗✓✓",
    "pad/select/stop": "✓✗✓✓",
    "clock/test": "✓✓✓✓",
}
"""ADR 0004's state table with ADR 0005's `midi/learn`, ADR 0007's kit messages and
ADR 0008's `clock/test`;
columns idle, recording, training, running. `test_engine_kits.py` checks the kit
messages again with a preset that has kits."""

STATES = ("idle", "recording", "training", "running")


def test_the_table_matches_the_engine() -> None:
    assert {m: {s for s, c in zip(STATES, row, strict=True) if c == "✓"} for m, row in
            TABLE.items()} == {m: set(s) for m, s in ALLOWED.items()}  # fmt: skip


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("message", sorted(TABLE))
def test_state_table(start: Any, state: str, message: str) -> None:
    front = start(preset="gated", presets=presets)
    enter(front, state)
    address = f"/mpciml/{message}"
    replies = front.ask(address, *ARGS.get(message, []))
    errors = [m[1] for m in replies if m[0] == "/mpciml/error"]
    if TABLE[message][STATES.index(state)] == "✗":
        assert [e[:2] for e in errors] == [["wrong_state", address]]
        assert state in errors[0][2]
        assert front.state() == state
    else:
        assert not [e for e in errors if e[0] == "wrong_state"], errors
    Gate.opened.set()


# Presets


def test_preset_list_and_load_through_the_plugin_interface(
    start: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.syspath_prepend(str(PLUGINS))
    front = start()
    trained(front)
    front.send("/mpciml/preset/list")
    assert front.expect("/mpciml/presets") == sorted(available_presets())
    assert "example-pressure" in available_presets()

    front.send("/mpciml/preset/load", "demo")
    assert front.expect("/mpciml/preset") == ["demo", DEMO.version]
    assert front.expect("/mpciml/layout") == [0, 0]
    assert front.expect("/mpciml/counts")[3] > 0

    front.send("/mpciml/preset/load", "example-pressure")
    assert front.expect("/mpciml/preset") == ["example-pressure", "0.1.0"]
    # No declared targets, so 0; two MIDI controllers (ADR 0006).
    assert front.expect("/mpciml/layout") == [0, 2]
    assert front.expect("/mpciml/counts") == []
    assert front.expect("/mpciml/trained") == [0]


def test_layout_reports_declared_targets_and_midi_controllers(start: Any) -> None:
    three = Preset(name="three", version="1", model_factory=Regressor, targets=3)
    front = start(presets=lambda: presets(three))
    replies = front.ask("/mpciml/preset/load", "three")
    assert [m for m in replies if m[0] == "/mpciml/layout"] == [("/mpciml/layout", [3, 0])]
    assert replies.index(("/mpciml/layout", [3, 0])) == 1
    replies = front.ask("/mpciml/preset/load", "three")
    assert ("/mpciml/layout", [3, 0]) in replies


def test_preset_controls_go_to_the_active_preset_only(start: Any) -> None:
    received: list[Sequence[Any]] = []

    def gain(args: Sequence[Any]) -> None:
        if not args:
            raise ValueError("gain needs a value")
        received.append(args)

    knobs = Preset(name="knobs", version="1", controls={"gain": gain})
    front = start(preset="knobs", presets=lambda: presets(knobs))
    assert front.ask("/mpciml/preset/knobs/gain", 0.5) == []
    assert received == [[0.5]]
    assert front.error("/mpciml/preset/knobs/gain")[0] == "bad_arguments"
    assert front.error("/mpciml/preset/knobs/nope")[0] == "unknown_message"
    assert front.error("/mpciml/preset/demo/gain", 1)[0] == "inactive_preset"
    assert front.error("/mpciml/preset/other/gain", 1)[0] == "inactive_preset"
    assert front.error("/mpciml/preset/list/x")[0] == "unknown_message"


# Start and shutdown


def test_unknown_start_preset() -> None:
    with pytest.raises(PresetError):
        Engine("unused", preset="missing")


def test_parser_defaults() -> None:
    args = build_parser().parse_args(["data"])
    assert (args.control_port, args.reply_port, args.preset) == (6450, 6451, "demo")


def test_close_while_training_writes_only_saved_sets(start: Any, tmp_path: Path) -> None:
    front = start(LoopingReplay(HOLD), preset="gated", presets=presets)
    front.send("/mpciml/class", "soft")
    record(front, 0.1)
    front.send("/mpciml/examples/save", "mine")
    Gate.opened.clear()
    front.send("/mpciml/train")
    front.expect("/mpciml/state")
    threading.Timer(0.2, Gate.opened.set).start()
    front.engine.close()
    assert sorted(p.name for p in tmp_path.rglob("*")) == ["data", "mine.jsonl"]
