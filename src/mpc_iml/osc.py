"""OSC output following Wekinator's defaults (ADR 0002).

A sender sends a fixed-length sequence of floats to one OSC address, host and port.
It does not know about frames or models, so the data layer and the model layer can
both use it:

- gesture features: `inputs_sender()`, `/wek/inputs` on `127.0.0.1:6448`;
- model outputs: `outputs_sender()`, `/wek/outputs` on `127.0.0.1:12000`.

Wekinator expects the same number of values in every message, so a sender fixes the
count on its first message and rejects any later message with a different count.
"""

import math
import struct
from collections.abc import Sequence
from types import TracebackType
from typing import Self

from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.udp_client import UDPClient

__all__ = [
    "DEFAULT_HOST",
    "INPUTS_ADDRESS",
    "INPUTS_PORT",
    "OUTPUTS_ADDRESS",
    "OUTPUTS_PORT",
    "OscSender",
    "ValueCountError",
    "inputs_sender",
    "outputs_sender",
]

DEFAULT_HOST = "127.0.0.1"
"""Default host for both senders (Wekinator on the same Mac)."""

INPUTS_ADDRESS = "/wek/inputs"
"""Wekinator's default address for input features."""

INPUTS_PORT = 6448
"""Wekinator's default port for input features."""

OUTPUTS_ADDRESS = "/wek/outputs"
"""Wekinator's default address for model outputs."""

OUTPUTS_PORT = 12000
"""Wekinator's default port for model outputs."""


class ValueCountError(ValueError):
    """A message has a different number of values from the sender's first message."""


def _to_float32(index: int, value: float) -> float:
    """Return `value` as a float, rejecting values an OSC float32 cannot hold."""
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise TypeError(f"value {index} is not a number: {value!r}") from error
    if not math.isfinite(number):
        raise ValueError(f"value {index} is not finite: {number!r}")
    try:
        struct.pack(">f", number)
    except OverflowError as error:
        raise ValueError(f"value {index} is out of the float32 range: {number!r}") from error
    return number


class OscSender:
    """Sends a fixed number of floats to one OSC address over UDP.

    The defaults are Wekinator's input defaults. Use it as a context manager, or
    call `close()` when done.
    """

    def __init__(
        self, address: str = INPUTS_ADDRESS, host: str = DEFAULT_HOST, port: int = INPUTS_PORT
    ) -> None:
        if not address.startswith("/"):
            raise ValueError(f"OSC address must start with '/': {address!r}")
        if not 0 < port < 65536:
            raise ValueError(f"port must be between 1 and 65535: {port!r}")
        self._address = address
        self._host = host
        self._port = port
        self._count: int | None = None
        self._client = UDPClient(host, port)

    @property
    def address(self) -> str:
        """The OSC address messages are sent to."""
        return self._address

    @property
    def host(self) -> str:
        """The destination host."""
        return self._host

    @property
    def port(self) -> int:
        """The destination UDP port."""
        return self._port

    @property
    def count(self) -> int | None:
        """The number of values per message, or `None` before the first message."""
        return self._count

    def send(self, values: Sequence[float]) -> None:
        """Send `values` as OSC floats.

        Raises `ValueCountError` if the number of values differs from the first
        message, `ValueError` for an empty sequence or a non-finite value, and
        `TypeError` for a value that is not a number. Nothing is sent when it raises.
        """
        floats = [_to_float32(index, value) for index, value in enumerate(values)]
        if not floats:
            raise ValueError("cannot send an empty sequence of values")
        if self._count is not None and len(floats) != self._count:
            raise ValueCountError(
                f"{self._address} expects {self._count} values (fixed by the first "
                f"message), got {len(floats)}"
            )
        builder = OscMessageBuilder(address=self._address)
        for number in floats:
            builder.add_arg(number, OscMessageBuilder.ARG_TYPE_FLOAT)
        self._client.send(builder.build())
        self._count = len(floats)

    def close(self) -> None:
        """Close the UDP socket."""
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"OscSender({self._address!r}, host={self._host!r}, port={self._port!r})"


def inputs_sender(
    address: str = INPUTS_ADDRESS, host: str = DEFAULT_HOST, port: int = INPUTS_PORT
) -> OscSender:
    """A sender for gesture features, with Wekinator's input defaults."""
    return OscSender(address, host, port)


def outputs_sender(
    address: str = OUTPUTS_ADDRESS, host: str = DEFAULT_HOST, port: int = OUTPUTS_PORT
) -> OscSender:
    """A sender for model outputs, with Wekinator's output defaults."""
    return OscSender(address, host, port)
