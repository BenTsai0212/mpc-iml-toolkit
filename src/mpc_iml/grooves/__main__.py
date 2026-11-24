"""List the drummer's grooves in a recording: `python -m mpc_iml.grooves rec.jsonl`.

Reads a recording made with `python -m mpc_iml.record --clock` and runs the groove
tracker over its complete bars (`mpc_iml.grooves.offline`). Prints the sections (the
bars of each groove with its fills, free bars, gaps with no drums), then each groove
with its prototype as a 16-step grid per role and its mean features. `--json` prints
the `mpc-iml-grooves` document instead. The thresholds can be tried here only; live
they are fixed (RFC 0005 allows at most two controls to adjust while playing).

`--group-distance` (#250) adds the groups that `learn-group` would find at that
distance (`GROUP_DISTANCE` when given no value), each groove's rhythm descriptors with
its nearest other groove, and the spread of each descriptor over the grooves, so the
fixed scale and threshold can be checked against recorded sessions.
"""

import argparse
import json
import statistics
import sys
from collections.abc import Sequence

from mpc_iml.grooves import (
    FREE_BARS,
    GROUP_DISTANCE,
    GROUP_SCALE,
    PART_ROLES,
    RETURN,
    SIMILAR,
    STEPS,
    Descriptors,
    Groove,
    Tracker,
    descriptor_distance,
    rhythm_descriptors,
)
from mpc_iml.grooves.offline import Bar, Result, Section, descriptor_groups, document, track
from mpc_iml.recording import RecordingFormatError, read_recording

LABELS = {
    "groove": "groove {groove}",
    "free": "free",
    "none": "no groove",
    "silent": "no drums",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.grooves",
        description="List the grooves of a recording with MIDI clock.",
    )
    parser.add_argument("path", help="a recording made with `python -m mpc_iml.record --clock`")
    parser.add_argument("--json", action="store_true", help="print the mpc-iml-grooves document")
    parser.add_argument(
        "--similar",
        type=float,
        default=SIMILAR,
        help=f"similarity that continues or starts a groove (default: {SIMILAR})",
    )
    parser.add_argument(
        "--return",
        dest="return_at",
        type=float,
        default=RETURN,
        help=f"similarity at which a groove takes an earlier id (default: {RETURN})",
    )
    parser.add_argument(
        "--free-bars",
        type=int,
        default=FREE_BARS,
        help=f"fills in a row after which the bars are free (default: {FREE_BARS})",
    )
    parser.add_argument(
        "--group-distance",
        type=float,
        nargs="?",
        const=GROUP_DISTANCE,
        help=f"also list the groups at this descriptor distance (default: {GROUP_DISTANCE})",
    )
    parser.add_argument(
        "--beats-per-bar", type=int, default=4, help="quarter notes per bar (only 4)"
    )
    return parser


def grid(steps: frozenset[int]) -> str:
    """`x` for a step with a hit, `.` without, a space every 4 steps."""
    cells = "".join("x" if s in steps else "." for s in range(STEPS))
    return " ".join(cells[i : i + 4] for i in range(0, STEPS, 4))


def span(bars: Sequence[Bar], s: Section) -> str:
    first, last = bars[s.first], bars[s.last]
    where = f"bar {first.bar}" if s.length == 1 else f"bars {first.bar}-{last.bar}"
    return f"take {first.take}  {where}"


def format_section(bars: Sequence[Bar], s: Section) -> str:
    unit = "bar" if s.length == 1 else "bars"
    line = f"{span(bars, s)}  {LABELS[s.kind].format(groove=s.groove)}  ({s.length} {unit})"
    if s.fills:
        line += "  fills: " + ", ".join(str(bars[i].bar) for i in s.fills)
    return line


def format_groove(g: Groove) -> list[str]:
    lines = [f"groove {g.id}: {g.bars} bars"]
    lines += [f"  {name:<5} {grid(g.prototype.role(name))}" for name in PART_ROLES]
    values = "  ".join(f"{k} {v:.2f}" for k, v in g.features.as_dict().items())
    return [*lines, f"  {values}"]


def format_result(result: Result) -> list[str]:
    lines = [format_section(result.bars, s) for s in result.sections]
    for g in result.grooves:
        lines += ["", *format_groove(g)]
    return lines


def values(d: Descriptors | dict[str, float]) -> str:
    items = d.as_dict() if isinstance(d, Descriptors) else d
    return "  ".join(f"{k} {v:.2f}" for k, v in items.items())


def format_groups(grooves: Sequence[Groove], distance: float) -> list[str]:
    """The groups at `distance`, each groove's descriptors with its nearest other
    groove, and the spread (population standard deviation) over the grooves."""
    lines = [f"groups at distance {distance:.2f}  (scale: {values(GROUP_SCALE)})"]
    for n, ids in enumerate(descriptor_groups(grooves, distance), 1):
        unit = "groove" if len(ids) == 1 else "grooves"
        lines.append(f"  group {n}: {unit} " + ", ".join(str(i) for i in ids))
    found = [rhythm_descriptors(g.prototype) for g in grooves]
    for g, d in zip(grooves, found, strict=True):
        line = f"groove {g.id}  {values(d)}"
        others = [
            (descriptor_distance(d, e), h.id)
            for h, e in zip(grooves, found, strict=True)
            if h is not g
        ]
        if others:
            near, other = min(others)
            line += f"  nearest: groove {other} ({near:.2f})"
        lines.append(line)
    if len(found) > 1:
        spread = {
            name: statistics.pstdev(d.as_dict()[name] for d in found)
            for name in GROUP_SCALE.as_dict()
        }
        lines.append(f"spread: {values(spread)}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.beats_per_bar != 4:
        print("error: only 4/4 (--beats-per-bar 4) is supported", file=sys.stderr)
        return 2
    if args.free_bars < 1:
        print("error: --free-bars must be at least 1", file=sys.stderr)
        return 2
    if args.group_distance is not None and (args.json or args.group_distance < 0):
        print("error: --group-distance is at least 0 and not with --json", file=sys.stderr)
        return 2
    try:
        recording = read_recording(args.path)
        result = track(recording.events, Tracker(args.similar, args.return_at, args.free_bars))
    except (OSError, RecordingFormatError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(document(result, str(args.path)), indent=2))
    else:
        lines = format_result(result)
        if args.group_distance is not None:
            lines += ["", *format_groups(result.grooves, args.group_distance)]
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
