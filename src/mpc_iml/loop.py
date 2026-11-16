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

Real-time sources (`LiveSource`, `ReplaySource(realtime=True)`) run on their clock:
one frame per interval (10 ms at 100 Hz) whether or not MIDI arrives, so a held pad
keeps sending. When a step takes longer than an interval, late frames are dropped:
the next frame is the latest one due, with every event up to its time, and the
number of skipped frames is added to `dropped_frames`. Other event iterables, such
as a recording's events or `ReplaySource(realtime=False)`, run as fast as frames can
be computed, without sleeping.
"""

from collections.abc import Callable, Iterable, Iterator

from mpc_iml.events import Event
from mpc_iml.examples import ExampleSet
from mpc_iml.frames import DEFAULT_RATE, Frame, frames, realtime_frames
from mpc_iml.model import Model, ModelFactory
from mpc_iml.osc import OscSender
from mpc_iml.sources import ClockedSource


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
        self.dropped_frames = 0
        """Frames skipped by the last `run` because a step fell behind the clock."""
        self._model: Model | None = None

    @property
    def backend_on(self) -> bool:
        """False when the loop only sends `/wek/inputs` (Wekinator is the model)."""
        return self.model_factory is not None

    @property
    def model(self) -> Model | None:
        """The trained model in use, or None before the first `train()`."""
        return self._model

    def train(self, data: tuple[list[list[float]], list[list[float]]] | None = None) -> Model:
        """Fit a fresh model on the current examples and swap it in.

        `data` is `(inputs, outputs)` taken earlier with `examples.training_data()`,
        so a background retrain can fit on a snapshot while the examples change.
        Raises `BackendOffError` when the backend is off, and `ExampleError` when
        there are no examples; the previous model stays in use when it raises.
        """
        if self.model_factory is None:
            raise BackendOffError("the model backend is off; Wekinator is the model")
        inputs, outputs = data if data is not None else self.examples.training_data()
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

    def run(
        self,
        events: Iterable[Event] | ClockedSource,
        duration: float | None = None,
        stop: Callable[[], bool] | None = None,
    ) -> int:
        """Run `step` on every frame computed from `events`; return the frame count.

        A real-time source is run on its clock (see the module docstring); anything
        else as fast as possible. Stops at the end of the events, before a frame at
        or after `duration` seconds, or when `stop()` is true.
        """
        self.dropped_frames = 0
        stream: Iterator[Frame]
        if isinstance(events, ClockedSource) and events.realtime:
            stream = realtime_frames(events, self.rate, duration, stop, self._count_dropped)
        elif isinstance(events, Iterable):
            stream = frames(events, self.rate)
        else:
            raise TypeError("events must be an iterable of events or a real-time source")
        count = 0
        for frame in stream:
            if duration is not None and frame.t >= duration:
                break
            if stop is not None and stop():
                break
            self.step(frame)
            count += 1
        return count

    def _count_dropped(self, skipped: int) -> None:
        self.dropped_frames += skipped
