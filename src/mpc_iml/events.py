"""Typed events: MIDI messages and example markers (ADR 0002).

An event source is any iterable of `Event`, for example a recording read from a
file or, later, live MIDI input. Time `t` is seconds since the start of the
recording.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

MidiKind = Literal[
    "note_on",
    "note_off",
    "poly_pressure",
    "control_change",
    "program_change",
    "channel_pressure",
    "pitch_bend",
]

MIDI_KINDS: tuple[MidiKind, ...] = (
    "note_on",
    "note_off",
    "poly_pressure",
    "control_change",
    "program_change",
    "channel_pressure",
    "pitch_bend",
)
"""Channel voice message kinds stored as decoded fields."""

NOTE_KINDS: frozenset[MidiKind] = frozenset({"note_on", "note_off", "poly_pressure"})
"""Kinds that carry a `note`."""


@dataclass(frozen=True)
class MidiEvent:
    """A channel voice message, stored as decoded fields with values as received.

    `note` is set for note and poly pressure messages, `control` for control
    change; `channel` counts from 1.
    """

    t: float
    kind: MidiKind
    channel: int
    value: int
    note: int | None = None
    control: int | None = None


@dataclass(frozen=True)
class RawMidiEvent:
    """Any MIDI message that is not a channel voice message, as raw bytes."""

    t: float
    data: bytes


@dataclass(frozen=True)
class ExampleStart:
    """Start of an example: a `label` for classification or `targets` for regression."""

    t: float
    label: str | None = None
    targets: tuple[float, ...] | None = None


@dataclass(frozen=True)
class ExampleEnd:
    """End of the current example."""

    t: float


Event = MidiEvent | RawMidiEvent | ExampleStart | ExampleEnd
EventSource = Iterable[Event]
