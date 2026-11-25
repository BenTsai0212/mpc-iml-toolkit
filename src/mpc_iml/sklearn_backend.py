"""Built-in models using scikit-learn, close to Wekinator's defaults.

- `Classifier`: 1-nearest-neighbour; outputs the class number of the closest
  example.
- `Regressor`: a multilayer perceptron with one hidden layer of sigmoid units as
  wide as the input, trained with `lbfgs`, for smooth output between examples.
  Sigmoid (Wekinator's choice) rather than scikit-learn's default ReLU, whose
  units can all switch off when the layer is small, giving a constant output.

`Classifier` and `Regressor` scale inputs to 0-1 with a `MinMaxScaler` fitted on
the training data before the estimator, because the 49 frame values mix 0-1
(pressure, velocity, held) and 0-7 (bank). Scaling happens only inside these
models; the values sent to `/wek/inputs` are unchanged (ADR 0002).
"""

from collections.abc import Sequence
from typing import Any

import numpy as np
from sklearn.neighbors import KNeighborsClassifier
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler


def _check_rows(inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
    if not inputs:
        raise ValueError("no training examples")
    if len(inputs) != len(outputs):
        raise ValueError(f"{len(inputs)} input rows but {len(outputs)} output rows")


class Classifier:
    """k-nearest-neighbour classifier (k = 1 by default) on min-max scaled inputs."""

    def __init__(self, n_neighbors: int = 1, **kwargs: Any) -> None:
        self.n_neighbors = n_neighbors
        self.kwargs = kwargs
        self.pipeline: Pipeline | None = None

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        _check_rows(inputs, outputs)
        if any(len(row) != 1 for row in outputs):
            raise ValueError("classification outputs must have one value, the class number")
        y = np.array([row[0] for row in outputs])
        k = min(self.n_neighbors, len(inputs))
        estimator = KNeighborsClassifier(n_neighbors=k, **self.kwargs)
        pipeline = Pipeline([("scale", MinMaxScaler()), ("model", estimator)])
        pipeline.fit(np.asarray(inputs, dtype=float), y)
        self.pipeline = pipeline

    def predict(self, values: Sequence[float]) -> list[float]:
        if self.pipeline is None:
            raise RuntimeError("the model is not trained")
        result = self.pipeline.predict(np.asarray([values], dtype=float))
        return [float(result[0])]


class Regressor:
    """MLP regressor (one sigmoid hidden layer as wide as the input) on scaled inputs."""

    def __init__(
        self,
        hidden_layer_sizes: tuple[int, ...] | None = None,
        activation: str = "logistic",
        solver: str = "lbfgs",
        max_iter: int = 2000,
        random_state: int | None = 0,
        **kwargs: Any,
    ) -> None:
        self.hidden_layer_sizes = hidden_layer_sizes
        self.activation = activation
        self.solver = solver
        self.max_iter = max_iter
        self.random_state = random_state
        self.kwargs = kwargs
        self.pipeline: Pipeline | None = None

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        _check_rows(inputs, outputs)
        x = np.asarray(inputs, dtype=float)
        y = np.asarray(outputs, dtype=float)
        if y.ndim != 2 or y.shape[1] == 0:
            raise ValueError("regression outputs must be rows of one or more targets")
        hidden = self.hidden_layer_sizes or (x.shape[1],)
        estimator = MLPRegressor(
            hidden_layer_sizes=hidden,
            activation=self.activation,
            solver=self.solver,
            max_iter=self.max_iter,
            random_state=self.random_state,
            **self.kwargs,
        )
        pipeline = Pipeline([("scale", MinMaxScaler()), ("model", estimator)])
        pipeline.fit(x, y[:, 0] if y.shape[1] == 1 else y)
        self.pipeline = pipeline

    def predict(self, values: Sequence[float]) -> list[float]:
        if self.pipeline is None:
            raise RuntimeError("the model is not trained")
        result = self.pipeline.predict(np.asarray([values], dtype=float))
        return [float(v) for v in np.ravel(result[0])]
