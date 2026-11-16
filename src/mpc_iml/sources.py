"""Event sources: live MIDI input from the MPC and replay of recordings (ADR 0002).

`LiveSource` and `ReplaySource` both iterate over `Event`s, so code downstream (frames,
OSC, models) takes either: test with a replay, run unchanged live. Both are also a
`ClockedSource` (non-blocking `poll` on a clock), which `frames.realtime_frames` uses
to produce frames on time even when no MIDI arrives.

`LiveSource` reads through a `MidiInputBackend`; `RtMidiBackend` wraps
`python-rtmidi`, and tests pass a fake backend. It is single-threaded: iterating polls
the backend, sleeping 1 ms when no message is pending, and `t` is the time a message
is received, in seconds since the source was opened.
"""

import json
import time
from collections.abc import Callable, Generator, Iterable, Iterator
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from mpc_iml.events import Event
from mpc_iml.midi import decode
from mpc_iml.recording import Header, Recording, event_to_dict, header_to_dict, read_recording

__all__ = [
    "DEFAULT_PORT_MATCH",
    "POLL_INTERVAL",
    "ClockedSource",
    "LiveSource",
    "MidiInputBackend",
    "PortNotFoundError",
    "ReplaySource",
    "RtMidiBackend",
    "record",
    "tee",
]

DEFAULT_PORT_MATCH = "MPC"
"""Live input opens the first port whose name contains this (case-insensitive)."""

POLL_INTERVAL = 0.001
"""Seconds to sleep when no message is pending."""


class PortNotFoundError(LookupError):
    """No MIDI input port name contains the requested text."""


@runtime_checkable
class ClockedSource(Protocol):
    """A non-blocking event source with its own clock, for `realtime_frames`."""

    @property
    def realtime(self) -> bool:
        """True when events arrive in real time, so frames should follow the clock."""
        ...

    def start(self) -> None:
        """Get ready to poll; `now()` starts at 0 (live: open the port)."""
        ...

    def now(self) -> float:
        """Seconds on the source's clock, in the same time base as event `t`."""
        ...

    def poll(self) -> Event | None:
        """Return one event received at or before `now()`, or `None` if none is pending."""
        ...

    def sleep(self, seconds: float) -> None:
        """Wait on the source's clock (tests pass a fake clock and sleep)."""
        ...

    def done(self) -> bool:
        """True when no more events will come (live: closed; replay: all given)."""
        ...


class MidiInputBackend(Protocol):
    """Minimal MIDI input: list ports, open one, poll complete messages, close."""

    def port_names(self) -> list[str]: ...

    def open(self, index: int) -> None: ...

    def poll(self) -> bytes | None:
        """Return one pending complete message, or `None` if none is pending."""
        ...

    def close(self) -> None: ...


class RtMidiBackend:
    """`MidiInputBackend` on `python-rtmidi`.

    MIDI clock and active sensing are ignored; SysEx is kept (as raw events).
    """

    def __init__(self) -> None:
        import rtmidi

        self._midi_in = rtmidi.MidiIn()
        self._midi_in.ignore_types(sysex=False, timing=True, active_sense=True)

    def port_names(self) -> list[str]:
        return list(self._midi_in.get_ports())

    def open(self, index: int) -> None:
        self._midi_in.open_port(index)

    def poll(self) -> bytes | None:
        message = self._midi_in.get_message()
        if message is None:
            return None
        return bytes(message[0])

    def close(self) -> None:
        self._midi_in.close_port()
        self._midi_in.delete()


class LiveSource:
    """Live MIDI input as events; a context manager that opens on `open()` or `with`."""

    def __init__(
        self,
        port_match: str = DEFAULT_PORT_MATCH,
        backend: MidiInputBackend | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._port_match = port_match
        self._backend = backend
        self._clock = clock
        self._sleep = sleep
        self._start: float | None = None
        self._port_name: str | None = None

    @property
    def realtime(self) -> bool:
        return True

    @property
    def port_name(self) -> str | None:
        """The opened port's name, or `None` before `open()`."""
        return self._port_name

    def open(self) -> Self:
        """Open the first port whose name contains `port_match`; `t` starts at 0 now."""
        if self._start is not None:
            return self
        if self._backend is None:
            self._backend = RtMidiBackend()
        names = self._backend.port_names()
        needle = self._port_match.casefold()
        for index, name in enumerate(names):
            if needle in name.casefold():
                self._backend.open(index)
                self._port_name = name
                self._start = self._clock()
                return self
        available = ", ".join(repr(n) for n in names) or "none"
        raise PortNotFoundError(
            f"no MIDI input port contains {self._port_match!r}; available: {available}"
        )

    def now(self) -> float:
        """Seconds since the source was opened (the `t` of an event received now)."""
        if self._start is None:
            raise RuntimeError("the source is not open")
        return self._clock() - self._start

    def start(self) -> None:
        """Same as `open()`."""
        self.open()

    def poll(self) -> Event | None:
        """One non-blocking read: the pending message stamped with `now()`, or `None`."""
        if self._start is None or self._backend is None:
            return None
        data = self._backend.poll()
        if data is None:
            return None
        return decode(data, self.now())

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    def done(self) -> bool:
        """True when the port is not open (after `close()`)."""
        return self._start is None

    def events(
        self, duration: float | None = None, stop: Callable[[], bool] | None = None
    ) -> Iterator[Event]:
        """Yield events as received until `close()`, `duration` seconds or `stop()`."""
        self.open()
        while not self.done():
            if duration is not None and self.now() >= duration:
                return
            if stop is not None and stop():
                return
            event = self.poll()
            if event is None:
                self._sleep(POLL_INTERVAL)
                continue
            yield event

    def __iter__(self) -> Iterator[Event]:
        return self.events()

    def close(self) -> None:
        """Close the port; iteration stops."""
        if self._start is not None and self._backend is not None:
            self._backend.close()
        self._start = None

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


class ReplaySource:
    """The events of a recording, as fast as possible or paced in real time."""

    def __init__(
        self,
        recording: Recording | Path | str,
        realtime: bool = False,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not isinstance(recording, Recording):
            recording = read_recording(recording)
        self._recording = recording
        self._realtime = realtime
        self._clock = clock
        self._sleep = sleep
        self._start: float | None = None
        self._next = 0

    @property
    def header(self) -> Header:
        return self._recording.header

    @property
    def realtime(self) -> bool:
        """True when replay is paced in real time (`realtime=True`)."""
        return self._realtime

    def start(self) -> None:
        """Restart from the first event; `now()` starts at 0."""
        self._start = self._clock()
        self._next = 0

    def now(self) -> float:
        """Seconds since `start()`, in the recording's time base."""
        if self._start is None:
            raise RuntimeError("the replay is not started")
        return self._clock() - self._start

    def poll(self) -> Event | None:
        """The next event once its `t` is at or before `now()`, otherwise `None`."""
        events = self._recording.events
        if self._next >= len(events) or events[self._next].t > self.now():
            return None
        self._next += 1
        return events[self._next - 1]

    def sleep(self, seconds: float) -> None:
        self._sleep(seconds)

    def done(self) -> bool:
        """True when every event has been given by `poll()`."""
        return self._start is not None and self._next >= len(self._recording.events)

    def __iter__(self) -> Iterator[Event]:
        start = self._clock()
        for event in self._recording.events:
            if self._realtime:
                wait = event.t - (self._clock() - start)
                if wait > 0:
                    self._sleep(wait)
            yield event


def tee(events: Iterable[Event], path: Path | str, header: Header) -> Generator[Event, None, None]:
    """Pass events through while writing them to `path` as a recording.

    The file is closed when the iteration ends, is closed, or raises.
    """
    with Path(path).open("w", encoding="utf-8") as f:
        f.write(json.dumps(header_to_dict(header)) + "\n")
        for event in events:
            f.write(json.dumps(event_to_dict(event)) + "\n")
            yield event


def record(events: Iterable[Event], path: Path | str, header: Header) -> int:
    """Write all events to `path` as a recording; return the number of events.

    Ctrl-C (`KeyboardInterrupt`) ends the recording normally: the events received
    so far are kept and the file is closed.
    """
    count = 0
    teed = tee(events, path, header)
    try:
        for _ in teed:
            count += 1
    except KeyboardInterrupt:
        pass
    finally:
        teed.close()
    return count
