"""The melody layer's loops and rules for `ensemble` (#144, RFC 0005). No I/O.

A loop is a few bars of notes written as chord tones (`tone` 0-3 is the root,
third, fifth or seventh), so it fits any chord: each note takes the chord of the bar
it falls in, through the chord's quality (`QUALITIES`). A note can also take the
chord of the next bar (`chord` 1) and a chromatic offset (`semitones`), for approach
and passing notes (the bass loops of #148, `bass`).

Variations (#158): every loop holds three named variations (`Loop.variations`),
each a complete line with two levels: level 1 is the full line, level 2 adds
ornaments. The loop's own notes are its skeleton, what `no-drums thin` plays. The
loops themselves are loop files (`mpc_iml.loops`, ADR 0010, #173); the built-in
`keys`, `pluck` and the hip-hop loops (#232) live in `mpc_iml/loops/ensemble/`.

Once per bar, at the bar line, a `Follower` decides the next bar from the drum hits
of the bar that just ended (RFC 0005, causality first): the hits choose the
variation (`melody_variation`) and whether its ornaments play (`melody_ornaments`),
so a sparse bar changes the line instead of thinning it; their average velocity
sets the loudness and the hits on `hat` pads the brightness CC (`brightness`, at
most `BRIGHTNESS_STEP` from the value sent before, #218). Bars without drums follow
the `no-drums` rule (`NO_DRUMS`).

A little surprise (#158): at the last bar of each 4-bar phrase, with probability
`SURPRISE_CHANCE`, one change the musician did not ask for (`surprise`): a bass fill
(`bass.bass_fill`), the melody an octave up (`octave_up`) or a passing note into the
next bar (`passing`). The choice comes from a seeded `random.Random`. By default
only the bass fill can come; the melody surprises need `surprise 2` (#178).
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mpc_iml.rhythm import Taken

__all__ = [
    "BRIGHTNESS",
    "BRIGHTNESS_STEP",
    "FADE",
    "MELODY_VARIATIONS",
    "NO_DRUMS",
    "ORNAMENTS",
    "PHRASE",
    "SURPRISES",
    "SURPRISE_CHANCE",
    "QUALITIES",
    "BarPlan",
    "Follower",
    "Loop",
    "LoopNote",
    "brightness",
    "brightness_step",
    "chord_note",
    "loop_pitch",
    "melody_ornaments",
    "melody_variation",
    "melody_velocity",
    "octave_up",
    "passing",
    "surprise",
]

QUALITIES = {
    "m7": (0, 3, 7, 10),
    "maj7": (0, 4, 7, 11),
    "7": (0, 4, 7, 10),
    "m7b5": (0, 3, 6, 10),
}
"""Semitones above the root of tones 0-3 (root, third, fifth, seventh); `m7b5`'s
fifth is the flat fifth (#236)."""

FIXED_VELOCITY = 100
"""Velocity of every note when the melody does not follow the drums."""

ORNAMENTS = 2
"""The level of a variation's ornaments; level 1 is its full line."""

MELODY_VARIATIONS = ("home", "open", "busy")
"""The variations of every melody loop, in order (`home` is the loop itself)."""

NO_DRUMS = ("lead", "hold", "thin")
"""What the loops play in bars without drums (`Follower`); `lead` is the default."""

FADE = (0.4, 0.7)
"""Velocity weights of the last and the second-to-last bar before the loops stop."""

SURPRISES = ("fill", "octave", "passing")
"""The surprises: a bass fill, the melody an octave up, a passing note."""

PHRASE = 4
"""Bars per phrase; a surprise can come in the last bar of each phrase."""

SURPRISE_CHANCE = 0.5
"""The probability of a surprise at the end of a phrase."""

BRIGHTNESS = (48, 110)
"""The brightness CC with no hats and with 16 or more (#218)."""

BRIGHTNESS_STEP = 24
"""The most the brightness CC changes from one bar to the next (#218)."""


@dataclass(frozen=True)
class LoopNote:
    """A note of a loop: `step` (16ths) of the loop's `bar`, a chord `tone` 0-3,
    `octave` above the melody octave, `length` in 16ths, `level` 1 or 2 and a velocity
    weight 0-1. `chord` 0 takes the chord of the note's own bar, 1 the chord of the
    next bar; `semitones` is added after the tone (an approach note half a step
    below the next root is `tone=0, chord=1, semitones=-1`). `offset` is how far
    the note sits from its step, a fraction of a 16th from -0.5 to 0.5 (loop files,
    ADR 0010)."""

    bar: int
    step: int
    tone: int
    length: int
    level: int
    octave: int = 0
    velocity: float = 1.0
    chord: int = 0
    semitones: int = 0
    offset: float = 0.0


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
    """The CC value a bar with `hats` hat hits aims at: 0 is 48, 16 or more is 110
    (`BRIGHTNESS`); `brightness_step` limits the change from the bar before."""
    low, high = BRIGHTNESS
    return round(low + min(hats, 16) * (high - low) / 16)


def brightness_step(last: int | None, target: int) -> int:
    """The CC value to send toward `target` after `last` was sent: at most
    `BRIGHTNESS_STEP` away from it (`target` itself when nothing was sent yet)."""
    if last is None:
        return target
    return min(max(target, last - BRIGHTNESS_STEP), last + BRIGHTNESS_STEP)


def surprise(rng: random.Random, bar: int, candidates: Sequence[str]) -> str | None:
    """The surprise of song bar `bar`, one of `candidates` (the `SURPRISES` that can
    sound now), or `None`: only in the last bar of a phrase, with probability
    `SURPRISE_CHANCE`, drawn from `rng`."""
    if bar % PHRASE != PHRASE - 1 or not candidates:
        return None
    if rng.random() >= SURPRISE_CHANCE:
        return None
    return rng.choice(list(candidates))


def octave_up(notes: Sequence[LoopNote]) -> tuple[LoopNote, ...]:
    """`notes` an octave up (the surprise `octave`)."""
    return tuple(replace(n, octave=n.octave + 1) for n in notes)


def passing(notes: Sequence[LoopNote]) -> tuple[LoopNote, ...]:
    """`notes` with the last one replaced by a passing note half a step below the same
    chord tone of the next bar's chord (the surprise `passing`). When the last step
    holds a chord, every note of it moves, so the chord slides into the next one
    (#232)."""
    if not notes:
        return tuple(notes)
    last = max(n.step for n in notes)
    return tuple(replace(n, chord=1, semitones=-1) if n.step == last else n for n in notes)


@dataclass(frozen=True)
class BarPlan:
    """What a loop plays in one bar: variation `variation` up to `level` (`None`:
    silence), at `velocity`, after sending the brightness CC `cc` (`None`: no CC).
    `skeleton` (`no-drums thin`) plays the loop's own level 1 instead (#144).
    `surprise` is whether the bar may carry a surprise: it follows the drums or keeps
    playing without them, not fixed, `thin`, fading or silent. `transform` is the
    rhythm transformation the bar plays (`rhythm.TRANSFORMS`, #189) and `taken` what
    it took from the drums (`None`: nothing, the line as written)."""

    variation: str | None
    level: int
    velocity: int
    cc: int | None
    skeleton: bool = False
    surprise: bool = False
    transform: str = "plain"
    taken: "Taken | None" = None

    def notes(self, loop: Loop, bar: int) -> tuple[LoopNote, ...]:
        """The notes of `loop` this plan plays in song bar `bar`."""
        if self.variation is None:
            return ()
        if self.skeleton:
            return loop.bar_notes(bar, 1)
        return loop.variation(self.variation).bar_notes(bar, self.level)


class Follower:
    """Decides each bar of a loop from the drums of the bar before (#158).

    A bar with drums plays the variation and level its drums chose (the caller's
    `melody_variation` and `melody_ornaments`, or the bass's). The loop stays silent
    until the first drum hit after Start; a bar the clock did not run through
    (`complete` false) with no hits counts as a new start. Bars without drums follow
    `no_drums` (`NO_DRUMS`): `lead` plays the loop's `lead` variation and level
    (the melody's `open` with ornaments, the bass's `home` line), `hold` keeps the
    last bar's choice, both at the last velocity, for `fade_bars` empty bars (0:
    never stop), the last two at `FADE` of it; `thin` is #144's rule, the skeleton
    after one empty bar and silence after two. A bar that does not follow
    (`follow` false) plays `home` at all levels at `FIXED_VELOCITY`. The brightness
    CC of a bar with drums moves toward its `cc` from the last one planned, at most
    `BRIGHTNESS_STEP` (`brightness_step`, #218), so the plan holds the value sent.
    """

    def __init__(self, lead: tuple[str, int]) -> None:
        self._lead = lead
        self._last = ("home", 1)
        self._empty: int | None = None
        self._velocity = FIXED_VELOCITY
        self._cc: int | None = None

    def plan_bar(
        self,
        velocities: Sequence[int],
        chosen: tuple[str, int],
        cc: int | None,
        complete: bool,
        follow: bool,
        no_drums: str = "lead",
        fade_bars: int = 8,
    ) -> BarPlan:
        """The plan for the bar that starts now, from the drum hits of the bar that
        ended: `velocities` of all counted hits, the variation and level they
        `chosen`, and the brightness `cc` they aim at."""
        if velocities:
            self._empty = 0
            self._velocity = melody_velocity(sum(velocities) / len(velocities))
            self._last = chosen
        elif not complete:
            self._empty = None
        elif self._empty is not None:
            self._empty += 1
        if not follow:
            return BarPlan("home", ORNAMENTS, FIXED_VELOCITY, None)
        if velocities:
            if cc is not None:
                cc = self._cc = brightness_step(self._cc, cc)
            return BarPlan(*chosen, self._velocity, cc, surprise=True)
        empty = self._empty
        if empty is None or (no_drums == "thin" and empty > 1):
            return BarPlan(None, 0, self._velocity, None)
        if no_drums == "thin":
            return BarPlan("home", 1, self._velocity, None, skeleton=True)
        if fade_bars and empty > fade_bars:
            return BarPlan(None, 0, self._velocity, None)
        left = fade_bars - empty if fade_bars else len(FADE)
        weight = FADE[left] if left < len(FADE) else 1.0
        velocity = max(round(self._velocity * weight), 1)
        chosen = self._lead if no_drums == "lead" else self._last
        return BarPlan(*chosen, velocity, None, surprise=weight == 1.0)
