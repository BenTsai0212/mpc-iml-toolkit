"""User progression files for `ensemble` (#236 PR 3, ADR 0011): the data folder,
`reload-loops`, and the reply `progression-errors`."""

import json
from pathlib import Path
from typing import Any

import pytest
import test_engine
from test_engine_preset_state import installed
from test_progressions import HIP_HOP, SETS, TWO

from mpc_iml.ensemble import Ensemble, make_preset
from mpc_iml.progressions import (
    chord_names,
    load_progressions,
    load_user_progressions,
    main,
    parse_progression,
)

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

PREFIX = "/mpciml/preset/ensemble/"
BUILT_IN = ["minor-two", "minor-four", *sorted(HIP_HOP | SETS)]


def write(folder: Path, name: str, data: Any) -> Path:
    """Write `data` as `<folder>/progressions/<name>.json` (text when it is a string)."""
    path = folder / "progressions" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def named(name: str, **fields: Any) -> dict[str, Any]:
    return {**TWO, "name": name, **fields}


def state(ensemble: Ensemble) -> dict[str, list[Any]]:
    return {name: list(args) for name, args in ensemble.state()}


def loaded(folder: Path) -> tuple[Ensemble, list[str]]:
    lines: list[str] = []
    ensemble = Ensemble(lines.append)
    ensemble.data_folder(folder)
    return ensemble, lines


# The loader


def test_user_progressions_come_after_the_built_in_ones_by_name(tmp_path: Path) -> None:
    write(tmp_path, "zed", named("zed"))
    write(tmp_path, "abe", named("abe"))
    progressions, errors = load_user_progressions(tmp_path / "progressions", load_progressions())
    assert errors == []
    assert list(progressions) == [*BUILT_IN, "abe", "zed"]
    assert progressions["abe"].origin == str(tmp_path / "progressions" / "abe.json")


def test_a_missing_folder_has_no_user_progressions(tmp_path: Path) -> None:
    progressions, errors = load_user_progressions(tmp_path / "progressions", load_progressions())
    assert (list(progressions), errors) == (BUILT_IN, [])


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("broken", "{not json", "broken.json: cannot read"),
        (
            "bad",
            named("bad", chords=[{"root": 0, "quality": "m9"}]),
            "bad.json: chords[0]: quality must be one of m7, maj7, 7, m7b5, got 'm9'",
        ),
        ("long", named("long", chords=[{"root": 0, "quality": "m7", "bars": 3}]), "got 3"),
        ("other", named("line"), "other.json: the file name must equal the name 'line'"),
        ("minor-two", named("minor-two"), "a progression named 'minor-two' already exists"),
    ],
)
def test_a_bad_user_file_is_skipped_with_a_message(
    tmp_path: Path, name: str, data: Any, message: str
) -> None:
    write(tmp_path, "good", named("good"))
    write(tmp_path, name, data)
    progressions, errors = load_user_progressions(tmp_path / "progressions", load_progressions())
    assert list(progressions) == [*BUILT_IN, "good"]
    assert progressions["minor-two"] == load_progressions()["minor-two"]
    (error,) = errors
    assert message in error


def test_list_with_the_data_folder(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(tmp_path, "two", TWO)
    assert main(["list", "--data", str(tmp_path)]) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "two: Bbm7 (2) Eb7 (2)"
    write(tmp_path, "broken", "{")
    assert main(["list", "--data", str(tmp_path)]) == 1
    assert "skipped: " in capsys.readouterr().err


# The preset


def test_the_data_folder_hook_reads_the_user_progressions(tmp_path: Path) -> None:
    write(tmp_path, "two", TWO)
    ensemble, lines = loaded(tmp_path)
    replies = state(ensemble)
    assert replies["progressions"] == [*BUILT_IN, "two"]
    assert replies["progression"] == ["minor-two"]
    assert replies["progression-errors"] == [0]
    folder = tmp_path / "progressions"
    assert f"ensemble: 1 user progressions from {folder}, 0 skipped" in lines


def test_no_user_files_log_nothing(tmp_path: Path) -> None:
    _, lines = loaded(tmp_path)
    assert not any("progression" in line for line in lines)


def test_bad_files_are_logged_and_counted(tmp_path: Path) -> None:
    write(tmp_path, "broken", "{")
    write(tmp_path, "soul-minor", named("soul-minor"))
    ensemble, lines = loaded(tmp_path)
    assert state(ensemble)["progression-errors"] == [2]
    assert sum("ensemble: skipped a progression file: " in line for line in lines) == 2
    assert state(ensemble)["progressions"] == BUILT_IN
    assert state(ensemble)["loop-errors"] == [0]


def test_a_user_progression_is_chosen_and_plays_its_chords(tmp_path: Path) -> None:
    write(tmp_path, "two", TWO)
    ensemble, _ = loaded(tmp_path)
    ensemble.controls()["progression"](["two"])
    assert ensemble.progression == parse_progression(TWO, ensemble.progression.origin)
    assert chord_names(ensemble.progression) == "Bbm7 (2) Eb7 (2)"
    assert ensemble.progression.root_note(2, 1) == 24 + 3
    ensemble.controls()["progression-step"]([1])
    assert ensemble.progression.name == "minor-two"


def test_reload_uses_a_changed_file_and_keeps_a_gone_progression(tmp_path: Path) -> None:
    path = write(tmp_path, "two", TWO)
    ensemble, _ = loaded(tmp_path)
    controls = ensemble.controls()
    controls["progression"](["two"])
    changed = named("two", tonic="C")
    write(tmp_path, "two", changed)
    controls["reload-loops"]([])
    assert ensemble.progression.tonic == 0
    path.unlink()
    write(tmp_path, "broken", "{")
    controls["reload-loops"]([])
    replies = state(ensemble)
    assert (replies["progression"], replies["progressions"]) == (["two"], BUILT_IN)
    assert replies["progression-errors"] == [1]
    assert ensemble.progression.tonic == 0
    controls["progression-step"]([-1])
    assert state(ensemble)["progression"] == [BUILT_IN[-1]]
    with pytest.raises(ValueError, match="expected one of"):
        controls["progression"](["two"])


def test_without_a_data_folder_there_are_only_built_in_ones() -> None:
    replies = state(Ensemble(lambda line: None))
    assert (replies["progressions"], replies["progression-errors"]) == (BUILT_IN, [0])


# The engine


def test_ensemble_in_the_engine_lists_and_reloads_user_progressions(start: Any) -> None:
    preset = make_preset(lambda line: None)
    front = start(preset="ensemble", presets=installed(preset))
    write(front.engine.data_dir, "two", TWO)
    assert (PREFIX + "progressions", BUILT_IN) in front.ask("/mpciml/state/get")
    replies = front.ask(PREFIX + "reload-loops")
    assert (PREFIX + "progressions", [*BUILT_IN, "two"]) in replies
    assert (PREFIX + "progression-errors", [0]) in replies
    assert (PREFIX + "progression", ["two"]) in front.ask(PREFIX + "progression-step", -1)
