"""User loop files for `ensemble` (#173 PR 3, ADR 0010): the data folder, the controls
`reload-loops`, `bass-loop-step` and `loop-step`, and the reply `loop-errors`."""

import copy
import json
from pathlib import Path
from typing import Any

import pytest
import test_engine
from test_engine_preset_state import Stateful, installed
from test_loops import LOOP, MELODY

from mpc_iml.ensemble import Ensemble, make_preset
from mpc_iml.loops import load_loops, load_user_loops, parse_loop

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

PREFIX = "/mpciml/preset/ensemble/"


def write(folder: Path, name: str, data: Any) -> Path:
    """Write `data` as `<folder>/loops/<name>.json` (text when it is a string)."""
    path = folder / "loops" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    return path


def named(name: str, base: dict[str, Any] = LOOP) -> dict[str, Any]:
    data = copy.deepcopy(base)
    data["name"] = name
    return data


def state(ensemble: Ensemble) -> dict[str, list[Any]]:
    return {name: list(args) for name, args in ensemble.state()}


def loaded(folder: Path) -> tuple[Ensemble, list[str]]:
    lines: list[str] = []
    ensemble = Ensemble(lines.append)
    ensemble.data_folder(folder)
    return ensemble, lines


# The loader


def test_user_loops_come_after_the_installed_ones_by_name(tmp_path: Path) -> None:
    write(tmp_path, "zed", named("zed"))
    write(tmp_path, "abe", named("abe"))
    write(tmp_path, "arp", MELODY)
    library, errors = load_user_loops(tmp_path / "loops", load_loops())
    assert errors == []
    assert library.names("bass") == ["boom", "walk", "abe", "zed"]
    assert library.names("melody") == ["keys", "pluck", "arp"]


def test_a_missing_folder_has_no_user_loops(tmp_path: Path) -> None:
    library, errors = load_user_loops(tmp_path / "loops", load_loops())
    assert (library.names("bass"), errors) == (["boom", "walk"], [])


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("broken", "{not json", "broken.json: cannot read"),
        ("bad", {**named("bad"), "bars": 3}, "bad.json: bars must be 1, 2 or 4"),
        ("other", named("line"), "other.json: the file name must equal the name 'line'"),
        ("boom", named("boom"), "boom.json: a loop named 'boom' already exists"),
    ],
)
def test_a_bad_user_file_is_skipped_with_a_message(
    tmp_path: Path, name: str, data: Any, message: str
) -> None:
    write(tmp_path, "good", named("good"))
    write(tmp_path, name, data)
    library, errors = load_user_loops(tmp_path / "loops", load_loops())
    assert library.names("bass") == ["boom", "walk", "good"]
    assert library.get("boom", "bass").origin != str(tmp_path / "loops" / "boom.json")
    (error,) = errors
    assert message in error


# The preset


def test_the_data_folder_hook_reads_the_user_loops(tmp_path: Path) -> None:
    write(tmp_path, "line", LOOP)
    write(tmp_path, "arp", MELODY)
    ensemble, lines = loaded(tmp_path)
    replies = state(ensemble)
    assert replies["bass-loops"] == ["boom", "walk", "line"]
    assert replies["loops"] == ["keys", "pluck", "arp"]
    assert replies["loop-errors"] == [0]
    assert lines == [f"ensemble: 2 user loops from {tmp_path / 'loops'}, 0 skipped"]
    assert make_preset(lambda line: None).data_folder is not None


def test_bad_files_are_logged_and_counted(tmp_path: Path) -> None:
    write(tmp_path, "broken", "{")
    write(tmp_path, "walk", named("walk"))
    ensemble, lines = loaded(tmp_path)
    assert state(ensemble)["loop-errors"] == [2]
    assert sum("ensemble: skipped a loop file: " in line for line in lines) == 2
    assert state(ensemble)["bass-loops"] == ["boom", "walk"]


def test_a_user_loop_is_chosen_by_name_and_plays_its_notes(tmp_path: Path) -> None:
    write(tmp_path, "line", LOOP)
    ensemble, _ = loaded(tmp_path)
    ensemble.controls()["bass-loop"](["line"])
    assert ensemble.bass_loop == parse_loop(LOOP).loop()
    with pytest.raises(ValueError, match="expected one of keys, pluck, got"):
        ensemble.controls()["loop"](["line"])


def test_reload_uses_a_changed_file_and_keeps_a_gone_loop_playing(tmp_path: Path) -> None:
    path = write(tmp_path, "line", LOOP)
    ensemble, _ = loaded(tmp_path)
    controls = ensemble.controls()
    controls["bass-loop"](["line"])
    changed = copy.deepcopy(LOOP)
    changed["variations"]["home"][0]["tone"] = 2
    write(tmp_path, "line", changed)
    controls["reload-loops"]([])
    assert ensemble.bass_loop == parse_loop(changed).loop()
    path.unlink()
    write(tmp_path, "broken", "{")
    controls["reload-loops"]([])
    replies = state(ensemble)
    assert (replies["bass-loop"], replies["bass-loops"]) == (["line"], ["boom", "walk"])
    assert replies["loop-errors"] == [1]
    assert ensemble.bass_loop == parse_loop(changed).loop()
    controls["bass-loop-step"]([1])
    assert state(ensemble)["bass-loop"] == ["boom"]


def test_reload_needs_the_data_folder_and_no_arguments(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no data folder"):
        Ensemble().controls()["reload-loops"]([])
    ensemble, _ = loaded(tmp_path)
    with pytest.raises(ValueError, match="expected no arguments"):
        ensemble.controls()["reload-loops"]([1])


@pytest.mark.parametrize(
    ("control", "reply", "steps", "names"),
    [
        (
            "bass-loop-step",
            "bass-loop",
            [1, 1, 1, -1, -1],
            ["walk", "line", "boom", "line", "walk"],
        ),
        ("loop-step", "loop", [-1, -1, 1], ["arp", "pluck", "arp"]),
    ],
)
def test_step_moves_through_the_list_and_wraps(
    tmp_path: Path, control: str, reply: str, steps: list[int], names: list[str]
) -> None:
    write(tmp_path, "line", LOOP)
    write(tmp_path, "arp", MELODY)
    ensemble, _ = loaded(tmp_path)
    seen = []
    for step in steps:
        ensemble.controls()[control]([step])
        seen.append(state(ensemble)[reply][0])
    assert seen == names


@pytest.mark.parametrize("args", [[], [0], [2], ["next"], [1, 1]])
def test_step_takes_1_or_minus_1(args: list[Any]) -> None:
    with pytest.raises(ValueError, match="expected 1 or -1"):
        Ensemble().controls()["loop-step"](args)


# The engine


def test_the_engine_gives_the_preset_its_data_folder(start: Any) -> None:
    folders: list[Path] = []
    preset = Stateful().preset(data_folder=folders.append)
    front = start(preset="stateful", presets=installed(preset))
    assert folders == [front.engine.data_dir]
    front.ask("/mpciml/preset/load", "demo")
    front.ask("/mpciml/preset/load", "stateful")
    assert folders == [front.engine.data_dir] * 2


def test_a_data_folder_hook_that_raises_is_logged(start: Any) -> None:
    lines: list[str] = []

    def broken(folder: Path) -> None:
        raise RuntimeError("broken")

    preset = Stateful().preset(data_folder=broken)
    front = start(preset="stateful", presets=installed(preset), log=lines.append)
    assert any("data folder hook failed" in line for line in lines)
    assert front.state() == "idle"


def test_ensemble_in_the_engine_lists_and_reloads_user_loops(start: Any) -> None:
    preset = make_preset(lambda line: None)
    front = start(preset="ensemble", presets=installed(preset))
    write(front.engine.data_dir, "line", LOOP)
    assert (PREFIX + "bass-loops", ["boom", "walk"]) in front.ask("/mpciml/state/get")
    replies = front.ask(PREFIX + "reload-loops")
    assert (PREFIX + "bass-loops", ["boom", "walk", "line"]) in replies
    assert replies[-1] == (PREFIX + "loop-errors", [0])
    assert (PREFIX + "bass-loop", ["line"]) in front.ask(PREFIX + "bass-loop-step", -1)
