"""Reference example: record, train and run the IML loop end to end (Issue #24).

A three-class demo on pad 1 (bank A, note 36): "rest" (no pads), "soft" (pad 1
held lightly) and "hard" (pad 1 held firmly), with the built-in 1-nearest-neighbour
`Classifier`. Three subcommands:

- `python -m mpc_iml.demo record examples.jsonl`: guided recording from the MPC;
  for each class it counts down, then records a few seconds between
  `example_start` / `example_end` markers, all in one ADR 0002 recording.
- `python -m mpc_iml.demo run examples.jsonl`: trains on the recording, then runs
  live from the MPC and sends the class number to `/wek/outputs`
  (`127.0.0.1:12000`). `--replay performance.jsonl` runs from a recording instead,
  without hardware.
- `python -m mpc_iml.demo listen`: a terminal receiver that shows each new class
  received on `/wek/outputs`.

The demo uses the feature set `mpc_iml.examples.played_features`: per pad, the
velocity while the pad is held (0 once released) and the pressure. The default 49 values keep a
pad's last velocity after release, so "rest" after playing would look like the
last hit.

The demo is also the built-in preset `demo` (`PRESET`), registered in the
`mpc_iml.presets` entry point group like any external preset.
"""

import argparse
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from mpc_iml import __version__
from mpc_iml.events import Event, ExampleEnd, ExampleStart
from mpc_iml.examples import played_features
from mpc_iml.loop import IMLLoop
from mpc_iml.osc import DEFAULT_HOST, OUTPUTS_ADDRESS, OUTPUTS_PORT, outputs_sender
from mpc_iml.presets import OscOutput, Preset
from mpc_iml.recording import Header, write_recording
from mpc_iml.sklearn_backend import Classifier
from mpc_iml.sources import (
    DEFAULT_PORT_MATCH,
    POLL_INTERVAL,
    ClockedSource,
    LiveSource,
    MidiInputBackend,
    PortNotFoundError,
    ReplaySource,
)

CLASSES = {"rest": 1, "soft": 2, "hard": 3}
"""Class numbers sent to `/wek/outputs`, fixed so receivers can rely on them."""

PROMPTS = {
    "rest": "Do not touch any pad.",
    "soft": "Press and hold pad 1 lightly, for example a light fingertip touch.",
    "hard": (
        "Press and hold pad 1 firmly, for example a firm press with the whole finger;"
        " make it clearly different from soft."
    ),
}

AFTER = {
    "soft": "Release pad 1 now.",
    "hard": "Release pad 1 now.",
}
"""Said when a class ends, before the next countdown starts."""

LABELS = {number: label for label, number in CLASSES.items()}

Say = Callable[[str], None]


PRESET = Preset(
    name="demo",
    version=__version__,
    description="Reference example: rest / soft / hard on pad 1",
    features=played_features,
    model_factory=Classifier,
    classes=CLASSES,
    outputs=(OscOutput(),),
)
"""The reference example as the built-in preset `demo`; it has no patch yet."""


def _collect(source: ClockedSource, events: list[Event], until: float) -> None:
    """Poll `source` into `events` until its clock reaches `until`."""
    while (now := source.now()) < until:
        event = source.poll()
        if event is None:
            source.sleep(min(POLL_INTERVAL, until - now))
        else:
            events.append(event)


def guided_record(
    source: ClockedSource,
    seconds: float = 3.0,
    countdown: float = 3.0,
    labels: Sequence[str] = tuple(CLASSES),
    say: Say = print,
) -> list[Event]:
    """Record each label for `seconds` after a `countdown`; return events with markers."""
    events: list[Event] = []
    source.start()
    for label in labels:
        say(f"Next: {label}. {PROMPTS.get(label, '')} Recording starts in {countdown:g} s...")
        _collect(source, events, source.now() + countdown)
        start = source.now()
        say(f"Recording {label} for {seconds:g} s...")
        events.append(ExampleStart(t=start, label=label))
        _collect(source, events, start + seconds)
        events.append(ExampleEnd(t=source.now()))
        if label in AFTER:
            say(AFTER[label])
    say("Done.")
    return events


def build_loop(examples_path: str, host: str, port: int) -> IMLLoop:
    """A loop with the demo features and classes, trained on `examples_path`."""
    examples = PRESET.example_set()
    examples.add_recording(examples_path)
    loop = PRESET.build_loop(examples, outputs=outputs_sender(host=host, port=port))
    loop.train()
    return loop


def describe(values: Sequence[float]) -> str:
    """One line for a received `/wek/outputs` message, for example `2 soft  ████`."""
    if not values:
        return "(empty message)"
    number = round(values[0])
    label = LABELS.get(number, "?")
    return f"{number} {label:<5} {'█' * 4 * (number - 1)}".rstrip()


def make_server(
    on_values: Callable[[list[float]], None], host: str = DEFAULT_HOST, port: int = OUTPUTS_PORT
) -> BlockingOSCUDPServer:
    """A UDP server that passes the values of each `/wek/outputs` message to `on_values`."""
    dispatcher = Dispatcher()

    def handle(_address: str, *args: Any) -> None:
        on_values([float(a) for a in args])

    dispatcher.map(OUTPUTS_ADDRESS, handle)
    return BlockingOSCUDPServer((host, port), dispatcher)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.demo",
        description="Reference example: rest / soft / hard on pad 1 (see the README).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    rec = sub.add_parser("record", help="guided recording of examples from the MPC")
    rec.add_argument("path", help="output recording, for example examples.jsonl")
    rec.add_argument("--seconds", type=float, default=3.0, help="seconds per class (default 3)")
    rec.add_argument("--countdown", type=float, default=3.0, help="seconds before each class")
    rec.add_argument("--port", default=DEFAULT_PORT_MATCH, help="MIDI input port name contains")
    rec.add_argument("--firmware", default="", help="MPC firmware version, for example 1.3.0")
    rec.add_argument("--full-level", action=argparse.BooleanOptionalAction, default=None)

    run = sub.add_parser("run", help="train on a recording, then run live or from a replay")
    run.add_argument("examples", help="recording with examples, from `demo record`")
    run.add_argument("--replay", help="run from this recording instead of the MPC")
    run.add_argument("--fast", action="store_true", help="replay as fast as possible")
    run.add_argument("--duration", type=float, default=None, help="seconds to run")
    run.add_argument("--port", default=DEFAULT_PORT_MATCH, help="MIDI input port name contains")
    run.add_argument("--osc-host", default=DEFAULT_HOST, help="receiver host")
    run.add_argument("--osc-port", type=int, default=OUTPUTS_PORT, help="receiver UDP port")

    listen = sub.add_parser("listen", help="show the classes received on /wek/outputs")
    listen.add_argument("--host", default=DEFAULT_HOST, help="address to listen on")
    listen.add_argument("--osc-port", type=int, default=OUTPUTS_PORT, help="UDP port")
    return parser


def _record(args: argparse.Namespace, live: Callable[[str], LiveSource]) -> int:
    if args.seconds <= 0 or args.countdown < 0:
        print("error: --seconds must be positive and --countdown not negative", file=sys.stderr)
        return 2
    settings: dict[str, Any] = {}
    if args.full_level is not None:
        settings["full_level"] = args.full_level
    source = live(args.port)
    try:
        source.open()
    except PortNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    with source:
        print(f"Recording from {source.port_name!r}.")
        events = guided_record(source, args.seconds, args.countdown)
    write_recording(args.path, Header(firmware=args.firmware, settings=settings), events)
    print(f"Wrote {len(events)} events to {args.path}")
    return 0


def _run(args: argparse.Namespace, live: Callable[[str], LiveSource]) -> int:
    loop = build_loop(args.examples, args.osc_host, args.osc_port)
    classes = ", ".join(f"{n} {label}" for label, n in CLASSES.items())
    print(f"Trained on {len(loop.examples)} examples ({classes}).")
    print(f"Sending {OUTPUTS_ADDRESS} to {args.osc_host}:{args.osc_port}. Ctrl-C stops.")
    source: LiveSource | ReplaySource
    if args.replay:
        source = ReplaySource(args.replay, realtime=not args.fast)
    else:
        source = live(args.port)
        try:
            source.open()
        except PortNotFoundError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    try:
        count = loop.run(source, duration=args.duration)
    except KeyboardInterrupt:
        count = None
    finally:
        if isinstance(source, LiveSource):
            source.close()
        if loop.outputs is not None:
            loop.outputs.close()
    if count is not None:
        print(f"Ran {count} frames.")
    return 0


def _listen(args: argparse.Namespace) -> int:
    last: list[str] = []

    def show(values: list[float]) -> None:
        line = describe(values)
        if not last or line != last[-1]:
            last[:] = [line]
            print(line, flush=True)

    with make_server(show, args.host, args.osc_port) as server:
        print(f"Listening for {OUTPUTS_ADDRESS} on {args.host}:{args.osc_port}. Ctrl-C stops.")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0


def main(
    argv: Sequence[str] | None = None,
    backend: MidiInputBackend | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Run a subcommand; tests pass a fake MIDI `backend`, `clock` and `sleep`."""
    args = build_parser().parse_args(argv)

    def live(port: str) -> LiveSource:
        return LiveSource(port_match=port, backend=backend, clock=clock, sleep=sleep)

    if args.command == "record":
        return _record(args, live)
    if args.command == "run":
        return _run(args, live)
    return _listen(args)


if __name__ == "__main__":
    raise SystemExit(main())
