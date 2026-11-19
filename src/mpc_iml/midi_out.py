"""MIDI control change output for model predictions (#65).

`MidiCcSender` sends each prediction as control changes, one controller per value,
as declared by a preset's `MidiCcOutput`. By default it opens a virtual output port
(`MidiCcOutput.port_name`, `mpc-iml`): on macOS this appears directly as a MIDI
source in any DAW, so the IAC driver does not need to be set up. With `port_match`
it sends instead to the first existing output port whose name contains that text
(case-insensitive), for example `IAC`.

A controller is only sent when its 0-127 value changes, so a steady prediction at
100 frames/s does not flood the port. `send_controller` sends one controller on its
own, for MIDI learn in a DAW (`/mpciml/midi/learn`, ADR 0005). `send_message` sends
any raw message, for notes the clock scheduler plays (ADR 0008).

`RtMidiOutBackend` wraps `python-rtmidi`; tests pass a fake `MidiOutputBackend`.
"""

from collections.abc import Callable, Sequence
from typing import Protocol

from mpc_iml.presets import MidiCcOutput
from mpc_iml.sources import PortNotFoundError

__all__ = ["MidiCcSender", "MidiOutputBackend", "RtMidiOutBackend"]


class MidiOutputBackend(Protocol):
    """Minimal MIDI output: list ports, open one or a virtual one, send, close."""

    def port_names(self) -> list[str]: ...

    def open(self, index: int) -> None: ...

    def open_virtual(self, name: str) -> None:
        """Create a virtual output port that other applications see as a source."""
        ...

    def send(self, message: bytes) -> None: ...

    def close(self) -> None: ...


class RtMidiOutBackend:
    """`MidiOutputBackend` on `python-rtmidi` (virtual ports need macOS or Linux)."""

    def __init__(self) -> None:
        import rtmidi

        self._midi_out = rtmidi.MidiOut()

    def port_names(self) -> list[str]:
        return list(self._midi_out.get_ports())

    def open(self, index: int) -> None:
        self._midi_out.open_port(index)

    def open_virtual(self, name: str) -> None:
        self._midi_out.open_virtual_port(name)

    def send(self, message: bytes) -> None:
        self._midi_out.send_message(list(message))

    def close(self) -> None:
        self._midi_out.close_port()
        self._midi_out.delete()


class MidiCcSender:
    """Sends predictions as MIDI control changes; open it before `send`.

    `port_match` `None` opens a virtual port named `output.port_name`; otherwise
    the first existing port whose name contains `port_match`.
    """

    def __init__(
        self,
        output: MidiCcOutput,
        port_match: str | None = None,
        backend: Callable[[], MidiOutputBackend] = RtMidiOutBackend,
    ) -> None:
        self.output = output
        self.port_match = port_match
        self._backend_factory = backend
        self._backend: MidiOutputBackend | None = None
        self._last: dict[int, int] = {}
        self.port_name: str | None = None
        """The opened port's name, or `None` before `open()`."""

    def open(self) -> None:
        """Open the port; raises `PortNotFoundError` or the backend's error."""
        if self._backend is not None:
            return
        backend = self._backend_factory()
        try:
            if self.port_match is None:
                backend.open_virtual(self.output.port_name)
                self.port_name = self.output.port_name
            else:
                names = backend.port_names()
                needle = self.port_match.casefold()
                index = next((i for i, n in enumerate(names) if needle in n.casefold()), None)
                if index is None:
                    available = ", ".join(repr(n) for n in names) or "none"
                    raise PortNotFoundError(
                        f"no MIDI output port contains {self.port_match!r}; available: {available}"
                    )
                backend.open(index)
                self.port_name = names[index]
        except BaseException:
            backend.close()
            raise
        self._backend = backend

    def send(self, values: Sequence[float]) -> None:
        """Send the controllers whose value changed; raises `ValueError` for a bad count."""
        messages = self.output.messages(values)
        if self._backend is None:
            raise RuntimeError("the MIDI output is not open")
        for message in messages:
            controller, value = message[1], message[2]
            if self._last.get(controller) != value:
                self._backend.send(message)
                self._last[controller] = value

    def send_controller(self, index: int, value: int) -> None:
        """Send one control change: controller `index` (0-based) set to `value` (0-127).

        Always sent, also when the value did not change, and recorded as the last
        value so `send` keeps sending only changes afterwards.
        """
        if not 0 <= value <= 127:
            raise ValueError(f"value must be 0-127: {value}")
        controller = self.output.controllers[index]
        if self._backend is None:
            raise RuntimeError("the MIDI output is not open")
        self._backend.send(bytes([0xB0 | (self.output.channel - 1), controller, value]))
        self._last[controller] = value

    def send_message(self, message: bytes) -> None:
        """Send one raw MIDI message as it is (for example a Note On), on the same port.

        Control changes sent this way are not recorded as last values.
        """
        if self._backend is None:
            raise RuntimeError("the MIDI output is not open")
        self._backend.send(bytes(message))

    def last_value(self, index: int) -> int | None:
        """The last value sent on controller `index` (0-based), or `None`."""
        return self._last.get(self.output.controllers[index])

    def close(self) -> None:
        """Close the port; the next `open()` starts with every controller unsent."""
        if self._backend is not None:
            self._backend.close()
            self._backend = None
        self._last = {}
