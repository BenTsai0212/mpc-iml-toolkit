"""The bass loops and kick rules in `mpc_iml.bass`, and the `melody` fields they use
(`LoopNote.chord` and `semitones`) (#148), and the bass variations (#158)."""

import pytest

from mpc_iml.bass import (
    BASS_VARIATIONS,
    OFF_KICK,
    accent,
    bass_note_velocity,
    bass_ornaments,
    bass_variation,
)
from mpc_iml.loops import load_loops
from mpc_iml.melody import (
    ORNAMENTS,
    LoopNote,
    chord_note,
    loop_pitch,
)
from mpc_iml.progressions import load_progressions

PROGRESSIONS = load_progressions()

BASS_LOOPS = load_loops().played("bass")
LOOPS = load_loops().played("melody")
FIRST = ("boom", "walk")
"""The bass loops before the hip-hop library (#232)."""
HELD = ("haze-bass", "midnight-808")
"""The bass loops of the lo-fi and trap sets (#262): `home` holds one long note in some
bars (long lo-fi roots, a held 808)."""


def chords(progression: str, bar: int) -> tuple[tuple[int, str], tuple[int, str]]:
    """(pitch class, quality) of the chord of `bar` and of the next bar."""
    p = PROGRESSIONS[progression]
    now, following = p.chord(bar), p.chord(bar + 1)
    return (p.tonic + now.root, now.quality), (p.tonic + following.root, following.quality)


def approach(progression: str, bar: int) -> int:
    note = LoopNote(0, 14, 0, 2, 1, chord=1, semitones=-1)
    return loop_pitch(note, *chords(progression, bar), 1)


def test_approach_notes_aim_at_the_next_root() -> None:
    assert [approach("minor-two", bar) for bar in range(4)] == [32, 28, 28, 32]
    assert [approach("minor-four", bar) for bar in range(4)] == [30, 33, 32, 25]


def test_chord_and_semitones_default_to_the_own_chord() -> None:
    now, following = chords("minor-four", 3)
    note = LoopNote(0, 0, 1, 2, 1, octave=1)
    assert loop_pitch(note, now, following, 1) == chord_note(*now, 1, 2)
    passing = LoopNote(0, 12, 0, 2, 3, chord=1, semitones=-2)
    assert loop_pitch(passing, now, following, 1) == 26 - 2
    melody = [n for name in ("keys", "pluck") for v in LOOPS[name].variations for n in v.notes]
    assert all(n.chord == 0 and n.semitones == 0 for n in melody)


def test_bass_loops_are_monophonic_with_a_skeleton_and_an_approach() -> None:
    boom, walk = BASS_LOOPS["boom"], BASS_LOOPS["walk"]
    assert (boom.bars, walk.bars) == (1, 2)
    assert [n.step for n in boom.bar_notes(0, 1)] == [0, 8]
    assert [n.step for n in walk.bar_notes(1, 1)] == [0, 8]
    for loop in (boom, walk):
        assert any(n.chord == 1 and n.semitones == -1 for n in loop.variation("home").notes)
        assert all(n.level == 1 and 0 <= n.tone <= 3 for n in loop.notes)


@pytest.mark.parametrize("name", list(BASS_LOOPS))
def test_every_bass_variation_is_a_full_monophonic_line(name: str) -> None:
    """Every built-in bass loop; the first two (`FIRST`) also keep their shape: both
    levels, an approach note and at least 4 notes a bar. The hip-hop loops (#232) may
    be sparser (`sub` holds its last note instead of approaching), and the loops of the
    lo-fi and trap sets (`HELD`, #262) may hold one note a bar."""
    loop = BASS_LOOPS[name]
    assert tuple(v.name for v in loop.variations) == BASS_VARIATIONS
    home = loop.variation("home")
    line = {(n.bar, n.step, n.tone, n.length) for n in home.notes if n.level == 1}
    assert {(n.bar, n.step, n.tone, n.length) for n in loop.notes} <= line
    for variation in loop.variations:
        assert variation.bars == loop.bars
        assert 1 in {n.level for n in variation.notes} <= {1, ORNAMENTS}
        if name in FIRST:
            assert {n.level for n in variation.notes} == {1, ORNAMENTS}
            last = variation.bar_notes(loop.bars - 1, 1)
            assert any(n.chord == 1 and n.semitones == -1 for n in last)
        for bar in range(loop.bars):
            line = variation.bar_notes(bar, 1)
            assert any(n.step == 0 for n in line)
            assert len(line) >= (4 if name in FIRST else 1 if name in HELD else 2)
            notes = sorted(variation.bar_notes(bar, ORNAMENTS), key=lambda n: n.step)
            ends = [n.step + n.length for n in notes]
            assert all(end <= nxt.step for end, nxt in zip(ends, notes[1:], strict=False))
            assert ends[-1] <= 16
        assert all(0 <= n.tone <= 3 for n in variation.notes)


@pytest.mark.parametrize(
    ("kicks", "variation"),
    [
        ([], "home"),
        ([0], "home"),
        ([0, 8], "home"),
        ([0, 4, 8, 12], "home"),
        ([0, 10], "push"),
        ([0, 3, 8], "push"),
        ([7], "push"),
        ([0, 4, 8, 12, 14], "drive"),
        ([0, 4, 8, 12, 0], "drive"),
    ],
)
def test_kick_positions_choose_the_bass_variation(kicks: list[int], variation: str) -> None:
    assert bass_variation(kicks) == variation


def test_bass_ornaments_join_with_three_kicks() -> None:
    assert [bass_ornaments(n) for n in range(6)] == [1, 1, 1, 2, 2, 2]


def test_accents_land_with_the_kicks() -> None:
    assert [accent(s, [0, 7]) for s in (0, 1, 2, 6, 8, 9)] == [1, 1, OFF_KICK, 1, 1, OFF_KICK]
    assert accent(0, []) == OFF_KICK
    root, ghost = BASS_LOOPS["boom"].variation("home").notes[:2]
    assert bass_note_velocity(root, 100, [0]) == 100
    assert bass_note_velocity(root, 100, [10]) == 80
    assert bass_note_velocity(ghost, 100, [3]) == 70
    assert bass_note_velocity(ghost, 100, None) == 70
    assert bass_note_velocity(root, 1, [8]) == 1
