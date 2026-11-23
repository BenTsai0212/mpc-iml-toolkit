"""Progression files (#236, ADR 0011): format, loading, and that the built-in
progressions play as the Python table did before."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.content import ContentError
from mpc_iml.ensemble import Ensemble
from mpc_iml.progressions import (
    DEFAULT,
    Chord,
    Progression,
    chord_names,
    load_progressions,
    main,
    parse_progression,
)

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
