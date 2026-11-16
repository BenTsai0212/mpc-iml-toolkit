"""Model extension point for classification and regression.

A model is any object with `fit` and `predict` (structural typing): a practice
repository can pass its own model without subclassing or changing the toolkit.

Inputs are rows of feature values, one row per frame. Outputs are rows of floats:
for classification one value per row, the class number (1, 2, ...) as in
Wekinator; for regression one value per target.
"""

from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class Model(Protocol):
    """A trainable model mapping one frame's feature values to output values."""

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        """Train on `inputs[i]` -> `outputs[i]`, replacing any earlier training."""
        ...

    def predict(self, values: Sequence[float]) -> list[float]:
        """Predict the output values for one frame's feature values."""
        ...


ModelFactory = Callable[[], Model]
"""Builds a new, untrained model; each retrain starts from a fresh one."""
