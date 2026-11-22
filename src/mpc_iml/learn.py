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

`LoopLearner` learns which loop a part plays (#196 PR 5, `ensemble`'s `learn-loops
1`): per context a weight per loop name, 0 for the loop the musician selected and
`LOOP_PRIOR` for the others, plus what likes added. A (loop, variation) pair weighs
the sum of its loop's weight and its variation's `Learner` weight, so the loop and
the variation are drawn apart: the loop once per phrase (`choose`), the variation
each bar. `like` adds `STEP` to the loop heard and `forget` moves the added weight
`FORGET` of the way back to 0. Weights are kept by loop name, so a loop that leaves
the choice space (its file is gone) keeps them and finds them again when it comes back.

`Demonstrations` is the demonstration learner (B, Wekinator style): the musician
marks the wanted variation while playing (`WANTS`, `auto` marks nothing), and each
bar played with a wanted variation adds an `Example`, the bar's `features` (the
numbers behind its context, named in `FEATURES`) mapped to that variation. A model
(`mpc_iml.model.Model`, by default `sklearn_backend.Tree`, a shallow decision tree)
is trained on the examples; with fewer than `MIN_EXAMPLES`, or only one variation
among them, `predict` gives `None`. Until a model is trained, `choose` plays the
marked contexts (#215): a bar whose context (`feature_context`) is that of one or
more examples gives their most common variation (ties: the one marked latest), and
`None` elsewhere, where the rules play. `plays` says which (`tree`, `marked
contexts` or `rules`).

What was learned is saved as a profile file by `mpc_iml.learn_profile`, which also
holds `python -m mpc_iml.learn show [<profile>]` and `summary <log>` (the per-bar
log of `mpc_iml.learn_log`).
"""

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from mpc_iml.bass import BASS_VARIATIONS
from mpc_iml.clock import GridHit
from mpc_iml.melody import MELODY_VARIATIONS
from mpc_iml.model import Model, ModelFactory

__all__ = [
    "ARMS",
    "BACKBEAT",
    "CONTEXTS",
    "DENSE_HITS",
    "DENSE_KICKS",
    "FEATURES",
    "FORGET",
    "GRACE",
    "LOOP_PRIOR",
    "MIN_EXAMPLES",
    "PARTS",
    "PRIOR",
    "SPARSE_HITS",
    "STEP",
    "TEMPERATURE",
    "WANTS",
    "Demonstrations",
    "Example",
    "Learner",
    "LoopLearner",
    "bass_context",
    "context",
    "feature_context",
    "features",
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
LOOP_PRIOR = -1.0
"""The starting weight of a loop the musician did not select (the selected one: 0);
with two loops the selected one starts at about 90%, with four at about 70%."""
GRACE = 4
"""A like in the first `GRACE` steps of a bar refers to the bar before."""
WANTS: Mapping[str, tuple[str, ...]] = {p: ("auto", *ARMS[p]) for p in PARTS}
"""What the musician can mark as wanted, in the order a pad cycles them; `auto`
marks nothing and plays the model's prediction."""
MIN_EXAMPLES = 4
"""Examples a part needs before its model is trained."""
FEATURES: Mapping[str, tuple[str, ...]] = {
    "bass": ("kicks", "off-grid kicks", "backbeat"),
    "melody": ("hits", "hats", "odd hats"),
}
"""The names of each part's `features`, in order."""


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


def features(part: str, drums: Sequence[GridHit], roles: Sequence[str]) -> list[float]:
    """The numbers behind the context of `part` for a bar with the hits `drums`
    (`FEATURES`): for the bass the kicks, the kicks off the quarters and the
    backbeat (1 or 0); for the melody the hits, the hats and the hats on odd steps."""
    if part == "bass":
        kicks = _steps(drums, roles, "kick")
        backbeat = set(_steps(drums, roles, "snare")).issuperset(BACKBEAT)
        return [len(kicks), sum(1 for step in kicks if step % 4), float(backbeat)]
    hats = _steps(drums, roles, "hat")
    return [len(drums), len(hats), sum(1 for step in hats if step % 2)]


def feature_context(part: str, values: Sequence[float]) -> str:
    """The context of `part` whose numbers are `values` (`features`), so
    `feature_context(part, features(part, drums, roles)) == context(part, drums, roles)`."""
    a, b, c = values
    if part == "bass":
        kick = "none" if a == 0 else "dense" if a >= DENSE_KICKS else "push" if b else "grid"
        return f"{kick}/{'beat' if c else '-'}"
    density = "sparse" if a <= SPARSE_HITS else "dense" if a >= DENSE_HITS else "mid"
    return f"{density}/{'none' if b == 0 else '16ths' if c else '8ths'}"


def rule_choice(part: str, context: str) -> str:
    """The variation the #158 rules choose in `context` of `part`."""
    a, b = context.split("/")
    if part == "bass":
        return {"dense": "drive", "push": "push"}.get(a, "home")
    if a == "dense" or b == "16ths":
        return "busy"
    return "open" if a == "sparse" else "home"


def _probabilities(weights: Mapping[str, float]) -> dict[str, float]:
    """The softmax of `weights` at `TEMPERATURE`."""
    top = max(weights.values())
    exp = {arm: math.exp((w - top) / TEMPERATURE) for arm, w in weights.items()}
    total = sum(exp.values())
    return {arm: e / total for arm, e in exp.items()}


def _draw(rng: random.Random, probabilities: Mapping[str, float]) -> str:
    """One draw from `rng` among `probabilities` (in their order)."""
    draw = rng.random()
    total = 0.0
    arms = list(probabilities)
    for arm in arms:
        total += probabilities[arm]
        if draw < total:
            return arm
    return arms[-1]


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
        return _probabilities(self._weights[context])

    def choose(self, context: str) -> str:
        """Draw the arm to play in `context` (one draw from the generator)."""
        return _draw(self._rng, self.probabilities(context))

    def table(self) -> dict[str, dict[str, float]]:
        """Every context's weights (a copy), for the profile."""
        return {c: dict(w) for c, w in self._weights.items()}

    def load(self, table: Mapping[str, Mapping[str, float]]) -> None:
        """Take the weights of `table` (as `table` gives them); a context it lacks
        starts from the rules. `ValueError` for an unknown context or arm, or a missing arm."""
        weights = {c: self.prior(c) for c in CONTEXTS[self.part]}
        for context, row in table.items():
            if context not in weights or set(row) != set(self.arms):
                raise ValueError(f"not a {self.part} context with its arms: {context}")
            weights[context] = {arm: float(row[arm]) for arm in self.arms}
        self._weights = weights

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


class LoopLearner:
    """The loop learner of one part (module docstring): which of `loops` to play in a
    context, starting from the loop the musician selected. Not thread-safe;
    `ensemble` holds its lock."""

    def __init__(self, part: str, rng: random.Random) -> None:
        self.part = part
        self._rng = rng
        self._added: dict[str, dict[str, float]] = {}

    def weights(self, context: str, loops: Sequence[str], selected: str) -> dict[str, float]:
        """The weight of each of `loops` in `context`, with `selected` selected."""
        added = self._added.get(context, {})
        return {
            name: (0.0 if name == selected else LOOP_PRIOR) + added.get(name, 0.0) for name in loops
        }

    def probabilities(self, context: str, loops: Sequence[str], selected: str) -> dict[str, float]:
        """The probability `choose` gives each of `loops` in `context`."""
        return _probabilities(self.weights(context, loops, selected))

    def choose(self, context: str, loops: Sequence[str], selected: str) -> str:
        """Draw the loop to play in `context` among `loops` (one draw)."""
        return _draw(self._rng, self.probabilities(context, loops, selected))

    def top(self, context: str, loops: Sequence[str], selected: str) -> str:
        """The loop with the highest weight in `context`; `selected` on a tie."""
        weights = self.weights(context, loops, selected)
        return max(loops, key=lambda name: (weights[name], name == selected))

    def like(self, context: str, loop: str) -> None:
        """The musician liked the loop `loop` played in `context`."""
        row = self._added.setdefault(context, {})
        row[loop] = row.get(loop, 0.0) + STEP

    def forget(self) -> None:
        """Move every added weight `FORGET` of the way back to 0."""
        for row in self._added.values():
            for name, added in row.items():
                row[name] = added * (1 - FORGET)

    def reset(self) -> None:
        """Forget everything learned: back to the selected loop."""
        self._added = {}

    def table(self) -> dict[str, dict[str, float]]:
        """What likes added, per context and loop name (a copy), for the profile."""
        return {c: dict(row) for c, row in self._added.items() if row}

    def load(self, table: Mapping[str, Mapping[str, float]]) -> None:
        """Take what `table` added (as `table` gives it). `ValueError` for an unknown
        context or a loop name that is not a string."""
        added: dict[str, dict[str, float]] = {}
        for context, row in table.items():
            if context not in CONTEXTS[self.part] or not all(isinstance(n, str) for n in row):
                raise ValueError(f"not a {self.part} context with loop names: {context}")
            added[context] = {name: float(value) for name, value in row.items()}
        self._added = added


@dataclass(frozen=True)
class Example:
    """One demonstration: in `bar`, drums with these `features` wanted `label`."""

    part: str
    features: tuple[float, ...]
    label: str
    bar: int


def _tree() -> Model:
    from mpc_iml.sklearn_backend import Tree

    return Tree()


class Demonstrations:
    """The demonstration learner of one part: its examples and the model trained on
    them (module docstring). Not thread-safe; `ensemble` holds its lock."""

    def __init__(self, part: str, factory: ModelFactory = _tree) -> None:
        self.part = part
        self.arms = ARMS[part]
        self.examples: list[Example] = []
        self._factory = factory
        self._model: Model | None = None

    @property
    def trained(self) -> bool:
        """Whether a model is trained, so `predict` gives a variation."""
        return self._model is not None

    def add(self, example: Example) -> None:
        """Keep `example` (of this part, with one of its variations); `train` uses it."""
        if example.part != self.part or example.label not in self.arms:
            raise ValueError(f"not an example of the {self.part}: {example}")
        self.examples.append(example)

    def train(self) -> bool:
        """Train a new model on the examples; `True` when one is trained. With fewer
        than `MIN_EXAMPLES`, or one variation among them, there is none."""
        labels = {e.label for e in self.examples}
        if len(self.examples) < MIN_EXAMPLES or len(labels) < 2:
            self._model = None
            return False
        model = self._factory()
        model.fit(
            [list(e.features) for e in self.examples],
            [[float(self.arms.index(e.label) + 1)] for e in self.examples],
        )
        self._model = model
        return True

    def predict(self, features: Sequence[float]) -> str | None:
        """The variation the model wants for `features`; `None` without a model."""
        if self._model is None:
            return None
        number = round(self._model.predict(list(features))[0])
        return self.arms[min(max(number, 1), len(self.arms)) - 1]

    def marked(self, context: str) -> str | None:
        """The most common variation of the examples in `context` (ties: the one
        whose latest example is the latest); `None` when no example is in it."""
        counts: dict[str, int] = {}
        latest: dict[str, int] = {}
        for index, e in enumerate(self.examples):
            if feature_context(self.part, e.features) == context:
                counts[e.label] = counts.get(e.label, 0) + 1
                latest[e.label] = index
        if not counts:
            return None
        return max(counts, key=lambda label: (counts[label], latest[label]))

    def choose(self, features: Sequence[float]) -> str | None:
        """What `auto` plays for `features`: the model's prediction, or before a
        model is trained the marked context's variation (`marked`); `None` for the
        rules."""
        if self._model is not None:
            return self.predict(features)
        return self.marked(feature_context(self.part, features))

    @property
    def plays(self) -> str:
        """What `choose` uses: `tree`, `marked contexts` (examples but no model) or
        `rules` (no examples)."""
        if self._model is not None:
            return "tree"
        return "marked contexts" if self.examples else "rules"

    def rules(self) -> str | None:
        """The trained model as rules (`sklearn_backend.Tree.rules`, named by
        `FEATURES` and the variations); `None` without a model or for one without rules."""
        rules = getattr(self._model, "rules", None)
        return None if rules is None else str(rules(FEATURES[self.part], self.arms))

    def reset(self) -> None:
        """Forget the examples and the model: back to the rules."""
        self.examples = []
        self._model = None


if __name__ == "__main__":
    from mpc_iml.learn_profile import main

    raise SystemExit(main())
