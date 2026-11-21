"""Write a `sim.Song` as a standard MIDI file with the standard library (#166).

A type 1 file at `PPQ` ticks per beat: a tempo track, then one track per part on
the channel `ensemble` uses (`CHANNELS`: drums on 10, bass on 2, keys on 3), built
with `mpc_iml.smf` (at the same tick a Note Off goes before the next Note On). The
keys track also has the brightness CC the melody sent (`BRIGHTNESS_CC`, the
preset's default `filter-cc`).
"""

from mpc_iml import smf
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
    tracks = [smf.track([smf.tempo(song.settings.tempo)])]
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
        tracks.append(smf.track(events))
    return smf.file(tracks, PPQ)
