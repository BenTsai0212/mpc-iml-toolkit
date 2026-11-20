"""The bass loops and kick rules in `mpc_iml.bass`, and the `melody` fields they use
(`LoopNote.chord` and `semitones`, `Follower(density=…)`) (#148)."""

from mpc_iml.bass import BASS_LOOPS, OFF_KICK, accent, bass_note_velocity, kick_density
from mpc_iml.ensemble import PROGRESSIONS
from mpc_iml.melody import LOOPS, BarPlan, Follower, LoopNote, chord_note, loop_pitch


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
    assert all(n.chord == 0 and n.semitones == 0 for loop in LOOPS.values() for n in loop.notes)


def test_bass_loops_are_monophonic_with_a_skeleton_and_an_approach() -> None:
    boom, walk = BASS_LOOPS["boom"], BASS_LOOPS["walk"]
    assert (boom.bars, walk.bars) == (1, 2)
    assert [n.step for n in boom.bar_notes(0, 1)] == [0, 8]
    assert [n.step for n in walk.bar_notes(1, 1)] == [0, 8]
    for loop in (boom, walk):
        assert any(n.chord == 1 and n.semitones == -1 for n in loop.notes)
        for bar in range(loop.bars):
            notes = sorted(loop.bar_notes(bar, 3), key=lambda n: n.step)
            ends = [n.step + n.length for n in notes]
            assert all(end <= nxt.step for end, nxt in zip(ends, notes[1:], strict=False))
            assert ends[-1] <= 16
        assert all(n.level in (1, 2, 3) and 0 <= n.tone <= 3 for n in loop.notes)


def test_kick_density() -> None:
    assert [kick_density(n) for n in range(1, 8)] == [1, 1, 2, 2, 3, 3, 3]


def test_accents_land_with_the_kicks() -> None:
    assert [accent(s, [0, 7]) for s in (0, 1, 2, 6, 8, 9)] == [1, 1, OFF_KICK, 1, 1, OFF_KICK]
    assert accent(0, []) == OFF_KICK
    root, ghost = BASS_LOOPS["boom"].notes[:2]
    assert bass_note_velocity(root, 100, [0]) == 100
    assert bass_note_velocity(root, 100, [10]) == 80
    assert bass_note_velocity(ghost, 100, [3]) == 70
    assert bass_note_velocity(ghost, 100, None) == 70
    assert bass_note_velocity(root, 1, [8]) == 1


def test_follower_with_kick_density() -> None:
    follower = Follower(density=kick_density)
    assert follower.plan_bar([], 0, True, True).level == 0
    assert follower.plan_bar([127, 127], 0, True, True).level == 1
    assert follower.plan_bar([127] * 3, 0, True, True).level == 2
    assert follower.plan_bar([1] * 5, 0, True, True) == BarPlan(3, 50, 40)
    assert follower.plan_bar([], 0, True, True) == BarPlan(1, 50, None)
    assert follower.plan_bar([], 0, True, True) == BarPlan(0, 50, None)
    assert Follower().plan_bar([127] * 3, 0, True, True).level == 1
