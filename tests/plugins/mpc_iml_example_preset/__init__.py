"""A minimal external preset package, used by `tests/test_presets.py`.

It depends only on the toolkit's public interface: its own features (pressure of
pads 1-4), its own model (nearest neighbour, no scikit-learn) and an OSC output.
It is registered through `../mpc_iml_example_preset-0.1.0.dist-info/entry_points.txt`,
as `pip` or `uv` would write it for an installed package.
"""

from collections.abc import Sequence

from mpc_iml.frames import Frame
from mpc_iml.presets import MidiCcOutput, OscOutput, Preset

ADDRESS = "/example/outputs"


def pressure_features(frame: Frame) -> list[float]:
    """4 values: the pressure of pads 1-4, 0-1."""
    return [p / 127 for p in frame.pressure[:4]]


class NearestNeighbour:
    """Predicts the outputs of the closest training row."""

    def __init__(self) -> None:
        self._rows: list[tuple[list[float], list[float]]] = []

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        self._rows = [(list(i), list(o)) for i, o in zip(inputs, outputs, strict=True)]

    def predict(self, values: Sequence[float]) -> list[float]:
        def distance(row: tuple[list[float], list[float]]) -> float:
            return sum((a - b) ** 2 for a, b in zip(row[0], values, strict=True))

        return list(min(self._rows, key=distance)[1])


PRESET = Preset(
    name="example-pressure",
    version="0.1.0",
    description="Two targets from the pressure of pads 1-4",
    features=pressure_features,
    model_factory=NearestNeighbour,
    outputs=(OscOutput(address=ADDRESS), MidiCcOutput(controllers=(20, 21))),
    patch="mpc_iml_example_preset:patch.pd",
)
