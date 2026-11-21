"""Standard MIDI Files with the standard library (#173, ADR 0010)."""

import pytest

from mpc_iml.smf import MidiFile, Note, SmfError, _number, file, read, tempo, track, write


def smf(form: int, division: int, *tracks: bytes) -> bytes:
    header = b"MThd" + (6).to_bytes(4) + form.to_bytes(2) + len(tracks).to_bytes(2)
    chunks = b"".join(b"MTrk" + len(t).to_bytes(4) + t for t in tracks)
    return header + division.to_bytes(2) + chunks


def test_write_then_read_keeps_the_notes() -> None:
    notes = (Note(0, 240, 45, 127), Note(240, 120, 52, 89, channel=1), Note(960, 1920, 57, 1))
    data = write(notes, length=3840)
    assert data[:14] == b"MThd\x00\x00\x00\x06\x00\x00\x00\x01\x01\xe0"
    assert read(data) == MidiFile(480, notes, 3840)


def test_tracks_build_a_format_1_file_with_long_delta_times() -> None:
    assert [_number(v) for v in (0, 0x7F, 0x80, 0x3FFF)] == [
        b"\x00",
        b"\x7f",
        b"\x81\x00",
        b"\xff\x7f",
    ]
    notes = [(0x3FFF, 1, b"\x91\x2d\x64"), (0x4000, 0, b"\x81\x2d\x00")]
    data = file([track([tempo(120.0)]), track(notes)], 96)
    assert data[8:14] == b"\x00\x01\x00\x02\x00\x60"
    assert read(data) == MidiFile(96, (Note(0x3FFF, 1, 45, 100, channel=1),), 0x4000)


def test_same_tick_note_off_before_note_on() -> None:
    data = write([Note(0, 120, 60, 100), Note(120, 120, 60, 100)])
    assert read(data).notes == (Note(0, 120, 60, 100), Note(120, 120, 60, 100))


def test_running_status_velocity_zero_and_format_1() -> None:
    # Track 1: tempo, a sysex, then Note On C3 and its Note On with velocity 0 by running
    # status. Track 2: a note on channel 3 with a long (2-byte) delta time.
    one = b"\x00\xff\x51\x03\x07\xa1\x20" + b"\x00\xf0\x02\x7e\xf7"
    one += b"\x00\x90\x30\x64" + b"\x18\x30\x00" + b"\x00\xff\x2f\x00"
    two = b"\x81\x00\x92\x40\x50" + b"\x60\x82\x40\x00" + b"\x00\xc2\x05" + b"\x00\xff\x2f\x00"
    clip = read(smf(1, 96, one, two))
    assert clip.division == 96
    assert clip.notes == (Note(0, 24, 48, 100), Note(128, 96, 64, 80, channel=2))
    assert clip.length == 224


def test_a_note_without_note_off_ends_at_the_track_end() -> None:
    track = b"\x00\x90\x30\x64" + b"\x60\xff\x2f\x00"
    assert read(smf(0, 96, track)).notes == (Note(0, 96, 48, 100),)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"RIFF0000", "no MThd"),
        (smf(2, 96), "format 2"),
        (smf(0, 0xE728), "SMPTE"),
        (smf(0, 96, b"\x00\x90\x30"), "ends inside an event"),
        (smf(0, 96, b"\x00\x30\x64"), "unexpected byte"),
        (smf(0, 96) + b"MTrk\x00\x00\x00\x09\x00", "ends inside a chunk"),
    ],
)
def test_bad_files_are_refused(data: bytes, message: str) -> None:
    with pytest.raises(SmfError, match=message):
        read(data)
