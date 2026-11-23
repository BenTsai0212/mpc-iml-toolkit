"""Progression files (#236, ADR 0011): format, loading, and that the built-in
progressions play as the Python table did before."""

import json
import re
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.content import ContentError
from mpc_iml.ensemble import Ensemble
from mpc_iml.loops import load_loops
from mpc_iml.melody import QUALITIES, LoopNote, loop_pitch
from mpc_iml.progressions import (
    DEFAULT,
    Chord,
    Progression,
    chord_names,
    load_progressions,
    main,
    parse_progression,
)
from mpc_iml.webdemo.sim import Settings, simulate

TWO = {
    "format": "mpc-iml-progression",
    "format_version": 1,
    "name": "two",
    "preset": "ensemble",
    "tonic": "Bb",
    "chords": [{"root": 0, "quality": "m7", "bars": 2}, {"root": 5, "quality": "7", "bars": 2}],
}

OLD = {
    "minor-two": (9, ((0, "m7"), (8, "maj7")), 2),
    "minor-four": (2, ((0, "m7"), (5, "m7"), (8, "maj7"), (7, "7")), 1),
}
"""The Python table `ensemble.PROGRESSIONS` before #236: tonic, (root, quality) per
chord, and bars per chord."""


def changed(**fields: Any) -> dict[str, Any]:
    return {**TWO, **fields}


def test_the_built_in_progressions_play_as_before() -> None:
    progressions = load_progressions()
    assert list(progressions)[:2] == ["minor-two", "minor-four"] == list(OLD)
    for name, (tonic, chords, per_chord) in OLD.items():
        p = progressions[name]
        assert p.origin.endswith(f"mpc_iml/progressions/ensemble/{name}.json")
        assert p.tonic == tonic
        assert [(c.root, c.quality) for c in p.chords] == list(chords)
        for bar in range(-1, 32):
            old = chords[(max(bar, 0) // per_chord) % len(chords)]
            assert (p.chord(bar).root, p.chord(bar).quality) == old
            for octave in (1, 4):
                assert p.root_note(bar, octave) == 12 * (octave + 1) + (tonic + old[0]) % 12


def test_a_progression_file_parses_with_defaults() -> None:
    p = parse_progression(changed(chords=[{"root": 0, "quality": "m7"}]))
    assert p == Progression("two", 10, (Chord(0, "m7", 1),), "Two", "", "progression")
    assert p.bars == 1
    assert chord_names(parse_progression(TWO)) == "Bbm7 (2) Eb7 (2)"


def test_chords_of_different_lengths_walk_the_progression() -> None:
    p = Progression("p", 0, (Chord(0, "m7", 3), Chord(5, "7", 1)))
    assert [p.chord(b).root for b in range(9)] == [0, 0, 0, 5, 0, 0, 0, 5, 0]


@pytest.mark.parametrize(
    ("tonic", "pitch_class"), [("C", 0), ("F#", 6), ("Bb", 10), ("Cb", 11), ("B#", 0)]
)
def test_the_tonic_is_a_note_name(tonic: str, pitch_class: int) -> None:
    assert parse_progression(changed(tonic=tonic)).tonic == pitch_class


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"tonic": 9}, "tonic must be a note name C-B with an optional # or b, got 9"),
        ({"tonic": "H"}, "tonic must be a note name"),
        ({"tonic": "Ax"}, "tonic must be a note name"),
        ({"chords": []}, "chords must be a list of 1-8 chords"),
        ({"chords": [{"root": 0, "quality": "m7"}] * 9}, "chords must be a list of 1-8"),
        ({"chords": [{"root": 0, "quality": "m9"}]}, "chords[0]: quality must be one of m7, maj7"),
        ({"chords": [{"quality": "m7"}]}, "chords[0]: root is required"),
        ({"chords": [{"root": 12, "quality": "m7"}]}, "chords[0]: root must be 0-11, got 12"),
        ({"chords": [{"root": 0, "quality": "m7", "bars": 5}]}, "chords[0]: bars must be 1-4"),
        ({"chords": [{"root": 0, "quality": "m7", "beats": 4}]}, "unknown field 'beats'"),
        ({"chords": ["Am7"]}, "chords[0]: a chord is an object"),
        ({"chords": [{"root": 0, "quality": "m7", "bars": 3}]}, "1, 2, 4, 8 bars in all, got 3"),
        ({"key": "A"}, "unknown field 'key'"),
        ({"preset": "pressure"}, "preset is 'pressure', expected 'ensemble'"),
    ],
)
def test_bad_progression_files_name_the_file_and_the_chord(
    fields: dict[str, Any], message: str
) -> None:
    with pytest.raises(ContentError, match=f"^lofi.json: .*{re.escape(message)}"):
        parse_progression(changed(**fields), "lofi.json")


def install(monkeypatch: pytest.MonkeyPatch, root: Path, name: str, files: dict[str, Any]) -> None:
    """Install a package `name` with progression files `files` (file stem: JSON)."""
    package = root / name
    (package / "progressions" / "ensemble").mkdir(parents=True)
    (package / "__init__.py").write_text(
        f"from mpc_iml.content import Content\nCONTENT = Content('ensemble', '{name}')\n"
    )
    for stem, data in files.items():
        (package / "progressions" / "ensemble" / f"{stem}.json").write_text(json.dumps(data))
    info = root / f"{name}-1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    (info / "entry_points.txt").write_text(f"[mpc_iml.content]\n{name} = {name}:CONTENT\n")
    monkeypatch.syspath_prepend(str(root))


def test_installed_progressions_follow_the_built_in_ones(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(
        monkeypatch, tmp_path, "chord_content", {"two": TWO, "a-first": changed(name="a-first")}
    )
    names = list(load_progressions())
    assert names[:2] == ["minor-two", "minor-four"]
    assert names[-2:] == ["a-first", "two"]
    ensemble = Ensemble(lambda line: None)
    ensemble.controls()["progression"](["two"])
    assert ensemble.progression.name == "two"


def test_two_progressions_with_the_same_name_are_an_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install(monkeypatch, tmp_path, "same_chords", {"minor-two": changed(name="minor-two")})
    with pytest.raises(ContentError, match="two progressions named 'minor-two'"):
        load_progressions()


def test_an_unknown_progression_lists_the_names() -> None:
    ensemble = Ensemble(lambda line: None)
    assert ensemble.progression.name == DEFAULT
    with pytest.raises(ValueError, match="expected one of minor-two, minor-four"):
        ensemble.controls()["progression"](["lofi"])


def test_check_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "two.json", tmp_path / "bad.json"
    good.write_text(json.dumps(TWO))
    bad.write_text(json.dumps(TWO))
    assert main(["check", str(good)]) == 0
    assert capsys.readouterr().out.endswith("ok, progression 'two', 4 bar(s): Bbm7 (2) Eb7 (2)\n")
    assert main(["check", str(good), str(bad)]) == 1
    assert "the file name must equal the name 'two'" in capsys.readouterr().err
    assert main(["list"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        "minor-two: Am7 (2) Fmaj7 (2)",
        "minor-four: Dm7 (1) Gm7 (1) Bbmaj7 (1) A7 (1)",
    ]


# The built-in set (#236 PR 2)

HIP_HOP = {
    "dark-minor": "Cm7 (2) Dbmaj7 (2)",
    "lofi-descent": "Fmaj7 (1) Em7 (1) Dm7 (1) Cmaj7 (1)",
    "minor-turn": "Bm7b5 (1) E7 (1) Am7 (2)",
    "soul-minor": "Am7 (2) Dm7 (2)",
    "two-five-one": "Dm7 (1) G7 (1) Cmaj7 (2)",
}
"""The hip-hop progressions of the `## Decision` on #236, with their chords."""

FOLDER = Path(__file__).parents[1] / "src" / "mpc_iml" / "progressions" / "ensemble"
BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70] * 16}
OPEN = {"kick": [100, 0, 0, 0, 0, 0, 0, 0] * 2}


def test_the_built_in_set_follows_the_two_old_progressions() -> None:
    progressions = load_progressions()
    assert list(progressions) == ["minor-two", "minor-four", *HIP_HOP]
    assert {name: chord_names(progressions[name]) for name in HIP_HOP} == HIP_HOP
    for name in progressions:
        assert main(["check", str(FOLDER / f"{name}.json")]) == 0


def test_m7b5_has_a_flat_fifth() -> None:
    """Tones 0-3 of `m7b5` are root, minor third, flat fifth and minor seventh, so a
    loop's tones plus `semitones` keep their shape (Bm7b5: B D F A)."""
    assert QUALITIES["m7b5"] == (0, 3, 6, 10)
    b = (11, "m7b5")
    pitches = [loop_pitch(LoopNote(0, 0, tone, 1, 1), b, b, 4) for tone in range(4)]
    assert pitches == [71, 74, 77, 81]
    assert loop_pitch(LoopNote(0, 0, 3, 1, 1, semitones=1), b, b, 4) == 82


@pytest.mark.parametrize("progression", HIP_HOP)
def test_every_built_in_loop_plays_on_the_new_progressions(progression: str) -> None:
    """Each built-in bass and melody loop over 8 bars with the surprises on: every
    note is a MIDI note, the bass stays monophonic, and the bass's first note of
    each bar (each loop starts on its root) follows the progression's roots."""
    library = load_loops()
    p = load_progressions()[progression]
    bass, melody = library.names("bass"), library.names("melody")
    grid = [BUSY, OPEN] * 4
    for bass_loop, loop in zip(bass, melody, strict=True):
        song = simulate(
            grid, Settings(progression=progression, bass_loop=bass_loop, loop=loop, surprise=2)
        )
        notes = [n for n in song.notes if n.part in ("bass", "keys")]
        assert {n.part for n in notes} == {"bass", "keys"}
        assert all(0 <= n.pitch <= 127 for n in notes)
        line = sorted((n for n in notes if n.part == "bass"), key=lambda n: n.tick)
        assert all(a.tick + a.ticks <= b.tick for a, b in pairwise(line)), bass_loop
        played_pitch_classes = {n.pitch % 12 for n in line}
        roots = {(p.tonic + c.root) % 12 for c in p.chords}
        assert roots <= played_pitch_classes, bass_loop


def test_progression_step_walks_the_list_and_wraps_around() -> None:
    ensemble = Ensemble(lambda line: None)
    step = ensemble.controls()["progression-step"]
    names = list(ensemble.progressions)
    seen = []
    for _ in names:
        step([1])
        seen.append(ensemble.progression.name)
    assert seen == [*names[1:], names[0]]
    step([-1.0])
    assert ensemble.progression.name == names[-1]
    for bad in ([], [2], ["next"], [1, 1]):
        with pytest.raises(ValueError, match="expected 1 or -1"):
            step(bad)
