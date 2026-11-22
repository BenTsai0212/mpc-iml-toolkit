"""Objective measures of a `record --clock` recording for blind trials (#197, PR 2)."""

from pathlib import Path

import pytest
from test_webdemo_replay import BUSY, SPARSE, take

from mpc_iml.events import RawMidiEvent
from mpc_iml.measures import (
    CAP,
    EXPLORATORY,
    Response,
    band_changes,
    distance,
    main,
    measure,
    replay_settings,
    response,
)
from mpc_iml.recording import read_recording
from mpc_iml.trial.spec import load_trial
from mpc_iml.webdemo.sim import Settings, replay

DATA = Path(__file__).parent / "data"
TWO_BARS = DATA / "trial-two-bars.jsonl"
EXAMPLE = Path(__file__).parents[1] / "examples" / "trial" / "rhythm.json"
LEARN = EXAMPLE.with_name("learn.json")


def test_the_two_bar_recording_has_known_measures() -> None:
    """Bar 1: kicks 1 and 9, snares 5 and 13, hats on 8ths; bar 2 adds a kick on 11
    and hats on every 16th (8 of them odd)."""
    m = measure(read_recording(TWO_BARS).events)
    assert (m.bars, m.hits, m.kicks, m.hats) == (2, (12, 21), (2, 3), (8, 16))
    assert m.syncopation == pytest.approx(8 / 33)
    assert m.changes == pytest.approx((9 / 21,))
    assert m.response is None
    summary = m.summary()
    assert summary["hits_per_bar"] == 16.5 and summary["pattern_change"] == pytest.approx(3 / 7)
    assert EXPLORATORY <= set(summary) and summary["answered"] is None


def test_a_steady_pattern_does_not_change() -> None:
    m = measure(take([SPARSE] * 6))
    assert (m.bars, m.hits, m.syncopation) == (6, (4,) * 6, 0.0)
    assert m.changes == (0.0,) * 5


def test_only_complete_bars_of_the_first_take_count() -> None:
    events = take([BUSY] * 3)
    ticks = [i for i, e in enumerate(events) if isinstance(e, RawMidiEvent) and e.data == b"\xf8"]
    m = measure(events[: ticks[2 * 96 + 48]])
    assert (m.bars, m.hits) == (2, (26, 26))
    assert measure(take([BUSY] * 3, bank=2)) == measure(take([BUSY] * 3))


def test_no_clock_gives_no_bars() -> None:
    m = measure([e for e in take([BUSY]) if not isinstance(e, RawMidiEvent)], settings=Settings())
    assert (m.bars, m.syncopation, m.changes, m.response) == (0, None, (), None)
    assert m.summary()["hits_per_bar"] is None


def test_distance() -> None:
    a = frozenset({("kick", 0), ("hat", 2)})
    assert distance(a, a) == 0.0 and distance(frozenset(), frozenset()) == 0.0
    assert distance(a, frozenset({("kick", 0)})) == 0.5
    assert distance(a, frozenset()) == 1.0


def test_response_counts_bars_until_the_musician_changes() -> None:
    changes = [0.0, 0.0, 0.0, 0.6, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.9]
    assert len(changes) + 1 == 12
    # Band changes in bar 2: answered in bar 4; bar 5: no answer in bars 6-9; bars 9
    # and 10: answered in bar 11; bar 11: no bar after it to see, left out.
    assert response(changes, [2, 5, 9, 10]) == Response((2, None, 2, 1))
    assert response(changes, [10, 11]) == Response((1,))
    assert Response((2, None, 2, 1)).answered == 0.75
    assert Response((2, None, 2, 1)).mean == pytest.approx(5 / 3)
    assert Response(()).answered is None and Response((None,)).mean is None
    assert response([0.0] * 10, [3]) == Response((None,)) and CAP == 4


def test_the_musician_answers_the_band_one_bar_later() -> None:
    """The musician changes every 2 bars; the band follows in the bar after, and the
    musician's next change comes one bar after that."""
    events = take([SPARSE, SPARSE, BUSY, BUSY] * 3)
    assert band_changes(replay(events).rows) == [3, 5, 7, 9, 11]
    m = measure(events, settings=Settings())
    assert m.response == Response((1, 1, 1, 1))
    assert m.summary()["band_changes"] == 4 and m.summary()["response_bars"] == 1.0


def test_no_answer_when_the_musician_keeps_the_pattern() -> None:
    m = measure(take([SPARSE, SPARSE] + [BUSY] * 8), settings=Settings())
    assert m.response == Response((None,))
    assert measure(take([SPARSE, BUSY] * 3), 3, settings=Settings()).response is None


def test_replay_settings_from_a_trial() -> None:
    trial, _ = load_trial(EXAMPLE)
    rhythm = next(c for c in trial.conditions if c.name == "rhythm-1")
    assert replay_settings(trial.messages(rhythm)) == Settings(surprise=1, rhythm=1)
    assert replay_settings([("bass-loop", ["walk"]), ("fade-bars", [4])]) == Settings(
        bass_loop="walk", fade_bars=4
    )
    learn, _ = load_trial(LEARN)
    demo = next(c for c in learn.conditions if c.name == "learn-demo")
    assert replay_settings(learn.messages(demo)) == Settings(surprise=1, learn="demo")
    for bad in [("bass", ["rule"]), ("learn-loops", [1]), ("learn-log", [2]), ("rhythm", [])]:
        with pytest.raises(ValueError, match="the replay cannot play"):
            replay_settings([bad])


def test_the_command_prints_the_measures(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(TWO_BARS)]) == 0
    lines = dict(line.split("\t", 1) for line in capsys.readouterr().out.splitlines())
    assert lines["bars"] == "2" and lines["hits_per_bar"] == "16.50"
    assert lines["syncopation"] == "0.24" and lines["kicks_per_bar"] == "2.50"
    assert lines["band_changes"] == "0\t(exploratory)"
    assert lines["response_bars"] == "-\t(exploratory)"
    args = [str(TWO_BARS), "--trial", str(EXAMPLE), "--condition", "rhythm-1"]
    assert main(args) == 0


def test_the_command_refuses_bad_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing.jsonl")]) == 1
    assert main([str(TWO_BARS), "--condition", "rhythm-1"]) == 1
    assert main([str(TWO_BARS), "--trial", str(EXAMPLE), "--condition", "nope"]) == 1
    assert "rhythm-0, rhythm-1" in capsys.readouterr().err
    assert main([str(TWO_BARS), "--beats-per-bar", "0"]) == 2
    empty = tmp_path / "empty.jsonl"
    empty.write_text(TWO_BARS.read_text().splitlines()[0] + "\n")
    assert main([str(empty)]) == 0
    assert "no complete bar" in capsys.readouterr().err
