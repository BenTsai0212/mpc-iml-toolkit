"""`python -m mpc_iml.new`: the practice-repository template (Issue #25).

The generated project is checked in a subprocess with this repository's environment
(toolkit already installed, generated `src/` on PYTHONPATH): it runs on a replay,
its own tests pass, and it is clean under ruff and mypy --strict. Installing it with
uv is checked in CI (`.github/workflows/ci.yml`).
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

import mpc_iml
from mpc_iml import __version__
from mpc_iml.new import create, main, package_name

EXPECTED = {
    ".gitignore",
    ".python-version",
    "README.md",
    "pyproject.toml",
    "src/my_practice/__init__.py",
    "src/my_practice/__main__.py",
    "src/my_practice/model.py",
    "tests/data/example.jsonl",
    "tests/test_model.py",
}


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("practice") / "my-practice"
    create(target)
    return target


def run(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(project / "src")}
    return subprocess.run(
        [sys.executable, *args], cwd=project, env=env, capture_output=True, text=True
    )


def test_layout(project: Path) -> None:
    written = {p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()}
    assert written == EXPECTED


def test_dependency_pinned_to_git_tag(project: Path) -> None:
    pyproject = (project / "pyproject.toml").read_text()
    assert 'name = "my-practice"' in pyproject
    tag = f"git+https://github.com/BenTsai0212/mpc-iml-toolkit@v{__version__}"
    assert f'"mpc-iml-toolkit @ {tag}"' in pyproject
    assert f"v{__version__}" in (project / "README.md").read_text()


def test_no_copy_of_toolkit_code(project: Path) -> None:
    assert not list(project.rglob("mpc_iml"))

    def definitions(paths: list[Path]) -> set[str]:
        return {
            ast.dump(node)
            for path in paths
            for node in ast.parse(path.read_text()).body
            if isinstance(node, ast.FunctionDef | ast.ClassDef)
        }

    toolkit = definitions(list(Path(mpc_iml.__file__).parent.glob("*.py")))
    assert definitions(list(project.rglob("*.py"))).isdisjoint(toolkit)


@pytest.mark.parametrize(
    "args",
    [
        ("-m", "my_practice", "tests/data/example.jsonl"),
        ("-m", "pytest", "-q", "-p", "no:cacheprovider"),
        ("-m", "ruff", "check", "--no-cache"),
        ("-m", "ruff", "format", "--check", "--no-cache"),
        ("-m", "mypy", "--no-incremental", "--cache-dir", os.devnull),
    ],
    ids=["run", "pytest", "ruff-check", "ruff-format", "mypy"],
)
def test_generated_project_passes(project: Path, args: tuple[str, ...]) -> None:
    result = run(project, *args)
    assert result.returncode == 0, result.stdout + result.stderr


def test_run_trains_and_replays(project: Path) -> None:
    result = run(project, "-m", "my_practice", "tests/data/example.jsonl")
    assert "Trained on 10 examples" in result.stdout


def test_package_name() -> None:
    assert package_name("my-practice") == "my_practice"
    assert package_name("Gesture Study 2") == "gesture_study_2"
    for bad in ["2025-study", "class", "---", "mpc-iml"]:
        with pytest.raises(ValueError):
            package_name(bad)


def test_name_option(tmp_path: Path) -> None:
    assert main([str(tmp_path / "x"), "--name", "rolls"]) == 0
    assert (tmp_path / "x" / "src" / "rolls" / "model.py").is_file()
    assert 'name = "rolls"' in (tmp_path / "x" / "pyproject.toml").read_text()


def test_refuses_non_empty_directory(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    assert main([str(tmp_path), "--name", "p"]) == 1
    assert "not an empty directory" in capsys.readouterr().err
    assert [p.name for p in tmp_path.iterdir()] == ["keep.txt"]
