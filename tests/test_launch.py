"""The launch command `mpc-iml` (#66): engine plus the Pure Data front end."""

import re
import sys
import tomllib
from pathlib import Path
from typing import Any

import pytest

from mpc_iml import launch
from mpc_iml.engine import Engine
from mpc_iml.presets import available_presets

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "tests" / "fixtures" / "recordings" / "hold-pressure.jsonl"


@pytest.fixture
def no_serve(monkeypatch: pytest.MonkeyPatch) -> list[Engine]:
    """Return at once from `serve_forever`, keeping the engines that would have served."""
    served: list[Engine] = []
    monkeypatch.setattr(Engine, "serve_forever", lambda self: served.append(self))
    return served


def start(tmp_path: Path, *extra: str, opener: Any) -> int:
    argv = [str(tmp_path / "data"), "--replay", str(REPLAY), "--control-port", "0", *extra]
    return launch.main(argv, opener=opener)


def test_console_script() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["mpc-iml"] == "mpc_iml.launch:main"


def test_defaults() -> None:
    args = launch.build_parser().parse_args([])
    assert (args.data, args.no_patch, args.preset) == ("mpc-iml-data", False, "demo")
    assert (args.control_port, args.reply_port) == (6450, 6451)


def test_patch_is_the_general_front_end() -> None:
    path = launch.patch_path()
    assert path.is_file()
    assert path.name == "mpc-iml.pd"
    for name in ("demo", "pressure"):
        assert available_presets()[name].patch_path() is not None
        assert Path(str(available_presets()[name].patch_path())) == path


def test_opens_the_patch_after_the_engine_listens(
    tmp_path: Path, no_serve: list[Engine], capsys: pytest.CaptureFixture[str]
) -> None:
    opened: list[tuple[Path, bool]] = []

    def opener(path: Path) -> bool:
        opened.append((path, not no_serve))
        return True

    assert start(tmp_path, opener=opener) == 0
    assert opened == [(launch.patch_path(), True)]
    assert len(no_serve) == 1
    assert "Opened the front end" in capsys.readouterr().out


def test_prints_the_path_when_it_cannot_open(
    tmp_path: Path, no_serve: list[Engine], capsys: pytest.CaptureFixture[str]
) -> None:
    assert start(tmp_path, opener=lambda path: False) == 0
    assert f"Open this patch in Pure Data: {launch.patch_path()}" in capsys.readouterr().out
    assert len(no_serve) == 1


def test_no_patch_starts_only_the_engine(tmp_path: Path, no_serve: list[Engine]) -> None:
    opened: list[Path] = []
    assert start(tmp_path, "--no-patch", opener=lambda path: bool(opened.append(path))) == 0
    assert opened == []
    assert len(no_serve) == 1


def test_engine_options_are_passed_on(tmp_path: Path, no_serve: list[Engine]) -> None:
    assert start(tmp_path, "--preset", "pressure", "--no-patch", opener=lambda p: True) == 0
    assert no_serve[0]._preset.name == "pressure"


def test_unknown_preset_does_not_open_the_patch(tmp_path: Path) -> None:
    opened: list[Path] = []
    code = start(tmp_path, "--preset", "missing", opener=lambda path: bool(opened.append(path)))
    assert code == 2
    assert opened == []


def test_open_file_without_opener(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    assert launch.open_file(tmp_path / "x.pd", platform="darwin") is False
    assert launch.open_file(tmp_path / "x.pd", platform="linux") is False


@pytest.mark.parametrize(("platform", "opener"), [("darwin", "open"), ("linux", "xdg-open")])
@pytest.mark.parametrize("returncode", [0, 1])
def test_open_file_runs_the_system_opener(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, platform: str, opener: str, returncode: int
) -> None:
    calls: list[list[str]] = []

    class Done:
        def __init__(self, code: int) -> None:
            self.returncode = code

    def run(command: list[str], **kwargs: Any) -> Done:
        calls.append(command)
        return Done(returncode)

    monkeypatch.setattr(launch.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(launch.subprocess, "run", run)
    assert launch.open_file(tmp_path / "x.pd", platform=platform) is (returncode == 0)
    assert calls == [[opener, str(tmp_path / "x.pd")]]


@pytest.mark.skipif(sys.platform == "win32", reason="os.startfile exists on Windows")
def test_open_file_on_windows_without_startfile(tmp_path: Path) -> None:
    assert launch.open_file(tmp_path / "x.pd", platform="win32") is False


WALKTHROUGH = {"README.md": "## Play in 20 minutes", "README.zh-TW.md": "## 20 分鐘開始演奏"}


def walkthrough(name: str) -> str:
    text = (ROOT / name).read_text()
    start = text.index(WALKTHROUGH[name] + "\n")
    end = text.index("\n## ", start + 1)
    return text[start:end]


@pytest.mark.parametrize("name", sorted(WALKTHROUGH))
def test_readme_walkthrough(name: str) -> None:
    section = walkthrough(name)
    assert "uv run mpc-iml\n" in section
    assert "--no-patch" in section
    for control in ("connect", "pressure", "record", "stop_recording", "train", "run"):
        assert f"`{control}`" in section


def test_readme_walkthroughs_have_the_same_steps() -> None:
    steps = [re.findall(r"^(\d+)\. ", walkthrough(name), re.M) for name in sorted(WALKTHROUGH)]
    prose = [
        re.sub(r"```.*?```", "", walkthrough(name), flags=re.S) for name in sorted(WALKTHROUGH)
    ]
    commands = [re.findall(r"`([^`]+)`", text) for text in prose]
    assert steps[0] == steps[1] and len(steps[0]) >= 5
    assert sorted(commands[0]) == sorted(commands[1])
