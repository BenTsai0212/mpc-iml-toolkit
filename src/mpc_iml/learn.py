"""Learning which variation `ensemble` plays (RFC 0005 step 8, #196). No I/O.

The #158 rules choose each part's variation from the drums of the bar that ended
(`bass.bass_variation`, `melody.melody_variation`). This module describes that bar
as a small readable context per part and learns, per context, which variation the
musician wants. The rules give the starting point, so a learner that has learned
nothing plays close to them.

Contexts (`CONTEXTS`), written as `<a>/<b>`:

- bass (`bass_context`): the kicks, `none`, `grid` (all on quarters), `push` (a kick
  off the quarters) or `dense` (`DENSE_KICKS` or more), and the backbeat, `beat`
  (snares on both `BACKBEAT` steps) or `-`. For example `push/beat`.
- melody (`melody_context`): the hits, `sparse` (`SPARSE_HITS` or fewer), `mid` or
  `dense` (`DENSE_HITS` or more), and the hats, `none`, `8ths` (only even steps) or
  `16ths` (a hat on an odd step). For example `mid/8ths`.

The rules' choice is a function of the context (`rule_choice`), so the starting
weights are exactly today's rules.

`Learner` is the likes learner (a weighted softmax): per context a weight per arm
(a variation name), `PRIOR` for the rules' choice and 0 for the others. `choose`
draws an arm with probability proportional to `exp(weight / TEMPERATURE)` from its
own seeded generator, so the rules' choice has about 80% at the start (exploration).
`like` adds `STEP` to the arm that was heard in its context; `forget`, once per
phrase, moves every weight `FORGET` of the way back to its starting value, so a
context no longer liked drifts back to the rules. `liked_bar` is which bar a like
refers to: the bar playing, or the bar before when pressed in its first beat.
"""

import math
import random
from collections.abc import Mapping, Sequence

from mpc_iml.bass import BASS_VARIATIONS
from mpc_iml.clock import GridHit
from mpc_iml.melody import MELODY_VARIATIONS

__all__ = [
    "ARMS",
    "BACKBEAT",
    "CONTEXTS",
    "DENSE_HITS",
    "DENSE_KICKS",
    "FORGET",
    "GRACE",
    "PARTS",
    "PRIOR",
    "SPARSE_HITS",
    "STEP",
    "TEMPERATURE",
    "Learner",
    "bass_context",
    "context",
    "liked_bar",
    "melody_context",
    "rule_choice",
]

PARTS = ("bass", "melody")
ARMS: Mapping[str, tuple[str, ...]] = {"bass": BASS_VARIATIONS, "melody": MELODY_VARIATIONS}
"""What each part chooses from: its variations."""

DENSE_KICKS = 5
"""Kicks in a bar from which the bass rule plays `drive`."""
BACKBEAT = (4, 12)
"""The steps of the backbeat snares in a 16-step bar."""
SPARSE_HITS = 5
"""Hits in a bar up to which the melody rule plays `open`."""
DENSE_HITS = 14
"""Hits in a bar from which the melody rule plays `busy`."""

KICKS = ("none", "grid", "push", "dense")
SNARES = ("beat", "-")
DENSITIES = ("sparse", "mid", "dense")
HATS = ("none", "8ths", "16ths")
CONTEXTS: Mapping[str, tuple[str, ...]] = {
    "bass": tuple(f"{k}/{s}" for k in KICKS for s in SNARES),
    "melody": tuple(f"{d}/{h}" for d in DENSITIES for h in HATS),
}
"""Every context of each part, in order."""

PRIOR = 1.0
"""The starting weight of the rules' choice; the other arms start at 0."""
TEMPERATURE = 0.48
"""Softmax temperature: with 3 arms the rules' choice starts at about 80%."""
STEP = 0.5
"""What a like adds to the weight of the arm heard."""
FORGET = 0.05
"""How far each weight moves back to its starting value once per phrase."""
GRACE = 4
"""A like in the first `GRACE` steps of a bar refers to the bar before."""


def _steps(drums: Sequence[GridHit], roles: Sequence[str], role: str) -> list[int]:
    return [h.step for h in drums if roles[h.pad] == role]


def bass_context(drums: Sequence[GridHit], roles: Sequence[str]) -> str:
    """The bass context of a bar with the hits `drums` (pad roles `roles`)."""
    kicks = _steps(drums, roles, "kick")
    if not kicks:
        kick = "none"
    elif len(kicks) >= DENSE_KICKS:
        kick = "dense"
    else:
        kick = "push" if any(step % 4 for step in kicks) else "grid"
    snares = set(_steps(drums, roles, "snare"))
    return f"{kick}/{'beat' if snares.issuperset(BACKBEAT) else '-'}"


def melody_context(drums: Sequence[GridHit], roles: Sequence[str]) -> str:
    """The melody context of a bar with the hits `drums` (pad roles `roles`)."""
    hits = len(drums)
    density = "sparse" if hits <= SPARSE_HITS else "dense" if hits >= DENSE_HITS else "mid"
    hats = _steps(drums, roles, "hat")
    hat = "none" if not hats else "16ths" if any(step % 2 for step in hats) else "8ths"
    return f"{density}/{hat}"


def context(part: str, drums: Sequence[GridHit], roles: Sequence[str]) -> str:
    """The context of `part` (`bass` or `melody`) for a bar with the hits `drums`."""
    return bass_context(drums, roles) if part == "bass" else melody_context(drums, roles)


def rule_choice(part: str, context: str) -> str:
    """The variation the #158 rules choose in `context` of `part`."""
    a, b = context.split("/")
    if part == "bass":
        return {"dense": "drive", "push": "push"}.get(a, "home")
    if a == "dense" or b == "16ths":
        return "busy"
    return "open" if a == "sparse" else "home"


def liked_bar(bar: int, step: int) -> int:
    """The bar a like pressed at `step` of `bar` refers to: in the first beat, the
    bar before (reaction time), else the bar playing."""
    return bar - 1 if step < GRACE and bar > 0 else bar


class Learner:
    """The likes learner of one part: a weighted softmax per context, starting from
    the rules (module docstring). Not thread-safe; `ensemble` holds its lock."""

    def __init__(self, part: str, rng: random.Random) -> None:
        self.part = part
        self.arms = ARMS[part]
        self._rng = rng
        self._weights: dict[str, dict[str, float]] = {}
        self.reset()

    def prior(self, context: str) -> dict[str, float]:
        """The starting weights of `context`."""
        rule = rule_choice(self.part, context)
        return {arm: PRIOR if arm == rule else 0.0 for arm in self.arms}

    def reset(self) -> None:
        """Forget everything learned: back to the rules."""
        self._weights = {c: self.prior(c) for c in CONTEXTS[self.part]}

    def weights(self, context: str) -> dict[str, float]:
        """The weights of `context` (a copy)."""
        return dict(self._weights[context])

    def probabilities(self, context: str) -> dict[str, float]:
        """The probability `choose` gives each arm in `context`."""
        weights = self._weights[context]
        top = max(weights.values())
        exp = {arm: math.exp((w - top) / TEMPERATURE) for arm, w in weights.items()}
        total = sum(exp.values())
        return {arm: e / total for arm, e in exp.items()}

    def choose(self, context: str) -> str:
        """Draw the arm to play in `context` (one draw from the generator)."""
        draw = self._rng.random()
        total = 0.0
        probabilities = self.probabilities(context)
        for arm in self.arms:
            total += probabilities[arm]
            if draw < total:
                return arm
        return self.arms[-1]

    def like(self, context: str, arm: str) -> None:
        """The musician liked `arm` played in `context`."""
        self._weights[context][arm] += STEP

    def forget(self) -> None:
        """Move every weight `FORGET` of the way back to its starting value."""
        for context, weights in self._weights.items():
            prior = self.prior(context)
            for arm, weight in weights.items():
                weights[arm] = weight + FORGET * (prior[arm] - weight)

    def top(self, context: str) -> str:
        """The arm with the highest weight in `context`; the rules' choice on a tie."""
        rule = rule_choice(self.part, context)
        weights = self._weights[context]
        return max(self.arms, key=lambda arm: (weights[arm], arm == rule))

    def learned(self) -> list[str]:
        """`<part>:<context>><arm>` for each context, in order, whose top arm differs
        from the rules' choice."""
        return [
            f"{self.part}:{c}>{self.top(c)}"
            for c in CONTEXTS[self.part]
            if self.top(c) != rule_choice(self.part, c)
        ]
