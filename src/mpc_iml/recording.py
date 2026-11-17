"""Reading and writing recordings as JSON Lines (ADR 0002; version 2 in ADR 0007).

The first line is a header; every following line is one event in time order.
Channel voice messages are stored as decoded fields; any other MIDI message is
stored as `{"type": "midi", "bytes": [...]}` with the raw bytes as integers.

Format version 2 (ADR 0007) marks takes generated from modules: `example_start`
may carry `module`, `pad` and `amount`, and the header may carry `kit` and
`combine`. `write_recording` writes version 2 only when the events contain a
generated take, and version 1, unchanged, otherwise. Both versions are read.
"""

import json
import warnings
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field, replace
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
GENERATED_FORMAT_VERSION = 2
"""The version written when a recording contains generated takes (ADR 0007)."""
SUPPORTED_FORMAT_VERSIONS = frozenset({1, 2})
FULL_LEVEL_MIN_NOTES = 8


class RecordingFormatError(ValueError):
    """The file is not a recording this toolkit can read."""


class FullLevelWarning(UserWarning):
    """Every velocity is 127: the MPC's Full Level setting may have been on."""


@dataclass(frozen=True)
class Header:
    """Recording metadata; `settings` holds what the person recording declared.

    `kit` (the kit a set started from) and `combine` (`"add"` or `"none"`) are
    version 2 fields; they are written only with generated takes.
    `format_version` is the version read; `write_recording` chooses the version
    it writes from the events.
    """

    device: str = "MPC Sample"
    firmware: str = ""
    settings: dict[str, Any] = field(default_factory=dict)
    toolkit_version: str = __version__
    format_version: int = FORMAT_VERSION
    kit: str | None = None
    combine: str | None = None


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
            if event.module is not None:
                for key in ("module", "pad", "amount"):
                    value = getattr(event, key)
                    d[key] = list(value) if isinstance(value, tuple) else value
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
            **_generated_fields(d),
        )
    if kind == "example_end":
        return ExampleEnd(t=t)
    raise RecordingFormatError(f"unknown event type: {kind!r}")


def _generated_fields(d: dict[str, Any]) -> dict[str, Any]:
    """`module`, `pad` and `amount` of an `example_start` object (format version 2)."""
    present = [key for key in ("module", "pad", "amount") if key in d]
    if not present:
        return {}
    if len(present) != 3:
        raise RecordingFormatError("example_start needs all of module, pad and amount, or none")
    module, pad, amount = d["module"], d["pad"], d["amount"]
    if isinstance(module, str) and isinstance(pad, int) and isinstance(amount, int | float):
        if not 0 <= pad <= 16:
            raise RecordingFormatError(f"pad must be 0-16, got {pad}")
        return {"module": module, "pad": pad, "amount": float(amount)}
    if (
        all(isinstance(v, list) and len(v) == 2 for v in (module, pad, amount))
        and all(isinstance(m, str) for m in module)
        and all(isinstance(p, int) and 1 <= p <= 16 for p in pad)
        and all(isinstance(a, int | float) for a in amount)
    ):
        return {
            "module": (module[0], module[1]),
            "pad": (pad[0], pad[1]),
            "amount": (float(amount[0]), float(amount[1])),
        }
    raise RecordingFormatError(
        "module, pad and amount must be one id, pad and amount, or two of each"
    )


def header_to_dict(header: Header) -> dict[str, Any]:
    """Encode a header as the first JSON Lines object of a recording.

    `kit` and `combine` are written only in version 2 headers.
    """
    d: dict[str, Any] = {
        "type": "header",
        "format": FORMAT,
        "format_version": header.format_version,
        "toolkit_version": header.toolkit_version,
        "device": header.device,
        "firmware": header.firmware,
        "settings": header.settings,
    }
    if header.format_version >= GENERATED_FORMAT_VERSION:
        if header.kit is not None:
            d["kit"] = header.kit
        if header.combine is not None:
            d["combine"] = header.combine
    return d


def write_recording(path: Path | str, header: Header, events: Iterable[Event]) -> None:
    """Write a header and events to `path` as JSON Lines.

    The file is version 2 when an event is a generated take
    (`ExampleStart.generated`), otherwise version 1 as before; `header.format_version`
    is ignored. Raises `ValueError` for `kit` or `combine` without generated takes.
    """
    events = list(events)
    generated = any(isinstance(e, ExampleStart) and e.generated for e in events)
    if not generated and (header.kit is not None or header.combine is not None):
        raise ValueError("kit and combine are written only with generated takes")
    version = GENERATED_FORMAT_VERSION if generated else FORMAT_VERSION
    header = replace(header, format_version=version)
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
    if version >= GENERATED_FORMAT_VERSION:
        if not isinstance(d.get("kit", ""), str):
            raise RecordingFormatError(f"kit must be a name, got {d['kit']!r}")
        if d.get("combine", "add") not in ("add", "none"):
            raise RecordingFormatError(f"combine must be 'add' or 'none', got {d['combine']!r}")
    return Header(
        device=d.get("device", ""),
        firmware=d.get("firmware", ""),
        settings=dict(d.get("settings", {})),
        toolkit_version=d.get("toolkit_version", ""),
        format_version=int(version),
        kit=d.get("kit") if version >= GENERATED_FORMAT_VERSION else None,
        combine=d.get("combine") if version >= GENERATED_FORMAT_VERSION else None,
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
    if header.format_version < GENERATED_FORMAT_VERSION and any(
        isinstance(e, ExampleStart) and e.generated for e in events
    ):
        raise RecordingFormatError("generated takes (module, pad, amount) need format_version 2")
    check_full_level(events)
    return Recording(header=header, events=events)
