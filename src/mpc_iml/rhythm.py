"""Rhythm transformation for `ensemble` (RFC 0005 step 6, #189). No I/O.

The band's rhythm comes from what the musician just played: the onsets of the line
a variation plays (`melody.BarPlan.notes`) move towards the drum hits of the last
bar. The line keeps its notes, pitches and order; only onsets move, so the line can
never be emptied (RFC 0005 principle 7) and its pitches stay those of the loop,
built-in or the musician's own (#173).

The input is read per role (`motif`): the kick steps feed the bass, the snare and hat
steps the melody, each hit with its velocity and offset. A `Memory` keeps the motif
of the phrase: a bar close to it (the same number of hits, each within one step)
keeps the motif's onsets, so a steady groove gives a steady answer; a new pattern
replaces it at once. Fewer than `MIN_HITS` hits of a role is too little rhythm: the
line plays as written.

The transformations (`TRANSFORMS`):

- `lock` (bass): each note that may move goes to the nearest free kick within `REACH`
  steps; a note with no kick near stays.
- `answer` (bass): `lock`, then the notes it moved onto a kick sit one 16th later
  (call and response).
- `backbeat` (melody): as `lock`, towards the snare steps and the hat steps (16ths
  if the hats played an odd step, else 8ths only).

The phrase shapes the change (`bass_stage`): the first bar of each `melody.PHRASE`
is the plain line (the statement), the next two `lock` and the last `answer`, where
the surprise `fill` can still replace the last beat. `Taken` is what a bar took from
the drums, for the musician to see (RFC 0005 principle 12).

What never moves (RFC 0005 principle 10): the line's skeleton (`fixed_steps`: the
loop's `skeleton` notes, or the bar's first note when none is marked) and every note
taking the next bar's chord (`chord` 1, the approach notes). A moved note never
lands on or after the bar's first approach note, and stays strictly between its
neighbours, so it never shares a step with another note and the pitch order holds;
notes sharing a step (a chord) stay.
Among equally near hits the louder, then the earlier, wins. Dense input (more
hits than the line has notes) is taken on the 8th grid first: only its hits on even
steps are targets, when there are at least `MIN_HITS` of them. A moved note
takes `FEEL` of the offset of the hit it moved to (clamped to -0.5..0.5); a note
that does not move keeps its written offset.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass, replace

from mpc_iml.clock import GridHit
from mpc_iml.melody import PHRASE, Loop, LoopNote

__all__ = [
    "BASS_STAGES",
    "FEEL",
    "MIN_HITS",
    "REACH",
    "TRANSFORMS",
    "Memory",
    "Motif",
    "Move",
    "Onset",
    "Shaped",
    "Taken",
    "answer",
    "backbeat",
    "bass_stage",
    "fixed_steps",
    "lock",
    "motif",
    "similar",
]

TRANSFORMS = ("plain", "lock", "answer", "backbeat")
"""`plain` is the line as written."""

BASS_STAGES = ("plain", "lock", "lock", "answer")
"""The bass's transformation in each bar of a phrase (`melody.PHRASE` bars)."""

REACH = 2
"""How far, in 16ths, a note moves to a hit."""

FEEL = 0.5
"""The share of a hit's offset a note takes when it moves to that hit."""

MIN_HITS = 2
"""The fewest hits of a role that reshape the line; fewer play it as written."""

_OFFSET = 0.5
_STEPS = 16


@dataclass(frozen=True)
class Onset:
    """A drum hit of the last bar: `step` (16ths), `velocity` and `offset` from the
    step (-0.5 to 0.5, as `clock.GridHit`)."""

    step: int
    velocity: int
    offset: float = 0.0


@dataclass(frozen=True)
class Motif:
    """The rhythm of a bar per role, each in step order with one onset per step."""

    kicks: tuple[Onset, ...] = ()
    snares: tuple[Onset, ...] = ()
    hats: tuple[Onset, ...] = ()


@dataclass(frozen=True)
class Move:
    """A note that moved: from step `start` to step `step`, taken from the hit on
    step `source`."""

    start: int
    step: int
    source: int


@dataclass(frozen=True)
class Shaped:
    """A bar's notes after a transformation, in the order given, and the moves."""

    notes: tuple[LoopNote, ...]
    transform: str
    moves: tuple[Move, ...] = ()


@dataclass(frozen=True)
class Taken:
    """What a bar took from the drums: the `role` it answered (`kick` for the
    bass, `snare hat` for the melody), the `steps` of that rhythm (the remembered
    motif) and the `moves` of the line's notes."""

    role: str
    steps: tuple[int, ...]
    moves: tuple[Move, ...] = ()


def bass_stage(bar: int) -> str:
    """The bass's transformation in song `bar`, by its place in the phrase."""
    return BASS_STAGES[bar % PHRASE]


def _onsets(hits: Sequence[GridHit]) -> tuple[Onset, ...]:
    loudest: dict[int, GridHit] = {}
    for hit in hits:
        if hit.step not in loudest or hit.velocity > loudest[hit.step].velocity:
            loudest[hit.step] = hit
    return tuple(Onset(s, h.velocity, h.offset) for s, h in sorted(loudest.items()))


def motif(hits: Sequence[GridHit], roles: Sequence[str]) -> Motif:
    """The motif of a bar's `hits`, by the role of each hit's pad in `roles`
    (`kick`, `snare`, `hat`; other roles are not read). Hits on one step count once,
    the loudest."""

    def of(role: str) -> tuple[Onset, ...]:
        return _onsets([h for h in hits if h.pad < len(roles) and roles[h.pad] == role])

    return Motif(of("kick"), of("snare"), of("hat"))


def similar(a: Sequence[Onset], b: Sequence[Onset]) -> bool:
    """Whether two rhythms are close: as many onsets, each within one step."""
    return len(a) == len(b) and all(abs(x.step - y.step) <= 1 for x, y in zip(a, b, strict=True))


class Memory:
    """The motif of the phrase (#189): `take` returns the rhythm to answer, per role
    the remembered one while the bar stays `similar` to it, else the new one."""

    def __init__(self) -> None:
        self.motif = Motif()

    def take(self, new: Motif) -> Motif:
        old = self.motif

        def keep(a: tuple[Onset, ...], b: tuple[Onset, ...]) -> tuple[Onset, ...]:
            return a if len(a) >= MIN_HITS and similar(a, b) else b

        self.motif = Motif(
            keep(old.kicks, new.kicks), keep(old.snares, new.snares), keep(old.hats, new.hats)
        )
        return self.motif

    def reset(self) -> None:
        self.motif = Motif()


def fixed_steps(loop: Loop, bar: int) -> frozenset[int] | None:
    """The steps of the skeleton of `loop` in song `bar` (its own notes, the
    `skeleton` notes of a loop file), or `None` when the loop marks no skeleton (its
    own notes are `home`'s level 1, `loops.LoopFile.loop`): the bar's first note is
    kept then."""
    own = sorted(n.step for n in loop.bar_notes(bar, 1))
    try:
        home = sorted(n.step for n in loop.variation("home").bar_notes(bar, 1))
    except KeyError:
        home = []
    if not own or own == home:
        return None
    return frozenset(own)


def _clamp(offset: float) -> float:
    return min(max(offset, -_OFFSET), _OFFSET)


def _move(
    notes: Sequence[LoopNote],
    fixed: Collection[int] | None,
    targets: Sequence[Onset],
    transform: str,
) -> Shaped:
    """Move the notes that may move to the nearest free `targets` (see the module)."""
    if len(targets) < MIN_HITS or not notes:
        return Shaped(tuple(notes), "plain")
    eighths = [t for t in targets if t.step % 2 == 0]
    if len(targets) > len(notes) and len(eighths) >= MIN_HITS:
        targets = eighths
    order = sorted(range(len(notes)), key=lambda i: notes[i].step)
    first = notes[order[0]].step
    keep = frozenset(fixed) if fixed is not None else frozenset({first})
    approaches = [n.step for n in notes if n.chord]
    limit = min(approaches, default=_STEPS)
    steps = [n.step for n in notes]
    taken = set(steps)
    shared = {s for s in taken if steps.count(s) > 1}
    moves: list[Move] = []
    for k, i in enumerate(order):
        note = notes[i]
        if note.step in keep or note.step in shared or note.chord or note.step >= limit:
            continue
        if any(t.step == note.step for t in targets):
            continue
        low = steps[order[k - 1]] if k else -1
        high = steps[order[k + 1]] if k + 1 < len(order) else _STEPS
        free = [
            t
            for t in targets
            if abs(t.step - note.step) <= REACH
            and low < t.step < min(high, limit)
            and t.step not in taken
        ]
        if not free:
            continue
        best = min(free, key=lambda t: (abs(t.step - note.step), -t.velocity, t.step))
        taken.discard(note.step)
        taken.add(best.step)
        moves.append(Move(note.step, best.step, best.step))
        steps[i] = best.step
    shaped = [
        replace(n, step=s, offset=_clamp(FEEL * _target(targets, s).offset)) if s != n.step else n
        for n, s in zip(notes, steps, strict=True)
    ]
    return Shaped(tuple(shaped), transform, tuple(moves))


def _target(targets: Sequence[Onset], step: int) -> Onset:
    return next(t for t in targets if t.step == step)


def lock(
    notes: Sequence[LoopNote], fixed: Collection[int] | None, kicks: Sequence[Onset]
) -> Shaped:
    """`notes` of a bass bar with the notes that may move on the nearest free kick."""
    return _move(notes, fixed, kicks, "lock")


def answer(
    notes: Sequence[LoopNote], fixed: Collection[int] | None, kicks: Sequence[Onset]
) -> Shaped:
    """`lock`, then each note it moved one 16th later where that step is free (still
    before the next note and the approach note)."""
    locked = lock(notes, fixed, kicks)
    if locked.transform == "plain":
        return locked
    shaped = list(locked.notes)
    approaches = [n.step for n in shaped if n.chord]
    limit = min(approaches, default=_STEPS)
    moves: list[Move] = []
    for move in locked.moves:
        i = next(j for j, n in enumerate(shaped) if n.step == move.step)
        later = move.step + 1
        if later < limit and not any(n.step == later for n in shaped):
            shaped[i] = replace(shaped[i], step=later)
            moves.append(replace(move, step=later))
        else:
            moves.append(move)
    return Shaped(tuple(shaped), "answer", tuple(moves))


def backbeat(
    notes: Sequence[LoopNote],
    fixed: Collection[int] | None,
    snares: Sequence[Onset],
    hats: Sequence[Onset],
) -> Shaped:
    """`notes` of a melody bar moved as `lock` to the snare steps and the hat steps:
    16ths when a hat played an odd step, else the hats on 8ths only. A hat on a
    snare's step counts once, as the snare."""
    sixteenths = any(h.step % 2 for h in hats)
    on = {s.step for s in snares}
    grid = [h for h in hats if h.step not in on and (sixteenths or h.step % 2 == 0)]
    targets = sorted([*snares, *grid], key=lambda t: t.step)
    return _move(notes, fixed, targets, "backbeat")
