"""`learn demo` in `ensemble` (#196, RFC 0005 step 8): pads 16 and 15 keep the variation
playing or move to the next one until the phrase end (#215), the control `want` marks
the wanted variation, examples are added and the tree plays `auto`.

On the simulated DAW clock of `test_ensemble.py` (`Rig`).
"""

from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, Rig
from test_ensemble_learn import MELODY, STEADY, bar_of, reply
from test_melody import HAT

from mpc_iml.clock import PadHit

PUSHED = [(0, KICK), (6, KICK), (4, SNARE), (12, SNARE), (2, HAT)]
"""A bar in the bass context `push/beat` (rule `push`)."""


def demo(seed: int = 0) -> Rig:
    rig = Rig(melody=True, bass="loop", surprise=0, seed=seed)
    rig.ensemble.controls()["learn"](["demo"])
    rig.send(START)
    return rig


def play(rig: Rig, bars: range, hits: Any) -> None:
    for bar in bars:
        bar_of(rig, bar, hits=hits)


def test_a_press_in_auto_keeps_the_variation_playing_and_adds_its_example() -> None:
    rig = demo()
    bar_of(rig, 0, hits=PUSHED)
    bar_of(rig, 1, press=8)
    assert reply(rig, "want") == ["push", "auto"], "the rules answered bar 0 with push"
    assert reply(rig, "examples") == [1, 0]
    assert "ensemble: want bass push (kept) to bar 4" in rig.log
    assert reply(rig, "bass") == ["loop", "loop"]
    assert reply(rig, "melody-mode") == ["follow", "follow"]
    assert rig.reports[-1]["want"] == ["push", "auto"]


def test_a_keep_in_the_first_beat_keeps_the_bar_before() -> None:
    rig = demo()
    bar_of(rig, 0, hits=PUSHED)
    bar_of(rig, 1)
    bar_of(rig, 2, press=1)
    assert reply(rig, "want")[0] == "push", "bar 2 plays home, bar 1 played push"
    assert reply(rig, "examples") == [1, 0]


def test_a_keep_in_a_silent_bar_marks_the_rules_choice_without_an_example() -> None:
    rig = demo()
    bar_of(rig, 0, hits=[])
    bar_of(rig, 1, press=8, hits=[])
    assert reply(rig, "want")[0] != "auto"
    assert reply(rig, "examples") == [0, 0]
    assert any(line.endswith("(kept, rules) to bar 4") for line in rig.log)


def test_more_presses_cycle_the_variations_without_auto_from_the_next_bar_line() -> None:
    rig = demo()
    bar_of(rig, 0)
    rig.until(BAR + 4 * STEP)
    wants = []
    for _ in range(4):
        rig.hit(LAYER)
        wants.append(reply(rig, "want")[0])
    assert wants == ["home", "push", "drive", "home"]
    rig.hit(MELODY)
    rig.hit(MELODY)
    assert reply(rig, "want")[1] != "auto"
    assert "ensemble: want bass push (next) to bar 4" in rig.log
    rig.hit(LAYER)
    rig.until(BAR + 8 * STEP)
    rig.hit(KICK)
    rig.until(2 * BAR + STEP)
    assert reply(rig, "variation")[0] == "push"
    assert reply(rig, "chose")[0] == "want"


def test_a_pad_want_lasts_to_the_phrase_end_and_its_last_bar_adds_an_example() -> None:
    rig = demo()
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    play(rig, range(2, 4), STEADY)
    rig.until(4 * BAR + STEP)
    assert reply(rig, "want") == ["auto", "auto"]
    assert reply(rig, "examples") == [3, 0], "bar 0 (the keep), bars 2 and 3"
    assert (
        "ensemble: want bass auto (phrase end), plays model (marked contexts, 1 label)" in rig.log
    )
    assert rig.reports[-1]["want"] == ["auto", "auto"]


def test_a_press_with_fewer_than_2_bars_left_lasts_one_phrase_more() -> None:
    rig = demo()
    play(rig, range(2), STEADY)
    bar_of(rig, 2, press=8)
    assert "ensemble: want bass home (kept) to bar 8" in rig.log
    play(rig, range(3, 8), STEADY)
    rig.until(7 * BAR + STEP)
    assert reply(rig, "want")[0] == "home"
    rig.until(8 * BAR + STEP)
    assert reply(rig, "want")[0] == "auto"


def test_a_bar_whose_want_changed_adds_no_example() -> None:
    rig = demo()
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    bar_of(rig, 2, press=8)
    rig.until(3 * BAR + STEP)
    assert reply(rig, "want")[0] == "push"
    assert reply(rig, "examples") == [1, 0], "only the keep's example"


def test_the_want_control_holds_past_the_phrase_end() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["bass", "drive"])
    play(rig, range(6), STEADY)
    assert reply(rig, "want")[0] == "drive"
    assert not [line for line in rig.log if "phrase end" in line]


def test_a_pad_want_needs_a_running_clock() -> None:
    rig = Rig(clock=False, melody=True, bass="loop")
    rig.ensemble.controls()["learn"](["demo"])
    rig.ensemble.on_pad(PadHit(0.0, LAYER - 36, 0, 100, None))
    assert reply(rig, "want") == ["auto", "auto"]
    assert "ensemble: pad 16 ignored, the clock is not running" in rig.log


def test_a_wanted_variation_plays_and_adds_examples() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["bass", "drive"])
    play(rig, range(3), STEADY)
    rig.until(3 * BAR + STEP)
    assert reply(rig, "variation")[0] == "drive"
    assert reply(rig, "chose") == ["want", "rule"]
    assert reply(rig, "examples") == [3, 0]


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


def test_before_a_tree_the_marked_drums_play_what_was_marked() -> None:
    rig = demo()
    rig.ensemble.controls()["want"](["bass", "drive"])
    play(rig, range(3), STEADY)
    rig.ensemble.controls()["want"](["bass", "auto"])
    assert reply(rig, "examples") == [2, 0], "one variation: no tree"
    bar_of(rig, 3, hits=STEADY)
    rig.until(4 * BAR + STEP)
    assert reply(rig, "variation")[0] == "drive", "the rules play home here"
    assert reply(rig, "chose")[0] == "model"
    bar_of(rig, 4, hits=PUSHED)
    rig.until(5 * BAR + STEP)
    assert reply(rig, "variation")[0] == "push", "other drums play the rules"
    assert reply(rig, "chose")[0] == "rule"


def test_a_phrase_end_logs_what_auto_plays() -> None:
    rig = demo()
    play(rig, range(2), STEADY)
    bar_of(rig, 2, press=8)
    play(rig, range(3, 8), STEADY)
    rig.until(8 * BAR + STEP)
    assert (
        "ensemble: want bass auto (phrase end), plays model (marked contexts, 1 label)" in rig.log
    )
    bar_of(rig, 8, press=8, hits=PUSHED)
    bar_of(rig, 9, press=8, hits=PUSHED)
    play(rig, range(10, 12), PUSHED)
    rig.until(12 * BAR + STEP)
    assert "ensemble: trained bass tree" in " ".join(rig.log)
    assert "ensemble: want bass auto (phrase end), plays model (tree)" in rig.log


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
