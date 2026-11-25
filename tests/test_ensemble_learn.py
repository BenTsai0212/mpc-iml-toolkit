"""Learning in `ensemble` (#196, #250, RFC 0005 step 8): `learn off` plays as before,
`learn likes`, `learn demo` and their controls are refused naming the nod (#250),
and the replies they had keep their values.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). `learn off` must play
exactly what `main` played before the wiring: `tests/data/ensemble-learn-off.json`
was written from `main` with `SESSIONS` before `learn` existed, and written again
for #218 with only the brightness CC values changed (`write_golden`).
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


def session(name: str, learn: str | None, log: Path | None = None) -> dict[str, list[Any]]:
    """Every Note On and CC (tick, status, data 1, data 2) and every reported
    `variation` and `transform` of the session `name`; `learn` None keeps the
    default of a new `Ensemble`; with the data folder `log`, `learn-log 1`. The status
    line is on (#230), so the golden files check that it changes nothing that plays."""
    settings = SESSIONS[name]
    rig = Rig(melody=True, bass="loop", surprise=settings["surprise"], seed=SEEDS[name], status=1)
    controls = rig.ensemble.controls()
    for control, value in settings.items():
        if control != "surprise":
            controls[control]([value])
    if learn is not None:
        controls["learn"]([learn])
    if log is not None:
        rig.ensemble.data_folder(log)
        controls["learn-log"]([1])
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


def bar_of(rig: Rig, bar: int, press: int | None = None, hits: Any = STEADY) -> None:
    """Play `hits` in `bar`, pressing pad 16 at step `press`."""
    pressed = [] if press is None else [(press, LAYER)]
    for step, note in sorted(hits + pressed):
        rig.until(bar * BAR + step * STEP)
        rig.hit(note, 100)
    rig.until((bar + 1) * BAR)


def reply(rig: Rig, name: str) -> list[Any]:
    return dict(rig.ensemble.state())[name]


PUSHED = [(0, KICK), (6, KICK), (4, SNARE), (12, SNARE), (2, HAT)]
"""A bar in the bass context `push/beat` (rule `push`)."""


@pytest.mark.parametrize("mode", ["likes", "demo"])
def test_learn_likes_and_demo_are_refused_naming_the_nod(mode: str) -> None:
    rig = Rig(melody=True, bass="loop")
    with pytest.raises(ValueError, match=f"learn {mode} was removed .*learn nod"):
        rig.ensemble.controls()["learn"]([mode])
    assert reply(rig, "learn") == ["off"]
    with pytest.raises(ValueError, match="expected one of off, nod"):
        rig.ensemble.controls()["learn"](["teach"])


@pytest.mark.parametrize(
    ("control", "args"), [("like", []), ("want", ["bass", "push"]), ("learn-loops", [1])]
)
def test_the_controls_of_likes_and_demo_are_refused_naming_the_nod(
    control: str, args: list[Any]
) -> None:
    rig = Rig(melody=True, bass="loop")
    with pytest.raises(ValueError, match=f"{control} was removed .*use learn nod"):
        rig.ensemble.controls()[control](args)


def test_the_replies_of_likes_and_demo_stay_in_the_list() -> None:
    rig = Rig(melody=True, bass="loop")
    rig.send(START)
    bar_of(rig, 0)
    rig.until(BAR + STEP)
    names = [name for name, _ in rig.ensemble.state()]
    assert names.index("learned") + 1 == names.index("want")
    assert reply(rig, "want") == ["auto", "auto"]
    assert reply(rig, "examples") == [0, 0]
    assert reply(rig, "learn-loops") == [0]
    assert reply(rig, "chose") == ["rule", "rule"]
    assert reply(rig, "learned") == ["-"]


if __name__ == "__main__":
    write_golden()
