"""Trial files, play order and session files of comparison trials (#197)."""

import copy
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from mpc_iml.ensemble import Ensemble
from mpc_iml.trial.order import balanced_latin_square, letters, trial_order
from mpc_iml.trial.session import (
    ConditionRecord,
    Header,
    SessionError,
    SessionWriter,
    git_commit,
    read_session,
    session_folder,
)
from mpc_iml.trial.spec import Guide, TrialError, load_trial, parse_trial

EXAMPLE = Path(__file__).parent.parent / "examples" / "trial" / "rhythm.json"

TRIAL: dict[str, Any] = {
    "format": "mpc-iml-trial",
    "format_version": 1,
    "bars": 8,
    "base": {"rhythm": [0], "surprise": [1]},
    "conditions": [
        {"name": "plain", "settings": {}},
        {"name": "moved", "settings": {"rhythm": [1], "surprise": [0]}},
    ],
    "questions": [
        {"id": "fun", "text": "It is fun", "scale": "1-5"},
        {"id": "broken", "text": "A moment that felt broken", "scale": "text"},
    ],
}


def _with(**changes: Any) -> dict[str, Any]:
    data = copy.deepcopy(TRIAL)
    data.update(changes)
    return data


def test_parse_trial_reads_conditions_questions_and_messages() -> None:
    trial = parse_trial(TRIAL)
    assert trial.bars == 8
    assert [c.name for c in trial.conditions] == ["plain", "moved"]
    assert [(q.id, q.scale) for q in trial.questions] == [("fun", "1-5"), ("broken", "text")]
    moved = trial.conditions[1]
    assert trial.messages(moved) == [
        ("rhythm", (0,)),
        ("surprise", (1,)),
        ("rhythm", (1,)),
        ("surprise", (0,)),
    ]


def test_guide_lines_are_a_list_or_one_string() -> None:
    """#241: `guide.start` and `guide.condition`, each a list of strings or one string."""
    trial = parse_trial(
        _with(guide={"start": ["Lead the band.", "Nod with 16."], "condition": "Again."})
    )
    assert trial.guide == Guide(("Lead the band.", "Nod with 16."), ("Again.",))
    assert parse_trial(_with(guide={"condition": ["Again."]})).guide == Guide((), ("Again.",))


def test_a_trial_without_a_guide_has_no_lines() -> None:
    assert parse_trial(TRIAL).guide == Guide((), ())


def test_bars_default_to_16() -> None:
    data = _with()
    del data["bars"]
    assert parse_trial(data).bars == 16


def test_min_bars_is_optional_and_at_most_bars() -> None:
    """#243: without `min_bars` Enter ends a condition as before."""
    assert parse_trial(_with()).min_bars is None
    assert parse_trial(_with(min_bars=8)).min_bars == 8


def test_example_trials_set_a_minimum_length() -> None:
    """#243: 100 of 240 bars in the learning trial, 32 in the rhythm trial."""
    assert load_trial(EXAMPLE.with_name("learn.json"))[0].min_bars == 100
    rhythm = load_trial(EXAMPLE)[0]
    assert rhythm.min_bars == 32 and rhythm.bars >= 32


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ([], "not a JSON object"),
        (_with(format_version=2), "format_version 1"),
        (_with(extra=1), "unknown fields: extra"),
        (_with(bars=0), "bars must be"),
        (_with(bars=True), "bars must be"),
        (_with(min_bars=0), "min_bars must be a whole number 1-8"),
        (_with(min_bars=9), "min_bars must be .*at most bars.*got 9"),
        (_with(min_bars=2.5), "min_bars must be"),
        (_with(min_bars=True), "min_bars must be"),
        (_with(min_bars="4"), "min_bars must be"),
        (_with(conditions=TRIAL["conditions"][:1]), "at least 2"),
        (
            _with(conditions=[{"name": "a", "settings": {}}, {"name": "a", "settings": {}}]),
            "names must be unique",
        ),
        (
            _with(conditions=[*TRIAL["conditions"], {"name": "x", "settings": {"bass": ["off"]}}]),
            "sets bass, which base must also set",
        ),
        (_with(base={"rhythm": 0}), "base rhythm: expected a list"),
        (_with(base={"Rhythm": [0]}), "control must be lower case"),
        (_with(questions=[]), "questions must be"),
        (_with(guide=["Play."]), "guide must be an object"),
        (_with(guide={"start": [], "during": ["Play."]}), "guide: unknown fields: during"),
        (_with(guide={"start": ["Play.", 16]}), "guide.start must be a string or a list"),
        (_with(guide={"condition": 16}), "guide.condition must be a string or a list"),
        (_with(questions=[{"id": "a", "text": "A", "scale": "1-7"}]), "scale must be one of"),
        (
            _with(questions=[{"id": "a", "text": "A", "scale": "text"}] * 2),
            "ids must be unique",
        ),
    ],
)
def test_parse_trial_refuses_bad_files(data: Any, message: str) -> None:
    with pytest.raises(TrialError, match=message):
        parse_trial(data)


def test_example_file_has_the_issue_questions_and_ensemble_accepts_its_settings() -> None:
    trial, content = load_trial(EXAMPLE)
    assert content["format"] == "mpc-iml-trial"
    assert [c.name for c in trial.conditions] == ["rhythm-0", "rhythm-1"]
    assert [q.scale for q in trial.questions] == ["1-5"] * 5 + ["text"] * 2
    controls = Ensemble().controls()
    for condition in trial.conditions:
        for control, args in trial.messages(condition):
            controls[control](list(args))


def test_learn_trial_starts_every_condition_from_the_rules() -> None:
    trial, _ = load_trial(EXAMPLE.with_name("learn.json"))
    assert [c.name for c in trial.conditions] == ["learn-off", "learn-likes", "learn-demo"]
    assert trial.base["reset-learning"] == () and trial.base["learn-log"] == (0,)
    ensemble = Ensemble()
    controls = ensemble.controls()
    for condition in trial.conditions:
        for _ in range(4):
            ensemble._learners["bass"].like("grid/-", "drive")
        assert ensemble._learned() == ["bass:grid/->drive"]
        for control, args in trial.messages(condition):
            if control != "learn-log":
                controls[control](list(args))
        assert ensemble._learned() == []
        assert dict(ensemble.state())["learn"] == [condition.name.removeprefix("learn-")]
        assert dict(ensemble.state())["melody-mode"][0] == "still", "#233"


LEARN_GUIDE_START = [
    "You will play with three bands, one after another. Give each one a full go; "
    "they may sound alike, and that is fine. Play each the same way.",
    "You lead a band with your drums. The bass and keys follow your groove.",
    "Play as in a jam: start a groove, stay with it for a few phrases (4 bars each), "
    "then change it.",
    "When the bass plays something you want to hear again with this groove, tap pad 16 "
    "once, like a nod to the bass player. Keep your hands going.",
    "If you want the bass to change, change your groove. You do not need a pad for that.",
    "Try a few grooves: steady kicks on the beat, kicks that push ahead of the beat, a busy "
    "groove. Later, come back to a groove where you nodded, and listen whether the bass "
    "remembers.",
    "To rest, stop drumming; the band keeps playing. Do not press Stop in Live.",
]
LEARN_GUIDE_CONDITION = [
    "A new band. Play the same way: start a groove, nod (pad 16) when you like the bass, "
    "and come back to that groove later.",
]


def test_learn_trial_guides_the_musician_in_musical_terms() -> None:
    """#241: the text of the Issue, the same before every condition."""
    trial, content = load_trial(EXAMPLE.with_name("learn.json"))
    assert trial.guide == Guide(tuple(LEARN_GUIDE_START), tuple(LEARN_GUIDE_CONDITION))
    assert content["guide"]["start"] == LEARN_GUIDE_START


def test_rhythm_trial_guide_has_no_pads_to_press() -> None:
    trial, _ = load_trial(EXAMPLE)
    lines = trial.guide.start + trial.guide.condition
    assert trial.guide.start and trial.guide.condition
    assert not any("pad 1" in line for line in lines)
    assert any("sparse to busy" in line for line in trial.guide.condition)


@pytest.mark.parametrize(
    "name", ["rhythm.json", "learn.json", "groove.json", "nod.json", "catch.json"]
)
def test_example_trials_keep_the_modes_from_the_pads(name: str) -> None:
    trial, _ = load_trial(EXAMPLE.with_name(name))
    assert trial.base["mode-pads"] == (0,)
    ensemble = Ensemble()
    controls = ensemble.controls()
    for condition in trial.conditions:
        for control, args in trial.messages(condition):
            if control != "learn-log":
                controls[control](list(args))
        assert dict(ensemble.state())["mode-pads"] == [0]


def test_load_trial_reports_unreadable_files(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(TrialError, match="cannot read"):
        load_trial(path)


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
def test_balanced_latin_square_is_balanced(n: int) -> None:
    rows = balanced_latin_square(n)
    assert len(rows) == (n if n % 2 == 0 else 2 * n)
    for row in rows:
        assert sorted(row) == list(range(n))
    for position in range(n):
        firsts = [row[position] for row in rows]
        assert all(firsts.count(c) == len(rows) // n for c in range(n))
    pairs = [(row[i], row[i + 1]) for row in rows for i in range(n - 1)]
    for a in range(n):
        for b in range(n):
            if a != b:
                assert pairs.count((a, b)) == len(rows) // n


def test_two_conditions_alternate_by_seed_and_repeats_mirror() -> None:
    assert trial_order(2, seed=0) == [0, 1]
    assert trial_order(2, seed=7) == [1, 0]
    assert trial_order(2, seed=0, repeats=2) == [0, 1, 1, 0]
    row = trial_order(3, seed=4)
    assert trial_order(3, seed=4, repeats=3) == row + row[::-1] + row
    with pytest.raises(ValueError):
        trial_order(2, seed=0, repeats=0)


def test_letters_follow_play_order() -> None:
    assert letters([1, 0, 0, 1]) == {1: "A", 0: "B"}


def _header(**changes: Any) -> Header:
    values: dict[str, Any] = {
        "date": "2026-11-22T13:00:00+00:00",
        "commit": "abc123",
        "dirty": False,
        "version": "0.1.0",
        "trial_file": "rhythm.json",
        "trial": TRIAL,
        "seed": 7,
        "repeats": 1,
        "order": ["A", "B"],
        "mapping": {"A": "moved", "B": "plain"},
        "engine": {"clock": True},
    }
    values.update(changes)
    return Header(**values)


def _record(letter: str, position: int) -> ConditionRecord:
    return ConditionRecord(
        letter=letter,
        position=position,
        recording=f"{letter}.jsonl",
        bars=8,
        scores={"fun": 4},
        answers={"broken": "bar 3 felt late"},
    )


def test_session_file_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = SessionWriter(path, _header())
    writer.condition(_record("A", 0))
    writer.condition(_record("B", 1))
    writer.ranking(["B", "A"])
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["type"] for line in lines] == ["header", "condition", "condition", "ranking"]
    session = read_session(path)
    assert session.header == _header()
    assert session.conditions == (_record("A", 0), _record("B", 1))
    assert session.ranking == ("B", "A")
    assert session.condition_name("A") == "moved"


def test_session_file_marks_a_condition_ended_early(tmp_path: Path) -> None:
    """#243: `ended_early` round-trips; a session written before it reads as false."""
    path = tmp_path / "session.jsonl"
    writer = SessionWriter(path, _header())
    early = ConditionRecord("A", 0, "A.jsonl", 3, {"fun": 2}, {}, ended_early=True)
    writer.condition(early)
    writer.condition(_record("B", 1))
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["ended_early"] for line in lines[1:]] == [True, False]
    assert read_session(path).conditions == (early, _record("B", 1))
    for line in lines[1:]:
        del line["ended_early"]
    old = tmp_path / "old.jsonl"
    old.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    assert [c.ended_early for c in read_session(old).conditions] == [False, False]


def test_session_file_keeps_records_written_before_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = SessionWriter(path, _header())
    writer.condition(_record("A", 0))
    session = read_session(path)
    assert [c.letter for c in session.conditions] == ["A"]
    assert session.ranking is None


def test_session_writer_refuses_bad_records(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = SessionWriter(path, _header())
    with pytest.raises(SessionError, match="unknown letter"):
        writer.condition(_record("C", 0))
    with pytest.raises(SessionError, match="each letter once"):
        writer.ranking(["A"])
    with pytest.raises(FileExistsError):
        SessionWriter(path, _header())


@pytest.mark.parametrize(
    ("lines", "message"),
    [
        ([], "first record must be the header"),
        ([{"type": "condition"}], "first record must be the header"),
        ([{"type": "header", "format": "other", "format_version": 1}], "not an mpc-iml-session"),
        ([{"type": "header", "format": "mpc-iml-session", "format_version": 1}], "missing date"),
    ],
)
def test_read_session_refuses_bad_files(
    tmp_path: Path, lines: list[dict[str, Any]], message: str
) -> None:
    path = tmp_path / "session.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    with pytest.raises(SessionError, match=message):
        read_session(path)


def test_read_session_refuses_records_after_the_ranking(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    writer = SessionWriter(path, _header())
    writer.ranking(["A", "B"])
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps({"type": "ranking", "ranking": ["A", "B"]}) + "\n")
    with pytest.raises(SessionError, match="nothing may follow the ranking"):
        read_session(path)


def test_session_folder_is_new_and_named_by_time(tmp_path: Path) -> None:
    now = datetime(2026, 11, 22, 13, 5, 9)
    folder = session_folder(tmp_path, now)
    assert folder == tmp_path / "trials" / "20261122-130509"
    assert folder.is_dir()
    with pytest.raises(FileExistsError):
        session_folder(tmp_path, now)


def test_git_commit_outside_git_is_a_dash(tmp_path: Path) -> None:
    assert git_commit(tmp_path) == ("-", None)


def test_git_commit_in_the_repository() -> None:
    commit, dirty = git_commit(Path(__file__).parent)
    assert commit == "-" or len(commit) == 40
    assert dirty in (True, False, None)


def test_groove_trial_compares_following_each_bar_and_the_groove() -> None:
    """#250 trial 1: rules only, `follow-by` is the one difference."""
    trial, _ = load_trial(EXAMPLE.with_name("groove.json"))
    assert [c.name for c in trial.conditions] == ["follow-bar", "follow-groove"]
    assert trial.bars == 160 and trial.min_bars == 64
    assert "followed-change" in [q.id for q in trial.questions]
    ensemble = Ensemble()
    controls = ensemble.controls()
    for condition in trial.conditions:
        for control, args in trial.messages(condition):
            if control != "learn-log":
                controls[control](list(args))
        state = dict(ensemble.state())
        assert state["follow-by"] == [condition.name.removeprefix("follow-")]
        assert state["learn"] == ["off"] and state["new-groove"] == ["rules"]
        assert state["melody-mode"][0] == "still"
    assert not any("pad 1" in line for line in trial.guide.start + trial.guide.condition)


def test_nod_trial_compares_learning_off_and_nods_while_following_the_groove() -> None:
    """#250 trial 2: `follow-by groove` in both, `learn` is the one difference, and
    each condition starts from the rules."""
    trial, _ = load_trial(EXAMPLE.with_name("nod.json"))
    assert [c.name for c in trial.conditions] == ["learn-off", "learn-nod"]
    assert trial.bars == 240 and trial.min_bars == 100
    assert trial.base["reset-learning"] == () and trial.base["learn-log"] == (0,)
    ensemble = Ensemble()
    controls = ensemble.controls()
    for condition in trial.conditions:
        for control, args in trial.messages(condition):
            if control != "learn-log":
                controls[control](list(args))
        state = dict(ensemble.state())
        assert state["learn"] == [condition.name.removeprefix("learn-")]
        assert state["follow-by"] == ["groove"] and state["learn-group"] == [0]
        assert state["new-groove"] == ["rules"] and state["melody-mode"][0] == "still"
    assert any("pad 16" in line for line in trial.guide.start)


def test_catch_trial_compares_no_catch_the_catch_and_its_comparison() -> None:
    """#290: `catch` is the one difference; the melody follows, so it can catch."""
    trial, _ = load_trial(EXAMPLE.with_name("catch.json"))
    assert [c.name for c in trial.conditions] == ["catch-0", "catch-1", "catch-2"]
    assert trial.min_bars is not None and trial.min_bars <= trial.bars
    assert [(q.text, q.scale) for q in trial.questions] == [
        ("The band answered what I had just played", "1-5"),
        ("It sounded good", "1-5"),
        ("What did you notice?", "text"),
    ]
    ensemble = Ensemble()
    controls = ensemble.controls()
    for condition in trial.conditions:
        for control, args in trial.messages(condition):
            if control != "learn-log":
                controls[control](list(args))
        state = dict(ensemble.state())
        assert state["catch"] == [int(condition.name.removeprefix("catch-"))]
        assert state["melody-mode"][0] == "follow" and state["learn"] == ["off"]
    assert not any("pad 1" in line for line in trial.guide.start + trial.guide.condition)
