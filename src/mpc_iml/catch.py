"""The catch (#290): the keys answer the bar where the drummer leaves a groove.

When the drummer leaves a groove they were holding (a fill, or the first bar of
something new), `ensemble` with `catch 1` has the melody play, in the next bar, a
short phrase with the rhythm the drummer just played; the bass holds its line.
`catch 2` is the comparison for trials: the same bars get an answer with the same
pitches, lengths and accent, but its rhythm comes from the loop, not the drums.

Pure functions, no I/O and no random numbers:

- `answers`: whether the bar that starts answers the bar that just ended (the
  tracker's decision on it has a groove and `fill`, on the `CATCH_HOLD` bars before
  it the same groove without `fill`, and it has `CATCH_MIN` hits).
- `drummed` (`catch 1`) and `written` (`catch 2`): the rhythm, at most
  `CATCH_NOTES` onsets, one per 16th step.
- `catch_notes`: the notes, with an accent on step 0, the pitches of the planned
  variation's `chord` 0 notes in turn, lengths to the next note (1 to `MAX_LENGTH`
  steps, inside the bar), velocity weights from the hits (`MIN_WEIGHT` to 1.0) and
  `rhythm.FEEL` of the hits' offsets (none on a late note that ends on the bar
  line, so no catch note sounds past its bar).
"""

from collections.abc import Sequence
from dataclasses import dataclass

from mpc_iml.clock import GridHit
from mpc_iml.grooves import Decision
from mpc_iml.melody import Loop, LoopNote
from mpc_iml.rhythm import FEEL

__all__ = [
    "CATCH_HOLD",
    "CATCH_MIN",
    "CATCH_NOTES",
    "IGNORED_PADS",
    "MAX_LENGTH",
    "MIN_WEIGHT",
    "WRITTEN_VELOCITY",
    "Onset",
    "answers",
    "catch_notes",
    "counted",
    "drummed",
    "written",
]

CATCH_HOLD = 2
"""Bars of the same groove, without `fill`, before the bar a catch answers."""

CATCH_MIN = 2
"""The fewest hits (on pads other than 15 and 16) in the bar a catch answers."""

CATCH_NOTES = 8
"""The most onsets a catch's rhythm keeps (the loudest; the accent comes on top)."""

IGNORED_PADS = frozenset({14, 15})
"""Pads 15 and 16 (counted from 0, as `GridHit.pad`): the mode pads, never rhythm."""

MAX_LENGTH = 4
"""The longest catch note, in 16ths."""

MIN_WEIGHT = 0.5
"""The lowest velocity weight of a catch note other than the accent."""

WRITTEN_VELOCITY = 100
"""The velocity of each onset of `catch 2`'s rhythm (`written`)."""


@dataclass(frozen=True)
class Onset:
    """A step of a catch's rhythm: the 16th `step` of the bar, the `velocity` 1-127
    and `offset` (-0.5 to 0.5 of a 16th) of the hit on it."""

    step: int
    velocity: int
    offset: float = 0.0


def counted(hits: Sequence[GridHit]) -> list[GridHit]:
    """The hits a catch reads: every pad's but 15's and 16's, whatever its role."""
    return [h for h in hits if h.pad not in IGNORED_PADS]


def answers(
    decision: Decision | None, before: Sequence[Decision | None], hits: Sequence[GridHit]
) -> bool:
    """Whether the bar that starts answers the bar that just ended with a catch:
    `decision` (the tracker's on that bar) has a groove and `fill`, `before` (its
    decisions on the `CATCH_HOLD` bars before it, latest first; `None` when unknown)
    are bars of that groove without `fill`, and `hits` (that bar's) has at least
    `CATCH_MIN` hits on pads other than 15 and 16."""
    if decision is None or decision.groove is None or not decision.fill:
        return False
    held = list(before[:CATCH_HOLD])
    if len(held) < CATCH_HOLD:
        return False
    if any(d is None or d.groove != decision.groove or d.fill for d in held):
        return False
    return len(counted(hits)) >= CATCH_MIN


def _limit(onsets: Sequence[Onset]) -> tuple[Onset, ...]:
    """The `CATCH_NOTES` loudest of `onsets` (one per step; the earlier step first on
    a tie), in step order."""
    kept = sorted(onsets, key=lambda o: (-o.velocity, o.step))[:CATCH_NOTES]
    return tuple(sorted(kept, key=lambda o: o.step))


def drummed(hits: Sequence[GridHit], steps: int) -> tuple[Onset, ...]:
    """`catch 1`'s rhythm: the bar's hits on every pad but 15 and 16, one onset per
    step (the loudest hit on it, the first of equals), at most `CATCH_NOTES`."""
    loudest: dict[int, GridHit] = {}
    for hit in counted(hits):
        if not 0 <= hit.step < steps:
            continue
        if hit.step not in loudest or hit.velocity > loudest[hit.step].velocity:
            loudest[hit.step] = hit
    return _limit([Onset(h.step, h.velocity, h.offset) for h in loudest.values()])


def written(loop: Loop, variation: str | None, bar: int, steps: int) -> tuple[Onset, ...]:
    """`catch 2`'s rhythm: the steps of the level 1 notes in song bar `bar` of the
    variation after `variation` in `loop`'s order (wrapping; the loop's own notes
    when it has no other variation), each at `WRITTEN_VELOCITY` with no offset, at
    most `CATCH_NOTES`. It reads nothing the drums played."""
    names = [v.name for v in loop.variations]
    source = loop
    if variation in names and len(names) > 1:
        source = loop.variations[(names.index(variation) + 1) % len(names)]
    found = sorted({n.step for n in source.bar_notes(bar, 1) if 0 <= n.step < steps})
    return _limit([Onset(s, WRITTEN_VELOCITY) for s in found])


def _weight(velocity: int) -> float:
    return min(max(velocity / 127, MIN_WEIGHT), 1.0)


def catch_notes(
    rhythm: Sequence[Onset], planned: Sequence[LoopNote], bar: int, steps: int
) -> tuple[LoopNote, ...]:
    """The catch's notes in the loop's bar `bar` (`steps` 16ths long) for `rhythm`:
    a note on each onset and on step 0 (the accent, weight 1.0, the hit's offset
    times `FEEL` when the drummer played there, else none). The pitches are the
    `tone`, `octave` and `semitones` of the `chord` 0 notes of `planned` (the
    variation the melody would play) in step order, in turn (`tone` 0 when there
    are none). Each note lasts to the next one, 1 to `MAX_LENGTH` steps, inside the
    bar; its weight is the hit's velocity / 127, from `MIN_WEIGHT` to 1.0. A note
    that a late offset would carry past the bar line gets no offset, so it never
    cuts a note of the next bar."""
    onsets = {o.step: o for o in rhythm if 0 <= o.step < steps}
    accent = onsets.get(0, Onset(0, 127))
    onsets[0] = accent
    order = sorted(onsets)
    chord_tones = sorted((n for n in planned if n.chord == 0), key=lambda n: n.step)
    tones = [(n.tone, n.octave, n.semitones) for n in chord_tones]
    notes = []
    for i, step in enumerate(order):
        onset = onsets[step]
        tone, octave, semitones = tones[i % len(tones)] if tones else (0, 0, 0)
        following = order[i + 1] if i + 1 < len(order) else steps
        length = min(max(following - step, 1), MAX_LENGTH, steps - step)
        weight = 1.0 if step == 0 else _weight(onset.velocity)
        offset = FEEL * onset.offset
        if step + length >= steps and offset > 0:
            offset = 0.0
        notes.append(
            LoopNote(
                bar=bar,
                step=step,
                tone=tone,
                length=length,
                level=1,
                octave=octave,
                velocity=weight,
                chord=0,
                semitones=semitones,
                offset=offset,
            )
        )
    return tuple(notes)
