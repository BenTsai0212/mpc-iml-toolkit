"""Learning in `ensemble` (#196, RFC 0005 step 8): `learn off|likes`, pad 16 as like,
the control `like` and the replies `learn`, `likes`, `chose` and `learned`.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). `learn off` must play
exactly what `main` played before the wiring: `tests/data/ensemble-learn-off.json`
was written from `main` with `SESSIONS` before `learn` existed.
"""

import json
from pathlib import Path
from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, Rig
from test_ensemble_rhythm import PATTERN
from test_melody import HAT

DATA = Path(__file__).parent / "data" / "ensemble-learn-off.json"
"""What `main` played before #196's wiring for `SESSIONS`."""

MELODY = 50
"""Note of pad 15 (the melody pad), bank A."""

SESSIONS: dict[str, dict[str, Any]] = {
    "boom-lead": {"bass-loop": "boom", "loop": "keys", "no-drums": "lead", "surprise": 1},
    "walk-hold": {"bass-loop": "walk", "loop": "pluck", "no-drums": "hold", "surprise": 2},
    "boom-thin": {
        "bass-loop": "boom",
        "loop": "keys",
        "no-drums": "thin",
        "surprise": 2,
        "progression": "minor-four",
    },
    "pads": {"bass-loop": "walk", "loop": "keys", "no-drums": "lead", "surprise": 2},
}
"""Scripted sessions: settings, with the seeds of `SEEDS`; `pads` also presses pads
15 and 16 (`PRESSES`)."""

SEEDS = {"boom-lead": 3, "walk-hold": 7, "boom-thin": 11, "pads": 5}
PRESSES = {3: LAYER, 5: MELODY, 7: LAYER, 9: MELODY, 10: LAYER, 11: MELODY}
"""Bar -> pad pressed at its step 2, in the session `pads`."""


def session(name: str, learn: str | None) -> dict[str, list[Any]]:
    """Every Note On and CC (tick, status, data 1, data 2) and every reported
    `variation` and `transform` of the session `name`; `learn` None keeps the
    default of a new `Ensemble`."""
    settings = SESSIONS[name]
    rig = Rig(melody=True, bass="loop", surprise=settings["surprise"], seed=SEEDS[name])
    controls = rig.ensemble.controls()
    for control, value in settings.items():
        if control != "surprise":
            controls[control]([value])
    if learn is not None:
        controls["learn"]([learn])
    rig.send(START)
    for repeat in range(2):
        for i, hits in enumerate(PATTERN):
            bar = repeat * len(PATTERN) + i
            pressed = [(2, PRESSES[bar], 0.0)] if name == "pads" and bar in PRESSES else []
            for step, note, ticks in sorted(hits + pressed):
                rig.until(bar * BAR + step * STEP)
                rig.hit(note, 100, ticks)
            rig.until((bar + 1) * BAR)
    rig.until((2 * len(PATTERN) + 1) * BAR)
    sent = [[t, *m] for t, m in rig.sent if m[0] & 0xF0 in (0x90, 0xB0)]
    reports = [
        [*r["bass"], *r["melody-mode"], *r["variation"], *r["transform"]] for r in rig.reports
    ]
    return {"sent": sent, "reports": reports}


def test_learn_off_plays_exactly_what_main_played() -> None:
    before = json.loads(DATA.read_text())
    assert sorted(before) == sorted(SESSIONS)
    for name in SESSIONS:
        assert session(name, None) == before[name], name
        assert session(name, "off") == before[name], name


def write_golden() -> None:
    """Write `DATA` (run once from `main`, before the wiring)."""
    DATA.write_text(json.dumps({n: session(n, None) for n in SESSIONS}, indent=None) + "\n")


STEADY = [(0, KICK), (4, SNARE), (8, KICK), (12, SNARE), (2, HAT), (6, HAT), (10, HAT)]
"""A bar in the bass context `grid/beat` (rule `home`) and melody `mid/8ths` (`home`)."""


def likes(seed: int = 0) -> Rig:
    rig = Rig(melody=True, bass="loop", seed=seed)
    rig.ensemble.controls()["learn"](["likes"])
    rig.send(START)
    return rig


def bar_of(rig: Rig, bar: int, press: int | None = None, hits: Any = STEADY) -> None:
    """Play `hits` in `bar`, pressing pad 16 at step `press`."""
    pressed = [] if press is None else [(press, LAYER)]
    for step, note in sorted(hits + pressed):
        rig.until(bar * BAR + step * STEP)
        rig.hit(note, 100)
    rig.until((bar + 1) * BAR)


def reply(rig: Rig, name: str) -> list[Any]:
    return dict(rig.ensemble.state())[name]


def test_pad_16_likes_the_bar_playing_and_keeps_the_bass_mode() -> None:
    rig = likes()
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    assert reply(rig, "bass") == ["loop", "loop"]
    assert reply(rig, "likes") == [1]
    (line,) = [line for line in rig.log if line.startswith("ensemble: like")]
    assert line.startswith("ensemble: like bar 1 bass grid/beat>")
    assert " melody mid/8ths>" in line
    assert rig.reports[-1]["likes"] == [1]


def test_a_like_in_the_first_beat_credits_the_bar_before() -> None:
    rig = likes()
    bar_of(rig, 0)
    bar_of(rig, 1)
    bar_of(rig, 2, press=1)
    assert any(line.startswith("ensemble: like bar 1 ") for line in rig.log)


def test_a_bar_without_a_learned_choice_credits_nothing() -> None:
    rig = likes()
    bar_of(rig, 0, press=8)
    assert reply(rig, "likes") == [0]
    assert "ensemble: like bar 0, no learned choice to credit" in rig.log


def test_likes_teach_a_choice_and_the_reply_shows_it() -> None:
    rig = likes(seed=1)
    liked = None
    for bar in range(12):
        bar_of(rig, bar)
        rig.until((bar + 1) * BAR - STEP)
        variation = reply(rig, "variation")[0]
        if bar and liked is None and variation != "home":
            liked = variation
            for _ in range(4):
                rig.ensemble.controls()["like"]([])
    assert liked is not None
    assert reply(rig, "learned")[0] == f"bass:grid/beat>{liked}"
    assert f"ensemble: learned bass grid/beat>{liked} (rule home)" in rig.log


def test_chose_tells_rules_from_the_learner() -> None:
    off, on = Rig(melody=True, bass="loop"), likes()
    off.send(START)
    for rig in (off, on):
        bar_of(rig, 0)
        rig.until(BAR + STEP)
    assert reply(off, "chose") == ["rule", "rule"]
    assert reply(on, "chose") == ["bandit", "bandit"]
    assert reply(on, "learn") == ["likes"] and reply(off, "learned") == ["-"]


def test_the_like_control_needs_likes_and_a_running_clock() -> None:
    rig = Rig(melody=True, bass="loop")
    with pytest.raises(ValueError, match="learn is not likes"):
        rig.ensemble.controls()["like"]([])
    rig.ensemble.controls()["learn"](["likes"])
    with pytest.raises(ValueError, match="not running"):
        rig.ensemble.controls()["like"]([])
    with pytest.raises(ValueError):
        rig.ensemble.controls()["learn"](["teach"])


if __name__ == "__main__":
    write_golden()
