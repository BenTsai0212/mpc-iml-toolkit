"""Pad mapping and frames computed from events (ADR 0002).

A frame describes the 16 physical pads, whatever the bank: latest pressure,
latest velocity and whether each pad is held, plus the current bank (0-7).
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

from mpc_iml.events import NOTE_KINDS, Event, MidiEvent

PADS = 16
BANKS = 8
BASE_NOTE = 36
DEFAULT_RATE = 100.0
OSC_INPUT_COUNT = 3 * PADS + 1


def note_to_bank_pad(note: int) -> tuple[int, int]:
    """Map a note to (bank, pad), both from 0: note = (36 + 16 * bank + pad) mod 128."""
    if not 0 <= note <= 127:
        raise ValueError(f"note out of range: {note}")
    offset = (note - BASE_NOTE) % 128
    return offset // PADS, offset % PADS


def bank_pad_to_note(bank: int, pad: int) -> int:
    """Inverse of `note_to_bank_pad`."""
    if not (0 <= bank < BANKS and 0 <= pad < PADS):
        raise ValueError(f"bank or pad out of range: bank={bank}, pad={pad}")
    return (BASE_NOTE + PADS * bank + pad) % 128


@dataclass(frozen=True)
class Frame:
    """Pad state at time `t`; pressure and velocity are raw MIDI values (0-127)."""

    t: float
    pressure: tuple[int, ...]
    velocity: tuple[int, ...]
    held: tuple[bool, ...]
    bank: int

    def to_osc_values(self) -> list[float]:
        """The 49 OSC input values: 16 pressures, 16 velocities, 16 held flags, bank.

        Pressure and velocity are normalised to 0-1, held is 0 or 1, bank is 0-7.
        """
        return [
            *(p / 127 for p in self.pressure),
            *(v / 127 for v in self.velocity),
            *(1.0 if h else 0.0 for h in self.held),
            float(self.bank),
        ]


class PadState:
    """Mutable pad state updated one event at a time."""

    def __init__(self) -> None:
        self.pressure = [0] * PADS
        self.velocity = [0] * PADS
        self.held = [False] * PADS
        self.bank = 0

    def apply(self, event: Event) -> None:
        """Update from a pad note or pad pressure message; ignore everything else.

        `Note On` with velocity 0 counts as `Note Off` (MIDI convention).
        """
        if not isinstance(event, MidiEvent) or event.note is None:
            return
        if event.kind not in NOTE_KINDS:
            return
        bank, pad = note_to_bank_pad(event.note)
        if event.kind == "note_on" and event.value > 0:
            self.velocity[pad] = event.value
            self.held[pad] = True
            self.bank = bank
        elif event.kind == "poly_pressure":
            self.pressure[pad] = event.value
        else:
            self.pressure[pad] = 0
            self.held[pad] = False

    def frame(self, t: float) -> Frame:
        return Frame(
            t=t,
            pressure=tuple(self.pressure),
            velocity=tuple(self.velocity),
            held=tuple(self.held),
            bank=self.bank,
        )


def frames(events: Iterable[Event], rate: float = DEFAULT_RATE) -> Iterator[Frame]:
    """Yield frames at times k / rate (k = 0, 1, ...) up to the last event.

    Each frame reflects every event with `t` at or before the frame time. Events
    must be in time order.
    """
    if rate <= 0:
        raise ValueError(f"rate must be positive: {rate}")
    state = PadState()
    k = 0
    for event in events:
        while k / rate < event.t:
            yield state.frame(k / rate)
            k += 1
        state.apply(event)
    yield state.frame(k / rate)
