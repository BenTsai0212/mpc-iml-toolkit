"""The nods in the profile and the learn log (#250 PR 5, ADR 0009 "Amendment: learning
by groove", "The profile" and "Status line, logs and replies"): profile format version
2, a nod found again in a later session by its prototype, the version 1 rename,
`python -m mpc_iml.learn show`, the learn log's `nod` field and `summary`."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_ensemble_follow_groove import A_PUSHED, basses
from test_ensemble_grooves import A, B
from test_ensemble_learn import reply
from test_ensemble_nod import lines, rig, session

from mpc_iml.grooves import Features, Pattern
from mpc_iml.grooves.nods import NodMemory
from mpc_iml.learn_log import summary
from mpc_iml.learn_profile import (
    OLD_PROFILE,
    PROFILE,
    OldProfile,
    apply_profile,
    read_profile,
    show,
    write_profile,
)

GROOVE = Pattern(frozenset({0, 7, 10}), frozenset({4, 12}), frozenset(range(0, 16, 2)))
OTHER = Pattern(frozenset({0, 8}), frozenset({4, 12}), frozenset())
V1 = {
    "format": "mpc-iml-ensemble-profile",
    "format_version": 1,
    "toolkit": "0.1.0",
    "settings": {},
    "weights": {},
    "examples": [],
}


def write(path: Path, nods: NodMemory) -> None:
    write_profile(path, {"follow-by": "groove"}, nods)


def kept() -> NodMemory:
    nods = NodMemory()
    nods.nod(1, OTHER, Features(kicks=2), "drive", "boom", "2026-11-23")
    nods.nod(2, GROOVE, Features(kicks=3, hats=8), "push", "boom", "2026-11-24")
    nods.nod(2, GROOVE, Features(kicks=3, hats=8), "push", "boom", "2026-11-24")
    return nods


def test_the_nods_round_trip_the_most_recent_first(tmp_path: Path) -> None:
    path = tmp_path / PROFILE
    write(path, kept())
    data = json.loads(path.read_text())
    assert data["format_version"] == 2
    assert sorted(data) == ["format", "format_version", "nods", "settings", "toolkit"]
    assert data["nods"][0] == {
        "prototype": {"kick": [0, 7, 10], "snare": [4, 12], "hat": list(range(0, 16, 2))},
        "features": Features(kicks=3, hats=8).as_dict(),
        "part": "bass",
        "variation": "push",
        "nods": 2,
        "loop": "boom",
        "last": "2026-11-24",
    }
    profile = read_profile(path)
    assert [(n.prototype, n.variation, n.nods) for n in profile.nods] == [
        (GROOVE, "push", 2),
        (OTHER, "drive", 1),
    ]
    fresh = NodMemory()
    fresh.nod(9, A_PATTERN, Features(), "home")
    apply_profile(profile, fresh)
    assert [n.variation for n in fresh.nods] == ["push", "drive"]
    assert fresh.bound_grooves() == ()
    assert fresh.match(5, GROOVE, GROOVE) is fresh.nods[0]


A_PATTERN = Pattern(frozenset({1}))


@pytest.mark.parametrize(
    "nod",
    [
        {"variation": "bounce"},
        {"part": "drums"},
        {"nods": 0},
        {"nods": True},
        {"prototype": {"kick": [16], "snare": [], "hat": []}},
        {"prototype": {"kick": [], "snare": []}},
        {"features": {"kicks": 1}},
        {"last": 3},
        {"extra": 1},
    ],
)
def test_a_bad_nod_is_refused(tmp_path: Path, nod: dict[str, Any]) -> None:
    path = tmp_path / PROFILE
    write(path, kept())
    data = json.loads(path.read_text())
    data["nods"][0].update(nod)
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="mpc-iml-ensemble-profile 2: bad"):
        read_profile(path)


def test_a_version_1_profile_is_old(tmp_path: Path) -> None:
    path = tmp_path / PROFILE
    path.parent.mkdir()
    path.write_text(json.dumps(V1))
    with pytest.raises(OldProfile, match="version 1"):
        read_profile(path)


def test_show_lists_the_nods_with_their_grids(tmp_path: Path) -> None:
    path = tmp_path / PROFILE
    write(path, kept())
    text = show(read_profile(path)).splitlines()
    assert text[:5] == [
        "nods: 2",
        "  bass push, 2 nods, last 2026-11-24",
        "    kick  x... ...x ..x. ....",
        "    snare .... x... .... x...",
        "    hat   x.x. x.x. x.x. x.x.",
    ]
    assert text[5] == "  bass drive, 1 nod, last 2026-11-23"


def test_a_nod_is_found_again_in_a_later_session(tmp_path: Path) -> None:
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    assert f"ensemble: saved the profile {tmp_path / PROFILE}" in played.log
    (stored,) = read_profile(tmp_path / PROFILE).nods
    assert stored.variation == "push"
    assert read_profile(tmp_path / PROFILE).settings["follow-by"] == "bar"

    later = rig("bar")
    later.ensemble.data_folder(tmp_path)
    assert any(line.endswith(": 1 nods") for line in later.log)
    session(later, [A, A, A, A, A], {})
    assert "ensemble: groove 1 back, bass push (nod from profile)" in later.log
    shown = basses(later)
    assert [shown[b] for b in (3, 4, 5)] == ["bass push (nod)"] * 3
    assert reply(later, "chose") == ["nod", "rule"]


def test_a_stored_nod_is_not_taken_by_another_groove(tmp_path: Path) -> None:
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    later = rig("bar")
    later.ensemble.data_folder(tmp_path)
    session(later, [B, B, B, B], {})
    assert not lines(later, "ensemble: groove 1 back")
    assert "nod" not in " ".join(basses(later).values())


def test_reset_learning_forgets_the_nods_and_saves_none(tmp_path: Path) -> None:
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    played.ensemble.controls()["reset-learning"]([])
    played.ensemble.controls()["save-profile"]([])
    assert read_profile(tmp_path / PROFILE).nods == []


def test_a_version_1_profile_is_renamed_once_and_learning_starts_empty(tmp_path: Path) -> None:
    (tmp_path / "learn").mkdir()
    (tmp_path / PROFILE).write_text(json.dumps(V1))
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    assert "ensemble: profile version 1 (likes/demo) kept as learn/ensemble-v1.json" in played.log
    assert json.loads((tmp_path / OLD_PROFILE).read_text()) == V1
    assert not (tmp_path / PROFILE).exists()
    assert reply(played, "profile-errors") == [0]
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    assert len(read_profile(tmp_path / PROFILE).nods) == 1
    assert json.loads((tmp_path / OLD_PROFILE).read_text()) == V1


def test_a_version_1_profile_is_not_renamed_over_an_old_one(tmp_path: Path) -> None:
    (tmp_path / "learn").mkdir()
    (tmp_path / PROFILE).write_text(json.dumps(V1))
    (tmp_path / OLD_PROFILE).write_text("{}")
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    assert reply(played, "profile-errors") == [1]
    assert any("not renamed" in line for line in played.log)
    session(played, [A, A, A_PUSHED, A, A, A], {3: 8})
    assert json.loads((tmp_path / PROFILE).read_text()) == V1
    assert (tmp_path / OLD_PROFILE).read_text() == "{}"
    with pytest.raises(ValueError, match="version 1"):
        played.ensemble.controls()["load-profile"]([])


def logged(tmp_path: Path, bars: list[Any], nods: dict[int, int]) -> list[dict[str, Any]]:
    played = rig("bar")
    played.ensemble.data_folder(tmp_path)
    played.ensemble.controls()["learn-log"]([1])
    session(played, bars, nods)
    played.ensemble.controls()["learn-log"]([0])
    (log,) = (tmp_path / "learn").glob("log-*.jsonl")
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_the_learn_log_has_the_nod_on_the_line_of_its_bar(tmp_path: Path) -> None:
    header, *bars = logged(tmp_path, [A, A, A_PUSHED, A, A, A, B, B, B], {0: 8, 3: 8, 7: 8})
    nods = {b["bar"]: b["nod"] for b in bars if b["nod"] is not None}
    assert nods == {
        0: {"bar": 0, "groove": None, "variation": None, "from": "none"},
        3: {"bar": 3, "groove": 1, "variation": "push", "from": "bar"},
        7: {"bar": 7, "groove": 2, "variation": "push", "from": "bar"},
    }
    text = summary(header, bars).splitlines()
    assert text[-3] == (
        "nods: 3, 2 kept a variation, grooves nodded: 2; "
        "bass bars from a nod 5, a group 0, an invite 0"
    )
    assert text[-2:] == [
        "groove changes: 1, the bass changed in 0",
        "  bar 8: groove 1 -> 2, bass push -> push (same)",
    ]


def test_the_summary_counts_the_groove_changes_where_the_bass_stayed() -> None:
    def line(bar: int, groove: int | None, bass: str) -> dict[str, Any]:
        choice = {"bass": {"variation": bass}, "melody": None}
        return {
            "bar": bar,
            "learn": "off",
            "choice": choice,
            "rule": {"bass": bass, "melody": "home"},
            "source": {"bass": "rule", "melody": "-"},
            "groove": {"id": groove, "position": 1, "fill": False, "free": groove is None},
        }

    bars = [line(1, 1, "home"), line(2, None, "push"), line(3, 2, "home"), line(4, 1, "push")]
    text = summary({"toolkit": "0.1.0"}, bars).splitlines()
    assert text[-3:] == [
        "groove changes: 2, the bass changed in 1",
        "  bar 3: groove 1 -> 2, bass home -> home (same)",
        "  bar 4: groove 2 -> 1, bass home -> push",
    ]
    assert not any(t.startswith("nods:") for t in text)
