"""Following the groove in `ensemble` (#250 PR 3, ADR 0009 "Amendment: learning by
groove"): `follow-by groove`, `answer-after`, the fill answer and the replies.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). `follow-by bar` (the
default) plays exactly as before: the golden files of `test_ensemble_learn.py` and
`test_ensemble_rhythm.py` do not change. `tests/data/ensemble-follow-groove.json`
holds what `follow-by groove` plays for `SESSIONS` (`write_golden`), so a later
change to groove following shows in a diff.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from test_ensemble import BAR, KICK, SNARE, START, STEP, Rig
from test_ensemble_grooves import FILL, SILENT, A, B, play
from test_melody import HAT

from mpc_iml.ensemble import groove_choices
from mpc_iml.grooves import Pattern
from mpc_iml.learn_log import read_log

DATA = Path(__file__).parent / "data" / "ensemble-follow-groove.json"
"""What `follow-by groove` plays for `SESSIONS`."""

A_PUSHED = A + [(11, KICK)]
"""Groove A with a kick off the quarter grid: still groove A (0.93), but the per-bar
rules give the bass `push` where A gives `home`."""

BARS = [A, A, A_PUSHED, A, FILL, A, A_PUSHED, A, B, B, B, FILL, B, A, A, SILENT, A, A]
"""Groove A with pushed bars and a fill, a change to B, a fill, a return to A and a
silent bar."""

SESSIONS: dict[str, dict[str, Any]] = {
    "boom-lead": {"bass-loop": "boom", "loop": "keys", "no-drums": "lead", "surprise": 1},
    "walk-hold": {
        "bass-loop": "walk",
        "loop": "pluck",
        "no-drums": "hold",
        "surprise": 2,
        "rhythm": 2,
    },
    "answer-1": {
        "bass-loop": "boom",
        "loop": "keys",
        "no-drums": "lead",
        "surprise": 1,
        "answer-after": 1,
    },
}
SEEDS = {"boom-lead": 3, "walk-hold": 7, "answer-1": 5}


def rig(follow_by: str = "groove", seed: int = 1, **controls: Any) -> Rig:
    played = Rig(melody=True, bass="loop", status=1, seed=seed)
    played.ensemble.controls()["follow-by"]([follow_by])
    for name, value in controls.items():
        played.ensemble.controls()[name.replace("_", "-")]([value])
    played.send(START)
    return played


def basses(played: Rig) -> dict[int, str]:
    """Bar -> the bass field of its status line at the bar line (`bass push (rule)`)."""
    shown = {}
    for line in played.log:
        if line.startswith("ensemble: bar "):
            fields = line.split("  ")
            shown[int(fields[0].split()[2])] = fields[3]
    return shown


def bass_steps(played: Rig, bar: int) -> list[int]:
    """The steps of the bass's Note Ons (channel 2) in `bar`."""
    return [
        (t - bar * BAR) // STEP
        for t, m in played.sent
        if m[0] == 0x91 and m[2] > 0 and bar * BAR <= t < (bar + 1) * BAR
    ]


def session(name: str) -> dict[str, list[Any]]:
    """Every Note On and CC and every reported `variation`, `transform` and `chose`
    of the session `name` with `follow-by groove`."""
    settings = dict(SESSIONS[name])
    played = Rig(melody=True, bass="loop", surprise=settings.pop("surprise"), seed=SEEDS[name])
    controls = played.ensemble.controls()
    controls["follow-by"](["groove"])
    for control, value in settings.items():
        controls[control]([value])
    played.send(START)
    play(played, BARS)
    played.until((len(BARS) + 1) * BAR)
    sent = [[t, *m] for t, m in played.sent if m[0] & 0xF0 in (0x90, 0xB0)]
    reports = [[*r["variation"], *r["transform"], *r["chose"]] for r in played.reports]
    return {"sent": sent, "reports": reports}


def test_follow_by_groove_plays_the_golden_sessions() -> None:
    before = json.loads(DATA.read_text())
    assert sorted(before) == sorted(SESSIONS)
    for name in SESSIONS:
        assert session(name) == before[name], name


def write_golden() -> None:
    """Write `DATA` (again, when a change to groove following is meant)."""
    DATA.write_text(json.dumps({n: session(n) for n in SESSIONS}, indent=None) + "\n")


def test_the_rules_read_the_prototype_so_the_variation_holds_in_the_groove() -> None:
    grooved, per_bar = rig(), rig("bar")
    for played in (grooved, per_bar):
        play(played, [A, A, A_PUSHED, A, A_PUSHED])
    assert [basses(per_bar)[b] for b in (3, 4, 5)] == [
        "bass push (rule)",
        "bass home (rule)",
        "bass push (rule)",
    ]
    assert [basses(grooved)[b] for b in (3, 4, 5)] == ["bass home (rule)"] * 3


def test_groove_choices_are_the_rules_on_the_prototype() -> None:
    steady = Pattern(frozenset({0, 8}), frozenset({4, 12}), frozenset({2, 6, 10}))
    assert groove_choices(steady) == (("home", 1), ("home", 1))
    busy = Pattern(frozenset({0, 3, 6, 8, 11}), frozenset({4, 12}), frozenset(range(0, 16, 2)))
    assert groove_choices(busy) == (("drive", 2), ("busy", 2))


def test_after_a_fill_bar_the_bass_keeps_the_groove_and_plays_its_fill() -> None:
    played = rig()
    play(played, [A, A, A, FILL, A, A])
    shown = basses(played)
    assert shown[4] == "bass home (fill)"
    assert shown[5] == shown[6] == "bass home (rule)"
    assert bass_steps(played, 4)[-4:] == [12, 13, 14, 15]
    assert bass_steps(played, 5)[-4:] != [12, 13, 14, 15]
    assert played.ensemble.state()[-5:-1] == [
        ("follow-by", ["groove"]),
        ("learn-group", [0]),
        ("new-groove", ["rules"]),
        ("answer-after", [2]),
    ]
    assert dict(played.ensemble.state())["chose"] == ["rule", "rule"]


def test_a_fill_answer_draws_no_surprise() -> None:
    played = rig(surprise=1)

    class Always:
        def random(self) -> float:
            return 0.0

        def choice(self, items: list[str]) -> str:
            return items[0]

    played.ensemble._random = Always()  # type: ignore[assignment]
    play(played, [A, A, A, A, A, A, FILL, A, A, A, A, A])
    surprises = [line for line in played.log if line.startswith("ensemble: surprise")]
    assert surprises == ["ensemble: surprise fill in bar 3", "ensemble: surprise fill in bar 11"]
    assert basses(played)[7] == "bass home (fill)"


def test_a_new_groove_is_answered_from_the_bar_after_its_second_bar() -> None:
    grooved, per_bar = rig(), rig("bar")
    for played in (grooved, per_bar):
        play(played, [A, A, A, B, B, B])
    assert [basses(per_bar)[b] for b in (4, 5)] == ["bass push (rule)"] * 2
    assert basses(grooved)[4] == "bass home (fill)"
    assert basses(grooved)[5] == basses(grooved)[6] == "bass push (rule)"


def test_answer_after_1_answers_a_different_bar_at_once_and_goes_back() -> None:
    played = rig(answer_after=1)
    play(played, [A, A, A, B, A, A])
    shown = basses(played)
    assert [shown[b] for b in (4, 5, 6)] == [
        "bass push (rule)",
        "bass home (rule)",
        "bass home (rule)",
    ]
    assert bass_steps(played, 4)[-4:] != [12, 13, 14, 15]


def test_free_bars_and_bars_before_a_groove_follow_each_bar() -> None:
    roll = [(s, KICK) for s in range(16)]
    played = rig()
    play(played, [A_PUSHED, A, A, FILL, roll, FILL, roll, A_PUSHED, B])
    shown = basses(played)
    assert shown[1] == "bass push (rule)"
    assert shown[5] == shown[7] == "bass home (fill)"
    assert shown[8] == "bass push (rule)"


def test_without_kicks_no_drums_still_applies() -> None:
    played = rig()
    snares = [(4, SNARE), (12, SNARE), (2, HAT)]
    play(played, [A, A, A, snares, A])
    assert basses(played)[4] == "bass home (fill)"
    play(played, [SILENT, SILENT, A], first=5)
    assert basses(played)[7] == "bass home (rule)"


@pytest.mark.parametrize(
    ("control", "value"), [("follow-by", "each"), ("answer-after", 3), ("answer-after", 0)]
)
def test_bad_values_are_refused(control: str, value: Any) -> None:
    played = Rig()
    with pytest.raises(ValueError):
        played.ensemble.controls()[control]([value])


def test_the_learn_log_has_the_settings_and_the_fill_source(tmp_path: Path) -> None:
    played = Rig(melody=True, bass="loop", seed=1)
    controls = played.ensemble.controls()
    controls["follow-by"](["groove"])
    played.ensemble.data_folder(tmp_path)
    controls["learn-log"]([1])
    played.send(START)
    play(played, [A, A, A, FILL, A])
    controls["learn-log"]([0])
    (path,) = (tmp_path / "learn").glob("log-*.jsonl")
    header, bars = read_log(path)
    assert header["settings"]["follow-by"] == "groove"
    assert header["settings"]["answer-after"] == "2"
    by_bar = {b["bar"]: b for b in bars}
    assert by_bar[4]["source"]["bass"] == "fill"
    assert by_bar[2]["rule"] == {"bass": "home", "melody": "home"}
