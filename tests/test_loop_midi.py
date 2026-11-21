"""Loop files to and from MIDI clips, `python -m mpc_iml.loops` (#173, ADR 0010)."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from mpc_iml import smf
from mpc_iml.content import ContentError
from mpc_iml.ensemble import PROGRESSIONS
from mpc_iml.loop_midi import dump, from_midi, main, to_midi
from mpc_iml.loops import LoopFile, load_loops, parse_loop
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
    assert dump(parse_loop(_file(notes)))["variations"]["home"][0]["offset"] == 0.17


def _file(notes: list[LoopNote]) -> dict[str, object]:
    return dump(LoopFile("x", "melody", 1, {"home": tuple(notes)}))


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


def test_the_bass_plays_one_note_at_a_time() -> None:
    found = from_midi(smf.read(clip((0, 4, 52, 100), (0, 2, 45, 80), (2, 4, 45, 100))), "bass", TWO)
    assert [(n.step, n.length, n.tone) for n in found.notes] == [(0, 2, 2), (2, 4, 0)]
    assert len([m for m in found.messages if "bass" in m]) == 2


def test_the_cli_imports_adds_a_variation_checks_and_exports(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    home, push = tmp_path / "home.mid", tmp_path / "push.mid"
    home.write_bytes(clip((0, 3, 45, 127), (8, 2, 52, 100), (14, 2, 44, 100)))
    push.write_bytes(clip((0, 2, 45, 127), (3, 2, 45, 100), (10, 2, 57, 90)))
    out = tmp_path / "loops"
    assert main(["import", str(home), "--part", "bass", "--name", "mine", "--out", str(out)]) == 0
    assert "2 chord tones, 1 approach notes, 0 other notes, 0 offsets" in capsys.readouterr().out
    file = out / "mine.json"
    assert main(["import", str(push), "--variation", "push", "--into", str(file)]) == 0
    loop = parse_loop(json.loads(file.read_text()))
    assert list(loop.variations) == ["home", "push"]
    assert loop.variations["home"][2] == LoopNote(0, 14, 0, 2, 1, 1, 0.8, chord=1, semitones=-1)
    assert main(["check", str(file)]) == 0
    assert "ok, bass loop 'mine', 1 bar(s): home 3 notes, push 3 notes" in capsys.readouterr().out
    midi = tmp_path / "out.mid"
    assert main(["export", str(file), str(midi), "--variation", "push"]) == 0
    assert [n.pitch for n in smf.read(midi.read_bytes()).notes] == [45, 45, 57]
    assert main(["export", "boom", str(midi), "--data", str(tmp_path)]) == 0
    assert len(smf.read(midi.read_bytes()).notes) == 6


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["import", "{clip}", "--name", "x"], "--part"),
        (["import", "{clip}", "--part", "bass"], "--name"),
        (["import", "{clip}", "--part", "bass", "--name", "x", "--variation", "push"], "--into"),
        (
            ["import", "{clip}", "--part", "bass", "--name", "x", "--variation", "open"],
            "unknown variation",
        ),
        (["import", "{clip}", "--part", "bass", "--name", "boom"], "exists"),
        (["import", "{bad}", "--part", "bass", "--name", "x"], "no MThd"),
        (["check", "{bad}"], "cannot read"),
        (["export", "nothing", "{clip}"], "unknown loop 'nothing'"),
    ],
)
def test_cli_errors(
    args: list[str], message: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "c.mid").write_bytes(clip((0, 1, 45, 100)))
    (tmp_path / "bad.json").write_text("RIFF")
    (tmp_path / "boom.json").write_text("{}")
    paths = {"clip": str(tmp_path / "c.mid"), "bad": str(tmp_path / "bad.json")}
    argv = [a.format(**paths) for a in args] + ["--out", str(tmp_path)] * (args[0] == "import")
    assert main(argv) == 1
    assert message in capsys.readouterr().err


def test_python_m_mpc_iml_loops_runs_the_cli() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "mpc_iml.loops", "--help"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "import" in result.stdout and "export" in result.stdout
