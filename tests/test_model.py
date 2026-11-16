"""The model extension point and the built-in scikit-learn backend."""

from collections.abc import Sequence

import pytest

from mpc_iml.model import Model
from mpc_iml.sklearn_backend import Classifier, Regressor


class MeanModel:
    """A practice-repository model: no toolkit base class, predicts the mean output."""

    def __init__(self) -> None:
        self.mean: list[float] = []

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        self.mean = [sum(col) / len(col) for col in zip(*outputs, strict=True)]

    def predict(self, values: Sequence[float]) -> list[float]:
        return list(self.mean)


def test_any_object_with_fit_and_predict_is_a_model() -> None:
    models: list[Model] = [MeanModel(), Classifier(), Regressor()]
    assert all(isinstance(m, Model) for m in models)
    model = models[0]
    model.fit([[0.0], [1.0]], [[2.0], [4.0]])
    assert model.predict([0.5]) == [3.0]


def test_classifier_predicts_class_number_of_nearest_example() -> None:
    model = Classifier()
    model.fit([[0.0, 0.0], [0.1, 0.0], [1.0, 1.0], [0.9, 1.0]], [[1.0], [1.0], [2.0], [2.0]])
    assert model.predict([0.05, 0.1]) == [1.0]
    assert model.predict([0.95, 0.8]) == [2.0]


def test_classifier_scales_inputs_with_training_range() -> None:
    # Feature 0 is 0-1, feature 1 is 0-7 (like the bank); the scaler is fitted on the
    # training data and applied before predicting.
    inputs = [[0.0, 0.0], [1.0, 7.0], [1.0, 0.0]]
    model = Classifier()
    model.fit(inputs, [[1.0], [2.0], [3.0]])
    assert model.pipeline is not None
    scaler = model.pipeline.named_steps["scale"]
    assert list(scaler.data_min_) == [0.0, 0.0]
    assert list(scaler.data_max_) == [1.0, 7.0]
    # Unscaled, [0, 4] is nearest to [1, 7] (3.2 vs 4.0 to [0, 0]); scaled to
    # [0, 0.57] it is nearest to [0, 0] (0.57 vs 1.09 to [1, 1]).
    assert model.predict([0.0, 4.0]) == [1.0]


def test_regressor_fits_and_interpolates_multiple_targets() -> None:
    model = Regressor()
    inputs = [[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]
    model.fit(inputs, [[0.0, 1.0], [1.0, 0.0], [0.0, 1.0], [1.0, 0.0]])
    assert model.predict([0.0, 0.5]) == pytest.approx([0.0, 1.0], abs=0.1)
    assert model.predict([1.0, 0.5]) == pytest.approx([1.0, 0.0], abs=0.1)
    middle = model.predict([0.5, 0.5])
    assert 0.1 < middle[0] < 0.9


@pytest.mark.parametrize("width", [1, 2, 49])
def test_regressor_with_one_target_and_scaling(width: int) -> None:
    low, high = [0.0] * width, [1.0] * (width - 1) + [7.0]
    model = Regressor()
    model.fit([low, high], [[0.0], [1.0]])
    assert model.pipeline is not None
    assert list(model.pipeline.named_steps["scale"].data_max_) == high
    assert model.predict(high) == pytest.approx([1.0], abs=0.05)
    assert model.predict(low) == pytest.approx([0.0], abs=0.05)


def test_untrained_and_bad_training_data() -> None:
    with pytest.raises(RuntimeError):
        Classifier().predict([0.0])
    with pytest.raises(RuntimeError):
        Regressor().predict([0.0])
    with pytest.raises(ValueError):
        Classifier().fit([], [])
    with pytest.raises(ValueError):
        Classifier().fit([[0.0]], [[1.0, 2.0]])
