"""Pad mapping and frames computed from events (ADR 0002).

A frame describes the 16 physical pads, whatever the bank: latest pressure,
latest velocity and whether each pad is held, plus the current bank (0-7).

Frame `k` is at time `k / rate` and reflects every event with `t` at or before that
time. `FrameBuilder` holds this rule; two drivers use it:

- `frames()` steps through events as fast as possible (replay, tests);
- `realtime_frames()` steps on the source's clock, one frame per interval whether
  or not MIDI arrives (live input, replay with `realtime=True`).
"""

from collections import deque
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from mpc_iml.events import NOTE_KINDS, Event, MidiEvent
from mpc_iml.sources import POLL_INTERVAL, ClockedSource

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


class FrameBuilder:
    """The frame rule shared by `frames()` and `realtime_frames()`.

    Holds the pad state and the index `k` of the next frame, at time `k / rate`.
    """

    def __init__(self, rate: float = DEFAULT_RATE) -> None:
        if rate <= 0:
            raise ValueError(f"rate must be positive: {rate}")
        self.rate = rate
        self.state = PadState()
        self.k = 0

    @property
    def time(self) -> float:
        """Time of the next frame."""
        return self.k / self.rate

    def apply(self, event: Event) -> None:
        """Apply an event; it shows in every frame from the next one emitted."""
        self.state.apply(event)

    def emit(self) -> Frame:
        """Return the next frame and move on to the one after it."""
        frame = self.state.frame(self.time)
        self.k += 1
        return frame

    def skip_to(self, now: float) -> int:
        """Skip frames until the next one is the latest due at `now`; return how many."""
        skipped = 0
        while (self.k + 1) / self.rate <= now:
            self.k += 1
            skipped += 1
        return skipped


def frames(events: Iterable[Event], rate: float = DEFAULT_RATE) -> Iterator[Frame]:
    """Yield frames at times k / rate (k = 0, 1, ...) up to the last event.

    Each frame reflects every event with `t` at or before the frame time. Events
    must be in time order.
    """
    builder = FrameBuilder(rate)
    for event in events:
        while builder.time < event.t:
            yield builder.emit()
        builder.apply(event)
    yield builder.emit()


def realtime_frames(
    source: ClockedSource,
    rate: float = DEFAULT_RATE,
    duration: float | None = None,
    stop: Callable[[], bool] | None = None,
    on_drop: Callable[[int], None] | None = None,
) -> Iterator[Frame]:
    """Yield frame `k` when it is due at `k / rate` on the source's clock.

    A frame is yielded every interval whether or not events arrive, with the same
    times and contents as `frames()` gives for the same events. Between frames the
    source is polled, sleeping at most `POLL_INTERVAL`.

    When the consumer falls behind and several frames are due at once, every event
    up to the latest due frame time is applied and only that frame is yielded; the
    skipped frames are dropped and their number passed to `on_drop`. No event is
    lost, and frames never come in bursts.

    Stops when the source is done and every event it gave is in a yielded frame,
    when the source's clock reaches `duration` seconds, or when `stop()` is true.
    """
    builder = FrameBuilder(rate)
    pending: deque[Event] = deque()
    source.start()
    while True:
        now = source.now()
        if duration is not None and now >= duration:
            return
        if stop is not None and stop():
            return
        while (event := source.poll()) is not None:
            pending.append(event)
        if builder.time > now:
            source.sleep(min(POLL_INTERVAL, builder.time - now))
            continue
        dropped = builder.skip_to(now)
        if dropped and on_drop is not None:
            on_drop(dropped)
        while pending and pending[0].t <= builder.time:
            builder.apply(pending.popleft())
        yield builder.emit()
        if source.done() and not pending:
            return
