"""Write a `sim.Song` as a standard MIDI file with the standard library (#166).

A type 1 file at `PPQ` ticks per beat: a tempo track, then one track per part on
the channel `ensemble` uses (`CHANNELS`: drums on 10, bass on 2, keys on 3). The
keys track also has the brightness CC the melody sent (`BRIGHTNESS_CC`, the
preset's default `filter-cc`).
"""

import struct
from collections.abc import Iterable

from mpc_iml.clock import TICKS_PER_BEAT
from mpc_iml.webdemo.sim import DRUMS, Song

__all__ = ["BRIGHTNESS_CC", "CHANNELS", "PPQ", "write"]

PPQ = 480
BRIGHTNESS_CC = 74
CHANNELS = {"drums": 10, "bass": 2, "keys": 3}
"""The MIDI channel (1-16) of each part's track, in track order."""

_SCALE = PPQ // TICKS_PER_BEAT


def write(song: Song) -> bytes:
    """The bytes of a type 1 MIDI file of `song`."""
    tempo = round(60_000_000 / song.settings.tempo)
    tracks = [_track([(0, 0, b"\xff\x51\x03" + tempo.to_bytes(3, "big"))])]
    for part, channel in CHANNELS.items():
        events: list[tuple[int, int, bytes]] = []
        for n in song.notes:
            if ("drums" if n.part in DRUMS else n.part) == part:
                on = n.tick * _SCALE
                events.append((on, 1, bytes([0x90 | channel - 1, n.pitch, n.velocity])))
                events.append((on + n.ticks * _SCALE, 0, bytes([0x80 | channel - 1, n.pitch, 0])))
        if part == "keys":
            events += [
                (tick * _SCALE, 0, bytes([0xB0 | channel - 1, BRIGHTNESS_CC, value]))
                for tick, value in song.brightness
            ]
        tracks.append(_track(events))
    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(tracks), PPQ)
    return header + b"".join(tracks)


def _track(events: Iterable[tuple[int, int, bytes]]) -> bytes:
    """A track chunk of `(tick, order, message)`: at the same tick, lower `order`
    first, so a note's Note Off goes before the next Note On of the same pitch."""
    data = bytearray()
    now = 0
    for tick, _, message in sorted(events, key=lambda e: (e[0], e[1])):
        data += _varlen(tick - now) + message
        now = tick
    data += b"\x00\xff\x2f\x00"
    return b"MTrk" + struct.pack(">I", len(data)) + bytes(data)


def _varlen(value: int) -> bytes:
    out = [value & 0x7F]
    value >>= 7
    while value:
        out.append(0x80 | value & 0x7F)
        value >>= 7
    return bytes(reversed(out))
