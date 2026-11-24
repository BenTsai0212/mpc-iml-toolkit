"""The profile of what `ensemble` learned ("my band", #196, RFC 0005 step 8).

One JSON file, `<data folder>/learn/ensemble.json` (`PROFILE`), written atomically.
Format version 2 (#250, ADR 0009 "Amendment: learning by groove", "The profile"):

    {"format": "mpc-iml-ensemble-profile", "format_version": 2, "toolkit": "0.1.0",
     "settings": {"progression": "minor-two", "bass-loop": "boom", "follow-by": "groove"},
     "nods": [{"prototype": {"kick": [0, 7, 10], "snare": [4, 12], "hat": [0, 2, 4]},
               "features": {"kicks": 3, "double_kicks": 0, "late_kicks": 1,
                            "snare_off": 0, "hats": 3, "hat_presence": 1},
               "part": "bass", "variation": "push", "nods": 3, "loop": "boom",
               "last": "2026-11-24"}],
     "weights": {"bass": {"push/beat": {"home": 0.0, "push": 1.5, "drive": 0.0}, ...},
                 "melody": {...}},
     "examples": [{"part": "bass", "features": [6, 2, 1], "label": "drive", "bar": 3}],
     "loops": {"bass": {"push/beat": {"walk": 1.0}}, "melody": {}}}

`nods` are the nods kept (`grooves.nods.NodMemory`), the most recent first; the
prototype has the steps per role as in the groove group file of #249
(`grooves.groups.steps`, so a group in that file can be matched to a stored nod
without a new format). `weights` are each `learn.Learner`'s table and `examples`
each `learn.Demonstrations`' examples; `loops` is what likes added to each
`learn.LoopLearner`'s loops, by loop name. These three are optional and stay only
while `learn likes` and `learn demo` exist (#250 removes them); no model is saved,
the trees are trained again from the examples when a profile is read (no pickle).
`settings` records what the profile was learned with; reading does not apply them.
The file stays on the musician's machine: it is never committed or uploaded (RFC
0005 Scope rules).

A version 1 profile (`likes` and `demo`, #196) raises `OldProfile`: `ensemble`
renames it once to `learn/ensemble-v1.json` (`OLD_PROFILE`) and starts with no nods.

`python -m mpc_iml.learn show [<profile>]` prints it (default
`./mpc-iml-data/learn/ensemble.json`): each nod with its prototype as a 16-step grid
per role, its variation, count and date; then per part, each context with the
rules' choice and the learned weights, `*` where the learned top choice differs,
what likes added to the loops, and the tree trained on the examples as rules.
`python -m mpc_iml.learn summary <log>` prints a per-bar log (`learn_log.summary`).
"""

import argparse
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from mpc_iml import __version__
from mpc_iml.grooves import PART_ROLES, STEPS, Features, Pattern
from mpc_iml.grooves.nods import Nod, NodMemory
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
from mpc_iml.learn_log import read_log, summary

__all__ = [
    "DEFAULT",
    "OLD_PROFILE",
    "PROFILE",
    "PROFILE_FORMAT",
    "PROFILE_VERSION",
    "OldProfile",
    "Profile",
    "apply_profile",
    "main",
    "read_profile",
    "show",
    "write_profile",
]

PROFILE_FORMAT = "mpc-iml-ensemble-profile"
PROFILE_VERSION = 2
PROFILE = Path("learn") / "ensemble.json"
"""The profile's path in the engine's data folder."""
OLD_PROFILE = Path("learn") / "ensemble-v1.json"
"""Where a version 1 profile is kept when it is read (#250)."""
_NOD_KEYS = ("prototype", "features", "part", "variation", "nods", "loop", "last")
DEFAULT = Path("mpc-iml-data") / PROFILE
"""The profile `show` reads without an argument (the data folder of `uv run mpc-iml`)."""


class OldProfile(ValueError):
    """The file is a version 1 profile (`likes` and `demo`, #196)."""


@dataclass(frozen=True)
class Profile:
    """What a profile file holds: the nods, the most recent first, and per part the
    weights, the examples and what likes added to the loops."""

    weights: Mapping[str, Mapping[str, Mapping[str, float]]]
    examples: Sequence[Example]
    settings: Mapping[str, str]
    loops: Mapping[str, Mapping[str, Mapping[str, float]]] = field(default_factory=dict)
    nods: Sequence[Nod] = ()


def write_profile(
    path: Path,
    learners: Mapping[str, Learner],
    demos: Mapping[str, Demonstrations],
    settings: Mapping[str, str],
    loops: Mapping[str, LoopLearner] | None = None,
    nods: NodMemory | None = None,
) -> None:
    """Write the profile of `learners`, `demos`, the loop learners `loops` and the
    nods kept in `nods` to `path` atomically (a partial file, then a rename), making
    its folder."""
    data = {
        "format": PROFILE_FORMAT,
        "format_version": PROFILE_VERSION,
        "toolkit": __version__,
        "settings": dict(settings),
        "nods": [
            {
                "prototype": {r: sorted(n.prototype.role(r)) for r in PART_ROLES},
                "features": n.features.as_dict(),
                "part": n.part,
                "variation": n.variation,
                "nods": n.nods,
                "loop": n.loop,
                "last": n.last,
            }
            for n in (nods.nods if nods is not None else ())
        ],
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
    """Read and check the profile at `path`. `OldProfile` for a version 1 profile,
    `ValueError` (with the reason) for a file that cannot be read or is not a version
    2 profile."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"{path}: {error}") from error
    if isinstance(data, dict) and data.get("format") == PROFILE_FORMAT:
        if data.get("format_version") == 1:
            raise OldProfile(f"{path}: profile version 1 (likes/demo)")
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
    nods = [_nod(n) for n in data["nods"]]
    return Profile(weights, examples, settings, loops, nods)


def _nod(data: Any) -> Nod:
    if not isinstance(data, dict) or set(data) != set(_NOD_KEYS):
        raise ValueError(f"bad nod {data!r}")
    if not isinstance(data["prototype"], dict) or set(data["prototype"]) != set(PART_ROLES):
        raise ValueError(f"bad prototype {data['prototype']!r}")
    prototype = Pattern(*(_steps(data["prototype"][r]) for r in PART_ROLES))
    names = Features().as_dict()
    if not isinstance(data["features"], dict) or set(data["features"]) != set(names):
        raise ValueError(f"bad features {data['features']!r}")
    features = Features(**{k: float(data["features"][k]) for k in names})
    count = data["nods"]
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise ValueError(f"bad count of nods {count!r}")
    part, variation, loop, last = (data[k] for k in ("part", "variation", "loop", "last"))
    if not all(isinstance(t, str) for t in (part, variation, loop, last)):
        raise ValueError(f"bad nod {data!r}")
    if part not in PARTS or variation not in ARMS[part]:
        raise ValueError(f"bad variation {part} {variation!r}")
    return Nod(prototype, features, variation, part=part, nods=count, loop=loop, last=last)


def _steps(value: Any) -> frozenset[int]:
    if not isinstance(value, list):
        raise ValueError(f"bad steps {value!r}")
    for s in value:
        if not isinstance(s, int) or isinstance(s, bool) or not 0 <= s < STEPS:
            raise ValueError(f"bad step {s!r}")
    return frozenset(value)


def apply_profile(
    profile: Profile,
    learners: Mapping[str, Learner],
    demos: Mapping[str, Demonstrations],
    loops: Mapping[str, LoopLearner] | None = None,
    nods: NodMemory | None = None,
) -> None:
    """Load `profile` into `learners`, `demos`, the loop learners `loops` and `nods`
    (which forgets its nods first), training the trees again."""
    if nods is not None:
        nods.reset()
        for nod in reversed(profile.nods):
            nods.add(replace(nod))
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
    lines = [f"nods: {len(profile.nods)}"]
    for nod in profile.nods:
        times = "nod" if nod.nods == 1 else "nods"
        lines.append(f"  {nod.part} {nod.variation}, {nod.nods} {times}, last {nod.last or '-'}")
        lines += [f"    {r:<5} {_grid(nod.prototype.role(r))}" for r in PART_ROLES]
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


def _grid(on: frozenset[int]) -> str:
    """`x` for a step with a hit, `.` without, a space every 4 steps (as `python -m
    mpc_iml.grooves` prints a prototype)."""
    cells = "".join("x" if s in on else "." for s in range(STEPS))
    return " ".join(cells[i : i + 4] for i in range(0, STEPS, 4))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.learn", description="What ensemble learned (#196, #250)."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    shown = commands.add_parser("show", help="print a profile")
    shown.add_argument("profile", nargs="?", type=Path, default=DEFAULT)
    summed = commands.add_parser("summary", help="summarise a per-bar log (learn-log)")
    summed.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    if args.command == "summary":
        try:
            header, bars = read_log(args.log)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        print(summary(header, bars))
        return 0
    try:
        profile = read_profile(args.profile)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(show(profile))
    return 0
