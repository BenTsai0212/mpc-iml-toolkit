"""The `hardware` marker is registered and hardware tests are skipped by default."""

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"

SAMPLE_TESTS = """
import pytest

@pytest.mark.hardware
def test_needs_mpc():
    pass

def test_plain():
    pass
"""


@pytest.fixture
def project(pytester: pytest.Pytester) -> pytest.Pytester:
    """A temporary project with this repository's pytest configuration."""
    pytester.makepyprojecttoml(PYPROJECT.read_text(encoding="utf-8"))
    tests = pytester.mkdir("tests")
    (tests / "test_sample.py").write_text(SAMPLE_TESTS, encoding="utf-8")
    return pytester


def test_hardware_tests_are_deselected_by_default(project: pytest.Pytester) -> None:
    result = project.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, deselected=1)


def test_hardware_tests_run_with_marker(project: pytest.Pytester) -> None:
    result = project.runpytest("-p", "no:cacheprovider", "-m", "hardware")
    result.assert_outcomes(passed=1, deselected=1)


def test_hardware_marker_is_registered(project: pytest.Pytester) -> None:
    result = project.runpytest("-p", "no:cacheprovider", "--markers")
    result.stdout.fnmatch_lines(["@pytest.mark.hardware:*"])
