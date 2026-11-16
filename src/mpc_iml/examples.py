"""Training examples built from recordings (ADR 0002).

Frames inside an `example_start` / `example_end` segment become examples with the
segment's `label` (classification) or `targets` (regression); frames outside any
segment are dropped. Frame timing is the same as `frames.frames`.

Class numbers follow Wekinator (1, 2, ...). Within one `ExampleSet` a label keeps
its number once assigned, also after its examples are removed, so receivers of
`/wek/outputs` never see numbers shift.
"""

from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mpc_iml.events import Event, ExampleEnd, ExampleStart
from mpc_iml.frames import DEFAULT_RATE, Frame, PadState
from mpc_iml.recording import read_recording

FeatureFn = Callable[[Frame], Sequence[float]]
"""Turns a frame into feature values; the default is the 49 `/wek/inputs` values."""


class ExampleError(ValueError):
    """Examples are malformed or cannot be combined."""


def default_features(frame: Frame) -> Sequence[float]:
    return frame.to_osc_values()


def labelled_frames(
    events: Iterable[Event], rate: float = DEFAULT_RATE
) -> Iterator[tuple[Frame, ExampleStart | None]]:
    """Yield each frame with the `ExampleStart` of the segment it is in, or None.

    Raises `ExampleError` for nested segments, an `example_end` without a start,
    or a start without an end.
    """
    if rate <= 0:
        raise ValueError(f"rate must be positive: {rate}")
    state = PadState()
    current: ExampleStart | None = None
    k = 0
    for event in events:
        while k / rate < event.t:
            yield state.frame(k / rate), current
            k += 1
        if isinstance(event, ExampleStart):
            if current is not None:
                raise ExampleError(f"example_start at t={event.t} inside another example")
            if (event.label is None) == (event.targets is None):
                raise ExampleError(f"example_start at t={event.t} needs a label or targets")
            current = event
        elif isinstance(event, ExampleEnd):
            if current is None:
                raise ExampleError(f"example_end at t={event.t} without example_start")
            current = None
        else:
            state.apply(event)
    yield state.frame(k / rate), current
    if current is not None:
        raise ExampleError(f"example_start at t={current.t} without example_end")


@dataclass(frozen=True)
class Example:
    """One frame's feature values with its label or targets."""

    features: tuple[float, ...]
    label: str | None = None
    targets: tuple[float, ...] | None = None


class ExampleSet:
    """Editable training examples for one task, classification or regression."""

    def __init__(
        self, features: FeatureFn = default_features, classes: Mapping[str, int] | None = None
    ) -> None:
        self.features = features
        self.examples: list[Example] = []
        self._classes: dict[str, int] = {}
        for label, number in (classes or {}).items():
            if number < 1 or number in self._classes.values():
                raise ExampleError(f"class numbers must be unique and from 1: {label}={number}")
            self._classes[label] = number

    @property
    def classes(self) -> dict[str, int]:
        """Label to class number, including labels that no longer have examples."""
        return dict(self._classes)

    def class_number(self, label: str) -> int:
        """The label's class number, assigning the next free one the first time."""
        if label not in self._classes:
            self._classes[label] = max(self._classes.values(), default=0) + 1
        return self._classes[label]

    def _check(self, new: Sequence[Example]) -> None:
        reference = self.examples[0] if self.examples else (new[0] if new else None)
        for example in new:
            assert reference is not None
            if (example.label is None) == (example.targets is None):
                raise ExampleError("an example needs a label or targets, not both")
            if (example.label is None) != (reference.label is None):
                raise ExampleError("cannot mix classification (label) and regression (targets)")
            if example.targets is not None and reference.targets is not None:
                if len(example.targets) != len(reference.targets):
                    raise ExampleError(
                        f"targets have {len(example.targets)} values, "
                        f"expected {len(reference.targets)}"
                    )

    def _extend(self, new: Sequence[Example]) -> int:
        self._check(new)
        for example in new:
            if example.label is not None:
                self.class_number(example.label)
        self.examples.extend(new)
        return len(new)

    def add(
        self, frame: Frame, label: str | None = None, targets: Sequence[float] | None = None
    ) -> None:
        """Add one frame as an example."""
        values = tuple(float(v) for v in self.features(frame))
        target_values = None if targets is None else tuple(float(v) for v in targets)
        self._extend([Example(values, label, target_values)])

    def add_events(self, events: Iterable[Event], rate: float = DEFAULT_RATE) -> int:
        """Add every frame inside an example segment; returns how many were added.

        Nothing is added if the events or their segments are malformed.
        """
        new = [
            Example(tuple(float(v) for v in self.features(frame)), start.label, start.targets)
            for frame, start in labelled_frames(events, rate)
            if start is not None
        ]
        return self._extend(new)

    def add_recording(self, path: Path | str, rate: float = DEFAULT_RATE) -> int:
        """Add the examples in a recording file; returns how many were added."""
        return self.add_events(read_recording(path).events, rate)

    def remove(self, label: str) -> int:
        """Remove the examples with `label`; its class number stays reserved."""
        before = len(self.examples)
        self.examples = [e for e in self.examples if e.label != label]
        return before - len(self.examples)

    def clear(self) -> None:
        """Remove all examples; class numbers stay assigned."""
        self.examples = []

    def __len__(self) -> int:
        return len(self.examples)

    def inputs(self) -> list[list[float]]:
        return [list(e.features) for e in self.examples]

    def outputs(self) -> list[list[float]]:
        """Class numbers (one value per row) or regression targets."""
        return [
            [float(self._classes[e.label])] if e.label is not None else list(e.targets or ())
            for e in self.examples
        ]

    def training_data(self) -> tuple[list[list[float]], list[list[float]]]:
        """`(inputs, outputs)` for `Model.fit`; raises `ExampleError` if there are none."""
        if not self.examples:
            raise ExampleError("no examples to train on")
        return self.inputs(), self.outputs()
