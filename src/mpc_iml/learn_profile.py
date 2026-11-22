"""The profile of what `ensemble` learned ("my band", #196, RFC 0005 step 8).

One JSON file, `<data folder>/learn/ensemble.json` (`PROFILE`), written atomically:

    {"format": "mpc-iml-ensemble-profile", "format_version": 1, "toolkit": "0.1.0",
     "settings": {"progression": "minor-two", "bass-loop": "boom", "loop": "keys"},
     "weights": {"bass": {"push/beat": {"home": 0.0, "push": 1.5, "drive": 0.0}, ...},
                 "melody": {...}},
     "examples": [{"part": "bass", "features": [6, 2, 1], "label": "drive", "bar": 3}],
     "loops": {"bass": {"push/beat": {"walk": 1.0}}, "melody": {}}}

`weights` are each `learn.Learner`'s table and `examples` each
`learn.Demonstrations`' examples; `loops` (#196 PR 5, optional) is what likes added
to each `learn.LoopLearner`'s loops, by loop name, so it outlives a loop file that
is gone for a while; no model is saved, the trees are trained again
from the examples when a profile is read (no pickle). `settings` records what the
profile was learned with; reading does not apply them. The file stays on the
musician's machine: it is never committed or uploaded (RFC 0005 Scope rules).

`python -m mpc_iml.learn show [<profile>]` prints it (default
`./mpc-iml-data/learn/ensemble.json`): per part, each context with the rules'
choice and the learned weights, `*` where the learned top choice differs, what
likes added to the loops, and the tree trained on the examples as rules.
"""

import argparse
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mpc_iml import __version__
from mpc_iml.learn import (
    ARMS,
    CONTEXTS,
    FEATURES,
    PARTS,
    Demonstrations,
    Example,
    Learner,
    LoopLearner,
    rule_choice,
)

__all__ = [
    "DEFAULT",
    "PROFILE",
    "PROFILE_FORMAT",
    "PROFILE_VERSION",
    "Profile",
    "apply_profile",
    "main",
    "read_profile",
    "show",
    "write_profile",
]

PROFILE_FORMAT = "mpc-iml-ensemble-profile"
PROFILE_VERSION = 1
PROFILE = Path("learn") / "ensemble.json"
"""The profile's path in the engine's data folder."""
DEFAULT = Path("mpc-iml-data") / PROFILE
"""The profile `show` reads without an argument (the data folder of `uv run mpc-iml`)."""


@dataclass(frozen=True)
class Profile:
    """What a profile file holds: per part the weights, the examples and what likes
    added to the loops."""

    weights: Mapping[str, Mapping[str, Mapping[str, float]]]
    examples: Sequence[Example]
    settings: Mapping[str, str]
    loops: Mapping[str, Mapping[str, Mapping[str, float]]] = field(default_factory=dict)


def write_profile(
    path: Path,
    learners: Mapping[str, Learner],
    demos: Mapping[str, Demonstrations],
    settings: Mapping[str, str],
    loops: Mapping[str, LoopLearner] | None = None,
) -> None:
    """Write the profile of `learners`, `demos` and the loop learners `loops` to
    `path` atomically (a partial file, then a rename), making its folder."""
    data = {
        "format": PROFILE_FORMAT,
        "format_version": PROFILE_VERSION,
        "toolkit": __version__,
        "settings": dict(settings),
        "weights": {p: learners[p].table() for p in PARTS},
        "examples": [
            {"part": e.part, "features": list(e.features), "label": e.label, "bar": e.bar}
            for p in PARTS
            for e in demos[p].examples
        ],
        "loops": {p: loops[p].table() if loops else {} for p in PARTS},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.name}.partial")
    partial.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    os.replace(partial, path)


def read_profile(path: Path) -> Profile:
    """Read and check the profile at `path`. `ValueError` (with the reason) for a
    file that cannot be read or is not a version 1 profile."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    try:
        return _parse(data)
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"{path}: not a {PROFILE_FORMAT} {PROFILE_VERSION}: {error}") from error


def _parse(data: Any) -> Profile:
    if data["format"] != PROFILE_FORMAT or data["format_version"] != PROFILE_VERSION:
        raise ValueError(f"format {data['format']!r} version {data['format_version']!r}")
    weights = {p: dict(data["weights"].get(p, {})) for p in PARTS}
    for part, table in weights.items():
        Learner(part, random.Random(0)).load(table)
    examples = [
        Example(
            str(e["part"]), tuple(float(v) for v in e["features"]), str(e["label"]), int(e["bar"])
        )
        for e in data.get("examples", [])
    ]
    for example in examples:
        if example.part not in PARTS or len(example.features) != len(FEATURES[example.part]):
            raise ValueError(f"bad example {example}")
        Demonstrations(example.part).add(example)
    settings = {str(k): str(v) for k, v in dict(data.get("settings", {})).items()}
    loops = {p: dict(data.get("loops", {}).get(p, {})) for p in PARTS}
    for part, table in loops.items():
        LoopLearner(part, random.Random(0)).load(table)
    return Profile(weights, examples, settings, loops)


def apply_profile(
    profile: Profile,
    learners: Mapping[str, Learner],
    demos: Mapping[str, Demonstrations],
    loops: Mapping[str, LoopLearner] | None = None,
) -> None:
    """Load `profile` into `learners`, `demos` and the loop learners `loops`, training
    the trees again."""
    for part in PARTS:
        learners[part].load(profile.weights[part])
        if loops is not None:
            loops[part].load(profile.loops.get(part, {}))
        demos[part].reset()
        for example in profile.examples:
            if example.part == part:
                demos[part].add(example)
        demos[part].train()


def show(profile: Profile) -> str:
    """The text `python -m mpc_iml.learn show` prints for `profile`."""
    learners = {p: Learner(p, random.Random(0)) for p in PARTS}
    demos = {p: Demonstrations(p) for p in PARTS}
    apply_profile(profile, learners, demos)
    lines: list[str] = []
    for part in PARTS:
        arms = ARMS[part]
        lines.append(f"{part}: context, rule, weights {' '.join(arms)}")
        for context in CONTEXTS[part]:
            weights = learners[part].weights(context)
            rule = rule_choice(part, context)
            top = learners[part].top(context)
            mark = f" * learned {top}" if top != rule else ""
            values = " ".join(f"{weights[a]:.2f}" for a in arms)
            lines.append(f"  {context:<12} {rule:<6} {values}{mark}")
        for context, row in profile.loops.get(part, {}).items():
            added = " ".join(f"{name} +{value:.2f}" for name, value in row.items())
            lines.append(f"{part}: loops in {context}: {added}")
        count = len(demos[part].examples)
        rules = demos[part].rules()
        if rules is None:
            lines.append(f"{part}: {count} examples, no tree (the rules play)")
        else:
            lines.append(f"{part}: {count} examples, tree:")
            lines.extend(f"  {line}" for line in rules.rstrip().splitlines())
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.learn", description="What ensemble learned (#196)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    shown = commands.add_parser("show", help="print a profile")
    shown.add_argument("profile", nargs="?", type=Path, default=DEFAULT)
    args = parser.parse_args(argv)
    try:
        profile = read_profile(args.profile)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(show(profile))
    return 0
