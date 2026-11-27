"""The catch's pure functions (#290, `mpc_iml.catch`): when it answers, its rhythm
with `catch 1` and `catch 2`, and its notes."""

from mpc_iml.catch import (
    CATCH_NOTES,
    MAX_LENGTH,
    MIN_WEIGHT,
    Onset,
    answers,
    catch_notes,
    compared,
    drummed,
)
from mpc_iml.clock import GridHit
from mpc_iml.grooves import Decision
from mpc_iml.melody import LoopNote
from mpc_iml.rhythm import FEEL

STEPS = 16


def hit(step: int, velocity: int = 100, pad: int = 0, offset: float = 0.0) -> GridHit:
    return GridHit(0.0, pad, 0, velocity, 3, step, offset, offset * 125)


def groove(bar: int, fill: bool = False, id_: int | None = 1) -> Decision:
    return Decision(bar=bar, groove=id_, position=bar, start=0, fill=fill)


TWO = [hit(0), hit(8)]


def test_a_fill_after_two_bars_of_its_groove_is_answered() -> None:
    assert answers(groove(3, fill=True), [groove(2), groove(1)], TWO)


def test_no_answer_without_the_held_groove_a_fill_or_hits() -> None:
    held = [groove(2), groove(1)]
    assert not answers(groove(3), held, TWO)
    assert not answers(None, held, TWO)
    assert not answers(groove(3, fill=True, id_=None), held, TWO)
    assert not answers(groove(3, fill=True), [groove(2), None], TWO)
    assert not answers(groove(3, fill=True), [groove(2)], TWO)
    assert not answers(groove(3, fill=True), [groove(2, fill=True), groove(1)], TWO)
    assert not answers(groove(3, fill=True), [groove(2), groove(1, id_=2)], TWO)
    assert not answers(groove(3, fill=True), held, [hit(0)])
    assert not answers(groove(3, fill=True), held, [hit(0), hit(4, pad=14), hit(8, pad=15)])


def test_drummed_takes_the_loudest_hit_of_each_step_and_skips_pads_15_and_16() -> None:
    hits = [
        hit(0, 80, pad=0),
        hit(0, 110, pad=1, offset=-0.2),
        hit(4, 127, pad=14),
        hit(6, 90, pad=15),
        hit(10, 70, pad=12),
    ]
    assert drummed(hits, STEPS) == (Onset(0, 110, -0.2), Onset(10, 70, 0.0))


def test_drummed_keeps_the_eight_loudest_onsets_earlier_first_on_a_tie() -> None:
    hits = [hit(s, 100) for s in range(12)] + [hit(12, 120), hit(14, 60)]
    rhythm = drummed(hits, STEPS)
    assert len(rhythm) == CATCH_NOTES
    assert [o.step for o in rhythm] == [0, 1, 2, 3, 4, 5, 6, 12]


EARLIER = [hit(2, 90, offset=0.1), hit(2, 60, pad=3), hit(7, 120), hit(9, 127, pad=15)]
"""An earlier bar: two steps on counted pads (and pad 16, never read)."""


def test_compared_reads_the_earlier_bar_as_drummed_does() -> None:
    assert compared(EARLIER, TWO, STEPS) == drummed(EARLIER, STEPS)
    assert compared(EARLIER, TWO, STEPS) == (Onset(2, 90, 0.1), Onset(7, 120, 0.0))
    many = [hit(s, 100) for s in range(12)] + [hit(12, 120)]
    assert compared(many, TWO, STEPS) == drummed(many, STEPS)
    assert len(compared(many, TWO, STEPS)) == CATCH_NOTES


def test_compared_does_not_read_the_bar_it_answers() -> None:
    assert compared(EARLIER, TWO, STEPS) == compared(EARLIER, [hit(5), hit(11)], STEPS)


def test_compared_reads_the_bar_that_ended_without_an_earlier_bar_of_two_hits() -> None:
    assert compared(None, TWO, STEPS) == drummed(TWO, STEPS)
    assert compared([hit(3)], TWO, STEPS) == drummed(TWO, STEPS)
    assert compared([hit(3), hit(5, pad=14), hit(6, pad=15)], TWO, STEPS) == drummed(TWO, STEPS)
    assert compared([], TWO, STEPS) == drummed(TWO, STEPS)


PLANNED = (
    LoopNote(0, 8, 2, 2, 1, octave=1),
    LoopNote(0, 0, 0, 2, 1),
    LoopNote(0, 4, 1, 2, 1, semitones=-1),
    LoopNote(0, 12, 3, 2, 1, chord=1),
)


def test_the_accent_is_on_step_0_with_weight_1() -> None:
    notes = catch_notes((Onset(3, 40), Onset(9, 127)), PLANNED, 0, STEPS)
    assert notes[0].step == 0 and notes[0].velocity == 1.0 and notes[0].offset == 0
    assert [n.velocity for n in notes[1:]] == [MIN_WEIGHT, 1.0]
    played = catch_notes((Onset(0, 30, 0.3), Onset(5, 100)), PLANNED, 0, STEPS)
    assert played[0].velocity == 1.0 and played[0].offset == FEEL * 0.3
    assert played[1].velocity == 100 / 127


def test_pitches_follow_the_chord_0_notes_in_step_order_and_start_again() -> None:
    rhythm = tuple(Onset(s, 100) for s in (2, 5, 7, 9))
    notes = catch_notes(rhythm, PLANNED, 0, STEPS)
    assert [(n.tone, n.octave, n.semitones) for n in notes] == [
        (0, 0, 0),
        (1, 0, -1),
        (2, 1, 0),
        (0, 0, 0),
        (1, 0, -1),
    ]
    assert all(n.chord == 0 and n.level == 1 for n in notes)


def test_a_variation_without_chord_0_notes_gives_tone_0() -> None:
    notes = catch_notes((Onset(4, 100),), (LoopNote(0, 0, 3, 2, 1, chord=1),), 0, STEPS)
    assert [(n.tone, n.octave, n.semitones) for n in notes] == [(0, 0, 0)] * 2


def test_lengths_reach_the_next_note_from_1_to_4_steps_inside_the_bar() -> None:
    rhythm = tuple(Onset(s, 100) for s in (1, 2, 10, 15))
    notes = catch_notes(rhythm, PLANNED, 0, STEPS)
    assert [(n.step, n.length) for n in notes] == [
        (0, 1),
        (1, 1),
        (2, MAX_LENGTH),
        (10, 4),
        (15, 1),
    ]
    assert all(n.step + n.length <= STEPS for n in notes)


def test_offsets_are_the_hits_offsets_times_feel() -> None:
    rhythm = drummed([hit(4, offset=0.4), hit(9, offset=-0.5)], STEPS)
    notes = catch_notes(rhythm, PLANNED, 0, STEPS)
    assert [n.offset for n in notes] == [0.0, FEEL * 0.4, FEEL * -0.5]


def test_a_late_note_that_ends_on_the_bar_line_gets_no_offset() -> None:
    rhythm = drummed([hit(12, offset=0.3), hit(14, offset=0.4), hit(15, offset=-0.2)], STEPS)
    notes = catch_notes(rhythm, PLANNED, 0, STEPS)
    assert [n.offset for n in notes] == [0.0, FEEL * 0.3, FEEL * 0.4, FEEL * -0.2]
    late = catch_notes(drummed([hit(13, offset=0.4)], STEPS), PLANNED, 0, STEPS)
    assert [(n.step, n.length, n.offset) for n in late] == [(0, 4, 0.0), (13, 3, 0.0)]
    assert all(n.step + n.length + n.offset <= STEPS for n in notes + late)
