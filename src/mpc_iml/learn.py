"""The drums of a bar as a small readable context per part, and the bar a nod refers
to (RFC 0005 step 8, #196, #250). No I/O.

The #158 rules choose each part's variation from the drums of the bar that ended
(`bass.bass_variation`, `melody.melody_variation`). This module describes that bar
as a small readable context per part, for the learn log and the reply `learned`
(`CONTEXTS`), written as `<a>/<b>`:

- bass (`bass_context`): the kicks, `none`, `grid` (all on quarters), `push` (a kick
  off the quarters) or `dense` (`DENSE_KICKS` or more), and the backbeat, `beat`
  (snares on both `BACKBEAT` steps) or `-`. For example `push/beat`.
- melody (`melody_context`): the hits, `sparse` (`SPARSE_HITS` or fewer), `mid` or
  `dense` (`DENSE_HITS` or more), and the hats, `none`, `8ths` (only even steps) or
  `16ths` (a hat on an odd step). For example `mid/8ths`.

The rules' choice is a function of the context (`rule_choice`). `liked_bar` is which
bar a nod refers to: the bar playing, or the bar before when pressed in its first
beat.

Learning by likes per context (`Learner`, `LoopLearner`) and by demonstrations
(`Demonstrations`, #196) was replaced by the nod (#250, `grooves.nods`). What was
learned is saved as a profile file by `mpc_iml.learn_profile`, which also holds
`python -m mpc_iml.learn show [<profile>]` and `summary <log>` (the per-bar log of
`mpc_iml.learn_log`).
"""

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
    "GRACE",
    "PARTS",
    "SPARSE_HITS",
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

GRACE = 4
"""A nod in the first `GRACE` steps of a bar refers to the bar before."""


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
    """The bar a nod pressed at `step` of `bar` refers to: in the first beat, the
    bar before (reaction time), else the bar playing."""
    return bar - 1 if step < GRACE and bar > 0 else bar


if __name__ == "__main__":
    from mpc_iml.learn_profile import main

    raise SystemExit(main())
