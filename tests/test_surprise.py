"""`ensemble`'s little surprise (#158): at the last bar of each 4-bar phrase, with
probability 1/2, a bass fill, the melody an octave up or a passing note, seeded.
`surprise 1` (the default, #178) allows only the fill, `surprise 2` all three.

The preset runs on the simulated DAW clock of `test_ensemble.py` (`Rig`). Over
`minor-two`, bar 3 is Fmaj7 and bar 4 Am7: in bass octave 1 the fill of bar 3 is
F1, C2, F2 and G#1 (half a step below A1).
"""

import random
from itertools import pairwise

import pytest
from test_ensemble import BAR, KICK, START, STEP, Rig
from test_melody import HAT, play_bar

from mpc_iml.bass import bass_fill
from mpc_iml.ensemble import Ensemble
from mpc_iml.loops import load_loops
from mpc_iml.melody import (
    PHRASE,
    SURPRISES,
    LoopNote,
    octave_up,
    passing,
    surprise,
)

BASS_LOOPS = load_loops().played("bass")
LOOPS = load_loops().played("melody")

DRUMS = [(0, KICK), (4, HAT), (8, KICK), (12, HAT)]
"""A sparse bar: the bass plays `home`, the melody `open`."""


def seed_for(kind: str) -> int:
    """A seed whose first draw at a phrase end (with every surprise possible) is
    `kind`."""
    return next(s for s in range(100) if surprise(random.Random(s), 3, SURPRISES) == kind)


def run(bars: int, level: int = 2, seed: int = 0, **controls: str | int) -> Rig:
    """`ensemble` with both loops following `DRUMS` in bars 0 to `bars - 1`, run to
    the end of bar `bars`, with `surprise` at `level`."""
    rig = Rig(melody=True, bass="loop", surprise=level, seed=seed)
    for name, value in controls.items():
        rig.ensemble.controls()[name.replace("_", "-")]([value])
    rig.send(START)
    for bar in range(bars):
        play_bar(rig, bar, DRUMS)
    rig.until((bars + 1) * BAR)
    return rig


def notes(rig: Rig, status: int, bar: int) -> list[tuple[int, int, int]]:
    """(step of `bar`, note, velocity) of the Note Ons with `status` in `bar`."""
    return [
        (t // STEP - 16 * bar, m[1], m[2])
        for t, m in rig.sent
        if m[0] == status and bar * BAR <= t < (bar + 1) * BAR
    ]


def surprises(rig: Rig) -> list[str]:
    return [line for line in rig.log if "surprise" in line]


class Fixed(random.Random):
    """A `random.Random` whose `random()` is always `value`."""

    def __init__(self, value: float) -> None:
        super().__init__(0)
        self.value = value

    def random(self) -> float:
        return self.value


def test_only_at_the_end_of_a_phrase_with_probability_one_half() -> None:
    assert PHRASE == 4
    assert [surprise(Fixed(0.0), bar, SURPRISES) for bar in range(8)] == [None] * 3 + ["fill"] + [
        None
    ] * 3 + ["fill"]
    assert surprise(Fixed(0.49), 3, ["octave"]) == "octave"
    assert surprise(Fixed(0.5), 3, SURPRISES) is None
    assert surprise(Fixed(0.0), 3, []) is None
    drawn = [surprise(random.Random(s), 7, SURPRISES) for s in range(400)]
    assert 150 < drawn.count(None) < 250
    assert set(drawn) == {None, *SURPRISES}


def test_the_same_seed_gives_the_same_surprises() -> None:
    first, second = random.Random(5), random.Random(5)
    bars = range(3, 200, 4)
    assert [surprise(first, b, SURPRISES) for b in bars] == [
        surprise(second, b, SURPRISES) for b in bars
    ]


@pytest.mark.parametrize("loop", ["boom", "walk"])
def test_the_fill_replaces_the_last_beat_and_stays_monophonic(loop: str) -> None:
    for variation in BASS_LOOPS[loop].variations:
        for bar in range(variation.bars):
            line = variation.bar_notes(bar, 2)
            filled = bass_fill(line, bar)
            before = [(n.step, n.tone, n.octave) for n in filled if n.step < 12]
            assert before == [(n.step, n.tone, n.octave) for n in line if n.step < 12]
            assert [n for n in filled if n.step == 0] == [n for n in line if n.step == 0]
            assert [(n.step, n.tone, n.octave, n.semitones) for n in filled if n.step >= 12] == [
                (12, 0, 0, 0),
                (13, 2, 0, 0),
                (14, 0, 1, 0),
                (15, 0, 0, -1),
            ]
            ordered = sorted(filled, key=lambda n: n.step)
            assert all(a.step + a.length <= b.step for a, b in pairwise(ordered))


def test_octave_up_and_the_passing_note() -> None:
    line = LOOPS["keys"].variation("home").bar_notes(1, 1)
    assert [n.octave for n in octave_up(line)] == [n.octave + 1 for n in line]
    changed = passing(line)
    last = max(line, key=lambda n: n.step)
    assert [n for n in changed if n.step != last.step] == [n for n in line if n is not last]
    (moved,) = [n for n in changed if n.step == last.step]
    assert (moved.tone, moved.chord, moved.semitones) == (last.tone, 1, -1)
    assert passing(()) == ()
    assert LoopNote(0, 0, 0, 1, 1) in octave_up([LoopNote(0, 0, 0, 1, 1, octave=-1)])


def test_a_bass_fill_ends_the_phrase() -> None:
    plain, rig = run(4, level=0), run(4, seed=seed_for("fill"))
    assert surprises(rig) == ["ensemble: surprise fill in bar 3"]
    bass = notes(rig, 0x91, 3)
    assert [(s, n) for s, n, _ in bass if s >= 12] == [(12, 29), (13, 36), (14, 41), (15, 32)]
    assert [x for x in bass if x[0] < 12] == [x for x in notes(plain, 0x91, 3) if x[0] < 12]
    assert notes(rig, 0x92, 3) == notes(plain, 0x92, 3)
    assert [notes(rig, 0x91, b) for b in range(3)] == [notes(plain, 0x91, b) for b in range(3)]


def test_the_melody_goes_an_octave_up_or_ends_on_a_passing_note() -> None:
    plain = notes(run(4, level=0), 0x92, 3)
    up = run(4, seed=seed_for("octave"))
    assert surprises(up) == ["ensemble: surprise octave in bar 3"]
    assert notes(up, 0x92, 3) == [(s, n + 12, v) for s, n, v in plain]
    moved = run(4, seed=seed_for("passing"))
    assert surprises(moved) == ["ensemble: surprise passing in bar 3"]
    melody = notes(moved, 0x92, 3)
    assert melody[:-1] == plain[:-1] and melody[-1][0] == plain[-1][0]
    assert melody[-1][1] != plain[-1][1]
    assert notes(moved, 0x91, 3) == notes(run(4, level=0), 0x91, 3)


def test_only_surprises_that_can_sound() -> None:
    seed = seed_for("fill")
    assert "fill" not in str(surprises(run(4, seed=seed, bass="rule")))
    assert "octave" not in str(surprises(run(4, seed=seed, melody_mode="off")))
    assert surprises(run(8, seed=seed, melody_mode="fixed")) == []
    assert surprises(run(8, level=0)) == []


def test_never_while_fading_or_in_thin() -> None:
    def quiet(**controls: str | int) -> list[str]:
        rig = Rig(melody=True, bass="loop", surprise=2, seed=seed_for("fill"))
        for name, value in controls.items():
            rig.ensemble.controls()[name.replace("_", "-")]([value])
        rig.send(START)
        play_bar(rig, 0, DRUMS)
        play_bar(rig, 1, DRUMS)
        rig.until(5 * BAR)
        return surprises(rig)

    assert quiet(fade_bars=2) == []
    assert quiet(no_drums="thin") == []
    assert quiet() == ["ensemble: surprise fill in bar 3"]


def test_by_default_only_the_bass_fill() -> None:
    assert Ensemble().surprise == 1
    for kind in ("octave", "passing"):
        rig = run(4, level=1, seed=seed_for(kind))
        assert surprises(rig) == ["ensemble: surprise fill in bar 3"]
        assert notes(rig, 0x92, 3) == notes(run(4, level=0), 0x92, 3)
    drawn = {line for s in range(20) for line in surprises(run(8, level=1, seed=s))}
    assert drawn == {"ensemble: surprise fill in bar 3", "ensemble: surprise fill in bar 7"}
    assert surprises(run(8, level=1, seed=seed_for("octave"), bass="rule")) == []


def test_the_surprise_control() -> None:
    rig = Rig(surprise=2)
    for level in (0, 1, 2):
        rig.ensemble.controls()["surprise"]([level])
        assert dict(rig.ensemble.state())["surprise"] == [level]
    rig.ensemble.controls()["surprise"]([0])
    for bad in ([3], [-1], [1.5], ["on"], [True], [], [1, 2]):
        with pytest.raises(ValueError):
            rig.ensemble.controls()["surprise"](bad)
    assert dict(rig.ensemble.state())["surprise"] == [0]
