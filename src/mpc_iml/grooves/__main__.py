"""List the drummer's grooves in a recording: `python -m mpc_iml.grooves rec.jsonl`.

Reads a recording made with `python -m mpc_iml.record --clock` and runs the groove
tracker over its complete bars (`mpc_iml.grooves.offline`). Prints the sections (the
bars of each groove with its fills, free bars, gaps with no drums), then each groove
with its prototype as a 16-step grid per role and its mean features. `--json` prints
the `mpc-iml-grooves` document instead. The thresholds can be tried here only; live
they are fixed (RFC 0005 allows at most two controls to adjust while playing).
"""

import argparse
import json
import sys
from collections.abc import Sequence

from mpc_iml.grooves import FREE_BARS, PART_ROLES, RETURN, SIMILAR, STEPS, Groove, Tracker
from mpc_iml.grooves.offline import Bar, Result, Section, document, track
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


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.beats_per_bar != 4:
        print("error: only 4/4 (--beats-per-bar 4) is supported", file=sys.stderr)
        return 2
    if args.free_bars < 1:
        print("error: --free-bars must be at least 1", file=sys.stderr)
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
        print("\n".join(format_result(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
