"""The profile of what `ensemble` learned ("my band", #196, RFC 0005 step 8).

One JSON file, `<data folder>/learn/ensemble.json` (`PROFILE`), written atomically.
Format version 2 (#250, ADR 0009 "Amendment: learning by groove", "The profile"):

    {"format": "mpc-iml-ensemble-profile", "format_version": 2, "toolkit": "0.1.0",
     "settings": {"progression": "minor-two", "bass-loop": "boom", "follow-by": "groove"},
     "nods": [{"prototype": {"kick": [0, 7, 10], "snare": [4, 12], "hat": [0, 2, 4]},
               "features": {"kicks": 3, "double_kicks": 0, "late_kicks": 1,
                            "snare_off": 0, "hats": 3, "hat_presence": 1},
               "part": "bass", "variation": "push", "nods": 3, "loop": "boom",
               "last": "2026-11-24"}]}

`nods` are the nods kept (`grooves.nods.NodMemory`), the most recent first; the
prototype has the steps per role as in the groove group file of #249
(`grooves.groups.steps`, so a group in that file can be matched to a stored nod
without a new format). A version 2 file written before `learn likes` and `learn
demo` were removed (#250) may also have `weights`, `examples` and `loops`; reading
ignores them and the next save leaves them out.
`settings` records what the profile was learned with; reading does not apply them.
The file stays on the musician's machine: it is never committed or uploaded (RFC
0005 Scope rules).

A version 1 profile (`likes` and `demo`, #196) raises `OldProfile`: `ensemble`
renames it once to `learn/ensemble-v1.json` (`OLD_PROFILE`) and starts with no nods.

`python -m mpc_iml.learn show [<profile>]` prints it (default
`./mpc-iml-data/learn/ensemble.json`): each nod with its prototype as a 16-step grid
per role, its variation, count and date.
`python -m mpc_iml.learn summary <log>` prints a per-bar log (`learn_log.summary`).
"""

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mpc_iml import __version__
from mpc_iml.grooves import PART_ROLES, STEPS, Features, Pattern
from mpc_iml.grooves.nods import Nod, NodMemory
from mpc_iml.learn import ARMS, PARTS
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
    """What a profile file holds: the settings it was learned with and the nods, the
    most recent first."""

    settings: Mapping[str, str]
    nods: Sequence[Nod] = ()


def write_profile(path: Path, settings: Mapping[str, str], nods: NodMemory) -> None:
    """Write the profile of the nods kept in `nods` to `path` atomically (a partial
    file, then a rename), making its folder."""
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
            for n in nods.nods
        ],
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
    settings = {str(k): str(v) for k, v in dict(data.get("settings", {})).items()}
    if not isinstance(data["nods"], list):
        raise ValueError(f"bad nods {data['nods']!r}")
    return Profile(settings, [_nod(n) for n in data["nods"]])


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


def apply_profile(profile: Profile, nods: NodMemory) -> None:
    """Load the nods of `profile` into `nods`, which forgets its nods first."""
    nods.reset()
    for nod in reversed(profile.nods):
        nods.add(replace(nod))


def show(profile: Profile) -> str:
    """The text `python -m mpc_iml.learn show` prints for `profile`."""
    lines = [f"nods: {len(profile.nods)}"]
    for nod in profile.nods:
        times = "nod" if nod.nods == 1 else "nods"
        lines.append(f"  {nod.part} {nod.variation}, {nod.nods} {times}, last {nod.last or '-'}")
        lines += [f"    {r:<5} {_grid(nod.prototype.role(r))}" for r in PART_ROLES]
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
