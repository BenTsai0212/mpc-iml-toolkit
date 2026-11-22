"""The learning profile of `ensemble` (#196, RFC 0005 step 8): `learn_profile`, the
controls `save-profile`, `load-profile` and `reset-learning`, the autoload and the
save at each phrase start, the reply `profile-errors` and `python -m mpc_iml.learn
show`."""

import json
import random
from pathlib import Path

import pytest
from test_ensemble import BAR, START, Rig
from test_ensemble_learn import bar_of, reply

from mpc_iml.learn import Demonstrations, Example, Learner
from mpc_iml.learn_profile import (
    PROFILE,
    PROFILE_FORMAT,
    apply_profile,
    main,
    read_profile,
    show,
    write_profile,
)

SETTINGS = {"progression": "minor-two", "bass-loop": "boom", "loop": "keys"}


def taught() -> tuple[dict[str, Learner], dict[str, Demonstrations]]:
    """Learners with `push/beat` liked as `drive`, and enough bass examples for a tree."""
    learners = {p: Learner(p, random.Random(0)) for p in ("bass", "melody")}
    for _ in range(3):
        learners["bass"].like("push/beat", "drive")
    demos = {p: Demonstrations(p) for p in ("bass", "melody")}
    for bar, (values, label) in enumerate(
        [((2, 0, 1), "home"), ((2, 0, 1), "home"), ((3, 1, 1), "push"), ((4, 2, 1), "push")]
    ):
        demos["bass"].add(Example("bass", values, label, bar))
    return learners, demos


def test_a_profile_round_trips_and_trains_the_trees(tmp_path: Path) -> None:
    learners, demos = taught()
    path = tmp_path / PROFILE
    write_profile(path, learners, demos, SETTINGS)
    data = json.loads(path.read_text())
    assert (data["format"], data["format_version"], data["settings"]) == (
        PROFILE_FORMAT,
        1,
        SETTINGS,
    )
    assert not list(tmp_path.glob("learn/.*")), "no partial file is left"
    profile = read_profile(path)
    fresh = {p: Learner(p, random.Random(0)) for p in ("bass", "melody")}
    trees = {p: Demonstrations(p) for p in ("bass", "melody")}
    apply_profile(profile, fresh, trees)
    assert fresh["bass"].table() == learners["bass"].table()
    assert fresh["bass"].learned() == ["bass:push/beat>drive"]
    assert trees["bass"].trained and not trees["melody"].trained
    assert trees["bass"].predict([4, 2, 1]) == "push"


@pytest.mark.parametrize(
    "text",
    [
        "{",
        json.dumps({"format": "mpc-iml-loop", "format_version": 1}),
        json.dumps({"format": PROFILE_FORMAT, "format_version": 2}),
        json.dumps(
            {"format": PROFILE_FORMAT, "format_version": 1, "weights": {"bass": {"x/y": {}}}}
        ),
        json.dumps(
            {
                "format": PROFILE_FORMAT,
                "format_version": 1,
                "weights": {},
                "examples": [{"part": "bass", "features": [1], "label": "home", "bar": 0}],
            }
        ),
        json.dumps(
            {
                "format": PROFILE_FORMAT,
                "format_version": 1,
                "weights": {},
                "examples": [{"part": "bass", "features": [1, 0, 1], "label": "busy", "bar": 0}],
            }
        ),
    ],
)
def test_a_bad_profile_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "ensemble.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="ensemble.json"):
        read_profile(path)


def test_show_marks_what_differs_from_the_rules_and_prints_the_tree(tmp_path: Path) -> None:
    learners, demos = taught()
    path = tmp_path / "ensemble.json"
    write_profile(path, learners, demos, SETTINGS)
    text = show(read_profile(path))
    (row,) = [line for line in text.splitlines() if "push/beat" in line]
    assert row.split()[:2] == ["push/beat", "push"] and row.endswith("* learned drive")
    assert "bass: 4 examples, tree:" in text
    assert "off-grid kicks" in text
    assert "melody: 0 examples, no tree (the rules play)" in text


def test_the_show_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    learners, demos = taught()
    path = tmp_path / "ensemble.json"
    write_profile(path, learners, demos, SETTINGS)
    assert main(["show", str(path)]) == 0
    assert "* learned drive" in capsys.readouterr().out
    assert main(["show", str(tmp_path / "none.json")]) == 1
    assert "error:" in capsys.readouterr().err


# In `ensemble`


def learning(folder: Path, learn: str = "likes") -> Rig:
    rig = Rig(melody=True, bass="loop", seed=1)
    rig.ensemble.data_folder(folder)
    rig.ensemble.controls()["learn"]([learn])
    rig.send(START)
    return rig


def test_a_phrase_start_saves_the_profile_while_learning(tmp_path: Path) -> None:
    rig = learning(tmp_path)
    for bar in range(4):
        bar_of(rig, bar, press=8)
    rig.until(4 * BAR + 1)
    profile = read_profile(tmp_path / PROFILE)
    assert profile.settings == {**SETTINGS, "learn-loops": "0"}
    assert f"ensemble: saved the profile {tmp_path / PROFILE}" in rig.log


def test_learn_off_never_writes_the_profile(tmp_path: Path) -> None:
    rig = learning(tmp_path, "off")
    for bar in range(9):
        bar_of(rig, bar)
    assert not (tmp_path / "learn").exists()


def test_the_data_folder_loads_the_profile(tmp_path: Path) -> None:
    learners, demos = taught()
    write_profile(tmp_path / PROFILE, learners, demos, SETTINGS)
    rig = learning(tmp_path)
    assert reply(rig, "learned") == ["bass:push/beat>drive"]
    assert reply(rig, "examples") == [4, 0]
    assert reply(rig, "profile-errors") == [0]
    assert any(line.startswith("ensemble: loaded the profile ") for line in rig.log)


def test_a_bad_profile_plays_the_rules_and_is_not_overwritten(tmp_path: Path) -> None:
    path = tmp_path / PROFILE
    path.parent.mkdir()
    path.write_text("{")
    rig = learning(tmp_path)
    assert reply(rig, "profile-errors") == [1]
    assert reply(rig, "learned") == ["-"]
    assert any(line.startswith("ensemble: skipped the profile: ") for line in rig.log)
    for bar in range(5):
        bar_of(rig, bar)
    assert path.read_text() == "{", "a phrase start keeps the bad file"
    rig.ensemble.controls()["save-profile"]([])
    read_profile(path)
    rig.ensemble.controls()["load-profile"]([])
    assert reply(rig, "profile-errors") == [0]


def test_reset_learning_goes_back_to_the_rules(tmp_path: Path) -> None:
    learners, demos = taught()
    write_profile(tmp_path / PROFILE, learners, demos, SETTINGS)
    rig = learning(tmp_path)
    rig.ensemble.controls()["reset-learning"]([])
    assert reply(rig, "learned") == ["-"]
    assert reply(rig, "examples") == [0, 0]
    assert read_profile(tmp_path / PROFILE).examples, "the file changes only on a save"
    assert rig.reports, "the state is sent again"


def test_the_profile_controls_need_a_data_folder_and_no_arguments(tmp_path: Path) -> None:
    rig = Rig(melody=True, bass="loop")
    controls = rig.ensemble.controls()
    for name in ("save-profile", "load-profile"):
        with pytest.raises(ValueError, match="no data folder"):
            controls[name]([])
    rig.ensemble.data_folder(tmp_path)
    with pytest.raises(ValueError, match="ensemble.json"):
        controls["load-profile"]([])
    for name in ("save-profile", "load-profile", "reset-learning"):
        with pytest.raises(ValueError, match="no arguments"):
            controls[name]([1])
