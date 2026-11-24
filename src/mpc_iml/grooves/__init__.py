"""Groove recognition for `ensemble` (#245). No I/O; it changes nothing the band plays.

A **groove** is a stable pattern of kick, snare and hat held over several bars, with
fills in between. This module reduces each bar to its `Pattern`, compares bars with
a `similarity` that tolerates a hit one step off, describes a bar in musical terms
(`features`), and follows the drummer bar by bar with a `Tracker`.

`pattern` reads the hits by the role of their pad (`ensemble.DEFAULT_ROLES`, or the
roles the `role` control set). Pads 16 and 15 (indices 15 and 14) are never part of
it, whatever their role: they are controls, even when the kit plays an open hat on
pad 16. `other` hits and velocity are not read; several hits on one step count once.

`similarity` is, per role, the share of hits that pair with a hit of the other bar at
most one step away (Dice), and the mean over the roles that play in either bar.

The `Tracker` makes one `Decision` per complete bar, in order:

- No drums (no kick, snare or hat) for `SILENT_BARS` bars ends the groove. A single
  bar with no drums is a fill.
- With no groove, two similar bars in a row start one, confirmed at the end of the
  second bar.
- A bar `SIMILAR` to the groove's prototype continues it.
- A different bar is a **fill**; the groove stays. Two different bars that are
  similar to each other start a new groove at the first of them. Two different bars
  that differ from each other are both fills (the two bars of a two-bar fill).
- After `FREE_BARS` fills in a row the groove ends: the bars after it are **free**
  until two similar bars start a groove.

A starting groove takes the id of a groove seen before when both its bars reach
`RETURN` against that groove's prototype (the best one), else the next id from 1.
The prototype is a vote per role and step: each bar of the groove multiplies the
votes by `DECAY` and adds 1 to its own steps, and the prototype is the steps with at
least half of the (decayed) bar count. Fills do not vote. With a decay of 0.8 the
vote keeps about the last five bars, so a groove that drifts slowly keeps its id.

`rhythm_descriptors` (#250) describes a pattern with the five descriptors of
Gómez-Marín, Jordà and Herrera (2020, "Drum rhythm spaces: from polyphonic
similarity to generative maps", JNMR 49(5)), which predict how alike people hear two
polyphonic drum patterns. They are computed as in the authors' `rhythmtoolbox` (MIT),
with low = kick, mid = snare and high = hat. Two grooves are in a **group** when
`descriptor_distance` between their prototypes is at most `GROUP_DISTANCE`.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, fields

from mpc_iml.clock import GridHit

__all__ = [
    "CONTROL_PADS",
    "DECAY",
    "FREE_BARS",
    "GROUP_DISTANCE",
    "GROUP_SCALE",
    "PART_ROLES",
    "RETURN",
    "SALIENCE",
    "SILENT_BARS",
    "SIMILAR",
    "STEPS",
    "Decision",
    "Descriptors",
    "Features",
    "Groove",
    "Pattern",
    "Tracker",
    "descriptor_distance",
    "features",
    "matched",
    "mean_features",
    "pattern",
    "rhythm_descriptors",
    "similarity",
    "syncopation",
]

STEPS = 16
"""Steps in a bar (4/4 only)."""

PART_ROLES = ("kick", "snare", "hat")
"""The roles a pattern reads."""

CONTROL_PADS = frozenset({14, 15})
"""Pads 15 and 16 (from 0), never part of a pattern."""

SIMILAR = 0.8
"""The similarity at which a bar continues a groove, or two bars start one."""

RETURN = 0.8
"""The mean similarity of a starting groove's two bars to an earlier prototype at
which the groove takes that earlier id."""

FREE_BARS = 4
"""Fills in a row after which the groove ends and the bars are free."""

SILENT_BARS = 2
"""Bars with no drums in a row that end the groove."""

DECAY = 0.8
"""The factor on a prototype's votes before each new bar of the groove votes."""


@dataclass(frozen=True)
class Pattern:
    """A bar's kick, snare and hat steps (0-15)."""

    kick: frozenset[int] = frozenset()
    snare: frozenset[int] = frozenset()
    hat: frozenset[int] = frozenset()

    def role(self, name: str) -> frozenset[int]:
        steps: frozenset[int] = getattr(self, name)
        return steps

    @property
    def empty(self) -> bool:
        """No kick, snare or hat: no drums."""
        return not (self.kick or self.snare or self.hat)


def pattern(hits: Iterable[GridHit], roles: Sequence[str]) -> Pattern:
    """The pattern of a bar's `hits`, by the role of each hit's pad in `roles` (the
    bank is ignored, as in `measures`). Pads 15 and 16, `other` hits and hits with a
    step outside 0-15 are left out."""
    steps: dict[str, set[int]] = {name: set() for name in PART_ROLES}
    for hit in hits:
        if hit.pad in CONTROL_PADS or not 0 <= hit.pad < len(roles):
            continue
        role = roles[hit.pad]
        if role in steps and 0 <= hit.step < STEPS:
            steps[role].add(hit.step)
    return Pattern(*(frozenset(steps[name]) for name in PART_ROLES))


def matched(a: Iterable[int], b: Iterable[int]) -> int:
    """The largest number of pairs of one step of `a` and one of `b`, each used once,
    at most one step apart. On a line, pairing from the left is the largest."""
    xs, ys = sorted(set(a)), sorted(set(b))
    i = j = count = 0
    while i < len(xs) and j < len(ys):
        if abs(xs[i] - ys[j]) <= 1:
            count += 1
            i += 1
            j += 1
        elif xs[i] < ys[j]:
            i += 1
        else:
            j += 1
    return count


def similarity(a: Pattern, b: Pattern) -> float:
    """How alike two bars are, 0-1: per role `2 * matched / (|a| + |b|)`, and the mean
    of the roles that play in either bar, each with the same weight. Two bars with no
    drums are 1.0; one with no drums against one with drums is 0.0."""
    scores = []
    for name in PART_ROLES:
        x, y = a.role(name), b.role(name)
        if x or y:
            scores.append(2 * matched(x, y) / (len(x) + len(y)))
    return sum(scores) / len(scores) if scores else 1.0


@dataclass(frozen=True)
class Features:
    """A bar (or the mean over a groove's bars) in musical terms.

    `kicks`: kick steps. `double_kicks`: steps `s` with a kick on `s` and `s + 1`.
    `late_kicks`: kicks on steps 8-15 (the second half). `snare_off`: snare steps more
    than one step from both backbeats (4 and 12). `hats`: hat steps. `hat_presence`:
    1 when the bar has a hat, else 0.
    """

    kicks: float = 0.0
    double_kicks: float = 0.0
    late_kicks: float = 0.0
    snare_off: float = 0.0
    hats: float = 0.0
    hat_presence: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def features(p: Pattern) -> Features:
    """The features of one bar."""
    return Features(
        kicks=len(p.kick),
        double_kicks=sum(1 for s in p.kick if s + 1 in p.kick),
        late_kicks=sum(1 for s in p.kick if s >= STEPS // 2),
        snare_off=sum(1 for s in p.snare if abs(s - 4) > 1 and abs(s - 12) > 1),
        hats=len(p.hat),
        hat_presence=1 if p.hat else 0,
    )


def mean_features(bars: Sequence[Features]) -> Features:
    """The mean of `bars`; all zero when there are none."""
    if not bars:
        return Features()
    names = [f.name for f in fields(Features)]
    return Features(**{n: sum(getattr(b, n) for b in bars) / len(bars) for n in names})


SALIENCE = (5, 1, 2, 1, 3, 1, 2, 1, 4, 1, 2, 1, 3, 1, 2, 1)
"""The metrical weight of each step, Longuet-Higgins and Lee style (as in
`rhythmtoolbox`): the downbeat 5, beat 3 4, beats 2 and 4 3, the other 8ths 2, 16ths 1."""


def syncopation(steps: Iterable[int]) -> int:
    """The syncopation of one role's steps: each hit followed by a step without a hit
    (the bar wraps, so step 15 is followed by step 0) adds the weight of that next step
    minus its own (`SALIENCE`). A hit on a strong step before a rest counts below 0, a
    hit before a stronger rest above 0. As `rhythmtoolbox.descriptors.syncopation16`."""
    hits = set(steps)
    return sum(SALIENCE[(s + 1) % STEPS] - SALIENCE[s] for s in hits if (s + 1) % STEPS not in hits)


@dataclass(frozen=True)
class Descriptors:
    """A pattern's rhythm descriptors (module docstring), named as in the paper.

    `lowsync`: the kick's `syncopation`. `midD`: snare steps. `hiD`: hat steps.
    `hiness`: hat steps divided by the steps with any kick, snare or hat (0 with no
    drums). `hisyness`: the hat's syncopation divided by its steps (0 with no hat).
    """

    lowsync: float = 0.0
    midD: float = 0.0
    hiD: float = 0.0
    hiness: float = 0.0
    hisyness: float = 0.0

    def as_dict(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def rhythm_descriptors(p: Pattern) -> Descriptors:
    """The rhythm descriptors of one pattern (a bar or a groove's prototype)."""
    onsets = len(p.kick | p.snare | p.hat)
    return Descriptors(
        lowsync=syncopation(p.kick),
        midD=len(p.snare),
        hiD=len(p.hat),
        hiness=len(p.hat) / onsets if onsets else 0.0,
        hisyness=syncopation(p.hat) / len(p.hat) if p.hat else 0.0,
    )


GROUP_SCALE = Descriptors(lowsync=4.0, midD=2.0, hiD=4.0, hiness=0.25, hisyness=1.0)
"""The fixed scale of each descriptor in `descriptor_distance`: about the spread of
each over common 16-step grooves, so a difference of one scale is a clear change
(4 for kick syncopation, 2 snare hits, 4 hat hits, a quarter of the hits, 1 for the
hat's syncopation per hit, the difference between hats on the 8ths and on the 16ths
is about 1.9). Proposed in #250 and checked with `python -m mpc_iml.grooves
--group-distance` against recorded sessions."""

GROUP_DISTANCE = 2.0
"""The largest `descriptor_distance` at which two grooves are in a group (#250,
`learn-group 1`). Proposed with `GROUP_SCALE`, checked the same way."""


def descriptor_distance(
    a: Descriptors | Pattern, b: Descriptors | Pattern, scale: Descriptors = GROUP_SCALE
) -> float:
    """The Euclidean distance between two descriptor vectors (of patterns, or computed
    already), each descriptor divided by its `scale`."""
    x = a if isinstance(a, Descriptors) else rhythm_descriptors(a)
    y = b if isinstance(b, Descriptors) else rhythm_descriptors(b)
    total = 0.0
    for f in fields(Descriptors):
        unit: float = getattr(scale, f.name)
        total += ((getattr(x, f.name) - getattr(y, f.name)) / unit) ** 2
    return float(total**0.5)


@dataclass
class _Vote:
    """A groove's prototype vote and its bars' features."""

    decay: float
    count: float = 0.0
    votes: dict[str, list[float]] = field(
        default_factory=lambda: {name: [0.0] * STEPS for name in PART_ROLES}
    )
    bars: list[Features] = field(default_factory=list)

    def add(self, p: Pattern) -> None:
        self.count = self.count * self.decay + 1
        for name in PART_ROLES:
            row = self.votes[name]
            for s in range(STEPS):
                row[s] = row[s] * self.decay + (1.0 if s in p.role(name) else 0.0)
        self.bars.append(features(p))

    def prototype(self) -> Pattern:
        half = self.count / 2
        return Pattern(
            *(
                frozenset(s for s, v in enumerate(self.votes[name]) if v > 0 and v >= half)
                for name in PART_ROLES
            )
        )


@dataclass(frozen=True)
class Groove:
    """A groove seen in this session: its `id`, `prototype` now, the number of `bars`
    that voted (fills do not) and the mean `features` of those bars."""

    id: int
    prototype: Pattern
    bars: int
    features: Features


@dataclass(frozen=True)
class Decision:
    """The tracker's decision on one bar, as known at its end.

    `groove` is the current groove's id, or `None` (no groove yet, no drums, or
    `free`). `position` is the bar within the groove's section (from 1, fills
    included; the section starts at `start`, the first of the two bars that started
    it). `fill` marks a bar that differs from the groove. `free` marks a bar after
    `FREE_BARS` fills in a row, before a new groove starts. `new` marks the bar that
    confirmed a groove (new or returning), at position 2. `similarity` is to the
    groove's prototype, or to the bar before for the bar that starts a groove, or
    `None`.
    """

    bar: int
    groove: int | None = None
    position: int | None = None
    start: int | None = None
    fill: bool = False
    free: bool = False
    new: bool = False
    similarity: float | None = None


@dataclass
class _Current:
    id: int
    start: int
    vote: _Vote


class Tracker:
    """Follows the drummer's grooves (module docstring). `observe` takes each complete
    bar in order; incomplete bars are not passed. The library of grooves lasts as long
    as the tracker, across Stop and Start (`stop`)."""

    def __init__(
        self,
        similar: float = SIMILAR,
        return_at: float = RETURN,
        free_bars: int = FREE_BARS,
        decay: float = DECAY,
    ) -> None:
        if free_bars < 1:
            raise ValueError(f"free_bars must be at least 1: {free_bars}")
        self.similar = similar
        self.return_at = return_at
        self.free_bars = free_bars
        self.decay = decay
        self._library: dict[int, _Vote] = {}
        self._current: _Current | None = None
        self._pending: tuple[int, Pattern] | None = None
        self._fills = 0
        self._silent = 0
        self._free = False

    @property
    def grooves(self) -> tuple[Groove, ...]:
        """The grooves seen so far, by id."""
        return tuple(
            Groove(i, v.prototype(), len(v.bars), mean_features(v.bars))
            for i, v in sorted(self._library.items())
        )

    def stop(self) -> None:
        """The clock stopped: the groove ends; the library stays."""
        self._end()
        self._pending = None
        self._free = False
        self._silent = 0

    def observe(self, bar: int, p: Pattern) -> Decision:
        """The decision on complete `bar` with pattern `p`."""
        if p.empty:
            return self._silence(bar)
        self._silent = 0
        current = self._current
        score = None if current is None else similarity(current.vote.prototype(), p)
        if current is not None and score is not None and score >= self.similar:
            self._pending = None
            self._fills = 0
            current.vote.add(p)
            return self._at(bar, current, score)
        started = self._start(bar, p)
        if started is not None:
            return started
        self._pending = (bar, p)
        if current is None or score is None:
            return Decision(bar, free=self._free)
        return self._fill(bar, current, score)

    def _silence(self, bar: int) -> Decision:
        self._silent += 1
        self._pending = None
        current = self._current
        if self._silent >= SILENT_BARS:
            self._end()
            self._free = False
            return Decision(bar)
        if current is None:
            return Decision(bar, free=self._free)
        return self._fill(bar, current, similarity(current.vote.prototype(), Pattern()))

    def _fill(self, bar: int, current: _Current, score: float) -> Decision:
        self._fills += 1
        decision = Decision(
            bar,
            groove=current.id,
            position=bar - current.start + 1,
            start=current.start,
            fill=True,
            similarity=score,
        )
        if self._fills >= self.free_bars:
            self._end()
            self._free = True
        return decision

    def _start(self, bar: int, p: Pattern) -> Decision | None:
        """A groove from the pending bar and `p` when they are similar."""
        if self._pending is None:
            return None
        first_bar, first = self._pending
        score = similarity(first, p)
        if score < self.similar:
            return None
        self._end()
        best, best_score = None, self.return_at
        for i, vote in self._library.items():
            proto = vote.prototype()
            mean = (similarity(first, proto) + similarity(p, proto)) / 2
            if mean >= best_score and (best is None or mean > best_score):
                best, best_score = i, mean
        if best is None:
            best = max(self._library, default=0) + 1
            self._library[best] = _Vote(self.decay)
        vote = self._library[best]
        vote.add(first)
        vote.add(p)
        self._current = _Current(best, first_bar, vote)
        self._pending = None
        self._fills = 0
        self._free = False
        return self._at(bar, self._current, score, new=True)

    def _at(self, bar: int, current: _Current, score: float, new: bool = False) -> Decision:
        return Decision(
            bar,
            groove=current.id,
            position=bar - current.start + 1,
            start=current.start,
            new=new,
            similarity=score,
        )

    def _end(self) -> None:
        """The groove ends (its vote stays in the library); a pending bar stays."""
        self._current = None
        self._fills = 0
