"""Decoding raw MIDI bytes into events."""

import pytest

from mpc_iml.events import MidiEvent, RawMidiEvent
from mpc_iml.midi import decode


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([0x90, 36, 30], MidiEvent(t=1.0, kind="note_on", channel=1, note=36, value=30)),
        ([0x90, 36, 0], MidiEvent(t=1.0, kind="note_on", channel=1, note=36, value=0)),
        ([0x8F, 51, 64], MidiEvent(t=1.0, kind="note_off", channel=16, note=51, value=64)),
        ([0xA0, 36, 63], MidiEvent(t=1.0, kind="poly_pressure", channel=1, note=36, value=63)),
        ([0xB1, 7, 90], MidiEvent(t=1.0, kind="control_change", channel=2, control=7, value=90)),
        ([0xC0, 5], MidiEvent(t=1.0, kind="program_change", channel=1, value=5)),
        ([0xD2, 100], MidiEvent(t=1.0, kind="channel_pressure", channel=3, value=100)),
        ([0xE0, 0x00, 0x40], MidiEvent(t=1.0, kind="pitch_bend", channel=1, value=8192)),
        ([0xE0, 0x7F, 0x7F], MidiEvent(t=1.0, kind="pitch_bend", channel=1, value=16383)),
    ],
)
def test_channel_voice_messages(data: list[int], expected: MidiEvent) -> None:
    assert decode(data, 1.0) == expected


@pytest.mark.parametrize(
    "data",
    [
        [0xF8],
        [0xF0, 0x47, 0x00, 0xF7],
        [0xFA],
        [0x90, 36],
        [0x90, 36, 0x80],
        [0x24],
        [],
    ],
)
def test_other_messages_are_raw(data: list[int]) -> None:
    assert decode(data, 0.5) == RawMidiEvent(t=0.5, data=bytes(data))


def test_accepts_bytes() -> None:
    assert decode(b"\x90\x24\x1e", 0.0) == MidiEvent(
        t=0.0, kind="note_on", channel=1, note=36, value=30
    )
