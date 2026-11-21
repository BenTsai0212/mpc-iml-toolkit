"""Standard MIDI Files with the standard library (#173, ADR 0010).

`read` takes the notes of a format 0 or 1 file (running status, a Note On with
velocity 0 as a Note Off; meta and sysex events are skipped) and `write` writes notes
as a format 0 file; `track`, `tempo` and `file` build other files (the #166 download
is format 1). Times are ticks; `division` is ticks per quarter note (SMPTE
division is refused). For the loop import and export of #173 and the #166 MIDI
download.
"""

from collections import defaultdict, deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

__all__ = ["DIVISION", "MidiFile", "Note", "SmfError", "file", "read", "tempo", "track", "write"]

DIVISION = 480
"""Ticks per quarter note of written files."""

_DATA_BYTES = {0x8: 2, 0x9: 2, 0xA: 2, 0xB: 2, 0xC: 1, 0xD: 1, 0xE: 2}


class SmfError(ValueError):
    """A file is not a Standard MIDI File this module can read."""


@dataclass(frozen=True)
class Note:
    """A note: `start` and `length` in ticks, `channel` 0-15."""

    start: int
    length: int
    pitch: int
    velocity: int
    channel: int = 0


@dataclass(frozen=True)
class MidiFile:
    """The notes of a file by start, its `division` and its `length` in ticks (the
    last end of track or note end)."""

    division: int
    notes: tuple[Note, ...]
    length: int


def _variable(data: bytes, at: int) -> tuple[int, int]:
    value = 0
    for _ in range(4):
        if at >= len(data):
            raise SmfError("the file ends inside a delta time or length")
        byte = data[at]
        at += 1
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            return value, at
    raise SmfError("a variable-length number is longer than 4 bytes")


def _track(data: bytes) -> tuple[list[Note], int]:
    """The notes of one track chunk's data and its end in ticks."""
    notes: list[Note] = []
    playing: defaultdict[tuple[int, int], deque[tuple[int, int]]] = defaultdict(deque)
    at, tick, status = 0, 0, 0
    while at < len(data):
        delta, at = _variable(data, at)
        tick += delta
        if at >= len(data):
            raise SmfError("the file ends inside an event")
        if data[at] & 0x80:
            status = data[at]
            at += 1
        if status in (0xF0, 0xF7):
            size, at = _variable(data, at)
            at += size
            status = 0
            continue
        if status == 0xFF:
            if at >= len(data):
                raise SmfError("the file ends inside a meta event")
            kind = data[at]
            size, at = _variable(data, at + 1)
            at += size
            status = 0
            if kind == 0x2F:
                break
            continue
        if status < 0x80 or status >= 0xF0:
            raise SmfError(f"unexpected byte {status:#04x} in a track")
        size = _DATA_BYTES[status >> 4]
        if at + size > len(data):
            raise SmfError("the file ends inside an event")
        event, channel = status >> 4, status & 0x0F
        pitch, velocity = data[at], data[at + 1] if size == 2 else 0
        at += size
        if event == 0x9 and velocity:
            playing[channel, pitch].append((tick, velocity))
        elif event in (0x8, 0x9) and playing[channel, pitch]:
            start, on = playing[channel, pitch].popleft()
            notes.append(Note(start, tick - start, pitch, on, channel))
    for (channel, pitch), starts in playing.items():
        notes += [Note(start, tick - start, pitch, on, channel) for start, on in starts]
    return notes, tick


def read(data: bytes) -> MidiFile:
    """The notes of a format 0 or 1 Standard MIDI File; raises `SmfError`."""
    if data[:4] != b"MThd" or len(data) < 14:
        raise SmfError("not a Standard MIDI File (no MThd header)")
    header = int.from_bytes(data[4:8])
    form, division = int.from_bytes(data[8:10]), int.from_bytes(data[12:14])
    if form not in (0, 1):
        raise SmfError(f"MIDI file format {form} is not supported; export format 0 or 1")
    if division & 0x8000 or division == 0:
        raise SmfError("SMPTE time division is not supported; export ticks per quarter note")
    notes: list[Note] = []
    length, at = 0, 8 + header
    while at + 8 <= len(data):
        kind, size = data[at : at + 4], int.from_bytes(data[at + 4 : at + 8])
        chunk = data[at + 8 : at + 8 + size]
        if len(chunk) < size:
            raise SmfError("the file ends inside a chunk")
        if kind == b"MTrk":
            found, end = _track(chunk)
            notes += found
            length = max(length, end)
        at += 8 + size
    notes.sort(key=lambda n: (n.start, n.pitch))
    length = max([length] + [n.start + n.length for n in notes])
    return MidiFile(division, tuple(notes), length)


def _number(value: int) -> bytes:
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(out)


def track(events: Iterable[tuple[int, int, bytes]], length: int = 0) -> bytes:
    """A track chunk of `(tick, order, message)` events, sorted by tick and then
    `order`, ending at `length` ticks or the last event."""
    data = bytearray()
    tick = 0
    for at, _, message in sorted(events, key=lambda e: (e[0], e[1])):
        data += _number(at - tick) + message
        tick = at
    data += _number(max(length - tick, 0)) + b"\xff\x2f\x00"
    return b"MTrk" + len(data).to_bytes(4) + bytes(data)


def file(tracks: Sequence[bytes], division: int = DIVISION) -> bytes:
    """A file of `track` chunks: format 0 for one track, otherwise format 1."""
    kind = 0 if len(tracks) == 1 else 1
    header = (6).to_bytes(4) + kind.to_bytes(2) + len(tracks).to_bytes(2) + division.to_bytes(2)
    return b"MThd" + header + b"".join(tracks)


def tempo(bpm: float) -> tuple[int, int, bytes]:
    """A Set Tempo meta event at tick 0, as a `track` event."""
    return (0, 0, b"\xff\x51\x03" + round(60_000_000 / bpm).to_bytes(3))


def write(
    notes: Iterable[Note], division: int = DIVISION, bpm: float = 120.0, length: int = 0
) -> bytes:
    """A format 0 file of `notes` with a tempo, ending at `length` ticks or the last
    note end. At the same tick a Note Off comes before a Note On."""
    events = [tempo(bpm)]
    for n in notes:
        events.append((n.start, 1, bytes([0x90 | n.channel, n.pitch, n.velocity])))
        events.append((n.start + n.length, 0, bytes([0x80 | n.channel, n.pitch, 0])))
    return file([track(events, length)], division)
