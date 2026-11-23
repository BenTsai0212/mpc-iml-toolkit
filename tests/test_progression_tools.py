"""The musician's own progressions in the tools and the chord names (#236 PR 4,
ADR 0011): `--data` for `loops import|export`, `vargen --midi` and `measures`, the
replay's `library`, and `Progression.chord_name` for the status line."""

import json
from pathlib import Path

import pytest
from test_ensemble_user_progressions import named, write
from test_measures import EXAMPLE, TWO_BARS
from test_webdemo_replay import BUSY, SPARSE, take

from mpc_iml import loop_midi, measures, vargen
from mpc_iml.content import ContentError
from mpc_iml.progressions import find_progression, load_progressions, progression_library
from mpc_iml.webdemo.sim import Settings, chord_name, progressions, replay


@pytest.fixture
def data(tmp_path: Path) -> Path:
    """A data folder with the user progression `my-two` (Bbm7, Eb7; 2 bars each)."""
    write(tmp_path, "my-two", named("my-two"))
    return tmp_path


def test_chord_name_walks_the_chords() -> None:
    library = load_progressions()
    assert [library["minor-two"].chord_name(b) for b in range(-1, 5)] == (
        ["Am7", "Am7", "Am7", "Fmaj7", "Fmaj7", "Am7"]
    )
    assert [library["minor-turn"].chord_name(b) for b in range(4)] == [
        "Bm7b5",
        "E7",
        "Am7",
        "Am7",
    ]
    assert chord_name("minor-four", 3) == "A7"


def test_find_progression_reads_the_data_folder(data: Path) -> None:
    assert find_progression("minor-two", None) == load_progressions()["minor-two"]
    assert find_progression("my-two", data).chord_name(2) == "Eb7"
    with pytest.raises(
        ContentError, match=r"unknown progression 'my-two'; progressions: minor-two"
    ):
        find_progression("my-two", None)
    assert list(progression_library(data)[0])[-1] == "my-two"


def test_an_unknown_name_mentions_skipped_files(data: Path) -> None:
    write(data, "broken", "{")
    with pytest.raises(ContentError, match=r"1 file\(s\) in .* skipped"):
        find_progression("broken", data)


def test_loops_export_and_import_over_a_user_progression(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mine = data / "boom-my-two.mid"
    base = data / "boom.mid"
    exported = ["export", "boom", str(mine), "--progression", "my-two", "--data", str(data)]
    assert loop_midi.main(exported) == 0
    assert loop_midi.main(["export", "boom", str(base), "--data", str(data)]) == 0
    assert mine.read_bytes() != base.read_bytes(), "other chords, other pitches"
    out = data / "out"
    imported = ["import", str(mine), "--part", "bass", "--name", "back", "--out", str(out)]
    assert loop_midi.main([*imported, "--progression", "my-two", "--data", str(data)]) == 0
    back = loop_midi._read(out / "back.json").variations["home"]
    assert back == loop_midi._find("boom", str(data)).variations["home"], "the same chord tones"
    capsys.readouterr()
    assert loop_midi.main(["export", "boom", str(mine), "--progression", "nope"]) == 1
    assert "unknown progression 'nope'; progressions: minor-two" in capsys.readouterr().err


def test_vargen_writes_clips_over_a_user_progression(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["boom", "--count", "1", "--data", str(data), "--midi"]
    assert vargen.main([*args, "--progression", "my-two"]) == 0
    assert sorted(p.name for p in (data / "vargen").iterdir())[0] == "boom-home-0.mid"
    capsys.readouterr()
    assert vargen.main([*args, "--progression", "nope"]) == 1
    assert "unknown progression 'nope'" in capsys.readouterr().err


def test_the_replay_plays_a_progression_of_its_library(data: Path) -> None:
    library, _ = progression_library(data)
    song = replay(take([SPARSE, BUSY, SPARSE]), Settings(progression="my-two"), library)
    assert [row.chord for row in song.rows] == ["Bbm7", "Eb7", "Eb7"]
    with pytest.raises(ValueError, match="my-two"):
        replay(take([SPARSE]), Settings(progression="my-two"))
    assert "my-two" not in progressions()


def test_measures_replays_with_the_progressions_of_data(
    data: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trial = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    trial["base"]["progression"] = ["my-two"]
    path = data / "trial.json"
    path.write_text(json.dumps(trial), encoding="utf-8")
    args = [str(TWO_BARS), "--trial", str(path), "--condition", "rhythm-1"]
    assert measures.main([*args, "--data", str(data)]) == 0
    capsys.readouterr()
    assert measures.main([*args, "--data", str(data / "none")]) == 1
    assert "unknown progression 'my-two'" in capsys.readouterr().err
