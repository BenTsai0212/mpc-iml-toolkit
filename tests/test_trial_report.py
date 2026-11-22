"""Reports of blind trial sessions (#197, PR 4)."""

import shutil
from pathlib import Path

import pytest

from mpc_iml.trial.__main__ import main
from mpc_iml.trial.report import (
    RANK,
    Row,
    consistent,
    load_sessions,
    report,
    rows,
    session_scores,
)
from mpc_iml.trial.session import SESSION_FILE, ConditionRecord, Header, SessionWriter
from mpc_iml.trial.spec import load_trial

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples" / "trial" / "rhythm.json"
TWO_BARS = Path(__file__).parent / "data" / "trial-two-bars.jsonl"


def _session(
    folder: Path,
    date: str,
    scores: dict[str, dict[str, int]],
    ranking: list[str] | None,
    order: tuple[str, str] = ("rhythm-0", "rhythm-1"),
) -> Path:
    """A session of the example trial: `scores` by condition name, `ranking` by name."""
    _, content = load_trial(EXAMPLE)
    folder.mkdir(parents=True)
    mapping = {"A": order[0], "B": order[1]}
    letter = {name: code for code, name in mapping.items()}
    header = Header(
        date=date,
        commit="0123456789abcdef",
        dirty=False,
        version="0.0.0",
        trial_file="examples/trial/rhythm.json",
        trial=content,
        seed=1,
        repeats=1,
        order=["A", "B"],
        mapping=mapping,
        engine={"options": ["--clock", "--beats-per-bar", "4"]},
    )
    writer = SessionWriter(folder / SESSION_FILE, header)
    for position, code in enumerate(["A", "B"]):
        shutil.copy(TWO_BARS, folder / f"{code}.jsonl")
        answers = {"broken-moment": "the fill"} if code == "A" else {}
        record = ConditionRecord(code, position, f"{code}.jsonl", 2, scores[mapping[code]], answers)
        writer.condition(record)
    if ranking is not None:
        writer.ranking([letter[name] for name in ranking])
    return folder / SESSION_FILE


def _three(tmp_path: Path) -> list[Path]:
    return [
        _session(
            tmp_path / "s1",
            "2026-11-20T10:00:00+00:00",
            {"rhythm-0": {"fun": 2, "heard-me": 3}, "rhythm-1": {"fun": 4, "heard-me": 3}},
            ["rhythm-1", "rhythm-0"],
        ),
        _session(
            tmp_path / "s2",
            "2026-11-21T10:00:00+00:00",
            {"rhythm-0": {"fun": 3, "heard-me": 4}, "rhythm-1": {"fun": 5, "heard-me": 2}},
            ["rhythm-1", "rhythm-0"],
            order=("rhythm-1", "rhythm-0"),
        ),
        _session(
            tmp_path / "s0",
            "2026-11-19T10:00:00+00:00",
            {"rhythm-0": {"fun": 1, "heard-me": 2}, "rhythm-1": {"fun": 1, "heard-me": 5}},
            None,
        ),
    ]


def test_rows_reveal_names_and_measure_the_recordings(tmp_path: Path) -> None:
    [(file, session)] = load_sessions([_three(tmp_path)[0].parent])
    table = rows(file, session)
    assert [(r.name, r.letter, r.rank) for r in table] == [
        ("rhythm-0", "A", 2),
        ("rhythm-1", "B", 1),
    ]
    assert table[0].scores == {"fun": 2, "heard-me": 3}
    assert table[0].measures["bars"] == 2 and table[0].measures["hits_per_bar"] == 16.5
    assert "answered" in table[0].measures
    assert rows(file, session, with_measures=False)[0].measures == {}


def test_a_missing_recording_has_no_measures(tmp_path: Path) -> None:
    file = _three(tmp_path)[0]
    (file.parent / "A.jsonl").unlink()
    [(_, session)] = load_sessions([file])
    assert rows(file, session)[0].measures == {}


def test_sessions_are_sorted_by_date_and_scores_keep_raw_values(tmp_path: Path) -> None:
    sessions = load_sessions(_three(tmp_path))
    assert [f.parent.name for f, _ in sessions] == ["s0", "s1", "s2"]
    lines = report(sessions, with_measures=False)
    assert "rhythm-0\tfun\t1 2 3\t2.00" in lines
    assert "rhythm-1\theard-me\t5 3 2\t3.33" in lines
    assert f"rhythm-1\t{RANK}\t1 1\t1.00" in lines
    assert "rhythm-0\tbroken-moment\tthe fill" in lines
    assert "no ranking: the session ended early" in lines


def test_consistent_needs_two_sessions_and_none_against(tmp_path: Path) -> None:
    lines = report(load_sessions(_three(tmp_path)), with_measures=False)
    found = lines[lines.index(next(x for x in lines if x.startswith("Consistent"))) + 1 :]
    # fun: rhythm-1 higher in s1 and s2, a tie in s0. heard-me: mixed. rank: s1, s2.
    assert found == [
        "fun\trhythm-1 > rhythm-0\tconsistent\t2 of 3 sessions",
        f"{RANK}\trhythm-1 > rhythm-0\tconsistent\t2 of 2 sessions",
    ]


def test_consistent_rules() -> None:
    assert consistent([{"a": 1, "b": 2}]) == []
    assert consistent([{"a": 1, "b": 2}, {"a": 1, "b": 3}]) == [("b", "a", 2, 2)]
    assert consistent([{"a": 1, "b": 2}, {"a": 1, "b": 3}, {"a": 4, "b": 3}]) == []
    assert consistent([{"a": 1, "b": 2}, {"a": 1, "b": 2}], lower_is_better=True) == [
        ("a", "b", 2, 2)
    ]


def test_repeats_average_within_a_session() -> None:
    table = [Row("a", "A", "A.jsonl", {"fun": s}, {}, 1, {}) for s in (2, 5)]
    assert session_scores(table, "fun") == {"a": 3.5}
    assert session_scores(table, RANK) == {"a": 1.0}


def test_report_marks_exploratory_measures(tmp_path: Path) -> None:
    lines = report(load_sessions(_three(tmp_path)[:1]))
    header = next(x for x in lines if x.startswith("condition\tletter"))
    assert "hits_per_bar" in header.split("\t")
    assert "answered (exploratory)" in header.split("\t")
    assert lines[-1] == "none"


def test_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    files = _three(tmp_path)
    assert main(["report", str(files[0].parent), str(files[1]), "--no-measures"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Session s1\t") and "Across 2 sessions" in out
    assert main(["report", str(tmp_path / "missing")]) == 1
    assert "cannot read" in capsys.readouterr().err
