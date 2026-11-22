"""Learning the variation in `mpc_iml.learn` (RFC 0005 step 8, #196)."""

import random

import pytest

from mpc_iml.bass import bass_variation
from mpc_iml.clock import GridHit
from mpc_iml.ensemble import DEFAULT_ROLES
from mpc_iml.learn import (
    ARMS,
    CONTEXTS,
    FORGET,
    PRIOR,
    STEP,
    Learner,
    bass_context,
    context,
    liked_bar,
    melody_context,
    rule_choice,
)
from mpc_iml.melody import melody_variation

ROLES = list(DEFAULT_ROLES)
KICK, SNARE, HAT, OTHER = 0, 1, 2, 7


def hits(*pads_steps: tuple[int, int]) -> list[GridHit]:
    return [GridHit(0.0, pad, 0, 100, 0, step, 0.0, 0.0) for pad, step in pads_steps]


def bar(pad: int, *steps: int) -> list[tuple[int, int]]:
    return [(pad, s) for s in steps]


def test_contexts() -> None:
    assert len(CONTEXTS["bass"]) == 8
    assert len(CONTEXTS["melody"]) == 9
    assert bass_context([], ROLES) == "none/-"
    assert bass_context(hits(*bar(KICK, 0, 8), *bar(SNARE, 4, 12)), ROLES) == "grid/beat"
    assert bass_context(hits(*bar(KICK, 0, 6, 10), *bar(SNARE, 4)), ROLES) == "push/-"
    assert bass_context(hits(*bar(KICK, 0, 4, 8, 12, 14)), ROLES) == "dense/-"
    assert melody_context(hits(*bar(KICK, 0, 8)), ROLES) == "sparse/none"
    assert melody_context(hits(*bar(HAT, 0, 2, 4, 6, 8, 10)), ROLES) == "mid/8ths"
    assert melody_context(hits(*bar(HAT, *range(16))), ROLES) == "dense/16ths"
    assert context("melody", hits(*bar(HAT, 1)), ROLES) == "sparse/16ths"
    assert context("bass", hits(*bar(KICK, 0)), ROLES) == "grid/-"


def test_every_context_has_a_rule_arm() -> None:
    for part in ("bass", "melody"):
        for c in CONTEXTS[part]:
            assert rule_choice(part, c) in ARMS[part]


@pytest.mark.parametrize("seed", range(5))
def test_rule_choice_is_the_rules(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(500):
        drums = hits(*((rng.randrange(16), rng.randrange(16)) for _ in range(rng.randrange(20))))
        kicks = [h.step for h in drums if ROLES[h.pad] == "kick"]
        hats = [h.step for h in drums if ROLES[h.pad] == "hat"]
        assert rule_choice("bass", bass_context(drums, ROLES)) == bass_variation(kicks)
        melody = rule_choice("melody", melody_context(drums, ROLES))
        assert melody == melody_variation(len(drums), hats)


def test_start_is_the_rules() -> None:
    learner = Learner("bass", random.Random(0))
    assert learner.weights("push/beat") == {"home": 0.0, "push": PRIOR, "drive": 0.0}
    assert learner.probabilities("push/beat")["push"] == pytest.approx(0.8, abs=0.01)
    assert learner.learned() == []
    for c in CONTEXTS["bass"]:
        assert learner.top(c) == rule_choice("bass", c)


def test_choose_is_seeded_and_explores() -> None:
    a = Learner("melody", random.Random(7))
    b = Learner("melody", random.Random(7))
    draws = [a.choose("mid/8ths") for _ in range(1000)]
    assert draws == [b.choose("mid/8ths") for _ in range(1000)]
    assert draws.count("home") / len(draws) == pytest.approx(0.8, abs=0.05)
    assert set(draws) == {"home", "open", "busy"}


def test_like_moves_the_context_only() -> None:
    learner = Learner("bass", random.Random(0))
    for _ in range(3):
        learner.like("grid/beat", "drive")
    assert learner.weights("grid/beat")["drive"] == pytest.approx(3 * STEP)
    assert learner.top("grid/beat") == "drive"
    assert learner.weights("grid/-") == learner.prior("grid/-")
    assert learner.learned() == ["bass:grid/beat>drive"]
    draws = [learner.choose("grid/beat") for _ in range(500)]
    assert draws.count("drive") > draws.count("home")


def test_forget_drifts_back_to_the_rules() -> None:
    learner = Learner("bass", random.Random(0))
    learner.like("grid/beat", "drive")
    learner.like("grid/beat", "drive")
    learner.forget()
    weights = learner.weights("grid/beat")
    assert weights["drive"] == pytest.approx(2 * STEP * (1 - FORGET))
    assert weights["home"] == pytest.approx(PRIOR)
    for _ in range(40):
        learner.forget()
    assert learner.learned() == []
    learner.like("grid/beat", "push")
    learner.reset()
    assert learner.weights("grid/beat") == learner.prior("grid/beat")


def test_tie_keeps_the_rule() -> None:
    learner = Learner("melody", random.Random(0))
    learner.like("mid/none", "busy")
    learner.like("mid/none", "busy")
    learner.like("mid/none", "home")
    learner.like("mid/none", "home")
    assert learner.top("mid/none") == "home"


def test_liked_bar() -> None:
    assert liked_bar(5, 0) == 4
    assert liked_bar(5, 3) == 4
    assert liked_bar(5, 4) == 5
    assert liked_bar(0, 0) == 0
