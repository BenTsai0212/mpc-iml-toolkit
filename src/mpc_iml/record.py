"""Record live MPC input to a file: `uv run python -m mpc_iml.record out.jsonl --duration 5`.

Opens the live source, writes an ADR 0002 recording and stops after `--duration`
seconds or on Ctrl-C, with the file closed properly. `--firmware` and
`--full-level`/`--no-full-level` are written to the header as declared.
"""

import argparse
import sys
from collections.abc import Sequence
from typing import Any

from mpc_iml.recording import Header
from mpc_iml.sources import (
    DEFAULT_PORT_MATCH,
    LiveSource,
    MidiInputBackend,
    PortNotFoundError,
    record,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.record",
        description="Record live MIDI input from the MPC to a JSON Lines recording.",
    )
    parser.add_argument("path", help="output file, for example out.jsonl")
    parser.add_argument(
        "--duration", type=float, default=None, help="seconds to record (default: until Ctrl-C)"
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT_MATCH,
        help=f"open the first MIDI input port containing this text (default: {DEFAULT_PORT_MATCH})",
    )
    parser.add_argument("--firmware", default="", help="MPC firmware version, for example 1.3.0")
    parser.add_argument(
        "--full-level",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="whether the MPC's Full Level setting was on",
    )
    return parser


def main(argv: Sequence[str] | None = None, backend: MidiInputBackend | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.duration is not None and args.duration <= 0:
        print("error: --duration must be positive", file=sys.stderr)
        return 2
    settings: dict[str, Any] = {}
    if args.full_level is not None:
        settings["full_level"] = args.full_level
    header = Header(firmware=args.firmware, settings=settings)
    source = LiveSource(port_match=args.port, backend=backend)
    try:
        source.open()
    except PortNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    with source:
        until = f"for {args.duration} s" if args.duration is not None else "until Ctrl-C"
        print(f"Recording from {source.port_name!r} {until}...", file=sys.stderr)
        count = record(source.events(duration=args.duration), args.path, header)
    print(f"Wrote {count} events to {args.path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
