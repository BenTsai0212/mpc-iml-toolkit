"""Show where each pad hit of a recording fell on the grid: `python -m mpc_iml.grid rec.jsonl`.

Reads a recording made with `python -m mpc_iml.record --clock` (#139) and prints one
tab-separated line per pad hit: time in seconds, bar and step (both from 1), pad
(`A01` to `H16`), velocity and offset from the step in milliseconds (negative is
early). Hits while the clock was not running get `-` for bar, step and offset. A
summary (tempo range, tagged and untagged hits) goes to standard error, so standard
output pastes into a spreadsheet as it is.

Tagging is `mpc_iml.clock.tag_recording`, the same `MidiClock` the engine uses
live. The meter is chosen here (`--beats-per-bar`); MIDI clock carries none.
"""

import argparse
import sys
from collections.abc import Iterable, Sequence

from mpc_iml.clock import (
    EIGHTHS,
    SIXTEENTH_TRIPLETS,
    SIXTEENTHS,
    MidiClock,
    PadHit,
    tag_recording,
)
from mpc_iml.events import Event, RawMidiEvent
from mpc_iml.recording import RecordingFormatError, read_recording

RESOLUTIONS = {"16": SIXTEENTHS, "8": EIGHTHS, "16t": SIXTEENTH_TRIPLETS}
"""`--resolution` values and their ticks per step."""

COLUMNS = ("t", "bar", "step", "pad", "velocity", "offset_ms")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.grid",
        description="Place the pad hits of a recording with MIDI clock on the grid.",
    )
    parser.add_argument("path", help="a recording made with `python -m mpc_iml.record --clock`")
    parser.add_argument(
        "--beats-per-bar", type=int, default=4, help="quarter notes per bar (default: 4)"
    )
    parser.add_argument(
        "--resolution",
        choices=sorted(RESOLUTIONS),
        default="16",
        help="grid steps: 16ths, 8ths or 16th triplets (default: 16)",
    )
    return parser


def pad_name(bank: int, pad: int) -> str:
    """`A01` for bank 0, pad 0 (both from 0) up to `H16`."""
    return f"{chr(ord('A') + bank)}{pad + 1:02d}"


def format_hit(hit: PadHit) -> str:
    """One tab-separated line in `COLUMNS` order."""
    grid = hit.grid
    if grid is None:
        bar, step, offset = "-", "-", "-"
    else:
        bar, step, offset = str(grid.bar + 1), str(grid.step + 1), f"{grid.offset_ms:+.1f}"
    fields = (f"{hit.t:.3f}", bar, step, pad_name(hit.bank, hit.pad), str(hit.velocity), offset)
    return "\t".join(fields)


def bpm_range(events: Iterable[Event]) -> tuple[float, float] | None:
    """The lowest and highest tempo the clock reported, or `None` without one."""
    clock = MidiClock()
    tempos: list[float] = []
    for event in events:
        if isinstance(event, RawMidiEvent):
            bpm = clock.feed(event.data, event.t).bpm
            if bpm is not None:
                tempos.append(bpm)
    return (min(tempos), max(tempos)) if tempos else None


def summary(hits: Sequence[PadHit], tempo: tuple[float, float] | None) -> str:
    tagged = sum(hit.grid is not None for hit in hits)
    bpm = "no MIDI clock" if tempo is None else f"{tempo[0]:.1f}-{tempo[1]:.1f} BPM"
    return f"{len(hits)} hits: {tagged} on the grid, {len(hits) - tagged} not ({bpm})"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.beats_per_bar < 1:
        print("error: --beats-per-bar must be at least 1", file=sys.stderr)
        return 2
    try:
        recording = read_recording(args.path)
    except (OSError, RecordingFormatError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    hits = tag_recording(recording.events, args.beats_per_bar, RESOLUTIONS[args.resolution])
    print("\t".join(COLUMNS))
    for hit in hits:
        print(format_hit(hit))
    print(summary(hits, bpm_range(recording.events)), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
