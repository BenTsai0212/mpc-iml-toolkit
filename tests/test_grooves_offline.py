"""The grooves of a recording, after the fact: `python -m mpc_iml.grooves` (#245, PR 2)."""

import json
import random
from pathlib import Path

import pytest
from test_grooves import FILL, FILL2, SILENT, A, B, C, jitter

from mpc_iml.clock import SIXTEENTHS, TICKS_PER_BEAT
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.frames import bank_pad_to_note
from mpc_iml.grooves import FREE_BARS, PART_ROLES, Pattern, Tracker, similarity
from mpc_iml.grooves.__main__ import grid, main
from mpc_iml.grooves.offline import FORMAT, Result, track
from mpc_iml.recording import Header, write_recording

BAR = 4 * TICKS_PER_BEAT
PADS = {"kick": 0, "snare": 1, "hat": 2}
"""Pads with these roles in `ensemble.DEFAULT_ROLES`."""


def recording(*takes: list[Pattern], tempo: float = 100.0, extra: int = 0) -> list[Event]:
    """The events `record --clock` would write for `takes`, each a Start, its bars
    played on time and a Stop. `extra` adds hits on pads 15 and 16 and an `other` pad
    on every step 0."""
    interval = 60.0 / tempo / TICKS_PER_BEAT
    events: list[Event] = [MidiEvent(0.0, "note_on", 1, 80, bank_pad_to_note(0, 0))]
    t = 0.1
    for bars in takes:
        events.append(RawMidiEvent(t, b"\xfa"))
        for tick in range(len(bars) * BAR):
            events.append(RawMidiEvent(t, b"\xf8"))
            bar, rest = divmod(tick, BAR)
            if rest % SIXTEENTHS == 0:
                step = rest // SIXTEENTHS
                pads = [PADS[name] for name in PART_ROLES if step in bars[bar].role(name)]
                if extra and step == 0:
                    pads += [7, 14, 15]
                for pad in pads:
                    events.append(MidiEvent(t, "note_on", 1, 90, bank_pad_to_note(0, pad)))
            t += interval
        events.append(RawMidiEvent(t, b"\xfc"))
        t += 1.0
    return events


def kinds(result: Result) -> list[str]:
    return [b.kind if b.groove is None else f"{b.kind}{b.groove}" for b in result.bars]


def spans(result: Result) -> list[tuple[str, int | None, int, int]]:
    return [(s.kind, s.groove, result.bars[s.first].bar, s.length) for s in result.sections]


def test_complete_bars_are_tracked_as_live() -> None:
    bars = [A, A, A, FILL, A, A]
    result = track(recording(bars))
    # The last bar ends with Stop, not a bar line: it is never complete.
    assert [b.bar for b in result.bars] == [1, 2, 3, 4, 5]
    assert [b.pattern for b in result.bars] == bars[:5]
    live = Tracker()
    assert [b.decision for b in result.bars] == [live.observe(i, p) for i, p in enumerate(bars[:5])]
    assert kinds(result) == ["groove1", "groove1", "groove1", "fill1", "groove1"]
    assert spans(result) == [("groove", 1, 1, 5)]
    assert result.sections[0].fills == (3,)


def test_jitter_pads_15_and_16_and_other_pads_do_not_split_a_groove() -> None:
    rng = random.Random(7)
    result = track(recording([jitter(A, rng) for _ in range(9)], extra=1))
    assert spans(result) == [("groove", 1, 1, 8)]
    assert len(result.grooves) == 1 and similarity(result.grooves[0].prototype, A) >= 0.8


def test_a_groove_change_starts_at_its_first_bar_after_the_fact() -> None:
    result = track(recording([A, A, A, B, B, B, A, A, A]))
    assert [b.decision.fill for b in result.bars][3] is True
    assert kinds(result) == ["groove1"] * 3 + ["groove2"] * 3 + ["groove1"] * 2
    assert spans(result) == [("groove", 1, 1, 3), ("groove", 2, 4, 3), ("groove", 1, 7, 2)]
    assert [g.id for g in result.grooves] == [1, 2]


def test_fills_that_lead_to_free_bars_are_free() -> None:
    rng = random.Random(1)
    varying = [
        Pattern(*(frozenset(rng.sample(range(16), rng.randint(1, 6))) for _ in range(3)))
        for _ in range(8)
    ]
    result = track(recording([A, A, A, *varying, C, C, C]))
    assert kinds(result) == ["groove1"] * 3 + ["free"] * 8 + ["groove2"] * 2
    assert spans(result) == [("groove", 1, 1, 3), ("free", None, 4, 8), ("groove", 2, 12, 2)]
    assert [b.decision.fill for b in result.bars[3 : 3 + FREE_BARS]] == [True] * FREE_BARS


def test_silence_is_a_gap_and_a_one_bar_break_is_a_fill() -> None:
    result = track(recording([A, A, SILENT, A, A, FILL, SILENT, SILENT, A, A, A]))
    assert kinds(result) == (
        ["groove1", "groove1", "fill1", "groove1", "groove1"]
        + ["fill1", "silent", "silent", "groove1", "groove1"]
    )
    assert spans(result) == [("groove", 1, 1, 6), ("silent", None, 7, 2), ("groove", 1, 9, 2)]
    assert result.sections[0].fills == (2, 5)


def test_takes_share_the_library_and_stop_ends_the_groove() -> None:
    result = track(recording([A, A, A, FILL2], [FILL, A, A, B]))
    # The last bar of each take ends with Stop: never complete.
    assert [(b.take, b.bar) for b in result.bars] == [
        (1, 1),
        (1, 2),
        (1, 3),
        (2, 1),
        (2, 2),
        (2, 3),
    ]
    assert kinds(result) == ["groove1"] * 3 + ["none", "groove1", "groove1"]
    assert result.bars[4].decision.groove is None and result.bars[5].decision.new
    assert spans(result) == [("groove", 1, 1, 3), ("none", None, 1, 1), ("groove", 1, 2, 2)]


def test_a_recording_without_clock_is_refused() -> None:
    events = [e for e in recording([A, A]) if not isinstance(e, RawMidiEvent)]
    with pytest.raises(ValueError, match="no complete bar of MIDI clock"):
        track(events)


def test_grid() -> None:
    assert grid(A.kick) == "x... .... x.x. ...."
    assert grid(frozenset()) == ".... .... .... ...."


def write(tmp_path: Path, events: list[Event]) -> Path:
    path = tmp_path / "take.jsonl"
    write_recording(path, Header(), events)
    return path


def test_cli_lists_sections_and_grooves(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, recording([A, A, A, FILL, A, B, B, B]))
    assert main([str(path)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == [
        "take 1  bars 1-5  groove 1  (5 bars)  fills: 4",
        "take 1  bars 6-7  groove 2  (2 bars)",
    ]
    assert lines[3:6] == [
        "groove 1: 4 bars",
        "  kick  x... .... x.x. ....",
        "  snare .... x... .... x...",
    ]
    assert lines[7].startswith("  kicks 3.00  double_kicks 0.00")


def test_cli_json_and_thresholds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write(tmp_path, recording([A, A, A, FILL, FILL2, A]))
    assert main([str(path), "--json", "--free-bars", "1", "--similar", "0.7"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert (doc["format"], doc["version"]) == (FORMAT, 1)
    assert doc["settings"] == {"similar": 0.7, "return": 0.8, "free_bars": 1, "decay": 0.8}
    assert [b["kind"] for b in doc["bars"]] == ["groove", "groove", "groove", "free", "free"]
    assert doc["bars"][3]["live"] == {"groove": 1, "position": 4, "fill": True, "free": False}
    assert doc["bars"][0]["pattern"]["kick"] == [0, 8, 10]
    assert doc["sections"][0] == {
        "take": 1,
        "bar": 1,
        "length": 3,
        "kind": "groove",
        "groove": 1,
        "fills": [],
    }
    assert doc["grooves"][0]["prototype"]["snare"] == [4, 12]
    assert doc["grooves"][0]["features"]["hats"] == 8


def test_cli_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing.jsonl")]) == 1
    no_clock = write(tmp_path, [e for e in recording([A]) if not isinstance(e, RawMidiEvent)])
    assert main([str(no_clock)]) == 1
    assert main([str(no_clock), "--beats-per-bar", "3"]) == 2
    assert main([str(no_clock), "--free-bars", "0"]) == 2
    assert capsys.readouterr().err.count("error: ") == 4
