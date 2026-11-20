"""The melody layer's loops and rules for `ensemble` (#144, RFC 0005). No I/O.

A loop is a few bars of notes written as chord tones (`tone` 0-3 is the root,
third, fifth or seventh), so it fits any chord: each note takes the chord of the bar
it falls in, through the chord's quality (`QUALITIES`). Each note has a `level`
1-3: level 1 notes are the loop's skeleton, levels 2 and 3 fill it in. A note can
also take the chord of the next bar (`chord` 1) and a chromatic offset
(`semitones`), for approach and passing notes (the bass loops of #148, `bass`).

Once per bar, at the bar line, `plan_bar` decides the next bar from the drum hits of
the bar that just ended (RFC 0005, causality first): the number of hits sets the
density (which levels play), their average velocity the loudness, and the hits on
`hat` pads the brightness CC.

Variations (#158, not used by `ensemble` yet): every loop also holds three named
variations (`Loop.variations`), each a complete line with two levels: level 1 is the
full line, level 2 adds ornaments. The first, `home`, is the loop itself re-levelled
(`relevel`), so it plays the same notes. The drums of the last bar choose the
melody's variation (`melody_variation`) and whether its ornaments play
(`melody_ornaments`), so a sparse bar changes the line instead of thinning it.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

__all__ = [
    "LOOPS",
    "MELODY_VARIATIONS",
    "ORNAMENTS",
    "QUALITIES",
    "BarPlan",
    "Follower",
    "Loop",
    "LoopNote",
    "brightness",
    "chord_note",
    "density",
    "loop_pitch",
    "melody_ornaments",
    "melody_variation",
    "melody_velocity",
    "relevel",
]

QUALITIES = {"m7": (0, 3, 7, 10), "maj7": (0, 4, 7, 11), "7": (0, 4, 7, 10)}
"""Semitones above the root of tones 0-3 (root, third, fifth, seventh)."""

FIXED_VELOCITY = 100
"""Velocity of every note when the melody does not follow the drums."""

ORNAMENTS = 2
"""The level of a variation's ornaments; level 1 is its full line."""

MELODY_VARIATIONS = ("home", "open", "busy")
"""The variations of every melody loop, in order (`home` is the loop itself)."""


@dataclass(frozen=True)
class LoopNote:
    """A note of a loop: `step` (16ths) of the loop's `bar`, a chord `tone` 0-3,
    `octave` above the melody octave, `length` in 16ths, `level` 1-3 and a velocity
    weight 0-1. `chord` 0 takes the chord of the note's own bar, 1 the chord of the
    next bar; `semitones` is added after the tone (an approach note half a step
    below the next root is `tone=0, chord=1, semitones=-1`)."""

    bar: int
    step: int
    tone: int
    length: int
    level: int
    octave: int = 0
    velocity: float = 1.0
    chord: int = 0
    semitones: int = 0


@dataclass(frozen=True)
class Loop:
    """`bars` (1, 2 or 4) bars of notes; the loop's bar is the song bar `% bars`.
    `variations` are complete lines of the same length (#158), each a `Loop` with
    levels 1 (the full line) and `ORNAMENTS`."""

    name: str
    bars: int
    notes: tuple[LoopNote, ...]
    variations: tuple["Loop", ...] = ()

    def bar_notes(self, bar: int, level: int) -> tuple[LoopNote, ...]:
        """The notes of song bar `bar` up to `level`."""
        return tuple(n for n in self.notes if n.bar == bar % self.bars and n.level <= level)

    def variation(self, name: str) -> "Loop":
        """The variation called `name` (`KeyError` if the loop has none)."""
        for variation in self.variations:
            if variation.name == name:
                return variation
        raise KeyError(name)


def relevel(loop: Loop) -> Loop:
    """`loop` as its `home` variation: levels 1 and 2 become the full line (level 1),
    level 3 the ornaments, so all levels play the same notes as the loop."""
    notes = tuple(replace(n, level=1 if n.level <= 2 else ORNAMENTS) for n in loop.notes)
    return Loop("home", loop.bars, notes)


def with_variations(loop: Loop, *others: Loop) -> Loop:
    """`loop` holding its `home` variation (`relevel`) followed by `others`."""
    return replace(loop, variations=(relevel(loop), *others))


N = LoopNote
LOOPS = {
    loop.name: loop
    for loop in (
        with_variations(
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
                "open",
                2,
                (
                    N(0, 0, 1, 3, 1),
                    N(0, 3, 2, 1, 2, velocity=0.8),
                    N(0, 4, 2, 3, 1, velocity=0.9),
                    N(0, 8, 3, 6, 1),
                    N(0, 14, 0, 2, 2, octave=1, velocity=0.8),
                    N(1, 0, 2, 4, 1, octave=1),
                    N(1, 4, 1, 3, 1, octave=1, velocity=0.9),
                    N(1, 7, 2, 1, 2, octave=1, velocity=0.8),
                    N(1, 8, 0, 8, 1, octave=1),
                ),
            ),
            Loop(
                "busy",
                2,
                tuple(
                    note
                    for bar, tones in ((0, (0, 2, 1, 3)), (1, (1, 3, 2, 4)))
                    for i, tone in enumerate(tones)
                    for note in (
                        N(bar, 4 * i + 1, tone % 4, 1, 2, octave=tone // 4, velocity=0.75),
                        N(bar, 4 * i + 2, tone % 4, 2, 1, octave=tone // 4),
                    )
                ),
            ),
        ),
        with_variations(
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
            Loop(
                "open",
                1,
                (
                    N(0, 0, 0, 4, 1),
                    N(0, 4, 2, 4, 1, velocity=0.9),
                    N(0, 8, 0, 2, 1, octave=1),
                    N(0, 10, 2, 2, 2, octave=1, velocity=0.85),
                    N(0, 12, 3, 4, 1),
                ),
            ),
            Loop(
                "busy",
                1,
                tuple(
                    N(
                        0,
                        step,
                        tone % 4,
                        1,
                        1 if step % 2 == 0 else 2,
                        octave=tone // 4,
                        velocity=1.0 if step % 2 == 0 else 0.8,
                    )
                    for step, tone in enumerate([0, 1, 2, 3, 4, 5, 6, 7, 8, 7, 6, 5, 4, 3, 2, 1])
                ),
            ),
        ),
    )
}
"""`keys` (default): a sparse 2-bar keys riff; `open` asks a question in its first
bar (third, fifth, a held seventh) and answers an octave up ending on the root;
`busy` stabs the off-8ths with 16th pickups as ornaments. `pluck`: a 1-bar 8th-note
arpeggio with the downbeats as its skeleton; `open` is a quarter-note arpeggio
reaching an octave up to a held seventh; `busy` a 16th arpeggio over two octaves
(the 8ths are its line, the 16ths between them its ornaments)."""


def chord_note(pitch_class: int, quality: str, tone: int, octave: int) -> int:
    """The MIDI note of chord `tone` 0-3 for a chord on `pitch_class` (0 is C), with
    its root in `octave` (A4 is 69)."""
    return 12 * (octave + 1) + pitch_class % 12 + QUALITIES[quality][tone]


def loop_pitch(
    note: LoopNote, now: tuple[int, str], following: tuple[int, str], octave: int
) -> int:
    """The MIDI note of `note` in base `octave`, given the (pitch class, quality) of
    the chord of its bar (`now`) and of the next bar (`following`)."""
    pitch_class, quality = following if note.chord else now
    return chord_note(pitch_class, quality, note.tone, octave + note.octave) + note.semitones


def density(hits: int) -> int:
    """The highest level that plays after a bar with `hits` drum hits (1 or more)."""
    return 1 if hits <= 4 else 2 if hits <= 10 else 3


def melody_velocity(average: float) -> int:
    """An average hit velocity 1-127 mapped linearly to 50-120 (as the bass)."""
    return round(50 + (min(max(average, 1.0), 127.0) - 1) * 70 / 126)


def melody_variation(hits: int, hat_steps: Sequence[int]) -> str:
    """The melody variation after a bar with `hits` drum hits, the hat hits on
    `hat_steps` (#158): a hat on an odd 16th step or 14 or more hits is `busy`, 5 or
    fewer hits (space in the drums) `open`, anything else `home`."""
    if hits >= 14 or any(step % 2 for step in hat_steps):
        return "busy"
    return "open" if hits <= 5 else "home"


def melody_ornaments(hits: int) -> int:
    """The highest variation level after a bar with `hits` drum hits: the
    ornaments join the full line with 8 or more hits."""
    return ORNAMENTS if hits >= 8 else 1


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
    (`complete` false) with no hits counts as a new start. `density` maps the number
    of hits to the highest level (the bass passes its kick thresholds, #148).
    """

    def __init__(self, density: Callable[[int], int] = density) -> None:
        self._density = density
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
            return BarPlan(self._density(len(velocities)), self._velocity, brightness(hats))
        if self._empty == 1:
            return BarPlan(1, self._velocity, None)
        return BarPlan(0, self._velocity, None)
