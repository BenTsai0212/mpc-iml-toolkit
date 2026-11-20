"""Reading back a recording with MIDI clock (#139): `tag_recording` and `python -m mpc_iml.grid`.

`tests/data/clock_practice.jsonl` is a hand-made practice record at 120 BPM (a 16th
is 125 ms): a hit before Start, Start, one bar of ticks with a hit 10 ms early on
beat 2 and one 12 ms late on step 11, Stop, a hit while stopped, Song Position
Pointer to bar 3 and Continue, a hit on step 3 of bar 3, and a hit after the clock
was lost.
"""

from pathlib import Path

import pytest

from mpc_iml.clock import EIGHTHS, SIXTEENTH_TRIPLETS, tag_recording
from mpc_iml.events import MidiEvent, RawMidiEvent
from mpc_iml.grid import bpm_range, main, pad_name
from mpc_iml.recording import read_recording

PRACTICE = Path(__file__).parent / "data" / "clock_practice.jsonl"


def test_tags_each_hit_with_bar_step_and_offset() -> None:
    hits = tag_recording(read_recording(PRACTICE).events)
    assert [(h.t, h.bank, h.pad, h.velocity) for h in hits] == [
        (0.05, 0, 0, 80),
        (0.59, 0, 1, 90),
        (1.362, 0, 2, 100),
        (2.5, 1, 0, 70),
        (3.25, 0, 0, 110),
        (4.6, 0, 0, 60),
    ]
    tagged = [(h.grid.bar, h.grid.step) for h in hits if h.grid is not None]
    assert tagged == [(0, 4), (0, 10), (2, 2)]
    offsets = [h.grid.offset_ms for h in hits if h.grid is not None]
    assert offsets == pytest.approx([-10.0, 12.0, 0.0], abs=0.01)


def test_hits_before_start_while_stopped_and_after_lost_are_kept_untagged() -> None:
    hits = tag_recording(read_recording(PRACTICE).events)
    assert [h.t for h in hits if h.grid is None] == [0.05, 2.5, 4.6]


def test_other_resolutions_and_meters() -> None:
    events = read_recording(PRACTICE).events
    eighths = [h.grid for h in tag_recording(events, ticks_per_step=EIGHTHS) if h.grid]
    assert [(g.bar, g.step) for g in eighths] == [(0, 2), (0, 5), (2, 1)]
    triplets = [h.grid for h in tag_recording(events, ticks_per_step=SIXTEENTH_TRIPLETS) if h.grid]
    assert [(g.bar, g.step) for g in triplets] == [(0, 6), (0, 15), (2, 3)]
    three = [h.grid for h in tag_recording(events, beats_per_bar=3) if h.grid]
    assert [(g.bar, g.step) for g in three] == [(0, 4), (0, 10), (2, 10)]
    with pytest.raises(ValueError):
        tag_recording(events, ticks_per_step=5)


def test_without_clock_every_hit_is_untagged() -> None:
    events = [MidiEvent(0.1, "note_on", 1, 90, note=36), MidiEvent(0.2, "note_on", 1, 0, note=36)]
    hits = tag_recording(events)
    assert [(h.t, h.grid) for h in hits] == [(0.1, None)]
    assert bpm_range(events) is None


def test_bpm_range_follows_the_tempo() -> None:
    assert bpm_range(read_recording(PRACTICE).events) == pytest.approx((120.0, 120.0), abs=0.01)
    events = [RawMidiEvent(k / 48, b"\xf8") for k in range(30)]
    events += [RawMidiEvent(29 / 48 + k / 24, b"\xf8") for k in range(1, 40)]
    tempo = bpm_range(events)
    assert tempo is not None
    low, high = tempo
    assert low == pytest.approx(60.0, abs=0.01)
    assert high == pytest.approx(120.0, abs=0.01)


def test_pad_names() -> None:
    assert [pad_name(0, 0), pad_name(1, 0), pad_name(7, 15)] == ["A01", "B01", "H16"]


def test_cli_prints_one_line_per_hit_and_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(PRACTICE)]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == [
        "t\tbar\tstep\tpad\tvelocity\toffset_ms",
        "0.050\t-\t-\tA01\t80\t-",
        "0.590\t1\t5\tA02\t90\t-10.0",
        "1.362\t1\t11\tA03\t100\t+12.0",
        "2.500\t-\t-\tB01\t70\t-",
        "3.250\t3\t3\tA01\t110\t+0.0",
        "4.600\t-\t-\tA01\t60\t-",
    ]
    assert err.strip() == "6 hits: 3 on the grid, 3 not (120.0-120.0 BPM)"


def test_cli_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(PRACTICE), "--resolution", "8", "--beats-per-bar", "3"]) == 0
    rows = [line.split("\t")[1:3] for line in capsys.readouterr().out.splitlines()[1:]]
    assert [row for row in rows if row != ["-", "-"]] == [["1", "3"], ["1", "6"], ["3", "6"]]


def test_cli_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([str(tmp_path / "missing.jsonl")]) == 1
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    assert main([str(bad)]) == 1
    assert main([str(PRACTICE), "--beats-per-bar", "0"]) == 2
    assert "error" in capsys.readouterr().err
