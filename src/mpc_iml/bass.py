"""The bass loops of `ensemble` and their kick rules (#148, RFC 0005). No I/O.

A bass loop is written in the same chord-tone form as the melody loops
(`melody.LoopNote`), so it follows the progression: approach and passing notes
take the chord of the next bar (`chord` 1) with a chromatic offset (`semitones`).
Notes never overlap, so the loop plays on a monophonic bass.

The bass listens to the kick only. Every bass loop holds three named variations
(#158, `melody.Loop.variations`), each a complete, monophonic line whose level 1 is
never a skeleton; `home` is the loop itself re-levelled. Once per bar, at the bar
line, the kicks of the bar that ended decide the next bar (through its own
`melody.Follower`, which also gives the no-kick rules): their positions choose the
variation (`bass_variation`) and the accents (`accent`: a note within one step of a
kick keeps its full velocity, the others play at `OFF_KICK` of it), their number
whether the ornaments play (`bass_ornaments`) and their average velocity the
loudness.
"""

from collections.abc import Sequence

from mpc_iml.melody import ORNAMENTS, Loop, LoopNote, with_variations

__all__ = [
    "BASS_LOOPS",
    "BASS_VARIATIONS",
    "OFF_KICK",
    "accent",
    "bass_note_velocity",
    "bass_ornaments",
    "bass_variation",
]

BASS_VARIATIONS = ("home", "push", "drive")
"""The variations of every bass loop, in order (`home` is the loop itself)."""

OFF_KICK = 0.8
"""Velocity weight of a bass loop note that does not land near a kick."""

N = LoopNote
APPROACH = {"tone": 0, "chord": 1, "semitones": -1}
"""Half a step below the next bar's root."""

PASSING = {"tone": 0, "chord": 1, "semitones": -2}
"""A whole step below the next bar's root."""

BASS_LOOPS = {
    loop.name: loop
    for loop in (
        with_variations(
            Loop(
                "boom",
                1,
                (
                    N(0, 0, 0, 3, 1),
                    N(0, 3, 0, 1, 3, velocity=0.7),
                    N(0, 6, 0, 2, 2, octave=1),
                    N(0, 8, 2, 2, 1),
                    N(0, 11, 2, 1, 3, velocity=0.75),
                    N(0, 14, length=2, level=2, **APPROACH),
                ),
            ),
            Loop(
                "push",
                1,
                (
                    N(0, 0, 0, 2, 1),
                    N(0, 3, 0, 2, 1, velocity=0.9),
                    N(0, 7, 2, 3, 1),
                    N(0, 10, 0, 2, 1, octave=1, velocity=0.9),
                    N(0, 12, 2, 1, ORNAMENTS, velocity=0.7),
                    N(0, 14, length=2, level=1, **APPROACH),
                ),
            ),
            Loop(
                "drive",
                1,
                (
                    N(0, 0, 0, 2, 1),
                    N(0, 2, 0, 2, 1, velocity=0.85),
                    N(0, 4, 0, 1, 1, octave=1),
                    N(0, 5, 0, 1, ORNAMENTS, velocity=0.7),
                    N(0, 6, 0, 2, 1, velocity=0.85),
                    N(0, 8, 2, 2, 1),
                    N(0, 10, 2, 1, 1, velocity=0.85),
                    N(0, 11, 2, 1, ORNAMENTS, velocity=0.7),
                    N(0, 12, 3, 2, 1),
                    N(0, 14, length=2, level=1, **APPROACH),
                ),
            ),
        ),
        with_variations(
            Loop(
                "walk",
                2,
                (
                    N(0, 0, 0, 6, 1),
                    N(0, 6, 2, 2, 2),
                    N(0, 10, 0, 2, 3, octave=1),
                    N(0, 12, 3, 2, 2),
                    N(0, 14, length=2, level=1, **APPROACH),
                    N(1, 0, 0, 4, 1),
                    N(1, 6, 1, 2, 2),
                    N(1, 8, 2, 4, 1),
                    N(1, 12, length=2, level=3, **PASSING),
                    N(1, 14, length=2, level=2, **APPROACH),
                ),
            ),
            Loop(
                "push",
                2,
                (
                    N(0, 0, 0, 3, 1),
                    N(0, 3, 2, 3, 1, velocity=0.9),
                    N(0, 7, 0, 3, 1),
                    N(0, 10, 0, 1, ORNAMENTS, octave=1, velocity=0.7),
                    N(0, 11, 3, 2, 1, velocity=0.9),
                    N(0, 13, length=3, level=1, **APPROACH),
                    N(1, 0, 0, 3, 1),
                    N(1, 3, 1, 3, 1, velocity=0.9),
                    N(1, 6, 2, 1, ORNAMENTS, velocity=0.7),
                    N(1, 7, 2, 4, 1),
                    N(1, 11, length=2, level=1, **PASSING),
                    N(1, 13, length=3, level=1, **APPROACH),
                ),
            ),
            Loop(
                "drive",
                2,
                (
                    N(0, 0, 0, 2, 1),
                    N(0, 2, 0, 2, ORNAMENTS, octave=1, velocity=0.7),
                    N(0, 4, 1, 2, 1),
                    N(0, 6, 2, 2, ORNAMENTS, velocity=0.7),
                    N(0, 8, 2, 2, 1),
                    N(0, 10, 3, 2, ORNAMENTS, velocity=0.7),
                    N(0, 12, length=4, level=1, **APPROACH),
                    N(1, 0, 0, 2, 1),
                    N(1, 2, 1, 2, ORNAMENTS, velocity=0.7),
                    N(1, 4, 2, 2, 1),
                    N(1, 6, 3, 2, ORNAMENTS, velocity=0.7),
                    N(1, 8, 0, 2, 1, octave=1),
                    N(1, 10, length=2, level=ORNAMENTS, velocity=0.7, **PASSING),
                    N(1, 12, length=4, level=1, **APPROACH),
                ),
            ),
        ),
    )
}
"""`boom` (default): a 1-bar boom-bap line, root and fifth as its skeleton, with a
ghost note, an octave and an approach into the next bar. `walk`: 2 bars with more
motion, a passing note a whole step below the next root and approach notes.

Variations (#158): `push` answers off-beat kicks with anticipations (notes a 16th
early, a pushed approach); `drive` answers busy kicks with 8ths (`boom`) or a
quarter-note walk with 8th passing notes as ornaments (`walk`)."""


def bass_variation(kicks: Sequence[int]) -> str:
    """The bass variation after a bar with kicks on `kicks` (steps of that bar):
    5 or more kicks is `drive`, else a kick off the quarter grid (a pushed or
    syncopated kick) `push`, else `home`."""
    if len(kicks) >= 5:
        return "drive"
    return "push" if any(step % 4 for step in kicks) else "home"


def bass_ornaments(kicks: int) -> int:
    """The highest variation level after a bar with `kicks` kicks: the ornaments
    join the full line with 3 or more kicks."""
    return ORNAMENTS if kicks >= 3 else 1


def accent(step: int, kicks: Sequence[int]) -> float:
    """The velocity weight of a note at `step` after a bar with kicks on `kicks`
    (steps of that bar): 1 within one step of a kick, `OFF_KICK` otherwise."""
    return 1.0 if any(abs(step - kick) <= 1 for kick in kicks) else OFF_KICK


def bass_note_velocity(note: LoopNote, velocity: int, kicks: Sequence[int] | None) -> int:
    """The velocity of `note` in a bar planned at `velocity` (`melody.BarPlan`),
    accented by the last bar's `kicks` (`None` when the bass does not follow: no
    accents)."""
    weight = 1.0 if kicks is None else accent(note.step, kicks)
    return min(max(round(velocity * note.velocity * weight), 1), 127)
