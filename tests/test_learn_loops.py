"""Loops in the choice space of `learn likes` (#196 PR 5): `learn.LoopLearner`, the
control `learn-loops`, the replies `learn-loops` and `playing-loops`, user loops
joining and leaving on `reload-loops`, and the profile's `loops`."""

import json
import random
from pathlib import Path

import pytest
from test_ensemble import BAR, LAYER, START, Rig
from test_ensemble_learn import STEADY, bar_of, reply
from test_ensemble_user_loops import named, write
from test_learn_profile import SETTINGS, taught

from mpc_iml.learn import FORGET, LOOP_PRIOR, STEP, LoopLearner
from mpc_iml.learn_profile import PROFILE, apply_profile, read_profile, show, write_profile

CONTEXT = "grid/beat"
"""The bass context of `STEADY`."""


def learner(seed: int = 0) -> LoopLearner:
    return LoopLearner("bass", random.Random(seed))


# The loop learner


def test_the_selected_loop_starts_highest() -> None:
    loops = learner()
    assert loops.weights(CONTEXT, ["boom", "walk"], "boom") == {"boom": 0.0, "walk": LOOP_PRIOR}
    two = loops.probabilities(CONTEXT, ["boom", "walk"], "boom")
    four = loops.probabilities(CONTEXT, ["boom", "walk", "a", "b"], "walk")
    assert 0.85 < two["boom"] < 0.92
    assert 0.65 < four["walk"] < 0.75
    assert loops.top(CONTEXT, ["boom", "walk"], "walk") == "walk"


def test_a_like_raises_the_loop_and_forgetting_pulls_it_back() -> None:
    loops = learner()
    for _ in range(3):
        loops.like(CONTEXT, "walk")
    assert loops.weights(CONTEXT, ["boom", "walk"], "boom")["walk"] == LOOP_PRIOR + 3 * STEP
    assert loops.top(CONTEXT, ["boom", "walk"], "boom") == "walk"
    loops.forget()
    assert loops.table() == {CONTEXT: {"walk": pytest.approx(3 * STEP * (1 - FORGET))}}
    loops.reset()
    assert loops.table() == {}


def test_draws_are_seeded() -> None:
    draws = [learner(4).choose(CONTEXT, ["boom", "walk"], "boom") for _ in range(2)]
    many = learner(4)
    first = [many.choose(CONTEXT, ["boom", "walk"], "boom") for _ in range(40)]
    again = learner(4)
    assert first == [again.choose(CONTEXT, ["boom", "walk"], "boom") for _ in range(40)]
    assert draws[0] == draws[1] and set(first) == {"boom", "walk"}


def test_a_gone_loop_keeps_its_weight_by_name() -> None:
    loops = learner()
    loops.like(CONTEXT, "line")
    assert "line" not in loops.weights(CONTEXT, ["boom", "walk"], "boom")
    assert loops.weights(CONTEXT, ["boom", "line"], "boom")["line"] == LOOP_PRIOR + STEP


def test_load_checks_the_contexts() -> None:
    loops = learner()
    loops.load({CONTEXT: {"walk": 1.0}})
    assert loops.table() == {CONTEXT: {"walk": 1.0}}
    with pytest.raises(ValueError, match="not a bass context"):
        loops.load({"mid/8ths": {"walk": 1.0}})


# The preset


def loops_rig(learn_loops: bool, seed: int = 0, folder: Path | None = None) -> Rig:
    rig = Rig(melody=True, bass="loop", seed=seed)
    if folder is not None:
        rig.ensemble.data_folder(folder)
    controls = rig.ensemble.controls()
    controls["learn"](["likes"])
    controls["learn-loops"]([int(learn_loops)])
    rig.send(START)
    return rig


def playing(rig: Rig, bars: int, first: int = 0) -> list[list[str]]:
    """`playing-loops` in the bar after each of `bars` steady bars from `first`."""
    seen = []
    for bar in range(first, first + bars):
        bar_of(rig, bar)
        rig.until((bar + 1) * BAR + 1)
        seen.append(reply(rig, "playing-loops"))
    return seen


def test_learn_loops_0_plays_the_selected_loops() -> None:
    rig = loops_rig(False, seed=2)
    assert reply(rig, "learn-loops") == [0]
    assert all(p == ["boom", "keys"] for p in playing(rig, 24))
    assert not [line for line in rig.log if " loop " in line and "from bar" in line]


def test_the_loop_changes_only_at_a_phrase_start() -> None:
    rig = loops_rig(True, seed=3)
    seen = playing(rig, 40)
    for bar in range(1, len(seen)):
        if (bar + 1) % 4:
            assert seen[bar] == seen[bar - 1], bar
    assert {s[0] for s in seen} == {"boom", "walk"}
    assert {s[1] for s in seen} == {"keys", "pluck"}
    assert any(line.startswith("ensemble: bass loop walk from bar") for line in rig.log)
    assert playing(loops_rig(True, seed=3), 40) == seen


def test_a_liked_loop_is_chosen_at_the_next_phrase() -> None:
    rig = loops_rig(True)
    for _ in range(10):
        rig.ensemble._loop_learners["bass"].like(CONTEXT, "walk")
    seen = playing(rig, 5)
    assert [s[0] for s in seen] == ["boom", "boom", "boom", "walk", "walk"]
    assert "ensemble: bass loop walk from bar 4 (selected boom)" in rig.log
    assert reply(rig, "bass-loop") == ["boom"], "the selected loop does not change"


def test_a_like_credits_the_loop_heard() -> None:
    rig = loops_rig(True)
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    assert rig.ensemble._loop_learners["bass"].table() == {CONTEXT: {"boom": STEP}}
    (line,) = [line for line in rig.log if line.startswith("ensemble: like")]
    assert f"bass {CONTEXT}>" in line and "(boom)" in line and "(keys)" in line


def test_a_user_loop_joins_and_a_gone_one_plays_to_the_phrase_end(tmp_path: Path) -> None:
    write(tmp_path, "line", named("line"))
    rig = loops_rig(True, folder=tmp_path)
    for _ in range(10):
        rig.ensemble._loop_learners["bass"].like(CONTEXT, "line")
    assert [s[0] for s in playing(rig, 5)] == ["boom"] * 3 + ["line"] * 2
    (tmp_path / "loops" / "line.json").unlink()
    rig.ensemble.controls()["reload-loops"]([])
    assert reply(rig, "bass-loops") == ["boom", "walk"]
    seen = [s[0] for s in playing(rig, 3, first=5)]
    assert seen[:2] == ["line", "line"] and seen[2] != "line"
    assert rig.ensemble._loop_learners["bass"].table()[CONTEXT]["line"] > 0


def test_selecting_a_loop_plays_it_from_the_next_bar_line() -> None:
    rig = loops_rig(True)
    for _ in range(10):
        rig.ensemble._loop_learners["bass"].like(CONTEXT, "walk")
    playing(rig, 5)
    rig.ensemble.controls()["bass-loop"](["boom"])
    assert [s[0] for s in playing(rig, 4, first=5)] == ["boom", "boom", "walk", "walk"]


def test_learn_off_clears_the_chosen_loop() -> None:
    rig = loops_rig(True)
    for _ in range(10):
        rig.ensemble._loop_learners["bass"].like(CONTEXT, "walk")
    playing(rig, 5)
    rig.ensemble.controls()["learn"](["off"])
    bar_of(rig, 5)
    rig.until(6 * BAR + 1)
    assert reply(rig, "playing-loops")[0] == "boom"


def test_reset_learning_forgets_the_loops() -> None:
    rig = loops_rig(True)
    rig.ensemble._loop_learners["bass"].like(CONTEXT, "walk")
    rig.ensemble.controls()["reset-learning"]([])
    assert rig.ensemble._loop_learners["bass"].table() == {}


def test_pad_16_is_still_like_with_learn_loops() -> None:
    rig = loops_rig(True)
    bar_of(rig, 0, hits=[*STEADY, (8, LAYER)])
    assert reply(rig, "bass") == ["loop", "loop"]


# The profile


def test_the_profile_keeps_the_loops(tmp_path: Path) -> None:
    learners, demos = taught()
    loops = {p: LoopLearner(p, random.Random(0)) for p in ("bass", "melody")}
    loops["bass"].like(CONTEXT, "line")
    path = tmp_path / PROFILE
    write_profile(path, learners, demos, SETTINGS, loops)
    assert json.loads(path.read_text())["loops"] == {
        "bass": {CONTEXT: {"line": STEP}},
        "melody": {},
    }
    profile = read_profile(path)
    fresh = {p: LoopLearner(p, random.Random(0)) for p in ("bass", "melody")}
    apply_profile(profile, taught()[0], taught()[1], fresh)
    assert fresh["bass"].table() == loops["bass"].table()
    assert f"bass: loops in {CONTEXT}: line +0.50" in show(profile)


def test_a_profile_without_loops_reads(tmp_path: Path) -> None:
    learners, demos = taught()
    path = tmp_path / PROFILE
    write_profile(path, learners, demos, SETTINGS)
    data = json.loads(path.read_text())
    del data["loops"]
    path.write_text(json.dumps(data))
    fresh = {p: LoopLearner(p, random.Random(0)) for p in ("bass", "melody")}
    fresh["bass"].like(CONTEXT, "walk")
    apply_profile(read_profile(path), *taught(), fresh)
    assert fresh["bass"].table() == {}


def test_a_profile_with_a_bad_loop_context_is_refused(tmp_path: Path) -> None:
    learners, demos = taught()
    path = tmp_path / PROFILE
    write_profile(path, learners, demos, SETTINGS)
    data = json.loads(path.read_text())
    data["loops"] = {"bass": {"nope": {"walk": 1}}}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="not a bass context"):
        read_profile(path)


def test_the_ensemble_saves_and_loads_the_loops(tmp_path: Path) -> None:
    rig = loops_rig(True, folder=tmp_path)
    rig.ensemble._loop_learners["melody"].like("mid/8ths", "pluck")
    rig.ensemble.controls()["save-profile"]([])
    assert read_profile(tmp_path / PROFILE).settings["learn-loops"] == "1"
    other = loops_rig(True, folder=tmp_path)
    assert other.ensemble._loop_learners["melody"].table() == {"mid/8ths": {"pluck": STEP}}
