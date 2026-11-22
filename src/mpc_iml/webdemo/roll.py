"""Draw a `sim.Song` as a piano roll with numpy (#166).

One column of `PX_PER_STEP` pixels per 16th, one row of `PX_PER_PITCH` pixels per
semitone, high notes at the top. The drums, bass and keys have their own colour
(`COLOURS`), notes the rhythm transformation moved (#189) a lighter shade of it,
and the bar lines are grey. The result is an RGB `uint8` array for
`gr.Image`; no plotting library.
"""

import numpy as np
import numpy.typing as npt

from mpc_iml.clock import SIXTEENTHS
from mpc_iml.webdemo.sim import DRUMS, Song

__all__ = ["BACKGROUND", "BAR_LINE", "COLOURS", "PX_PER_PITCH", "PX_PER_STEP", "colour", "draw"]

PX_PER_STEP = 8
PX_PER_PITCH = 4
BACKGROUND = (250, 250, 250)
BAR_LINE = (190, 190, 190)
COLOURS = {"drums": (214, 96, 77), "bass": (67, 147, 195), "keys": (90, 174, 97)}
"""The colour of each part; `drums` is every drum."""

_MARGIN = 2
"""Empty semitones above and below the notes."""


def colour(part: str, moved: bool = False) -> tuple[int, int, int]:
    """The colour of a note of `part` (a drum, `bass` or `keys`); a `moved` note's
    is halfway to the background."""
    r, g, b = COLOURS["drums" if part in DRUMS else part]
    if not moved:
        return r, g, b
    br, bg, bb = BACKGROUND
    return (r + br) // 2, (g + bg) // 2, (b + bb) // 2


def draw(song: Song) -> npt.NDArray[np.uint8]:
    """The piano roll of `song`, `(height, width, 3)`: the song's length, and the
    pitches of its notes with a margin."""
    steps = song.ticks // SIXTEENTHS
    pitches = [n.pitch for n in song.notes] or [60]
    low, high = min(pitches) - _MARGIN, max(pitches) + _MARGIN
    image = np.empty(((high - low + 1) * PX_PER_PITCH, steps * PX_PER_STEP, 3), np.uint8)
    image[:] = BACKGROUND
    per_bar = song.ticks // song.bars // SIXTEENTHS * PX_PER_STEP
    image[:, ::per_bar] = BAR_LINE
    for note in song.notes:
        x0 = note.tick * PX_PER_STEP // SIXTEENTHS
        x1 = max((note.tick + note.ticks) * PX_PER_STEP // SIXTEENTHS - 1, x0 + 1)
        y0 = (high - note.pitch) * PX_PER_PITCH
        image[y0 + 1 : y0 + PX_PER_PITCH, x0:x1] = colour(note.part, note.moved)
    return image
