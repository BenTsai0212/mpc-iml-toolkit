"""The learning profile of `ensemble` (#196, #250, RFC 0005 step 8): `learn_profile`,
the controls `save-profile`, `load-profile` and `reset-learning`, the autoload and the
save at each phrase start, the reply `profile-errors` and `python -m mpc_iml.learn
show`. The nods themselves are in `test_learn_profile_nods.py`."""

import json
from pathlib import Path

import pytest
from test_ensemble import BAR, START, Rig
from test_ensemble_learn import bar_of, reply

from mpc_iml.grooves import Features, Pattern
from mpc_iml.grooves.nods import NodMemory
from mpc_iml.learn_profile import (
    PROFILE,
    PROFILE_FORMAT,
    apply_profile,
    main,
    read_profile,
    write_profile,
)

SETTINGS = {"progression": "minor-two", "bass-loop": "boom", "loop": "keys"}
GROOVE = Pattern(frozenset({0, 7, 10}), frozenset({4, 12}), frozenset(range(0, 16, 2)))


def taught() -> NodMemory:
    """One nod kept: `push` in `GROOVE`."""
    nods = NodMemory()
    nods.nod(2, GROOVE, Features(kicks=3, hats=8), "push", "boom", "2026-11-24")
    return nods


def test_a_profile_round_trips(tmp_path: Path) -> None:
    path = tmp_path / PROFILE
    write_profile(path, SETTINGS, taught())
    data = json.loads(path.read_text())
    assert (data["format"], data["format_version"], data["settings"]) == (
        PROFILE_FORMAT,
        2,
        SETTINGS,
    )
    assert not list(tmp_path.glob("learn/.*")), "no partial file is left"
    profile = read_profile(path)
    fresh = NodMemory()
    apply_profile(profile, fresh)
    assert profile.settings == SETTINGS
    assert [(n.prototype, n.variation) for n in fresh.nods] == [(GROOVE, "push")]


def test_the_fields_of_likes_and_demo_in_a_version_2_profile_are_ignored(
    tmp_path: Path,
) -> None:
    path = tmp_path / PROFILE
    write_profile(path, SETTINGS, taught())
    data = json.loads(path.read_text())
    data["weights"] = {"bass": {"push/beat": {"home": 0.0, "push": 1.5, "drive": 0.0}}}
    data["examples"] = [{"part": "bass", "features": [6, 2, 1], "label": "drive", "bar": 3}]
    data["loops"] = {"bass": {}, "melody": {}}
    path.write_text(json.dumps(data))
    assert [n.variation for n in read_profile(path).nods] == ["push"]


@pytest.mark.parametrize(
    "text",
    [
        "{",
        json.dumps({"format": "mpc-iml-loop", "format_version": 1}),
        json.dumps({"format": PROFILE_FORMAT, "format_version": 2}),
        json.dumps({"format": PROFILE_FORMAT, "format_version": 2, "nods": {}}),
        json.dumps({"format": PROFILE_FORMAT, "format_version": 3, "nods": []}),
    ],
)
def test_a_bad_profile_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "ensemble.json"
    path.write_text(text)
    with pytest.raises(ValueError, match="ensemble.json"):
        read_profile(path)


def test_the_show_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "ensemble.json"
    write_profile(path, SETTINGS, taught())
    assert main(["show", str(path)]) == 0
    assert capsys.readouterr().out.startswith("nods: 1\n  bass push, 1 nod")
    assert main(["show", str(tmp_path / "none.json")]) == 1
    assert "error:" in capsys.readouterr().err


# In `ensemble`


def learning(folder: Path, learn: str = "nod") -> Rig:
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
    assert profile.settings == {**SETTINGS, "follow-by": "bar"}
    assert f"ensemble: saved the profile {tmp_path / PROFILE}" in rig.log


def test_learn_off_never_writes_the_profile(tmp_path: Path) -> None:
    rig = learning(tmp_path, "off")
    for bar in range(9):
        bar_of(rig, bar)
    assert not (tmp_path / "learn").exists()


def test_the_data_folder_loads_the_profile(tmp_path: Path) -> None:
    write_profile(tmp_path / PROFILE, SETTINGS, taught())
    rig = learning(tmp_path)
    assert reply(rig, "profile-errors") == [0]
    assert f"ensemble: loaded the profile {tmp_path / PROFILE}: 1 nods" in rig.log


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
    write_profile(tmp_path / PROFILE, SETTINGS, taught())
    rig = learning(tmp_path)
    rig.ensemble.controls()["reset-learning"]([])
    assert reply(rig, "learned") == ["-"]
    assert "ensemble: reset learning to the rules" in rig.log
    assert read_profile(tmp_path / PROFILE).nods, "the file changes only on a save"
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
