"""Training examples generated from kits and modules (ADR 0007).

A `GeneratedSet` holds the takes generated for a kit: the resting values, the
module on each pad, and the takes themselves. It is what the engine keeps next to
its recorded demonstrations:

- `GeneratedSet.from_kit(library, name)` generates every take of a kit;
- `generated.assign(library, pad, module, amount)` replaces one pad's takes and the
  combined takes that include it, keeping all other takes;
- `with_generated(recorded, generated)` gives the whole example set as one event
  timeline (recorded demonstrations first, then the generated takes), for
  `ExampleSet.add_events` and for `write_recording` with `generated.header(...)`;
- `split_generated(recording)` splits a loaded timeline back into the recorded
  events and the `GeneratedSet` (pad assignments, resting values, kit and combine).

Takes, at the frame rate (100 Hz by default):

- **single-pad**: per pad, 4 takes at pressure 0.25, 0.5, 0.75 and 1.0, 20 frames
  each, with targets `clamp(rest + amount × offset(pressure), 0, 1)`;
- **rest**: one take of 20 frames, no pad pressed, the resting values as targets;
- **combined** (`combine == "add"`): for every two pads whose module is not `none`,
  2 takes of 10 frames, both pads at 0.5 and both at 1.0, with both offsets added.

A take starts with `example_start` and, at the same time, `note_on` (velocity 100,
bank A) and `poly_pressure` (`round(127 × pressure)`) for its pads; `note_off` and
`example_end` follow `frames` frames later. Weighting against recorded
demonstrations is by frame count.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import combinations

from mpc_iml.content import (
    COMBINE_MODES,
    NONE,
    PADS,
    Combine,
    ContentError,
    Library,
    PadAssignment,
)
from mpc_iml.events import Event, ExampleEnd, ExampleStart, MidiEvent
from mpc_iml.frames import DEFAULT_RATE, PadState, bank_pad_to_note, note_to_bank_pad
from mpc_iml.recording import Header, Recording, RecordingFormatError

__all__ = [
    "COMBINED_FRAMES",
    "COMBINED_PRESSURES",
    "REST_FRAMES",
    "TAKE_FRAMES",
    "TAKE_PRESSURES",
    "VELOCITY",
    "GeneratedSet",
    "GeneratedTake",
    "split_generated",
    "with_generated",
]

TAKE_PRESSURES = (0.25, 0.5, 0.75, 1.0)
TAKE_FRAMES = 20
REST_FRAMES = 20
COMBINED_PRESSURES = (0.5, 1.0)
COMBINED_FRAMES = 10
VELOCITY = 100


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)


@dataclass(frozen=True)
class GeneratedTake:
    """One generated take: its marking (ADR 0007), targets and pressed pads.

    `presses` holds `(pad, pressure value 0-127)` per pressed pad, pads 1-16;
    `frames` is the take's length in frames.
    """

    targets: tuple[float, ...]
    module: str | tuple[str, str]
    pad: int | tuple[int, int]
    amount: float | tuple[float, float]
    presses: tuple[tuple[int, int], ...]
    frames: int

    @property
    def pads(self) -> tuple[int, ...]:
        """The pads this take belongs to: none for the rest take."""
        if isinstance(self.pad, tuple):
            return self.pad
        return (self.pad,) if self.pad else ()

    def _key(self) -> tuple[int, ...]:
        level = self.presses[0][1] if self.presses else 0
        return (len(self.pads), *self.pads, level)

    def events(self, k: int, rate: float = DEFAULT_RATE) -> list[Event]:
        """The take's events, starting at frame `k`."""
        start, end = k / rate, (k + self.frames) / rate
        notes = [bank_pad_to_note(0, pad - 1) for pad, _ in self.presses]
        return [
            ExampleStart(start, None, self.targets, self.module, self.pad, self.amount),
            *(MidiEvent(start, "note_on", 1, VELOCITY, note=n) for n in notes),
            *(
                MidiEvent(start, "poly_pressure", 1, value, note=n)
                for n, (_, value) in zip(notes, self.presses, strict=True)
            ),
            *(MidiEvent(end, "note_off", 1, 0, note=n) for n in notes),
            ExampleEnd(end),
        ]


def _targets(
    library: Library,
    rest: Sequence[float],
    pressed: Iterable[tuple[PadAssignment, float]],
) -> tuple[float, ...]:
    values = list(rest)
    for assignment, pressure in pressed:
        module = library.module(assignment.module)
        for i, name in enumerate(library.output_names):
            values[i] += assignment.amount * module.offset(name, pressure)
    return tuple(_clamp(v) for v in values)


def _value(pressure: float) -> int:
    return round(127 * pressure)


def _single_takes(
    library: Library, rest: Sequence[float], pad: int, assignment: PadAssignment
) -> list[GeneratedTake]:
    return [
        GeneratedTake(
            _targets(library, rest, [(assignment, p)]),
            assignment.module,
            pad,
            assignment.amount,
            ((pad, _value(p)),),
            TAKE_FRAMES,
        )
        for p in TAKE_PRESSURES
    ]


def _combined_takes(
    library: Library,
    rest: Sequence[float],
    a: tuple[int, PadAssignment],
    b: tuple[int, PadAssignment],
) -> list[GeneratedTake]:
    (pad_a, asg_a), (pad_b, asg_b) = sorted([a, b], key=lambda x: x[0])
    return [
        GeneratedTake(
            _targets(library, rest, [(asg_a, p), (asg_b, p)]),
            (asg_a.module, asg_b.module),
            (pad_a, pad_b),
            (asg_a.amount, asg_b.amount),
            ((pad_a, _value(p)), (pad_b, _value(p))),
            COMBINED_FRAMES,
        )
        for p in COMBINED_PRESSURES
    ]


def _rest_take(rest: Sequence[float]) -> GeneratedTake:
    return GeneratedTake(tuple(_clamp(v) for v in rest), NONE, 0, 0.0, (), REST_FRAMES)


def _combines(assignment: PadAssignment | None) -> bool:
    return assignment is not None and assignment.module != NONE


@dataclass(frozen=True)
class GeneratedSet:
    """The generated takes of an example set, with what they were generated from.

    - `rest`: resting values in output order, or `None` when a loaded set has no
      rest take (then `assign` is refused: "load a kit first");
    - `pads`: the assignment of pads 1-16; `None` for a pad without generated takes;
    - `kit`: the kit the set started from, if any; `combine`: `"add"` or `"none"`.
    """

    rest: tuple[float, ...] | None
    pads: tuple[PadAssignment | None, ...]
    takes: tuple[GeneratedTake, ...]
    kit: str | None = None
    combine: Combine = "add"

    @classmethod
    def from_kit(cls, library: Library, name: str) -> "GeneratedSet":
        """Every take of kit `name`; raises `UnknownContentError` for an unknown kit."""
        kit = library.kit(name)
        rest = tuple(kit.rest[o] for o in library.output_names)
        takes = [_rest_take(rest)]
        for pad, assignment in enumerate(kit.pads, start=1):
            takes += _single_takes(library, rest, pad, assignment)
        if kit.combine == "add":
            combining = [(p, a) for p, a in enumerate(kit.pads, start=1) if _combines(a)]
            for a, b in combinations(combining, 2):
                takes += _combined_takes(library, rest, a, b)
        return cls(rest, kit.pads, tuple(sorted(takes, key=GeneratedTake._key)), name, kit.combine)

    def assign(
        self, library: Library, pad: int, module: str, amount: float = 1.0
    ) -> "GeneratedSet":
        """A copy with `module` at `amount` on `pad` (1-16).

        Replaces that pad's single-pad takes and the combined takes that include it;
        every other take is kept as it is. Raises `ContentError` for a pad outside
        1-16, an amount outside 0-1 or a set without resting values, and
        `UnknownContentError` for an unknown module.
        """
        if not 1 <= pad <= PADS:
            raise ContentError(f"pad must be 1-{PADS}, got {pad}")
        if self.rest is None:
            raise ContentError("no resting values: load a kit first")
        library.module(module)
        assignment = PadAssignment(module, amount)
        pads = list(self.pads)
        pads[pad - 1] = assignment
        takes = [t for t in self.takes if pad not in t.pads]
        takes += _single_takes(library, self.rest, pad, assignment)
        if self.combine == "add" and _combines(assignment):
            for other, other_assignment in enumerate(pads, start=1):
                if other != pad and other_assignment is not None and _combines(other_assignment):
                    takes += _combined_takes(
                        library, self.rest, (pad, assignment), (other, other_assignment)
                    )
        return replace(self, pads=tuple(pads), takes=tuple(sorted(takes, key=GeneratedTake._key)))

    def assignments(self) -> list[tuple[str, float]]:
        """`(module, amount)` for pads 1-16; `("", 1.0)` for a pad without takes."""
        return [(a.module, a.amount) if a else ("", 1.0) for a in self.pads]

    def frame_count(self) -> int:
        """The number of example frames the takes give."""
        return sum(t.frames for t in self.takes)

    def events(self, rate: float = DEFAULT_RATE, start: int = 0) -> list[Event]:
        """All takes as events, the first starting at frame `start`, one frame apart."""
        events: list[Event] = []
        k = start
        for take in self.takes:
            events += take.events(k, rate)
            k += take.frames + 1
        return events

    def header(self, header: Header) -> Header:
        """`header` with this set's `kit` and `combine`, for `write_recording`."""
        return replace(header, kit=self.kit, combine=self.combine)


def with_generated(
    recorded: Sequence[Event], generated: GeneratedSet | None, rate: float = DEFAULT_RATE
) -> list[Event]:
    """The recorded events followed by the generated takes, as one timeline.

    The generated takes start two frames after the last recorded event, after every
    pad still held or pressed is released, so no recorded pad state leaks into them.
    """
    if generated is None or not generated.takes:
        return list(recorded)
    state = PadState()
    for event in recorded:
        state.apply(event)
    k = math.floor(recorded[-1].t * rate) + 2 if recorded else 0
    t = k / rate
    release: list[Event] = [
        MidiEvent(t, "note_off", 1, 0, note=bank_pad_to_note(state.bank, pad))
        for pad in range(PADS)
        if state.held[pad] or state.pressure[pad] > 0
    ]
    return [*recorded, *release, *generated.events(rate, k)]


def _take_from(
    start: ExampleStart, presses: dict[int, int], end: ExampleEnd, rate: float
) -> GeneratedTake:
    if start.targets is None or start.pad is None or start.amount is None:
        raise RecordingFormatError(f"generated take at t={start.t} needs targets")
    assert start.module is not None
    return GeneratedTake(
        start.targets,
        start.module,
        start.pad,
        start.amount,
        tuple(sorted(presses.items())),
        round((end.t - start.t) * rate),
    )


def split_generated(
    recording: Recording, rate: float = DEFAULT_RATE
) -> tuple[list[Event], GeneratedSet | None]:
    """Split a recording into its recorded events and its generated takes.

    The pad assignments come from the single-pad takes, the resting values from the
    rest take, `kit` and `combine` from the header (ADR 0007). The set is `None`
    when the recording has no generated takes (every version 1 file). The release
    events `with_generated` wrote before the takes stay with the recorded events;
    they change nothing in a later `with_generated`. Raises
    `RecordingFormatError` for a malformed generated take or a pad with two modules.
    """
    recorded: list[Event] = []
    takes: list[GeneratedTake] = []
    start: ExampleStart | None = None
    presses: dict[int, int] = {}
    for event in recording.events:
        if start is None:
            if isinstance(event, ExampleStart) and event.generated:
                start, presses = event, {}
            else:
                recorded.append(event)
        elif isinstance(event, ExampleEnd):
            takes.append(_take_from(start, presses, event, rate))
            start = None
        elif isinstance(event, MidiEvent) and event.kind == "poly_pressure":
            assert event.note is not None
            presses[note_to_bank_pad(event.note)[1] + 1] = event.value
    if start is not None:
        raise RecordingFormatError(f"generated take at t={start.t} without example_end")
    if not takes:
        return recorded, None
    rest: tuple[float, ...] | None = None
    pads: list[PadAssignment | None] = [None] * PADS
    for take in takes:
        if take.pad == 0:
            rest = take.targets
        elif isinstance(take.pad, int):
            assert isinstance(take.module, str) and isinstance(take.amount, float)
            assignment = PadAssignment(take.module, take.amount)
            if pads[take.pad - 1] not in (None, assignment):
                raise RecordingFormatError(f"pad {take.pad} has takes of two modules")
            pads[take.pad - 1] = assignment
    combine = recording.header.combine or "add"
    if combine not in COMBINE_MODES:
        raise RecordingFormatError(f"combine must be 'add' or 'none', got {combine!r}")
    generated = GeneratedSet(
        rest,
        tuple(pads),
        tuple(sorted(takes, key=GeneratedTake._key)),
        recording.header.kit,
        combine,
    )
    return recorded, generated
