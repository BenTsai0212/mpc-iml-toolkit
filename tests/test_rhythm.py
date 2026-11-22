"""Rhythm transformation in `mpc_iml.rhythm` (RFC 0005 step 6, #189)."""

import random

import pytest

from mpc_iml.clock import GridHit
from mpc_iml.loops import load_loops
from mpc_iml.melody import ORNAMENTS, Loop, LoopNote
from mpc_iml.rhythm import (
    FEEL,
    MIN_HITS,
    Memory,
    Motif,
    Move,
    Onset,
    answer,
    backbeat,
    fixed_steps,
    lock,
    motif,
    similar,
)

BASS = load_loops().played("bass")
MELODY = load_loops().played("melody")


def onsets(*steps: int, velocity: int = 100, offset: float = 0.0) -> tuple[Onset, ...]:
    return tuple(Onset(s, velocity, offset) for s in steps)


def boom(level: int = ORNAMENTS) -> tuple[LoopNote, ...]:
    return BASS["boom"].variation("home").bar_notes(0, level)


def steps(notes: tuple[LoopNote, ...]) -> list[int]:
    return [n.step for n in notes]


def test_lock_puts_bass_notes_on_the_kicks() -> None:
    """Kicks on 0 6 10: the note on 11 moves to 10; 6 is already on a kick."""
    shaped = lock(boom(), fixed_steps(BASS["boom"], 0), onsets(0, 6, 10))
    assert steps(boom()) == [0, 3, 6, 8, 11, 14]
    assert steps(shaped.notes) == [0, 3, 6, 8, 10, 14]
    assert shaped.transform == "lock"
    assert shaped.moves == (Move(11, 10, 10),)


def test_skeleton_and_approach_notes_never_move() -> None:
    """Kicks next to the skeleton (0, 8) and the approach (14) leave them in place."""
    loop = BASS["boom"]
    assert fixed_steps(loop, 0) == {0, 8}
    shaped = lock(boom(1), fixed_steps(loop, 0), onsets(1, 9, 13, 15))
    assert steps(shaped.notes) == [0, 6, 8, 14]
    assert shaped.moves == ()


def test_one_kick_plays_the_line_as_written() -> None:
    for kicks in [(), onsets(4)]:
        assert len(kicks) < MIN_HITS
        shaped = lock(boom(), fixed_steps(BASS["boom"], 0), kicks)
        assert shaped.notes == boom()
        assert shaped.transform == "plain"


def test_dense_kicks_keep_the_note_count() -> None:
    """A kick on every step: no note is added, and moved notes land on 8ths."""
    shaped = lock(boom(), fixed_steps(BASS["boom"], 0), onsets(*range(16)))
    assert len(shaped.notes) == len(boom())
    assert steps(shaped.notes) == [0, 2, 6, 8, 10, 14]


def test_the_louder_kick_wins_a_tie() -> None:
    notes = (LoopNote(0, 0, 0, 2, 1), LoopNote(0, 6, 2, 2, 1), LoopNote(0, 12, 0, 2, 1))
    assert steps(lock(notes, {0}, onsets(5, 7, 12)).notes) == [0, 5, 12]
    assert steps(lock(notes, {0}, (Onset(5, 60), Onset(7, 120))).notes) == [0, 7, 12]


def test_dense_kicks_are_taken_on_the_8th_grid_first() -> None:
    notes = (LoopNote(0, 0, 0, 2, 1), LoopNote(0, 5, 2, 1, 1), LoopNote(0, 12, 0, 2, 1))
    assert steps(lock(notes, {0}, onsets(0, 3, 12)).notes) == [0, 3, 12]
    assert steps(lock(notes, {0}, onsets(0, 3, 6, 12)).notes) == [0, 6, 12]


def test_a_moved_note_takes_half_of_the_offset() -> None:
    late = (Onset(0, 100), Onset(6, 100), Onset(10, 100, 0.4))
    shaped = lock(boom(), fixed_steps(BASS["boom"], 0), late)
    moved = next(n for n in shaped.notes if n.step == 10)
    assert moved.offset == pytest.approx(FEEL * 0.4)
    kept = [n for n in shaped.notes if n.step != 10]
    assert [n.offset for n in kept] == [n.offset for n in boom() if n.step != 11]
    wild = lock(boom(), fixed_steps(BASS["boom"], 0), (Onset(0, 100), Onset(10, 100, -3.0)))
    assert next(n for n in wild.notes if n.step == 10).offset == -0.5


def test_moved_notes_keep_their_pitch_fields() -> None:
    """A user loop's non-chord tone keeps `tone`, `chord`, `semitones` and the rest."""
    odd = LoopNote(0, 7, 1, 2, 1, octave=1, velocity=0.6, semitones=2)
    notes = (LoopNote(0, 0, 0, 4, 1), odd, LoopNote(0, 14, 0, 2, 1, chord=1, semitones=-1))
    shaped = lock(notes, None, onsets(0, 8))
    assert shaped.notes[1] == LoopNote(0, 8, 1, 2, 1, octave=1, velocity=0.6, semitones=2)
    assert shaped.notes[2] == notes[2]


def test_answer_displaces_the_locked_notes_a_16th_later() -> None:
    shaped = answer(boom(1), fixed_steps(BASS["boom"], 0), onsets(0, 4, 9))
    assert steps(lock(boom(1), {0, 8}, onsets(0, 4, 9)).notes) == [0, 4, 8, 14]
    assert steps(shaped.notes) == [0, 5, 8, 14]
    assert shaped.transform == "answer"
    assert shaped.moves == (Move(6, 5, 4),)


def test_answer_stays_on_the_kick_when_the_next_step_is_taken() -> None:
    notes = (LoopNote(0, 0, 0, 2, 1), LoopNote(0, 3, 2, 1, 1), LoopNote(0, 5, 0, 2, 1))
    shaped = answer(notes, {0, 5}, onsets(0, 4))
    assert steps(shaped.notes) == [0, 4, 5]
    assert shaped.moves == (Move(3, 4, 4),)


def test_answer_without_kicks_is_plain() -> None:
    assert answer(boom(), {0, 8}, onsets(3)).transform == "plain"


def test_backbeat_moves_the_melody_to_the_snare() -> None:
    keys = MELODY["keys"]
    notes = keys.variation("home").bar_notes(0, 1)
    assert steps(notes) == [0, 6, 10]
    assert fixed_steps(keys, 0) == {0, 10}
    hats = onsets(0, 2, 8, 12, 14, velocity=60)
    shaped = backbeat(notes, fixed_steps(keys, 0), (Onset(4, 110), Onset(12, 110)), hats)
    assert steps(shaped.notes) == [0, 4, 10]
    assert shaped.transform == "backbeat"


def test_backbeat_takes_16ths_only_when_the_hats_play_them() -> None:
    keys = MELODY["keys"]
    notes = keys.variation("home").bar_notes(0, 1)
    sixteenths = backbeat(notes, {0, 10}, onsets(12), onsets(7, 9, velocity=60))
    assert steps(sixteenths.notes) == [0, 7, 10]
    eighths = backbeat(notes, {0, 10}, onsets(12), onsets(2, 4, velocity=60))
    assert steps(eighths.notes) == [0, 4, 10]
    snare_only = backbeat(notes, {0, 10}, onsets(4, 12), ())
    assert steps(snare_only.notes) == [0, 4, 10]


def test_without_a_marked_skeleton_the_first_note_stays() -> None:
    home = (LoopNote(0, 1, 0, 2, 1), LoopNote(0, 6, 2, 2, 1))
    loop = Loop("user", 1, home, (Loop("home", 1, home),))
    assert fixed_steps(loop, 0) is None
    assert steps(lock(home, None, onsets(0, 3, 5)).notes) == [1, 5]


def test_notes_on_one_step_stay() -> None:
    chord = (LoopNote(0, 0, 0, 4, 1), LoopNote(0, 6, 0, 2, 1), LoopNote(0, 6, 2, 2, 1))
    assert lock(chord, {0}, onsets(0, 5)).notes == chord


def test_motif_reads_each_role_and_the_loudest_hit_of_a_step() -> None:
    roles = ["kick", "snare", "hat", "other"]

    def hit(pad: int, step: int, velocity: int = 100, offset: float = 0.0) -> GridHit:
        return GridHit(0.0, pad, 0, velocity, 0, step, offset, 0.0)

    hits = [hit(0, 0), hit(2, 2), hit(1, 4), hit(0, 6, 50, 0.1), hit(0, 6, 90, -0.2), hit(3, 8)]
    assert motif(hits, roles) == Motif(
        kicks=(Onset(0, 100), Onset(6, 90, -0.2)), snares=(Onset(4, 100),), hats=(Onset(2, 100),)
    )


def test_memory_keeps_the_phrase_motif_while_the_groove_stays_close() -> None:
    memory = Memory()
    first = memory.take(Motif(kicks=onsets(0, 6, 10)))
    assert first.kicks == onsets(0, 6, 10)
    assert similar(onsets(0, 6, 10), onsets(1, 6, 9))
    assert memory.take(Motif(kicks=onsets(1, 6, 9))).kicks == onsets(0, 6, 10)
    assert memory.take(Motif(kicks=onsets(0, 4, 8, 12))).kicks == onsets(0, 4, 8, 12)
    assert memory.take(Motif(kicks=onsets(0, 3, 8, 12))).kicks == onsets(0, 4, 8, 12)
    memory.reset()
    assert memory.take(Motif(kicks=onsets(0, 3, 8, 12))).kicks == onsets(0, 3, 8, 12)


@pytest.mark.parametrize("name", ["boom", "walk", "keys", "pluck"])
def test_transformations_keep_the_line_on_random_bars(name: str) -> None:
    """On random hits: the note count, pitch order, fixed notes and approach notes
    hold, no two notes share a step, and moves stay within `REACH` (+1 for `answer`)."""
    loop = {**BASS, **MELODY}[name]
    rng = random.Random(name)
    for _ in range(200):
        variation = loop.variations[rng.randrange(len(loop.variations))]
        bar = rng.randrange(loop.bars)
        notes = variation.bar_notes(bar, rng.choice([1, ORNAMENTS]))
        fixed = fixed_steps(loop, bar)
        hits = onsets(*sorted(rng.sample(range(16), rng.randrange(17))))
        for shaped in (
            lock(notes, fixed, hits),
            answer(notes, fixed, hits),
            backbeat(notes, fixed, hits[::2], hits[1::2]),
        ):
            assert len(shaped.notes) == len(notes)
            before = sorted(notes, key=lambda n: n.step)
            after = sorted(shaped.notes, key=lambda n: n.step)
            assert [n.tone for n in after] == [n.tone for n in before]
            moved = [b for a, b in zip(notes, shaped.notes, strict=True) if a != b]
            assert len({n.step for n in moved}) == len(moved)
            for a, b in zip(notes, shaped.notes, strict=True):
                if a.chord or (fixed is not None and a.step in fixed):
                    assert a == b
                assert abs(a.step - b.step) <= 3
                assert (a.tone, a.chord, a.semitones, a.length) == (
                    b.tone,
                    b.chord,
                    b.semitones,
                    b.length,
                )
            approach = min([n.step for n in notes if n.chord], default=16)
            assert all(
                b.step < approach for a, b in zip(notes, shaped.notes, strict=True) if a != b
            )
