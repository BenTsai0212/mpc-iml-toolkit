"""Reading and writing recordings as JSON Lines (ADR 0002, format version 1).

The first line is a header; every following line is one event in time order.
Channel voice messages are stored as decoded fields; any other MIDI message is
stored as `{"type": "midi", "bytes": [...]}` with the raw bytes as integers.
"""

import json
import warnings
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mpc_iml import __version__
from mpc_iml.events import (
    MIDI_KINDS,
    Event,
    ExampleEnd,
    ExampleStart,
    MidiEvent,
    RawMidiEvent,
)

FORMAT = "mpc-iml-recording"
FORMAT_VERSION = 1
SUPPORTED_FORMAT_VERSIONS = frozenset({1})
FULL_LEVEL_MIN_NOTES = 8


class RecordingFormatError(ValueError):
    """The file is not a recording this toolkit can read."""


class FullLevelWarning(UserWarning):
    """Every velocity is 127: the MPC's Full Level setting may have been on."""


@dataclass(frozen=True)
class Header:
    """Recording metadata; `settings` holds what the person recording declared."""

    device: str = "MPC Sample"
    firmware: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    toolkit_version: str = __version__
    format_version: int = FORMAT_VERSION


@dataclass(frozen=True)
class Recording:
    header: Header
    events: tuple[Event, ...]


def event_to_dict(event: Event) -> dict[str, Any]:
    """Encode one event as a JSON Lines object."""
    match event:
        case MidiEvent():
            d: dict[str, Any] = {"t": event.t, "type": "midi", "kind": event.kind}
            d["channel"] = event.channel
            if event.note is not None:
                d["note"] = event.note
            if event.control is not None:
                d["control"] = event.control
            d["value"] = event.value
            return d
        case RawMidiEvent():
            return {"t": event.t, "type": "midi", "bytes": list(event.data)}
        case ExampleStart():
            d = {"t": event.t, "type": "example_start"}
            if event.label is not None:
                d["label"] = event.label
            if event.targets is not None:
                d["targets"] = list(event.targets)
            return d
        case ExampleEnd():
            return {"t": event.t, "type": "example_end"}


def event_from_dict(d: dict[str, Any]) -> Event:
    """Decode one JSON Lines object into an event."""
    t = float(d["t"])
    kind = d["type"]
    if kind == "midi":
        if "bytes" in d:
            return RawMidiEvent(t=t, data=bytes(d["bytes"]))
        if d.get("kind") not in MIDI_KINDS:
            raise RecordingFormatError(f"unknown MIDI kind: {d.get('kind')!r}")
        return MidiEvent(
            t=t,
            kind=d["kind"],
            channel=int(d["channel"]),
            value=int(d["value"]),
            note=d.get("note"),
            control=d.get("control"),
        )
    if kind == "example_start":
        targets = d.get("targets")
        return ExampleStart(
            t=t,
            label=d.get("label"),
            targets=None if targets is None else tuple(float(x) for x in targets),
        )
    if kind == "example_end":
        return ExampleEnd(t=t)
    raise RecordingFormatError(f"unknown event type: {kind!r}")


def header_to_dict(header: Header) -> dict[str, Any]:
    """Encode a header as the first JSON Lines object of a recording."""
    return {
        "type": "header",
        "format": FORMAT,
        "format_version": header.format_version,
        "toolkit_version": header.toolkit_version,
        "device": header.device,
        "firmware": header.firmware,
        "settings": header.settings,
    }


def write_recording(path: Path | str, header: Header, events: Iterable[Event]) -> None:
    """Write a header and events to `path` as JSON Lines."""
    with Path(path).open("w", encoding="utf-8") as f:
        f.write(json.dumps(header_to_dict(header)) + "\n")
        for event in events:
            f.write(json.dumps(event_to_dict(event)) + "\n")


def _parse_header(d: dict[str, Any]) -> Header:
    if d.get("type") != "header" or d.get("format") != FORMAT:
        raise RecordingFormatError(f"not an {FORMAT} file: the first line is not its header")
    version = d.get("format_version")
    if version not in SUPPORTED_FORMAT_VERSIONS:
        supported = ", ".join(str(v) for v in sorted(SUPPORTED_FORMAT_VERSIONS))
        raise RecordingFormatError(
            f"unsupported format_version {version!r}; this toolkit reads version(s) {supported}"
        )
    return Header(
        device=d.get("device", ""),
        firmware=d.get("firmware", ""),
        settings=dict(d.get("settings", {})),
        toolkit_version=d.get("toolkit_version", ""),
        format_version=int(version),
    )


def _lines(path: Path | str) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as f:
        for number, line in enumerate(f, start=1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise RecordingFormatError(f"line {number}: invalid JSON ({e.msg})") from e


def check_full_level(events: Iterable[Event]) -> bool:
    """Warn (and return True) if at least 8 notes all have velocity 127."""
    velocities = [
        e.value for e in events if isinstance(e, MidiEvent) and e.kind == "note_on" and e.value > 0
    ]
    if len(velocities) >= FULL_LEVEL_MIN_NOTES and all(v == 127 for v in velocities):
        warnings.warn(
            f"all {len(velocities)} note velocities are 127: Full Level may have been on",
            FullLevelWarning,
            stacklevel=3,
        )
        return True
    return False


def read_recording(path: Path | str) -> Recording:
    """Read a recording; raises `RecordingFormatError` for unknown versions or bad data."""
    lines = _lines(path)
    first = next(lines, None)
    if first is None:
        raise RecordingFormatError("empty file: missing header")
    header = _parse_header(first)
    try:
        events = tuple(event_from_dict(d) for d in lines)
    except (KeyError, TypeError, ValueError) as e:
        if isinstance(e, RecordingFormatError):
            raise
        raise RecordingFormatError(f"invalid event: {e!r}") from e
    check_full_level(events)
    return Recording(header=header, events=events)
