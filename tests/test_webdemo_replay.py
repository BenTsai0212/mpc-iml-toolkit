"""The web demo plays a `record --clock` recording into `ensemble` (#166, PR 3)."""

from pathlib import Path

import pytest

from mpc_iml.clock import SIXTEENTHS, TICKS_PER_BEAT, tag_recording
from mpc_iml.events import Event, MidiEvent, RawMidiEvent
from mpc_iml.frames import bank_pad_to_note
from mpc_iml.recording import read_recording
from mpc_iml.webdemo.app import HIT_HEADERS, TABLE_HEADERS, upload
from mpc_iml.webdemo.sim import DRUMS, MAX_BARS, STEPS, Settings, replay, simulate

DATA = Path(__file__).parent / "data"
BAR = 4 * TICKS_PER_BEAT
SPARSE = {"kick": [100, 0, 0, 0] * 4}
BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70] * STEPS}


def take(grid: list[dict[str, list[int]]], tempo: float = 100.0, bank: int = 0) -> list[Event]:
    """The events `record --clock` would write for `grid` played on time at `tempo`,
    with a hit before Start and events after a Stop."""
    interval = 60.0 / tempo / TICKS_PER_BEAT
    events: list[Event] = [MidiEvent(0.0, "note_on", 1, 80, bank_pad_to_note(bank, 0))]
    events.append(RawMidiEvent(0.1, b"\xfa"))
    for tick in range(len(grid) * BAR):
        t = 0.1 + tick * interval
        events.append(RawMidiEvent(t, b"\xf8"))
        bar, rest = divmod(tick, BAR)
        if rest % SIXTEENTHS == 0:
            for pad, drum in enumerate(DRUMS):
                velocity = grid[bar].get(drum, [0] * STEPS)[rest // SIXTEENTHS]
                if velocity:
                    note = bank_pad_to_note(bank, pad)
                    events.append(MidiEvent(t, "note_on", 1, velocity, note))
                    events.append(MidiEvent(t + 0.01, "note_on", 1, 0, note))
    end = 0.1 + len(grid) * BAR * interval
    events += [RawMidiEvent(end, b"\xfc"), RawMidiEvent(end + 0.1, b"\xfa")]
    events += [MidiEvent(end + 0.2, "note_on", 1, 100, bank_pad_to_note(bank, 0))]
    return events


def test_a_recording_plays_like_the_same_grid() -> None:
    grid = [SPARSE, BUSY, {}, SPARSE]
    song = replay(take(grid, 100.0), Settings(surprise=0))
    expected = simulate(grid, Settings(tempo=100.0, surprise=0))
    assert song.settings.tempo == pytest.approx(100.0)
    assert (song.bars, song.rows) == (expected.bars, expected.rows)
    assert song.notes == expected.notes and song.brightness == expected.brightness


def test_any_bank_plays_the_drums() -> None:
    grid = [SPARSE, BUSY]
    assert replay(take(grid, bank=2)).rows == replay(take(grid)).rows


def test_the_practice_recording_matches_tag_recording() -> None:
    events = read_recording(DATA / "clock_practice.jsonl").events
    song = replay(events)
    tagged = [h.grid for h in tag_recording(events) if h.grid is not None and h.grid.bar == 0]
    drums = [n for n in song.notes if n.part in DRUMS]
    assert [(n.tick // SIXTEENTHS, n.velocity) for n in drums] == [
        (g.step, g.velocity) for g in tagged
    ]
    assert [n.part for n in drums] == ["snare", "hat"]
    assert song.settings.tempo == pytest.approx(120.0) and song.bars == 2


def test_a_recording_without_clock_or_too_long_is_refused() -> None:
    no_start = [
        e for e in take([SPARSE]) if not (isinstance(e, RawMidiEvent) and e.data == b"\xfa")
    ]
    with pytest.raises(ValueError, match="no MIDI clock"):
        replay(no_start)
    with pytest.raises(ValueError, match="no MIDI clock"):
        replay([MidiEvent(0.0, "note_on", 1, 100, 36)])
    with pytest.raises(ValueError, match=f"at most {MAX_BARS} bars"):
        replay(take([{}] * (MAX_BARS + 1), 160.0))


def test_upload_shows_the_song_and_the_hits() -> None:
    shown, hits = upload(DATA / "clock_practice.jsonl", Settings())
    assert len(shown.table) == 1 and len(shown.table[0]) == len(TABLE_HEADERS)
    assert shown.table[0][2] == "11" and shown.midi.startswith(b"MThd")
    assert len(hits) == 6 and all(len(h) == len(HIT_HEADERS) for h in hits)
    assert hits[1][1:5] == ["1", "5", "A02", "90"] and hits[0][1] == "-"


def test_upload_refuses_what_it_cannot_read(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot read"):
        upload(tmp_path / "missing.jsonl", Settings())
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n")
    with pytest.raises(ValueError):
        upload(bad, Settings())
