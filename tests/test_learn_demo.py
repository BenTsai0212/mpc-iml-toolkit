"""Demonstrations in `mpc_iml.learn` and `sklearn_backend.Tree` (RFC 0005 step 8, #196)."""

import pytest
from test_learn import HAT, KICK, ROLES, SNARE, hits

from mpc_iml.learn import (
    FEATURES,
    MIN_EXAMPLES,
    WANTS,
    Demonstrations,
    Example,
    context,
    feature_context,
    features,
)
from mpc_iml.sklearn_backend import Tree


def test_features_are_the_numbers_behind_the_contexts() -> None:
    bar = hits((KICK, 0), (KICK, 6), (SNARE, 4), (SNARE, 12), (HAT, 2), (HAT, 3))
    assert features("bass", bar, ROLES) == [2, 1, 1.0]
    assert features("melody", bar, ROLES) == [6, 2, 1]
    assert features("bass", hits((SNARE, 4)), ROLES) == [0, 0, 0.0]
    assert {p: len(n) for p, n in FEATURES.items()} == {"bass": 3, "melody": 3}


def test_feature_context_is_the_context_of_the_features() -> None:
    bars = [
        hits(),
        hits((KICK, 0), (KICK, 8), (SNARE, 4), (SNARE, 12)),
        hits((KICK, 0), (KICK, 6), (SNARE, 4), (HAT, 2), (HAT, 3)),
        hits(*[(KICK, s) for s in range(0, 16, 2)], *[(HAT, s) for s in range(1, 16, 2)]),
        hits(*[(HAT, s) for s in range(0, 16, 2)]),
    ]
    for part in ("bass", "melody"):
        for bar in bars:
            values = features(part, bar, ROLES)
            assert feature_context(part, values) == context(part, bar, ROLES)


def test_wants_start_with_auto_then_the_variations() -> None:
    assert WANTS["bass"] == ("auto", "home", "push", "drive")
    assert WANTS["melody"] == ("auto", "home", "open", "busy")


def example(kicks: int, label: str, bar: int = 0) -> Example:
    return Example("bass", (float(kicks), 0.0, 1.0), label, bar)


def test_no_model_before_enough_examples_of_two_variations() -> None:
    demos = Demonstrations("bass")
    for bar in range(MIN_EXAMPLES - 1):
        demos.add(example(1 + bar % 2, "push" if bar % 2 else "home", bar))
    assert not demos.train() and demos.predict([1, 0, 1]) is None
    same = Demonstrations("bass")
    for bar in range(MIN_EXAMPLES):
        same.add(example(1 + bar, "drive", bar))
    assert not same.train(), "one variation only"


def test_before_a_model_the_marked_contexts_play_their_most_common_variation() -> None:
    demos = Demonstrations("bass")
    assert demos.plays == "rules" and demos.choose([1, 0, 1]) is None
    demos.add(example(1, "drive", 0))
    demos.add(example(2, "push", 1))
    assert not demos.train() and demos.plays == "marked contexts"
    assert demos.choose([1, 0, 1]) == "push", "grid/beat: a tie, push is the latest"
    demos.add(example(1, "drive", 2))
    assert demos.choose([2, 0, 1]) == "drive", "grid/beat: drive twice"
    assert demos.choose([1, 1, 1]) is None, "push/beat is not marked: the rules"
    assert demos.choose([5, 0, 0]) is None


def test_the_tree_learns_the_demonstrated_mapping() -> None:
    demos = Demonstrations("bass")
    for bar in range(4):
        demos.add(example(1, "drive", 2 * bar))
        demos.add(example(4, "home", 2 * bar + 1))
    assert demos.train() and demos.trained and demos.plays == "tree"
    assert demos.predict([1, 0, 1]) == "drive" == demos.choose([1, 0, 1])
    assert demos.predict([4, 0, 1]) == "home"
    demos.reset()
    assert not demos.trained and demos.examples == []


def test_an_example_of_another_part_or_variation_is_refused() -> None:
    demos = Demonstrations("bass")
    with pytest.raises(ValueError):
        demos.add(Example("melody", (1.0, 0.0, 0.0), "open", 0))
    with pytest.raises(ValueError):
        demos.add(example(1, "busy"))


def test_tree_is_deterministic_and_prints_its_rules() -> None:
    inputs = [[1, 0, 1], [1, 1, 1], [4, 0, 1], [5, 2, 0], [2, 0, 1], [6, 3, 0]]
    outputs = [[1.0], [1.0], [2.0], [3.0], [1.0], [3.0]]
    first, second = Tree(), Tree()
    first.fit(inputs, outputs)
    second.fit(inputs, outputs)
    probes = [[1, 0, 1], [3, 0, 1], [6, 2, 0]]
    assert [first.predict(p) for p in probes] == [second.predict(p) for p in probes]
    rules = first.rules(FEATURES["bass"], ("home", "push", "drive"))
    assert "kicks" in rules and "class: home" in rules
    with pytest.raises(RuntimeError):
        Tree().predict([1, 0, 1])
    with pytest.raises(ValueError):
        Tree().fit([[1, 0, 1]], [[1.0, 2.0]])
