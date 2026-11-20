"""The bass loops of `ensemble` and their kick rules (#148, RFC 0005). No I/O.

A bass loop is written in the same chord-tone form as the melody loops
(`melody.LoopNote`), so it follows the progression: approach and passing notes
take the chord of the next bar (`chord` 1) with a chromatic offset (`semitones`).
Notes never overlap, so the loop plays on a monophonic bass.

The bass listens to the kick only. Once per bar, at the bar line, the kicks of the
bar that ended decide the next bar: their number sets the density
(`kick_density`, through its own `melody.Follower`, which also gives the no-kick
rules), their average velocity the loudness, and their positions the accents
(`accent`): a note within one step of a kick keeps its full velocity, the others
play at `OFF_KICK` of it.
"""

from collections.abc import Sequence

from mpc_iml.melody import Loop, LoopNote

__all__ = ["BASS_LOOPS", "OFF_KICK", "accent", "bass_note_velocity", "kick_density"]

OFF_KICK = 0.8
"""Velocity weight of a bass loop note that does not land near a kick."""

N = LoopNote
APPROACH = {"tone": 0, "chord": 1, "semitones": -1}
"""Half a step below the next bar's root."""

BASS_LOOPS = {
    loop.name: loop
    for loop in (
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
                N(1, 12, 0, 2, 3, chord=1, semitones=-2),
                N(1, 14, length=2, level=2, **APPROACH),
            ),
        ),
    )
}
"""`boom` (default): a 1-bar boom-bap line, root and fifth as its skeleton, with a
ghost note, an octave and an approach into the next bar. `walk`: 2 bars with more
motion, a passing note a whole step below the next root and approach notes."""


def kick_density(kicks: int) -> int:
    """The highest level after a bar with `kicks` kicks (1 or more): 1-2 is the
    skeleton, 3-4 adds level 2, 5 or more plays everything."""
    return 1 if kicks <= 2 else 2 if kicks <= 4 else 3


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
