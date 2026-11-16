"""The IML loop: run mode over OSC, backend switched off, and retraining in place.

All tests use synthetic events or recordings and OSC servers on ephemeral ports on
127.0.0.1; no hardware.
"""

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from mpc_iml.events import Event, ExampleEnd, ExampleStart, MidiEvent
from mpc_iml.examples import ExampleError, ExampleSet
from mpc_iml.frames import OSC_INPUT_COUNT, frames
from mpc_iml.loop import BackendOffError, IMLLoop
from mpc_iml.osc import INPUTS_ADDRESS, OUTPUTS_ADDRESS, OscSender
from mpc_iml.recording import read_recording
from mpc_iml.sklearn_backend import Classifier, Regressor

DATA = Path(__file__).parent / "data"
LOCALHOST = "127.0.0.1"


class Receiver:
    """An OSC server on an ephemeral port that collects every message it receives."""

    def __init__(self) -> None:
        self.received: list[tuple[str, tuple[object, ...]]] = []
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(lambda address, *args: self.received.append((address, args)))
        self._server = BlockingOSCUDPServer((LOCALHOST, 0), dispatcher)
        self._server.timeout = 0.3
        self.port: int = self._server.server_address[1]

    def drain(self) -> list[tuple[str, tuple[object, ...]]]:
        """Handle messages until none arrives within the timeout; return all so far."""
        while True:
            before = len(self.received)
            self._server.handle_request()
            if len(self.received) == before:
                return self.received

    def close(self) -> None:
        self._server.server_close()


@pytest.fixture
def receivers() -> Iterator[tuple[Receiver, Receiver]]:
    pair = (Receiver(), Receiver())
    yield pair
    for receiver in pair:
        receiver.close()


def gesture(note: int, t: float = 0.0, label: str | None = None) -> list[Event]:
    """A firm press and release of one pad, optionally marked as an example."""
    press: list[Event] = [
        MidiEvent(t, "note_on", 1, 100, note=note),
        MidiEvent(t, "poly_pressure", 1, 100, note=note),
    ]
    if label is not None:
        press = [ExampleStart(t, label=label), *press, ExampleEnd(t + 0.04)]
    return [*press, MidiEvent(t + 0.05, "note_off", 1, 0, note=note)]


def held_predictions(loop: IMLLoop, events: Sequence[Event]) -> set[float]:
    """Class numbers predicted for the frames in which a pad is held."""
    predictions = set()
    for frame in frames(events):
        prediction = loop.step(frame)
        if any(frame.held):
            assert prediction is not None
            predictions.add(prediction[0])
    return predictions


class StubModel:
    """A practice-repository model: no toolkit base class, always predicts 0.5."""

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        self.rows = len(inputs)

    def predict(self, values: Sequence[float]) -> list[float]:
        return [0.5]


def test_run_sends_inputs_and_outputs_per_frame(receivers: tuple[Receiver, Receiver]) -> None:
    ins, outs = receivers
    examples = ExampleSet()
    examples.add_events([*gesture(36, label="a"), *gesture(40, 0.1, label="b")])
    with (
        OscSender(INPUTS_ADDRESS, LOCALHOST, ins.port) as inputs,
        OscSender(OUTPUTS_ADDRESS, LOCALHOST, outs.port) as outputs,
    ):
        loop = IMLLoop(Classifier, examples, inputs=inputs, outputs=outputs)
        loop.train()
        count = loop.run(gesture(40))
    sent_in, sent_out = ins.drain(), outs.drain()
    assert count == 6
    assert len(sent_in) == len(sent_out) == count
    assert all(a == INPUTS_ADDRESS and len(v) == OSC_INPUT_COUNT for a, v in sent_in)
    assert all(a == OUTPUTS_ADDRESS and len(v) == 1 for a, v in sent_out)
    assert sent_out[0][1] == (2.0,)


def test_any_model_object_runs_in_the_loop(receivers: tuple[Receiver, Receiver]) -> None:
    _, outs = receivers
    examples = ExampleSet()
    examples.add_recording(DATA / "basic.jsonl")
    with OscSender(OUTPUTS_ADDRESS, LOCALHOST, outs.port) as outputs:
        loop = IMLLoop(StubModel, examples, outputs=outputs)
        model = loop.train()
        assert isinstance(model, StubModel) and model.rows == len(examples)
        loop.run(read_recording(DATA / "basic.jsonl").events)
    assert {v for _, v in outs.drain()} == {(0.5,)}


def test_regression_outputs_all_targets(receivers: tuple[Receiver, Receiver]) -> None:
    _, outs = receivers
    examples = ExampleSet()
    examples.add_recording(DATA / "regression.jsonl")
    events = read_recording(DATA / "regression.jsonl").events
    with OscSender(OUTPUTS_ADDRESS, LOCALHOST, outs.port) as outputs:
        loop = IMLLoop(Regressor, examples, outputs=outputs)
        loop.train()
        loop.run(events)
        last = loop.step(list(frames(events))[-2])
    assert all(len(v) == 2 for _, v in outs.drain())
    assert last == pytest.approx([1.0, 0.0], abs=0.1)


def test_backend_off_sends_only_inputs(receivers: tuple[Receiver, Receiver]) -> None:
    ins, outs = receivers
    examples = ExampleSet()
    examples.add_recording(DATA / "basic.jsonl")
    with (
        OscSender(INPUTS_ADDRESS, LOCALHOST, ins.port) as inputs,
        OscSender(OUTPUTS_ADDRESS, LOCALHOST, outs.port) as outputs,
    ):
        loop = IMLLoop(None, examples, inputs=inputs, outputs=outputs)
        assert not loop.backend_on
        with pytest.raises(BackendOffError):
            loop.train()
        count = loop.run(read_recording(DATA / "basic.jsonl").events)
    assert len(ins.drain()) == count > 0
    assert outs.drain() == []


def test_untrained_loop_sends_no_outputs(receivers: tuple[Receiver, Receiver]) -> None:
    _, outs = receivers
    with OscSender(OUTPUTS_ADDRESS, LOCALHOST, outs.port) as outputs:
        loop = IMLLoop(Classifier, outputs=outputs)
        assert loop.model is None
        loop.run(gesture(36))
        with pytest.raises(ExampleError):
            loop.train()
        assert loop.model is None
    assert outs.drain() == []


def test_add_examples_and_retrain_without_restart() -> None:
    loop = IMLLoop(Classifier)
    loop.examples.add_events(gesture(36, label="a"))
    first = loop.train()
    assert held_predictions(loop, gesture(36)) == {1.0}
    assert held_predictions(loop, gesture(40)) == {1.0}

    loop.examples.add_events(gesture(40, label="b"))
    loop.train()
    assert loop.model is not first
    assert held_predictions(loop, gesture(36)) == {1.0}
    assert held_predictions(loop, gesture(40)) == {2.0}

    # Removing a label keeps the other label's class number.
    loop.examples.remove("a")
    loop.examples.add_events(gesture(44, label="c"))
    loop.train()
    assert held_predictions(loop, gesture(40)) == {2.0}
    assert held_predictions(loop, gesture(44)) == {3.0}


def test_rate_must_be_positive() -> None:
    with pytest.raises(ValueError):
        IMLLoop(Classifier, rate=0)
