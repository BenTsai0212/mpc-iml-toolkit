"""Decoding raw MIDI bytes into events (ADR 0002).

Channel voice messages become `MidiEvent` with values as received (a `Note On` with
velocity 0 stays `note_on` with value 0); any other message becomes `RawMidiEvent`.
Messages are complete, as delivered by `python-rtmidi` (no running status).
"""

from collections.abc import Sequence

from mpc_iml.events import MidiEvent, MidiKind, RawMidiEvent

_KINDS: dict[int, MidiKind] = {
    0x80: "note_off",
    0x90: "note_on",
    0xA0: "poly_pressure",
    0xB0: "control_change",
    0xC0: "program_change",
    0xD0: "channel_pressure",
    0xE0: "pitch_bend",
}
_LENGTHS: dict[MidiKind, int] = {
    "note_off": 3,
    "note_on": 3,
    "poly_pressure": 3,
    "control_change": 3,
    "program_change": 2,
    "channel_pressure": 2,
    "pitch_bend": 3,
}


def decode(data: Sequence[int] | bytes, t: float) -> MidiEvent | RawMidiEvent:
    """Decode one complete MIDI message received at time `t`."""
    raw = bytes(data)
    if not raw or raw[0] < 0x80 or raw[0] >= 0xF0:
        return RawMidiEvent(t=t, data=raw)
    kind = _KINDS[raw[0] & 0xF0]
    if len(raw) != _LENGTHS[kind] or any(b >= 0x80 for b in raw[1:]):
        return RawMidiEvent(t=t, data=raw)
    channel = (raw[0] & 0x0F) + 1
    match kind:
        case "note_on" | "note_off" | "poly_pressure":
            return MidiEvent(t=t, kind=kind, channel=channel, note=raw[1], value=raw[2])
        case "control_change":
            return MidiEvent(t=t, kind=kind, channel=channel, control=raw[1], value=raw[2])
        case "pitch_bend":
            return MidiEvent(t=t, kind=kind, channel=channel, value=raw[1] | (raw[2] << 7))
        case _:
            return MidiEvent(t=t, kind=kind, channel=channel, value=raw[1])
