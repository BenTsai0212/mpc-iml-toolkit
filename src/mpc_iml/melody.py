"""The melody layer's loops and rules for `ensemble` (#144, RFC 0005). No I/O.

A loop is a few bars of notes written as chord tones (`tone` 0-3 is the root,
third, fifth or seventh), so it fits any chord: each note takes the chord of the bar
it falls in, through the chord's quality (`QUALITIES`). Each note has a `level`
1-3: level 1 notes are the loop's skeleton, levels 2 and 3 fill it in.

Once per bar, at the bar line, `plan_bar` decides the next bar from the drum hits of
the bar that just ended (RFC 0005, causality first): the number of hits sets the
density (which levels play), their average velocity the loudness, and the hits on
`hat` pads the brightness CC.
"""

from collections.abc import Sequence
from dataclasses import dataclass

__all__ = [
    "LOOPS",
    "QUALITIES",
    "BarPlan",
    "Follower",
    "Loop",
    "LoopNote",
    "brightness",
    "chord_note",
    "density",
    "melody_velocity",
]

QUALITIES = {"m7": (0, 3, 7, 10), "maj7": (0, 4, 7, 11), "7": (0, 4, 7, 10)}
"""Semitones above the root of tones 0-3 (root, third, fifth, seventh)."""

FIXED_VELOCITY = 100
"""Velocity of every note when the melody does not follow the drums."""


@dataclass(frozen=True)
class LoopNote:
    """A note of a loop: `step` (16ths) of the loop's `bar`, a chord `tone` 0-3,
    `octave` above the melody octave, `length` in 16ths, `level` 1-3 and a velocity
    weight 0-1."""

    bar: int
    step: int
    tone: int
    length: int
    level: int
    octave: int = 0
    velocity: float = 1.0


@dataclass(frozen=True)
class Loop:
    """`bars` (1, 2 or 4) bars of notes; the loop's bar is the song bar `% bars`."""

    name: str
    bars: int
    notes: tuple[LoopNote, ...]

    def bar_notes(self, bar: int, level: int) -> tuple[LoopNote, ...]:
        """The notes of song bar `bar` up to `level`."""
        return tuple(n for n in self.notes if n.bar == bar % self.bars and n.level <= level)


N = LoopNote
LOOPS = {
    loop.name: loop
    for loop in (
        Loop(
            "keys",
            2,
            (
                N(0, 0, 0, 4, 1),
                N(0, 3, 1, 1, 3, velocity=0.8),
                N(0, 6, 2, 2, 2, velocity=0.9),
                N(0, 10, 3, 6, 1),
                N(1, 0, 1, 4, 1),
                N(1, 6, 3, 1, 3, velocity=0.8),
                N(1, 8, 2, 2, 2, velocity=0.9),
                N(1, 12, 0, 4, 3, octave=1),
            ),
        ),
        Loop(
            "pluck",
            1,
            tuple(
                N(0, 2 * i, tone, 2, level, velocity=1.0 if level == 1 else 0.85)
                for i, (tone, level) in enumerate(
                    [(0, 1), (1, 2), (2, 1), (3, 3), (2, 1), (1, 2), (2, 1), (1, 3)]
                )
            ),
        ),
    )
}
"""`keys` (default): a sparse 2-bar keys riff. `pluck`: a 1-bar 8th-note arpeggio
with the downbeats as its skeleton."""


def chord_note(pitch_class: int, quality: str, tone: int, octave: int) -> int:
    """The MIDI note of chord `tone` 0-3 for a chord on `pitch_class` (0 is C), with
    its root in `octave` (A4 is 69)."""
    return 12 * (octave + 1) + pitch_class % 12 + QUALITIES[quality][tone]


def density(hits: int) -> int:
    """The highest level that plays after a bar with `hits` drum hits (1 or more)."""
    return 1 if hits <= 4 else 2 if hits <= 10 else 3


def melody_velocity(average: float) -> int:
    """An average hit velocity 1-127 mapped linearly to 50-120 (as the bass)."""
    return round(50 + (min(max(average, 1.0), 127.0) - 1) * 70 / 126)


def brightness(hats: int) -> int:
    """The CC value after a bar with `hats` hat hits: 0 is 40, 16 or more is 127."""
    return round(40 + min(hats, 16) * 87 / 16)


@dataclass(frozen=True)
class BarPlan:
    """What the melody plays in one bar: notes up to `level` (0 is silence), at
    `velocity`, after sending the brightness CC `cc` (`None`: no CC)."""

    level: int
    velocity: int
    cc: int | None


class Follower:
    """Decides each bar from the drums of the bar before (no drums: option A, #144).

    The melody stays silent until the first drum hit after Start; then one empty bar
    plays the skeleton only, two empty bars in a row are silence, and the loop comes
    back at the bar after the next hit. A bar the clock did not run through
    (`complete` false) with no hits counts as a new start.
    """

    def __init__(self) -> None:
        self._empty: int | None = None
        self._velocity = FIXED_VELOCITY

    def plan_bar(
        self, velocities: Sequence[int], hats: int, complete: bool, follow: bool
    ) -> BarPlan:
        """The plan for the bar that starts now, from the drum hits of the bar that
        ended (`velocities` of all counted hits, `hats` of them on hat pads)."""
        if velocities:
            self._empty = 0
            self._velocity = melody_velocity(sum(velocities) / len(velocities))
        elif not complete:
            self._empty = None
        elif self._empty is not None:
            self._empty += 1
        if not follow:
            return BarPlan(3, FIXED_VELOCITY, None)
        if velocities:
            return BarPlan(density(len(velocities)), self._velocity, brightness(hats))
        if self._empty == 1:
            return BarPlan(1, self._velocity, None)
        return BarPlan(0, self._velocity, None)
