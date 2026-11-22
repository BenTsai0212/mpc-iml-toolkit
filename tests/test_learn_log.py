"""The per-bar log of `ensemble` (#196 PR 4b, `learn_log`): `learn-log 0|1`, its
lines in every `learn` mode, and `python -m mpc_iml.learn summary <log>`.

On the simulated DAW clock of `test_ensemble.py` (`Rig`).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from test_ensemble import BAR, START, STEP, Rig
from test_ensemble_demo import PUSHED
from test_ensemble_learn import DATA, SESSIONS, STEADY, bar_of, reply, session

from mpc_iml import __version__
from mpc_iml.learn_log import LOG_FORMAT, BarLog, log_path, read_log, summary
from mpc_iml.learn_profile import main


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def record(bar: int) -> dict[str, Any]:
    return {"bar": bar, "learn": "off"}


def test_a_bar_is_written_two_bar_lines_later_with_its_like(tmp_path: Path) -> None:
    log = BarLog(tmp_path / "log.jsonl", {"learn": "likes"}, 3, None)
    log.bar(record(0))
    log.bar(record(1))
    log.like(0)
    assert len(lines(log.path)) == 1, "the header only"
    log.bar(record(2))
    log.like(0)
    log.example(1, "bass", "drive")
    header, first = lines(log.path)
    assert header["format"] == LOG_FORMAT and header["seed"] == 3
    assert header["settings"] == {"learn": "likes"}
    assert first == {**record(0), "like": True, "example": {"bass": None, "melody": None}}
    log.close()
    written = lines(log.path)[1:]
    assert [b["bar"] for b in written] == [0, 1, 2]
    assert written[1]["example"] == {"bass": "drive", "melody": None}


def test_a_song_restart_writes_what_waits(tmp_path: Path) -> None:
    log = BarLog(tmp_path / "log.jsonl", {}, None, None)
    for bar in (0, 1, 2, 0):
        log.bar(record(bar))
    assert [b["bar"] for b in lines(log.path)[1:]] == [0, 1, 2]


def test_a_new_log_never_overwrites_one(tmp_path: Path) -> None:
    now = datetime(2026, 11, 22, 14, 5, 9)
    first = log_path(tmp_path, now)
    assert first == tmp_path / "learn" / "log-20261122-140509.jsonl"
    BarLog(first, {}, None, None).close()
    assert log_path(tmp_path, now).name == "log-20261122-140509-2.jsonl"


@pytest.mark.parametrize("text", ["", "{", '{"format": "other", "format_version": 1}\n'])
def test_a_bad_log_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "log.jsonl"
    path.write_text(text)
    with pytest.raises(ValueError, match="log.jsonl"):
        read_log(path)


# In `ensemble`


def logging(folder: Path, learn: str) -> Rig:
    rig = Rig(melody=True, bass="loop", seed=1)
    rig.ensemble.data_folder(folder)
    controls = rig.ensemble.controls()
    controls["learn"]([learn])
    controls["learn-log"]([1])
    rig.send(START)
    return rig


def stop(rig: Rig, folder: Path) -> list[dict[str, Any]]:
    """Close the log; its lines."""
    rig.ensemble.controls()["learn-log"]([0])
    (path,) = (folder / "learn").glob("log-*.jsonl")
    return lines(path)


def test_learn_log_needs_a_data_folder() -> None:
    rig = Rig(melody=True, bass="loop")
    with pytest.raises(ValueError, match="no data folder"):
        rig.ensemble.controls()["learn-log"]([1])
    rig.ensemble.controls()["learn-log"]([0])
    assert reply(rig, "learn-log") == [0]


def test_learn_off_with_the_log_still_plays_what_main_played(tmp_path: Path) -> None:
    before = json.loads(DATA.read_text())
    for i, name in enumerate(SESSIONS):
        assert session(name, None, tmp_path / str(i)) == before[name], name


def test_learn_off_logs_each_bar_with_the_rules(tmp_path: Path) -> None:
    rig = logging(tmp_path, "off")
    assert reply(rig, "learn-log") == [1]
    for bar in range(3):
        bar_of(rig, bar, hits=PUSHED)
    rig.until(3 * BAR + STEP)
    header, *bars = stop(rig, tmp_path)
    assert reply(rig, "learn-log") == [0]
    assert header["settings"]["learn"] == "off" and header["profile"] is None
    assert [b["bar"] for b in bars] == [0, 1, 2, 3]
    last = bars[-1]
    assert last["context"] == {"bass": "push/beat", "melody": "sparse/8ths"}
    assert last["choice"]["bass"] == {"loop": "boom", "variation": "push", "level": 1}
    assert last["source"] == {"bass": "rule", "melody": "rule"}
    assert last["rule"]["bass"] == "push"
    assert isinstance(last["t"], float)
    assert not any(b["like"] for b in bars)


def test_learn_likes_logs_the_likes_and_the_bandit(tmp_path: Path) -> None:
    rig = logging(tmp_path, "likes")
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    bar_of(rig, 2)
    bar_of(rig, 3, press=1)
    bars = stop(rig, tmp_path)[1:]
    assert [b["like"] for b in bars] == [False, True, True, False]
    assert bars[1]["source"] == {"bass": "bandit", "melody": "bandit"}
    assert bars[1]["context"] == {"bass": "grid/beat", "melody": "mid/8ths"}


def test_learn_demo_logs_the_wants_and_the_examples(tmp_path: Path) -> None:
    rig = logging(tmp_path, "demo")
    rig.ensemble.controls()["want"](["bass", "drive"])
    for bar in range(3):
        bar_of(rig, bar, hits=STEADY)
    bars = stop(rig, tmp_path)[1:]
    assert [b["example"]["bass"] for b in bars] == ["drive", "drive", None]
    assert bars[2]["want"] == {"bass": "drive", "melody": "auto"}
    assert bars[2]["source"]["bass"] == "want"
    assert bars[2]["choice"]["bass"]["variation"] == "drive"
    assert bars[2]["rule"]["bass"] == "home"


def test_the_summary_counts_likes_differences_and_examples(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rig = logging(tmp_path, "demo")
    rig.ensemble.controls()["want"](["bass", "drive"])
    for bar in range(3):
        bar_of(rig, bar, hits=STEADY)
    rig.ensemble.controls()["learn"](["likes"])
    bar_of(rig, 3, press=8)
    rig.until(4 * BAR + STEP)
    (path,) = (tmp_path / "learn").glob("log-*.jsonl")
    rig.ensemble.controls()["learn-log"]([0])
    text = summary(*read_log(path))
    assert text.splitlines()[:5] == [
        f"log: toolkit {__version__}, 5 bars",
        "demo: 3 bars, 0 likes (0% of bars)",
        "  bass: 2 bars playing, 2 differ from the rules (100%); want 2",
        "  bass examples: drive 2",
        "  melody: 2 bars playing, 0 differ from the rules (0%); rule 2",
    ]
    assert "likes: 2 bars, 1 likes (50% of bars)" in text
    assert main(["summary", str(path)]) == 0
    assert capsys.readouterr().out.strip() == text
    assert main(["summary", str(tmp_path / "none.jsonl")]) == 1
    assert "error:" in capsys.readouterr().err
