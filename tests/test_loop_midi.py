"""Loop variations to and from MIDI clips (#173, ADR 0010)."""

import pytest

from mpc_iml import smf
from mpc_iml.content import ContentError
from mpc_iml.ensemble import PROGRESSIONS
from mpc_iml.loop_midi import from_midi, to_midi
from mpc_iml.loops import LoopFile, load_loops
from mpc_iml.melody import LoopNote, loop_pitch

TWO = PROGRESSIONS["minor-two"]
Q = 120
"""Ticks per 16th at 480 per quarter note."""


def clip(*notes: tuple[float, float, int, int] | tuple[float, float, int, int, int]) -> bytes:
    """A MIDI file of (start, length in 16ths, pitch, velocity[, channel]) notes."""
    return smf.write([smf.Note(round(n[0] * Q), round(n[1] * Q), *n[2:]) for n in notes])


def imported(data: bytes, part: str = "melody", **options: object) -> list[LoopNote]:
    return from_midi(smf.read(data), part, TWO, **options).notes  # type: ignore[arg-type]


def heard(notes: tuple[LoopNote, ...] | list[LoopNote], bars: int) -> list[tuple[object, ...]]:
    """What plays over `minor-two` from bar 0, in base octave 3."""
    out = []
    for n in notes:
        chords = [
            ((TWO.tonic + TWO.chord(b).root) % 12, TWO.chord(b).quality) for b in (n.bar, n.bar + 1)
        ]
        pitch = loop_pitch(n, chords[0], chords[1], 3)
        out.append((n.bar, n.step, n.offset, n.length, n.level, n.velocity, pitch))
    return sorted(out)


@pytest.mark.parametrize("name", ["boom", "walk", "keys", "pluck"])
def test_export_then_import_keeps_every_built_in_loop(name: str) -> None:
    loop = load_loops().loops[name]
    for variation, notes in loop.variations.items():
        back = from_midi(
            smf.read(to_midi(loop, variation, TWO, octave=3)), loop.part, TWO, octave=3
        )
        assert back.bars == loop.bars
        assert heard(back.notes, loop.bars) == heard(notes, loop.bars)
        if name != "walk":  # walk approaches its next chord from step 10 on: chord 0 tones
            assert sorted(back.notes, key=_order) == sorted(notes, key=_order)


def _order(note: LoopNote) -> tuple[int, int, int, int]:
    return note.bar, note.step, note.tone, note.octave


def test_chord_tones_approach_notes_and_other_notes() -> None:
    # Over Am7 (A3 = 57) then, from bar 2, Fmaj7: A, B (C - 1), C, and G# before bar 1
    # (Am7 again: an approach to A) and E before bar 2 (Fmaj7's E: a chord tone of Am7).
    notes = imported(
        clip(
            (0, 2, 57, 100),
            (4, 2, 59, 100),
            (8, 2, 60, 100),
            (14, 2, 56, 100),
            (16, 2, 57, 100),
            (31, 1, 64, 100),
        ),
        octave=3,
    )
    assert [(n.tone, n.octave, n.chord, n.semitones) for n in notes] == [
        (0, 0, 0, 0),
        (1, 0, 0, -1),
        (1, 0, 0, 0),
        (0, 0, 1, -1),
        (0, 0, 0, 0),
        (2, 0, 0, 0),
    ]
    # F# before Fmaj7 is not an Am7 tone: it approaches F from above.
    (note,) = imported(clip((31, 1, 54, 90)), octave=3, bars=2)
    assert (note.tone, note.octave, note.chord, note.semitones) == (0, 0, 1, 1)


def test_steps_offsets_lengths_and_velocities() -> None:
    notes = imported(clip((0.18, 1.6, 57, 127), (4.5, 0.2, 57, 64), (7.9, 3, 57, 30)), octave=3)
    assert [(n.step, n.offset, n.length, n.velocity) for n in notes] == [
        (0, 1 / 6, 2, 1.0),
        (4, 0.5, 1, 0.5),
        (8, -1 / 6, 3, 0.25),
    ]
    # to_midi writes the offsets back: 1/6 of a 16th is 20 ticks.
    loop = LoopFile("x", "melody", 1, {"home": tuple(notes)})
    starts = [n.start for n in smf.read(to_midi(loop, "home", TWO, octave=3)).notes]
    assert starts == [20, 4 * Q + Q // 2, 8 * Q - 20]


def test_ornaments_from_channel_2_or_a_velocity_threshold() -> None:
    notes = imported(clip((0, 1, 57, 100), (2, 1, 57, 100, 1), (4, 1, 57, 40)), ornament_below=50)
    assert [n.level for n in notes] == [1, 2, 2]


def test_bars_crossing_the_end_and_notes_after_it() -> None:
    assert from_midi(smf.read(clip((0, 20, 57, 100))), "melody", TWO).bars == 2
    found = from_midi(smf.read(clip((12, 8, 57, 100))), "melody", TWO, bars=1)
    assert found.notes[0].length == 4
    assert any("shortened" in m for m in found.messages)
    with pytest.raises(ContentError, match="after the loop's 1 bar"):
        imported(clip((16, 1, 57, 100)), bars=1)
    with pytest.raises(ContentError, match="6 bars long; a loop has 1, 2 or 4 bars"):
        imported(clip((80, 4, 57, 100)))
    with pytest.raises(ContentError, match="no notes"):
        imported(smf.write([], length=16 * Q))


def test_the_bass_plays_one_note_at_a_time() -> None:
    found = from_midi(smf.read(clip((0, 4, 52, 100), (0, 2, 45, 80), (2, 4, 45, 100))), "bass", TWO)
    assert [(n.step, n.length, n.tone) for n in found.notes] == [(0, 2, 2), (2, 4, 0)]
    assert len([m for m in found.messages if "bass" in m]) == 2
