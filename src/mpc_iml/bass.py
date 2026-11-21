"""The bass loops of `ensemble` and their kick rules (#148, RFC 0005). No I/O.

A bass loop is written in the same chord-tone form as the melody loops
(`melody.LoopNote`), so it follows the progression: approach and passing notes
take the chord of the next bar (`chord` 1) with a chromatic offset (`semitones`).
Notes never overlap, so the loop plays on a monophonic bass.

The bass listens to the kick only. Every bass loop holds three named variations
(#158, `melody.Loop.variations`), each a complete, monophonic line whose level 1 is
never a skeleton. The loops are loop files (`mpc_iml.loops`, ADR 0010, #173); the
built-in `boom` and `walk` live in `mpc_iml/loops/ensemble/`. Once per bar, at the bar
line, the kicks of the bar that ended decide the next bar (through its own
`melody.Follower`, which also gives the no-kick rules): their positions choose the
variation (`bass_variation`) and the accents (`accent`: a note within one step of a
kick keeps its full velocity, the others play at `OFF_KICK` of it), their number
whether the ornaments play (`bass_ornaments`) and their average velocity the
loudness.
"""

from collections.abc import Sequence
from dataclasses import replace

from mpc_iml.melody import ORNAMENTS, LoopNote

__all__ = [
    "BASS_VARIATIONS",
    "OFF_KICK",
    "accent",
    "bass_fill",
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


def bass_variation(kicks: Sequence[int]) -> str:
    """The bass variation after a bar with kicks on `kicks` (steps of that bar):
    5 or more kicks is `drive`, else a kick off the quarter grid (a pushed or
    syncopated kick) `push`, else `home`."""
    if len(kicks) >= 5:
        return "drive"
    return "push" if any(step % 4 for step in kicks) else "home"


def bass_fill(notes: Sequence[LoopNote], bar: int, steps: int = 16) -> tuple[LoopNote, ...]:
    """The surprise `fill` (#158): `notes` of loop bar `bar` (a bar of `steps` 16ths)
    with the last beat replaced by a 16th run: root, fifth, octave and the approach
    note into the next bar. Notes before the last beat end by its start."""
    start = steps - 4
    kept = tuple(replace(n, length=min(n.length, start - n.step)) for n in notes if n.step < start)
    return kept + (
        N(bar, start, 0, 1, 1, velocity=0.9),
        N(bar, start + 1, 2, 1, 1, velocity=0.8),
        N(bar, start + 2, 0, 1, 1, octave=1, velocity=0.9),
        N(bar, start + 3, length=1, level=1, **APPROACH),
    )


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
