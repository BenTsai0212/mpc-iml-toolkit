"""The nod in `ensemble` (#250 PR 4, ADR 0009 "Amendment: learning by groove", "The
nod"): `learn nod`, pad 16 and the control `nod`, what a nod counts for, the nodded
variation in later groove bars and when the groove comes back, `learn-group`,
`new-groove invite`, the log lines and the replies.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). `learn off` plays exactly
as before: the golden files of `test_ensemble_learn.py`, `test_ensemble_rhythm.py`
and `test_ensemble_follow_groove.py` do not change.
"""

import json
from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, Rig
from test_ensemble_follow_groove import A_PUSHED, basses
from test_ensemble_grooves import FILL, SILENT, A, B
from test_ensemble_learn import bar_of, reply
from test_melody import HAT

from mpc_iml.ensemble import LEARN_MODES, NEW_GROOVE

C = [(0, KICK), (10, KICK), (4, SNARE), (12, SNARE), (2, HAT), (8, HAT), (13, HAT)]
"""Not groove A by its steps (similarity 0.61), but in A's group by the rhythm
descriptors (distance 0.5)."""


def rig(follow_by: str = "groove", seed: int = 1, **controls: Any) -> Rig:
    played = Rig(melody=True, bass="loop", status=1, seed=seed)
    played.ensemble.controls()["learn"](["nod"])
    played.ensemble.controls()["follow-by"]([follow_by])
    for name, value in controls.items():
        played.ensemble.controls()[name.replace("_", "-")]([value])
    played.send(START)
    return played


def session(played: Rig, bars: list[Any], nods: dict[int, int]) -> None:
    """Play `bars`, pressing pad 16 at step `nods[bar]` in those bars."""
    for bar, hits in enumerate(bars):
        bar_of(played, bar, press=nods.get(bar), hits=hits)
    played.until(len(bars) * BAR + STEP)


def lines(played: Rig, start: str) -> list[str]:
    return [line for line in played.log if line.startswith(start)]


def test_a_nod_in_a_groove_bar_keeps_the_bass_it_heard_in_that_groove() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    assert lines(played, "ensemble: nod") == ["ensemble: nod bar 3 -> groove 1 (bar 4), bass push"]
    shown = basses(played)
    assert shown[3] == "bass push (rule)"
    assert [shown[b] for b in (4, 5, 6)] == ["bass push (nod)"] * 3
    assert reply(played, "likes") == [1]
    assert reply(played, "learned") == ["bass:groove 1>push"]
    assert reply(played, "chose") == ["nod", "rule"]


def test_a_nod_in_the_first_beat_counts_for_the_bar_before() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, A, A], {4: 1})
    assert lines(played, "ensemble: nod") == ["ensemble: nod bar 3 -> groove 1 (bar 4), bass push"]
    shown = basses(played)
    assert shown[4] == "bass home (rule)"
    assert [shown[b] for b in (5, 6)] == ["bass push (nod)"] * 2


def test_a_nod_in_a_fill_counts_for_the_groove_that_ended_the_bar_before() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, FILL, A, A, A], {4: 8})
    assert lines(played, "ensemble: nod") == [
        "ensemble: nod bar 4 (fill) -> groove 1 (ended bar 3), bass push"
    ]
    shown = basses(played)
    assert shown[5] == "bass home (rule)"
    assert [shown[b] for b in (6, 7, 8)] == ["bass push (nod)"] * 3


def test_a_nod_with_no_groove_learns_nothing() -> None:
    played = rig()
    session(played, [A, B, A, A], {1: 8})
    assert lines(played, "ensemble: nod") == ["ensemble: nod bar 1, no groove to count for"]
    assert reply(played, "likes") == [0]
    assert reply(played, "learned") == ["-"]
    assert "nod" not in " ".join(basses(played).values())


def test_a_nod_two_bars_after_the_groove_learns_nothing() -> None:
    played = rig()
    session(played, [A, A, A, FILL, B, A, A], {4: 8})
    assert lines(played, "ensemble: nod") == ["ensemble: nod bar 4, no groove to count for"]


def test_the_nodded_variation_plays_when_the_groove_comes_back() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, A, B, B, B, A, A, A], {3: 8})
    assert "ensemble: groove 1 back, bass push (nod)" in played.log
    shown = basses(played)
    assert [shown[b] for b in (7, 8)] == ["bass push (rule)"] * 2
    assert [shown[b] for b in (10, 11)] == ["bass push (nod)"] * 2


def test_a_fill_answer_keeps_the_nodded_variation() -> None:
    played = rig()
    session(played, [A, A, A, A, FILL, A, A], {3: 8})
    assert lines(played, "ensemble: nod") == ["ensemble: nod bar 3 -> groove 1 (bar 4), bass home"]
    shown = basses(played)
    assert shown[5] == "bass home (fill)"
    assert shown[6] == "bass home (nod)"


def test_a_later_nod_replaces_the_variation() -> None:
    played = rig("bar", **{"new_groove": "invite"})
    session(played, [A, A, A, A, A_PUSHED, A, A, A], {3: 8, 5: 8})
    nodded = lines(played, "ensemble: nod")
    invited = nodded[0].rsplit(" ", 1)[1]
    assert invited != "home"
    assert nodded == [
        f"ensemble: nod bar 3 -> groove 1 (bar 4), bass {invited}",
        f"ensemble: nod bar 5 -> groove 1 (bar 6), bass {invited}",
    ]
    assert reply(played, "likes") == [2]
    assert basses(played)[6] == f"bass {invited} (nod)"


def test_new_groove_invite_plays_another_variation_once_per_groove() -> None:
    played = rig(new_groove="invite")
    session(played, [A, A, A, B, B, B, A, A, A], {})
    invites = lines(played, "ensemble: groove")
    assert len(invites) == 2
    assert invites[0].startswith("ensemble: groove 1 new, bass ")
    assert invites[1].startswith("ensemble: groove 2 new, bass ")
    first = invites[0].split()[-2]
    assert first != "home"
    shown = basses(played)
    assert [shown[b] for b in (2, 3)] == [f"bass {first} (invite)"] * 2
    assert shown[9] == f"bass {first} (invite)"


def test_invite_plays_only_with_learn_nod() -> None:
    played = Rig(melody=True, bass="loop", status=1, seed=1)
    controls = played.ensemble.controls()
    controls["follow-by"](["groove"])
    controls["new-groove"](["invite"])
    played.send(START)
    session(played, [A, A, A, A], {})
    assert set(basses(played).values()) <= {"bass -", "bass home (rule)"}


def group_session(seed: int) -> Rig:
    played = rig("bar", seed=seed, learn_group=1)
    session(played, [A, A, A_PUSHED, A, C, C, C, C], {3: 8})
    return played


def test_learn_group_draws_once_per_section_whether_the_group_nod_plays() -> None:
    outcomes = set()
    for seed in range(8):
        played = group_session(seed)
        drawn = lines(played, "ensemble: groove 2 group of 1")
        assert len(drawn) == 1
        shown = basses(played)
        if drawn[0].endswith("bass push (group)"):
            assert [shown[b] for b in (6, 7, 8)] == ["bass push (group)"] * 3
        else:
            assert drawn[0].endswith("rules (group draw)")
            assert "group" not in " ".join(shown[b] for b in (6, 7, 8))
        outcomes.add(drawn[0].rsplit(" (", 1)[1])
    assert outcomes == {"group)", "group draw)"}


def test_learn_group_0_never_plays_a_group_nod() -> None:
    played = rig("bar", seed=0)
    session(played, [A, A, A_PUSHED, A, C, C, C, C], {3: 8})
    assert lines(played, "ensemble: groove 2 group") == []


def test_pad_16_is_the_nod_and_the_status_line_says_so() -> None:
    played = rig()
    session(played, [A, A], {})
    assert lines(played, "ensemble: bar 1")[0].endswith("16: nod  15: melody fixed")
    assert reply(played, "bass") == ["loop", "loop"]


def test_the_nod_control_nods_at_the_clock_position() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A], {})
    played.until(3 * BAR + 8 * STEP)
    played.ensemble.controls()["nod"]([])
    for i, hits in enumerate([A, A, A]):
        bar_of(played, 4 + i, hits=hits)
    played.until(7 * BAR + STEP)
    assert "ensemble: nod bar 3 -> groove 1 (bar 4), bass push" in played.log


def test_the_nod_control_is_refused_with_learn_off_arguments_or_no_clock() -> None:
    played = Rig(melody=True, bass="loop", seed=1)
    nod = played.ensemble.controls()["nod"]
    with pytest.raises(ValueError, match="learn nod"):
        nod([])
    played.ensemble.controls()["learn"](["nod"])
    with pytest.raises(ValueError, match="no arguments"):
        nod([1])
    with pytest.raises(ValueError, match="not running"):
        nod([])


def test_pad_16_without_a_running_clock_is_ignored() -> None:
    played = Rig(melody=True, bass="loop", seed=1)
    played.ensemble.controls()["learn"](["nod"])
    played.hit(LAYER, 100)
    assert played.log[-1] == "ensemble: pad 16 ignored, the clock is not running"


def test_reset_learning_forgets_the_nods() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, A], {3: 8})
    assert reply(played, "learned") == ["bass:groove 1>push"]
    played.ensemble.controls()["reset-learning"]([])
    assert reply(played, "learned") == ["-"]
    assert reply(played, "likes") == [0]


def test_the_settings_replies_and_bad_values() -> None:
    played = Rig(melody=True, bass="loop", seed=1)
    controls = played.ensemble.controls()
    assert "nod" in LEARN_MODES
    assert NEW_GROOVE == ("rules", "invite")
    controls["learn-group"]([1])
    controls["new-groove"](["invite"])
    assert played.ensemble.state()[-4:] == [
        ("follow-by", ["bar"]),
        ("learn-group", [1]),
        ("new-groove", ["invite"]),
        ("answer-after", [2]),
    ]
    with pytest.raises(ValueError):
        controls["learn-group"]([2])
    with pytest.raises(ValueError):
        controls["new-groove"](["other"])


def test_a_silent_bar_after_the_groove_still_counts_the_nod() -> None:
    played = rig("bar")
    session(played, [A, A, A_PUSHED, A, SILENT, A, A, A], {4: 8})
    assert lines(played, "ensemble: nod") == [
        "ensemble: nod bar 4 (fill) -> groove 1 (ended bar 3), bass push"
    ]


def test_learn_nod_writes_no_profile_at_a_phrase_start(tmp_path: Any) -> None:
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    played.ensemble.controls()["learn-log"]([1])
    session(played, [A, A, A_PUSHED, A, A, A, A, A, A], {3: 8})
    assert not (tmp_path / "learn" / "ensemble.json").exists()
    played.ensemble.controls()["learn-log"]([0])
    (log,) = (tmp_path / "learn").glob("log-*.jsonl")
    header, *bars = [json.loads(line) for line in log.read_text().splitlines()]
    assert header["settings"]["learn-group"] == "0"
    assert header["settings"]["new-groove"] == "rules"
    assert bars[0]["learn"] == "nod"
    assert [b["source"]["bass"] for b in bars[4:6]] == ["nod", "nod"]
