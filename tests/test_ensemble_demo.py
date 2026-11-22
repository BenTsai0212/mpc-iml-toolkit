"""`learn demo` in `ensemble` (#196, RFC 0005 step 8): pads 16 and 15 and the control
`want` mark the wanted variation, examples are added and the tree plays `auto`.

On the simulated DAW clock of `test_ensemble.py` (`Rig`).
"""

from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, Rig
from test_ensemble_learn import MELODY, STEADY, bar_of, reply
from test_melody import HAT

PUSHED = [(0, KICK), (6, KICK), (4, SNARE), (12, SNARE), (2, HAT)]
"""A bar in the bass context `push/beat` (rule `push`)."""


def demo(seed: int = 0) -> Rig:
    rig = Rig(melody=True, bass="loop", surprise=0, seed=seed)
    rig.ensemble.controls()["learn"](["demo"])
    rig.send(START)
    return rig


def press(rig: Rig, note: int) -> None:
    rig.until(14 * STEP)
    rig.hit(note, 100)


def play(rig: Rig, bars: range, hits: Any) -> None:
    for bar in bars:
        bar_of(rig, bar, hits=hits)


def test_pads_16_and_15_cycle_the_wanted_variations_and_keep_the_modes() -> None:
    rig = demo()
    for _ in range(3):
        press(rig, LAYER)
    press(rig, MELODY)
    assert reply(rig, "want") == ["drive", "home"]
    assert reply(rig, "bass") == ["loop", "loop"]
    assert reply(rig, "melody-mode") == ["follow", "follow"]
    assert rig.reports[-1]["want"] == ["drive", "home"]
    press(rig, LAYER)
    assert reply(rig, "want")[0] == "auto"
    assert "ensemble: want bass drive" in rig.log


def test_a_wanted_variation_plays_and_adds_examples() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["bass", "drive"])
    play(rig, range(3), STEADY)
    rig.until(3 * BAR + STEP)
    assert reply(rig, "variation")[0] == "drive"
    assert reply(rig, "chose") == ["want", "rule"]
    assert reply(rig, "examples") == [3, 0]


def test_a_bar_whose_want_changed_adds_no_example() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["bass", "drive"])
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    rig.until(2 * BAR + STEP)
    assert reply(rig, "want")[0] == "auto"
    assert reply(rig, "examples") == [1, 0]


def test_auto_plays_the_tree_after_enough_examples() -> None:
    rig = demo()
    controls = rig.ensemble.controls()
    controls["want"](["bass", "drive"])
    play(rig, range(0, 3), STEADY)
    controls["want"](["bass", "home"])
    play(rig, range(3, 6), PUSHED)
    controls["want"](["bass", "auto"])
    assert "ensemble: trained bass tree, 4 examples" in rig.log, "bars 2 and 5 changed"
    bar_of(rig, 6, hits=STEADY)
    rig.until(7 * BAR + STEP)
    assert reply(rig, "chose")[0] == "model"
    assert reply(rig, "variation")[0] == "drive", "the rules play home here"
    bar_of(rig, 7, hits=PUSHED)
    rig.until(8 * BAR + STEP)
    assert reply(rig, "variation")[0] == "home", "the rules play push here"
    assert reply(rig, "examples") == [4, 0]


def test_auto_plays_the_rules_before_a_tree() -> None:
    rig = demo()
    play(rig, range(2), PUSHED)
    rig.until(2 * BAR + STEP)
    assert reply(rig, "chose") == ["rule", "rule"]
    assert reply(rig, "variation")[0] == "push"
    assert reply(rig, "examples") == [0, 0]


def test_bars_without_drums_add_no_example() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["melody", "busy"])
    bar_of(rig, 0, hits=STEADY)
    bar_of(rig, 1, hits=[])
    bar_of(rig, 2, hits=[])
    assert reply(rig, "examples") == [0, 1]


def test_the_want_control_needs_demo_and_a_known_variation() -> None:
    rig = Rig(melody=True, bass="loop")
    controls = rig.ensemble.controls()
    with pytest.raises(ValueError, match="learn is not demo"):
        controls["want"](["bass", "push"])
    controls["learn"](["demo"])
    for bad in (["bass", "busy"], ["drums", "auto"], ["bass"]):
        with pytest.raises(ValueError):
            controls["want"](bad)
    controls["want"](["melody", "open"])
    assert reply(rig, "want") == ["auto", "open"]
    assert reply(rig, "learn") == ["demo"]
