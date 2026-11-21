"""The web demo's piano roll and MIDI file (#166, PR 3)."""

import struct

import numpy as np

from mpc_iml.webdemo import midifile, roll
from mpc_iml.webdemo.sim import DRUM_NOTES, STEPS, Settings, simulate

SPARSE = {"kick": [100, 0, 0, 0] * 4, "hat": [0, 0, 70, 0] * 4}


def test_the_piano_roll_covers_the_song_and_colours_the_parts() -> None:
    song = simulate([SPARSE, SPARSE])
    image = roll.draw(song)
    pitches = [n.pitch for n in song.notes]
    rows = max(pitches) - min(pitches) + 5
    assert image.shape == (rows * roll.PX_PER_PITCH, 3 * STEPS * roll.PX_PER_STEP, 3)
    assert image.dtype == np.uint8
    kick = (max(pitches) + 2 - DRUM_NOTES["kick"]) * roll.PX_PER_PITCH + 1
    assert tuple(image[kick, 2]) == roll.COLOURS["drums"]
    assert tuple(image[kick, roll.PX_PER_STEP * 2]) == roll.BACKGROUND
    assert tuple(image[0, 0]) == tuple(image[0, STEPS * roll.PX_PER_STEP]) == roll.BAR_LINE
    colours = {tuple(c) for c in image.reshape(-1, 3)}
    assert {roll.COLOURS["bass"], roll.COLOURS["keys"]} <= colours


def chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    out = []
    while data:
        kind, size = data[:4], struct.unpack(">I", data[4:8])[0]
        out.append((kind, data[8 : 8 + size]))
        data = data[8 + size :]
    return out


def test_the_midi_file_has_a_tempo_track_and_a_track_per_part() -> None:
    song = simulate([SPARSE, SPARSE], Settings(tempo=120.0))
    (head, header), *tracks = chunks(midifile.write(song))
    assert head == b"MThd" and struct.unpack(">HHH", header) == (1, 4, midifile.PPQ)
    assert all(kind == b"MTrk" and data.endswith(b"\xff\x2f\x00") for kind, data in tracks)
    assert tracks[0][1].startswith(b"\x00\xff\x51\x03\x07\xa1\x20")
    assert tracks[1][1].startswith(b"\x00\x99\x24\x64")
    assert b"\x91" in tracks[2][1] and b"\xb2\x4a" in tracks[3][1]
    drums = sum(1 for n in song.notes if n.part in DRUM_NOTES)
    assert tracks[1][1].count(b"\x99") == drums


def test_varlen_writes_long_delta_times() -> None:
    assert midifile._varlen(0) == b"\x00"
    assert midifile._varlen(0x7F) == b"\x7f"
    assert midifile._varlen(0x80) == b"\x81\x00"
    assert midifile._varlen(0x3FFF) == b"\xff\x7f"
