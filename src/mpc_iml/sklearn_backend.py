"""Built-in models using scikit-learn, close to Wekinator's defaults.

- `Classifier`: 1-nearest-neighbour; outputs the class number of the closest
  example.
- `Regressor`: a multilayer perceptron with one hidden layer of sigmoid units as
  wide as the input, trained with `lbfgs`, for smooth output between examples.
  Sigmoid (Wekinator's choice) rather than scikit-learn's default ReLU, whose
  units can all switch off when the layer is small, giving a constant output.
- `Tree`: a shallow decision tree (`max_depth` 3, `min_samples_leaf` 2,
  `random_state` 0), deterministic and printable as rules (`Tree.rules`), for the
  few readable bar features of `learn` (#196). Inputs are not scaled, so its
  thresholds read in the features' own units.

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
from sklearn.tree import DecisionTreeClassifier, export_text


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


class Tree:
    """Decision tree classifier on unscaled inputs; outputs the class number."""

    def __init__(
        self,
        max_depth: int = 3,
        min_samples_leaf: int = 2,
        random_state: int | None = 0,
        **kwargs: Any,
    ) -> None:
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.random_state = random_state
        self.kwargs = kwargs
        self.tree: DecisionTreeClassifier | None = None

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        _check_rows(inputs, outputs)
        if any(len(row) != 1 for row in outputs):
            raise ValueError("classification outputs must have one value, the class number")
        tree = DecisionTreeClassifier(
            max_depth=self.max_depth,
            min_samples_leaf=self.min_samples_leaf,
            random_state=self.random_state,
            **self.kwargs,
        )
        tree.fit(np.asarray(inputs, dtype=float), np.array([row[0] for row in outputs]))
        self.tree = tree

    def predict(self, values: Sequence[float]) -> list[float]:
        if self.tree is None:
            raise RuntimeError("the model is not trained")
        return [float(self.tree.predict(np.asarray([values], dtype=float))[0])]

    def rules(self, feature_names: Sequence[str], class_names: Sequence[str]) -> str:
        """The tree as indented rules (`export_text`); `class_names[n - 1]` names the
        class number `n`."""
        if self.tree is None:
            raise RuntimeError("the model is not trained")
        names = [class_names[int(c) - 1] for c in self.tree.classes_]
        return str(export_text(self.tree, feature_names=list(feature_names), class_names=names))
