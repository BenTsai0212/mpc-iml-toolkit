"""The IML loop from RFC 0001: record examples, train, run, edit examples, retrain.

Run mode takes any event source (an iterable of events: live MIDI or a replayed
recording), computes frames, and for each frame:

1. sends its feature values to `/wek/inputs`, if an inputs sender is given;
2. predicts with the trained model and sends the result to `/wek/outputs`, if a
   model is trained and an outputs sender is given.

The model is an extension point (`mpc_iml.model`). With `model_factory=None` the
built-in backend is off: only `/wek/inputs` is sent, Wekinator acts as the model,
and receivers get the same `/wek/outputs` from Wekinator instead.

Examples can be added or removed and `train()` called again at any time without
restarting, also from another thread while `run` is running: a retrain builds a
new model and swaps it in with one assignment, so each frame is predicted by
either the old or the new model.

`run` does not sleep: a replayed recording runs as fast as frames can be computed.
Real-time pacing of live input belongs to the event source.
"""

from collections.abc import Iterable

from mpc_iml.events import Event
from mpc_iml.examples import ExampleSet
from mpc_iml.frames import DEFAULT_RATE, Frame, frames
from mpc_iml.model import Model, ModelFactory
from mpc_iml.osc import OscSender


class BackendOffError(RuntimeError):
    """`train()` was called on a loop whose model backend is switched off."""


class IMLLoop:
    """Trains a model on an `ExampleSet` and runs it on frames from an event source.

    Features for training and for `/wek/inputs` both come from `examples.features`
    (by default the 49 values of ADR 0002), so the model sees in run mode what it
    was trained on.
    """

    def __init__(
        self,
        model_factory: ModelFactory | None,
        examples: ExampleSet | None = None,
        inputs: OscSender | None = None,
        outputs: OscSender | None = None,
        rate: float = DEFAULT_RATE,
    ) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be positive: {rate}")
        self.model_factory = model_factory
        self.examples = examples if examples is not None else ExampleSet()
        self.inputs = inputs
        self.outputs = outputs
        self.rate = rate
        self._model: Model | None = None

    @property
    def backend_on(self) -> bool:
        """False when the loop only sends `/wek/inputs` (Wekinator is the model)."""
        return self.model_factory is not None

    @property
    def model(self) -> Model | None:
        """The trained model in use, or None before the first `train()`."""
        return self._model

    def train(self) -> Model:
        """Fit a fresh model on the current examples and swap it in.

        Raises `BackendOffError` when the backend is off, and `ExampleError` when
        there are no examples; the previous model stays in use when it raises.
        """
        if self.model_factory is None:
            raise BackendOffError("the model backend is off; Wekinator is the model")
        inputs, outputs = self.examples.training_data()
        model = self.model_factory()
        model.fit(inputs, outputs)
        self._model = model
        return model

    def step(self, frame: Frame) -> list[float] | None:
        """Send one frame's features and prediction; return the prediction or None."""
        values = list(self.examples.features(frame))
        if self.inputs is not None:
            self.inputs.send(values)
        model = self._model if self.backend_on else None
        if model is None:
            return None
        prediction = model.predict(values)
        if self.outputs is not None:
            self.outputs.send(prediction)
        return prediction

    def run(self, events: Iterable[Event]) -> int:
        """Run `step` on every frame computed from `events`; return the frame count."""
        count = 0
        for frame in frames(events, self.rate):
            self.step(frame)
            count += 1
        return count
