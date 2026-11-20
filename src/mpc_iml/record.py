"""Record live MPC input to a file: `uv run python -m mpc_iml.record out.jsonl --duration 5`.

Opens the live source, writes an ADR 0002 recording and stops after `--duration`
seconds or on Ctrl-C, with the file closed properly. `--firmware` and
`--full-level`/`--no-full-level` are written to the header as declared.

`--clock` also records MIDI clock from a DAW (#139), off by default: it opens the
virtual input `mpc-iml clock` (or `--clock-port`, as in the engine, ADR 0008) and
injects Timing Clock, Start, Continue, Stop and Song Position Pointer into the live
source, so pad and clock messages share one time base in one file. They are written
as raw `midi` events; the recording format does not change. Other messages on the
clock port are dropped. Pad events are recorded even when no clock arrives.

With `--clock`, standard error says when the first clock message arrives, says once
after `CLOCK_WAIT` seconds that it is still waiting if none has, and says when the
DAW's transport stops (Stop) and plays again (Start or Continue) (#160).
"""

import argparse
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from typing import Any

from mpc_iml.events import Event, RawMidiEvent
from mpc_iml.recording import Header
from mpc_iml.sources import (
    CLOCK_BYTES,
    DEFAULT_PORT_MATCH,
    ClockInput,
    ClockInputBackend,
    LiveSource,
    MidiInputBackend,
    PortNotFoundError,
    RtMidiClockBackend,
    record,
)

CLOCK_WAIT = 2.0
"""Seconds after the start to say once that MIDI clock has not arrived yet."""

START, CONTINUE, STOP = 0xFA, 0xFB, 0xFC


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
    parser.add_argument(
        "--clock",
        action="store_true",
        help="also record MIDI clock from a DAW on a virtual input 'mpc-iml clock'",
    )
    parser.add_argument(
        "--clock-port",
        default=None,
        help="record MIDI clock from the first input port containing this text"
        " (e.g. IAC) instead; implies --clock",
    )
    return parser


def is_clock(data: bytes) -> bool:
    """True for the clock messages `--clock` records (`CLOCK_BYTES`)."""
    return bool(data) and data[0] in CLOCK_BYTES


class ClockReport:
    """Counts the recorded clock messages and prints what the musician needs to know:
    when clock first arrives, and when the transport stops and plays again (#160)."""

    def __init__(self, port_name: str | None) -> None:
        self.port_name = port_name
        self.count = 0
        self.stopped = False

    def see(self, data: bytes) -> None:
        if not is_clock(data):
            return
        self.count += 1
        if self.count == 1:
            print(f"MIDI clock: receiving from {self.port_name!r}.", file=sys.stderr)
        status = data[0]
        if status == STOP and not self.stopped:
            self.stopped = True
            print("MIDI clock: Stop received; pad events are still recorded.", file=sys.stderr)
        elif status in (START, CONTINUE) and self.stopped:
            self.stopped = False
            name = "Start" if status == START else "Continue"
            print(f"MIDI clock: {name} received; playing again.", file=sys.stderr)

    def count_in(self, events: Iterable[Event]) -> Iterator[Event]:
        for event in events:
            if isinstance(event, RawMidiEvent):
                self.see(event.data)
            yield event


def main(
    argv: Sequence[str] | None = None,
    backend: MidiInputBackend | None = None,
    clock_backend: Callable[[], ClockInputBackend] = RtMidiClockBackend,
) -> int:
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
        clock_input: ClockInput | None = None
        if args.clock or args.clock_port is not None:

            def on_clock(data: bytes) -> None:
                if is_clock(data):
                    source.inject(data)

            clock_input = ClockInput(on_clock, args.clock_port, clock_backend)
            try:
                clock_input.open()
            except PortNotFoundError as error:
                print(f"error: {error}", file=sys.stderr)
                return 1
        try:
            return _record(args, source, clock_input, header)
        finally:
            if clock_input is not None:
                clock_input.close()


def _record(
    args: argparse.Namespace, source: LiveSource, clock_input: ClockInput | None, header: Header
) -> int:
    until = f"for {args.duration} s" if args.duration is not None else "until Ctrl-C"
    print(f"Recording from {source.port_name!r} {until}...", file=sys.stderr)
    if clock_input is None:
        count = record(source.events(duration=args.duration), args.path, header)
        print(f"Wrote {count} events to {args.path}", file=sys.stderr)
        return 0
    print(f"Recording MIDI clock from {clock_input.port_name!r}.", file=sys.stderr)
    report = ClockReport(clock_input.port_name)
    warned = False

    def warn_once() -> bool:
        nonlocal warned
        if not warned and report.count == 0 and source.now() >= CLOCK_WAIT:
            warned = True
            print(
                f"MIDI clock: waiting for {report.port_name!r} (pad events are being "
                "recorded). In Live, turn on Sync for this port "
                "(Settings > Link, Tempo & MIDI) and press Play.",
                file=sys.stderr,
            )
        return False

    events = report.count_in(source.events(duration=args.duration, stop=warn_once))
    count = record(events, args.path, header)
    print(f"Wrote {count} events ({report.count} clock messages) to {args.path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
