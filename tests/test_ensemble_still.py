"""`melody-mode still` in `ensemble` (#233): the melody plays `home` every bar with one
brightness value while the bass follows the kicks, with its rules and learning.

On the simulated DAW clock of `test_ensemble.py` (`Rig`).
"""

from typing import Any

import pytest
from test_ensemble import BAR, KICK, SNARE, START, STEP, Rig
from test_ensemble_learn import MELODY, STEADY, bar_of, reply
from test_melody import HAT

from mpc_iml.ensemble import MELODY_MODES, STILL_BRIGHTNESS, for_musician
from mpc_iml.learn import CONTEXTS

SPARSE = [(0, KICK), (8, KICK), (4, SNARE), (12, SNARE)]
"""Kicks on the beat: the bass rule plays `home`."""

SYNCOPATED = [(0, KICK), (6, KICK), (10, KICK), (4, SNARE), (12, SNARE)] + [
    (s, HAT) for s in range(0, 16, 2)
]
"""Kicks off the beat: `push`."""

DENSE = [(s, KICK) for s in (0, 2, 4, 8, 12)] + [(s, HAT) for s in range(16)]
"""5 kicks: `drive`."""

BARS = [SPARSE, SYNCOPATED, DENSE, [], SPARSE, DENSE, SYNCOPATED, SPARSE]
"""The bars played; bar 3 has no drums."""

MELODY_CC = 0xB2
"""A CC on the melody channel (3)."""


def played(mode: str, bars: Any = BARS) -> tuple[Rig, list[list[Any]]]:
    """Play `bars` with `melody-mode mode`; the `variation` reply after each bar line."""
    rig = Rig(melody=True, bass="loop")
    rig.ensemble.controls()["melody-mode"]([mode])
    rig.send(START)
    variations = []
    for bar, hits in enumerate(bars):
        bar_of(rig, bar, hits=hits)
        rig.until((bar + 1) * BAR + STEP)
        variations.append(reply(rig, "variation"))
    return rig, variations


def channel(rig: Rig, status: int) -> list[tuple[int, int, int]]:
    """(tick, data 1, data 2) of the messages with `status`."""
    return [(t, m[1], m[2]) for t, m in rig.sent if m[0] == status]


def test_still_bass_follows_as_in_follow_and_the_melody_plays_home_with_one_brightness() -> None:
    follow, follow_variations = played("follow")
    still, still_variations = played("still")
    bass = [v[0] for v in still_variations]
    assert bass == [v[0] for v in follow_variations]
    assert bass[:3] == ["home", "push", "drive"]
    assert channel(still, 0x91) == channel(follow, 0x91), "the same bass notes"
    assert [v[1] for v in still_variations] == ["home"] * len(BARS)
    assert {v[1] for v in follow_variations} != {"home"}, "follow changes the melody"
    values = {m[2] for _, m in still.sent if m[0] == MELODY_CC}
    assert values == {STILL_BRIGHTNESS}
    assert len({m[2] for _, m in follow.sent if m[0] == MELODY_CC}) > 1
    assert reply(still, "melody-mode") == ["still", "still"]
    assert reply(still, "chose") == ["rule", "still"]
    assert "melody home (still)" in still.ensemble.status_line(len(BARS))


def test_still_plays_the_same_melody_whatever_the_drums_and_without_them() -> None:
    still, _ = played("still")
    quiet, variations = played("still", [SPARSE] + [[]] * (len(BARS) - 1))
    assert [v[1] for v in variations] == ["home"] * len(BARS), "no-drums: keeps playing"
    for status in (0x92, MELODY_CC):
        assert channel(still, status) == channel(quiet, status)
    assert [t for t, _, _ in channel(quiet, 0x92) if t >= (len(BARS) - 1) * BAR]


def test_the_status_line_and_state_report_still() -> None:
    rig = Rig(melody=True, bass="loop", status=1)
    rig.ensemble.controls()["melody-mode"](["still"])
    rig.send(START)
    bar_of(rig, 0, hits=SYNCOPATED)
    rig.until(BAR + STEP)
    line = rig.ensemble.status_line(1)
    assert "bass push (rule)" in line and "melody home (still)" in line
    assert line.endswith("15: melody fixed"), "pad 15 cycles on from follow"


def test_the_controls_set_and_leave_still() -> None:
    rig = Rig(melody=True, bass="loop")
    controls = rig.ensemble.controls()
    controls["melody"](["still"])
    assert reply(rig, "melody-mode") == ["still", "still"]
    controls["melody"]([0])
    assert reply(rig, "melody-mode") == ["off", "off"]
    controls["melody"]([1])
    assert reply(rig, "melody-mode") == ["still", "still"]
    controls["follow"]([1])
    assert reply(rig, "melody-mode") == ["follow", "follow"]
    controls["melody-mode"](["still"])
    controls["melody-mode"](["fixed"])
    assert reply(rig, "melody-mode") == ["fixed", "fixed"]
    with pytest.raises(ValueError, match="still"):
        controls["melody-mode"](["stay"])


def test_pad_15_cycles_still_to_fixed_and_never_back_to_still() -> None:
    rig = Rig(melody=True, bass="loop", clock=False)
    rig.ensemble.controls()["melody-mode"](["still"])
    modes = []
    for _ in range(4):
        rig.hit(MELODY)
        modes.append(reply(rig, "melody-mode")[0])
    assert modes == ["fixed", "off", "follow", "fixed"]
    assert MELODY_MODES == ("follow", "fixed", "off")


def demo() -> Rig:
    rig = Rig(melody=True, bass="loop", status=1)
    controls = rig.ensemble.controls()
    controls["learn"](["demo"])
    controls["melody-mode"](["still"])
    rig.send(START)
    return rig


def test_learn_demo_still_pad_16_keeps_the_bass_and_pad_15_does_nothing() -> None:
    rig = demo()
    bar_of(rig, 0, hits=SYNCOPATED)
    bar_of(rig, 1, press=8)
    assert reply(rig, "want") == ["push", "auto"]
    assert reply(rig, "examples") == [1, 0]
    rig.until(2 * BAR + 4 * STEP)
    reports = len(rig.reports)
    rig.hit(MELODY)
    rig.hit(MELODY)
    ignored = "ensemble: pad 15 ignored, the melody is still"
    assert rig.log.count(ignored) == 2
    assert for_musician(ignored)
    assert reply(rig, "want") == ["push", "auto"]
    assert len(rig.reports) == reports, "nothing changed, nothing reported"
    assert rig.ensemble.pad_action(15) == "-"
    for bar in range(2, 6):
        bar_of(rig, bar, hits=SYNCOPATED)
    rig.until(6 * BAR + STEP)
    assert reply(rig, "examples")[1] == 0
    assert reply(rig, "variation")[1] == "home"
    assert reply(rig, "chose")[1] == "still"
    with pytest.raises(ValueError, match="still"):
        rig.ensemble.controls()["want"](["melody", "open"])
    rig.ensemble.controls()["want"](["bass", "drive"])
    assert reply(rig, "want") == ["drive", "auto"]


def test_learn_likes_still_a_like_changes_the_bass_and_never_the_melody() -> None:
    rig = Rig(melody=True, bass="loop", seed=1)
    controls = rig.ensemble.controls()
    controls["learn"](["likes"])
    controls["melody-mode"](["still"])
    rig.send(START)
    melody = rig.ensemble._learners["melody"]
    before = {c: melody.top(c) for c in CONTEXTS["melody"]}
    liked = None
    for bar in range(12):
        bar_of(rig, bar, hits=STEADY)
        rig.until((bar + 1) * BAR - STEP)
        variation, tune = reply(rig, "variation")
        assert tune == "home"
        if bar:
            assert reply(rig, "chose") == ["bandit", "still"]
        if bar and liked is None and variation != "home":
            liked = variation
            for _ in range(4):
                controls["like"]([])
    assert liked is not None
    assert reply(rig, "learned") == [f"bass:grid/beat>{liked}"]
    likes = [line for line in rig.log if line.startswith("ensemble: like bar")]
    assert likes and all(" melody " not in line for line in likes)
    assert {c: melody.top(c) for c in before} == before
    assert not melody.learned()


def test_still_does_not_move_the_melody_with_rhythm_2() -> None:
    rig = Rig(melody=True, bass="loop", rhythm=2)
    rig.ensemble.controls()["melody-mode"](["still"])
    rig.send(START)
    for bar in range(4):
        bar_of(rig, bar, hits=SYNCOPATED + [(5, SNARE)])
    rig.until(4 * BAR + STEP)
    assert reply(rig, "transform")[1] == "plain"
