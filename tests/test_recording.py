"""Recording files: write -> read round trip, version check, Full Level warning."""

import json
import warnings
from pathlib import Path

import pytest

from mpc_iml.events import ExampleEnd, ExampleStart, MidiEvent, RawMidiEvent
from mpc_iml.recording import (
    FullLevelWarning,
    Header,
    RecordingFormatError,
    read_recording,
    write_recording,
)

DATA = Path(__file__).parent / "data"


def test_read_basic_fixture() -> None:
    rec = read_recording(DATA / "basic.jsonl")
    assert rec.header.firmware == "1.3.0"
    assert rec.header.settings == {"full_level": False}
    assert rec.events[0] == ExampleStart(t=0.0, label="soft-roll")
    assert rec.events[1] == MidiEvent(t=0.01, kind="note_on", channel=1, note=36, value=30)
    assert rec.events[3] == MidiEvent(t=0.05, kind="control_change", channel=1, control=7, value=90)
    assert rec.events[4] == RawMidiEvent(t=0.05, data=b"\xf8")
    assert rec.events[-1] == ExampleEnd(t=0.08)


def test_round_trip(tmp_path: Path) -> None:
    header = Header(firmware="1.3.0", settings={"full_level": False})
    events = [
        ExampleStart(t=0.5, targets=(0.25, 1.0)),
        MidiEvent(t=0.512, kind="note_on", channel=1, note=36, value=30),
        MidiEvent(t=0.584, kind="poly_pressure", channel=1, note=36, value=63),
        RawMidiEvent(t=0.6, data=bytes([0xF0, 0x47, 0xF7])),
        MidiEvent(t=0.64, kind="note_off", channel=1, note=36, value=0),
        ExampleEnd(t=2.5),
        ExampleStart(t=3.0, label="tap"),
    ]
    path = tmp_path / "rec.jsonl"
    write_recording(path, header, events)
    rec = read_recording(path)
    assert rec.header == header
    assert list(rec.events) == events
    head = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert head["type"] == "header"
    assert head["format"] == "mpc-iml-recording"
    assert head["format_version"] == 1
    assert set(head) >= {"toolkit_version", "device", "firmware", "settings"}


def test_unknown_format_version_raises(tmp_path: Path) -> None:
    path = tmp_path / "future.jsonl"
    head = {"type": "header", "format": "mpc-iml-recording", "format_version": 99}
    path.write_text(json.dumps(head) + "\n", encoding="utf-8")
    with pytest.raises(RecordingFormatError, match="unsupported format_version 99"):
        read_recording(path)


def test_missing_header_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"t": 0, "type": "example_end"}\n', encoding="utf-8")
    with pytest.raises(RecordingFormatError, match="header"):
        read_recording(path)


def test_full_level_warning() -> None:
    with pytest.warns(FullLevelWarning, match="Full Level"):
        read_recording(DATA / "full_level.jsonl")


def test_no_full_level_warning_with_few_notes_or_varied_velocity(tmp_path: Path) -> None:
    seven = [MidiEvent(t=i / 10, kind="note_on", channel=1, note=36, value=127) for i in range(7)]
    varied = [*seven, MidiEvent(t=1.0, kind="note_on", channel=1, note=36, value=100)]
    for events in (seven, varied):
        path = tmp_path / "rec.jsonl"
        write_recording(path, Header(), events)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            read_recording(path)
