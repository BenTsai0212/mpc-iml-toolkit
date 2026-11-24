"""The groove tracker in `ensemble` (#245 PR 3): the status line and the learn log
show the live decision on the bar before each bar line, and nothing that plays
changes.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). The tracker itself is
tested in `test_grooves.py`; here only how `ensemble` feeds and shows it.
"""

import json
from pathlib import Path
from typing import Any

from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, STOP, Rig
from test_ensemble_demo import PUSHED
from test_ensemble_learn import STEADY, bar_of

from mpc_iml.ensemble import groove_record, groove_text
from mpc_iml.grooves import Decision
from mpc_iml.learn_log import read_log, summary

A = STEADY
"""Groove A: kicks 0 and 8, snares 4 and 12, hats 2, 6 and 10."""
B = PUSHED
"""Groove B: kicks 0 and 6, snares 4 and 12, hat 2 (0.67 against A)."""
FILL = [(s, SNARE) for s in range(0, 16, 2)] + [(0, KICK)]
"""A snare roll: a fill against A and B."""
ROLL = [(s, KICK) for s in range(16)]
"""Kicks on every step: a fill, and different from `FILL`."""
SILENT: list[tuple[int, int]] = []


def rig(status: int = 1, **kwargs: Any) -> Rig:
    return Rig(melody=True, bass="loop", status=status, seed=1, **kwargs)


def grooves(played: Rig) -> dict[int, str]:
    """Bar -> the groove field of its status line at the bar line."""
    shown = {}
    for line in played.log:
        if line.startswith("ensemble: bar "):
            fields = line.split("  ")
            shown[int(fields[0].split()[2])] = fields[2]
    return shown


def play(played: Rig, bars: list[list[tuple[int, int]]], first: int = 0) -> None:
    for i, hits in enumerate(bars):
        bar_of(played, first + i, hits=hits)
    played.until((first + len(bars)) * BAR + STEP)


def test_the_status_line_shows_the_groove_fills_a_change_a_return_and_silence() -> None:
    played = rig()
    played.send(START)
    play(played, [A, A, A, FILL, A, B, B, A, A, SILENT, SILENT, A])
    assert grooves(played) == {
        0: "groove -",
        1: "groove -",
        2: "groove 1 (bar 2)",
        3: "groove 1 (bar 3)",
        4: "fill",
        5: "groove 1 (bar 5)",
        6: "fill",
        7: "groove 2 (bar 2)",
        8: "fill",
        9: "groove 1 (bar 2)",
        10: "fill",
        11: "groove -",
        12: "groove -",
    }


def test_four_fills_in_a_row_free_the_groove_until_two_similar_bars() -> None:
    played = rig()
    played.send(START)
    play(played, [A, A, A, FILL, ROLL, FILL, ROLL, FILL, B, B])
    shown = grooves(played)
    assert [shown[bar] for bar in range(4, 11)] == [
        "fill",
        "fill",
        "fill",
        "fill",
        "groove free",
        "groove free",
        "groove 2 (bar 2)",
    ]


def test_stop_and_start_end_the_groove_and_keep_its_id() -> None:
    played = rig()
    played.send(START)
    play(played, [B, B, A, A])
    played.send(STOP)
    played.log.clear()
    played.next_tick = 0
    played.send(START)
    play(played, [A, A, A])
    shown = grooves(played)
    assert [shown[bar] for bar in range(4)] == [
        "groove -",
        "groove -",
        "groove 2 (bar 2)",
        "groove 2 (bar 3)",
    ]


def test_pads_16_and_15_are_not_part_of_the_groove() -> None:
    played = rig()
    played.send(START)
    with_pads = A + [(3, LAYER)]
    play(played, [A, A, with_pads, A])
    assert grooves(played)[4] == "groove 1 (bar 4)"


def test_the_groove_changes_nothing_that_plays(tmp_path: Path) -> None:
    bars = [A, A, A, FILL, B, B, A, SILENT, SILENT, A, A, FILL, ROLL, FILL, ROLL, A]
    sent = []
    for status, log in ((0, False), (1, False), (1, True)):
        played = rig(status)
        if log:
            played.ensemble.data_folder(tmp_path)
            played.ensemble.controls()["learn-log"]([1])
        played.send(START)
        play(played, bars)
        sent.append(played.sent)
    assert sent[0] == sent[1] == sent[2]


def test_the_learn_log_records_the_live_decision_and_the_summary_counts_it(
    tmp_path: Path,
) -> None:
    played = rig()
    played.ensemble.data_folder(tmp_path)
    played.ensemble.controls()["learn-log"]([1])
    played.send(START)
    play(played, [A, A, A, FILL, B, B, FILL, ROLL, FILL, ROLL, B])
    played.ensemble.controls()["learn-log"]([0])
    (path,) = (tmp_path / "learn").glob("log-*.jsonl")
    header, bars = read_log(path)
    by_bar = {b["bar"]: b["groove"] for b in bars}
    assert by_bar[0] == {"id": None, "position": None, "fill": False, "free": False}
    assert by_bar[3] == {"id": 1, "position": 3, "fill": False, "free": False}
    assert by_bar[4] == {"id": 1, "position": 4, "fill": True, "free": False}
    assert by_bar[5] == {"id": 1, "position": 5, "fill": True, "free": False}
    assert by_bar[6] == {"id": 2, "position": 2, "fill": False, "free": False}
    assert by_bar[11] == {"id": None, "position": None, "fill": False, "free": True}
    text = summary(header, bars).splitlines()
    assert text[-3:] == [
        "grooves: 2, fill bars: 6, free bars: 1",
        "groove changes: 1, the bass changed in 0",
        "  bar 6: groove 1 -> 2, bass push -> push (same)",
    ]


def test_a_log_without_the_groove_field_has_no_groove_line(tmp_path: Path) -> None:
    path = tmp_path / "old.jsonl"
    header = {"format": "mpc-iml-ensemble-log", "format_version": 1, "toolkit": "0.1.0"}
    line = {"bar": 1, "learn": "off", "choice": {}, "source": {}, "rule": {}}
    path.write_text(json.dumps(header) + "\n" + json.dumps(line) + "\n", encoding="utf-8")
    assert "grooves:" not in summary(*read_log(path))


def test_the_groove_text_and_record() -> None:
    assert groove_text(None) == "groove -"
    assert groove_text(Decision(3)) == "groove -"
    assert groove_text(Decision(3, free=True)) == "groove free"
    assert groove_text(Decision(3, groove=2, position=5, start=0)) == "groove 2 (bar 5)"
    assert groove_text(Decision(3, groove=2, position=5, start=0, fill=True)) == "fill"
    assert groove_record(Decision(3, groove=2, position=5, start=0, fill=True)) == {
        "id": 2,
        "position": 5,
        "fill": True,
        "free": False,
    }
