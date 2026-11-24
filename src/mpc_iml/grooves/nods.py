"""What a nod counts for, and the nods the band keeps (#250). No I/O; nothing plays.

With `learn nod` the drummer nods with pad 16 to say "keep this" (RFC 0005 principle
14; ADR 0009 "Amendment: learning by groove", "The nod"). This module holds the parts
that need no clock:

- `nod_groove` gives the groove a nod counts for, from the tracker's decisions on the
  nodded bar and the bar before: a groove bar counts for its groove (`from` `bar`);
  a fill, a free bar or a bar with no drums counts for the groove whose last groove
  bar is the bar before (`from` `fill`, "ended no more than one bar before");
  otherwise for nothing (`from` `none`). It also gives the bar whose bass variation
  is learned.
- `NodMemory` keeps one `Nod` per groove: the groove's prototype and features, the
  bass variation nodded to, the count of nods, the loop and the date. Within a
  session a nod belongs to the tracker's id of its groove (`bind`). Across sessions
  a confirmed groove finds a stored nod with the tracker's own return test
  (`match`: the mean step similarity of its two starting bars to the stored
  prototype at least `RETURN`). Two nods whose prototypes come to match at `RETURN`
  merge into the newer one. At most `NODS_MAX` are kept; the one nodded least
  recently goes first.
- `NodMemory.group` gives the nearest nod of another groove within `GROUP_DISTANCE`
  of a prototype (`descriptor_distance`), for `learn-group 1`, and `NodMemory.draw`
  plays it with probability `GROUP_SHARE`, from that nod's own seeded generator.
"""

import random
from dataclasses import dataclass, field
from typing import Literal

from mpc_iml.grooves import (
    GROUP_DISTANCE,
    RETURN,
    Decision,
    Features,
    Pattern,
    descriptor_distance,
    similarity,
)

__all__ = [
    "GROUP_SHARE",
    "NODS_MAX",
    "Nod",
    "NodMemory",
    "NodTarget",
    "nod_groove",
]

NODS_MAX = 64
"""The most nods kept; the one nodded least recently goes first."""

GROUP_SHARE = 0.5
"""The probability that a groove with no nod of its own plays the nod of its group,
drawn once per section (`learn-group 1`)."""

From = Literal["bar", "fill", "none"]


@dataclass(frozen=True)
class NodTarget:
    """What a nod on `bar` counts for. `groove` is the tracker's id, or `None` when
    nothing is learned. `learn_bar` is the bar whose bass variation is learned: the
    nodded bar when it was a groove bar (`from_` `bar`), else the groove's last groove
    bar (`from_` `fill`). `ended` is that last groove bar for `fill`, else `None`."""

    bar: int
    groove: int | None
    learn_bar: int | None
    from_: From
    ended: int | None = None


def _groove_bar(decision: Decision | None) -> bool:
    return decision is not None and decision.groove is not None and not decision.fill


def nod_groove(bar: int, decision: Decision | None, before: Decision | None) -> NodTarget:
    """The groove a nod on `bar` counts for, from the tracker's `decision` on `bar` and
    on the bar before (`before`; `None` when the tracker has none, for example after a
    Stop)."""
    if decision is not None and decision.bar != bar:
        raise ValueError(f"decision on bar {decision.bar}, not {bar}")
    if before is not None and before.bar != bar - 1:
        raise ValueError(f"decision on bar {before.bar}, not {bar - 1}")
    if decision is not None and _groove_bar(decision):
        return NodTarget(bar, decision.groove, bar, "bar")
    if before is not None and _groove_bar(before):
        return NodTarget(bar, before.groove, before.bar, "fill", ended=before.bar)
    return NodTarget(bar, None, None, "none")


@dataclass
class Nod:
    """One nod kept for a groove (the profile's `nods` entry, ADR 0009 "The profile").
    `loop` is the bass loop it was heard in, a record only. `last` is the date of the
    last nod (`YYYY-MM-DD`). `order` grows with each nod, so the least recent is the
    smallest."""

    prototype: Pattern
    features: Features
    variation: str
    part: str = "bass"
    nods: int = 1
    loop: str = ""
    last: str = ""
    order: int = 0
    rng: random.Random = field(default_factory=random.Random, repr=False, compare=False)


class NodMemory:
    """The nods the band keeps (module docstring). `seed` seeds each nod's own
    generator, with the order in which the nods were made."""

    def __init__(
        self,
        nods_max: int = NODS_MAX,
        return_at: float = RETURN,
        seed: int | None = None,
    ) -> None:
        if nods_max < 1:
            raise ValueError(f"nods_max must be at least 1: {nods_max}")
        self.nods_max = nods_max
        self.return_at = return_at
        self.seed = seed
        self._nods: list[Nod] = []
        self._bound: dict[int, Nod] = {}
        self._order = 0
        self._made = 0

    @property
    def nods(self) -> tuple[Nod, ...]:
        """The nods kept, the most recent first."""
        return tuple(sorted(self._nods, key=lambda n: n.order, reverse=True))

    def reset(self) -> None:
        """Forget every nod (`reset-learning`)."""
        self._nods.clear()
        self._bound.clear()

    def variation(self, groove: int) -> str | None:
        """The variation nodded to for the tracker's `groove` in this session."""
        nod = self._bound.get(groove)
        return None if nod is None else nod.variation

    def bound(self, groove: int) -> Nod | None:
        """The nod that belongs to `groove` in this session."""
        return self._bound.get(groove)

    def add(self, nod: Nod) -> Nod:
        """Keep a stored nod (from the profile), as the most recent, unbound."""
        self._order += 1
        nod.order = self._order
        nod.rng = self._rng()
        self._nods.append(nod)
        self._cap()
        return nod

    def nod(
        self,
        groove: int,
        prototype: Pattern,
        features: Features,
        variation: str,
        loop: str = "",
        day: str = "",
    ) -> Nod:
        """A nod for the tracker's `groove`, whose prototype and features are now
        `prototype` and `features`: a later nod replaces the variation and moves the
        prototype. Other nods whose prototypes match it merge into it."""
        self._order += 1
        nod = self._bound.get(groove)
        if nod is None:
            nod = Nod(prototype, features, variation, rng=self._rng())
            self._nods.append(nod)
            self._bound[groove] = nod
        else:
            nod.nods += 1
        nod.prototype, nod.features, nod.variation = prototype, features, variation
        nod.loop, nod.last, nod.order = loop, day, self._order
        for other in [n for n in self._nods if n is not nod]:
            if similarity(other.prototype, prototype) >= self.return_at:
                self._merge(other, nod)
        self._cap()
        return nod

    def match(self, groove: int, first: Pattern, second: Pattern) -> Nod | None:
        """The nod of the tracker's `groove`, confirmed now with its two starting bars
        `first` and `second`: the nod it already has in this session, else the stored
        nod of no groove yet whose prototype both bars reach on average at `RETURN`
        (the best; ties the most recent), which then belongs to `groove`."""
        if groove in self._bound:
            return self._bound[groove]
        taken = {id(n) for n in self._bound.values()}
        best: Nod | None = None
        best_score = self.return_at
        for nod in self.nods:
            if id(nod) in taken:
                continue
            score = (similarity(first, nod.prototype) + similarity(second, nod.prototype)) / 2
            if score >= best_score and (best is None or score > best_score):
                best, best_score = nod, score
        if best is not None:
            self._bound[groove] = best
        return best

    def group(
        self, groove: int, prototype: Pattern, distance: float = GROUP_DISTANCE
    ) -> Nod | None:
        """The nod nearest to `prototype` by `descriptor_distance` within `distance`,
        other than the nod of `groove` itself (ties: the most recent)."""
        own = self._bound.get(groove)
        best: Nod | None = None
        best_distance = distance
        for nod in self.nods:
            if nod is own:
                continue
            d = descriptor_distance(prototype, nod.prototype)
            if d <= best_distance and (best is None or d < best_distance):
                best, best_distance = nod, d
        return best

    def draw(self, nod: Nod) -> bool:
        """Whether a section of a groove in `nod`'s group plays it: `GROUP_SHARE`."""
        return nod.rng.random() < GROUP_SHARE

    def _rng(self) -> random.Random:
        self._made += 1
        return random.Random(None if self.seed is None else f"{self.seed}:{self._made}")

    def _merge(self, old: Nod, new: Nod) -> None:
        new.nods += old.nods
        self._nods.remove(old)
        for groove, nod in list(self._bound.items()):
            if nod is old:
                self._bound[groove] = new

    def _cap(self) -> None:
        while len(self._nods) > self.nods_max:
            oldest = min(self._nods, key=lambda n: n.order)
            self._nods.remove(oldest)
            for groove in [g for g, n in self._bound.items() if n is oldest]:
                del self._bound[groove]
