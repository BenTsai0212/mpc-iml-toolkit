"""OSC sender: Wekinator defaults, fixed value count, and delivery to a local server.

Every test that sends uses an OSC server on an ephemeral port on 127.0.0.1.
"""

import math
from collections.abc import Iterator

import pytest
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import BlockingOSCUDPServer

from mpc_iml import osc

LOCALHOST = "127.0.0.1"


class LocalServer:
    """A blocking OSC server on an ephemeral port that records received messages."""

    def __init__(self) -> None:
        self.received: list[tuple[str, tuple[object, ...]]] = []
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._record)
        self._server = BlockingOSCUDPServer((LOCALHOST, 0), dispatcher)
        self._server.timeout = 2.0
        self.port: int = self._server.server_address[1]

    def _record(self, address: str, *args: object) -> None:
        self.received.append((address, args))

    def receive(self) -> tuple[str, tuple[object, ...]]:
        """Wait for one message and return its address and arguments."""
        before = len(self.received)
        self._server.handle_request()
        assert len(self.received) == before + 1, "no OSC message arrived"
        return self.received[-1]

    def close(self) -> None:
        self._server.server_close()


@pytest.fixture
def server() -> Iterator[LocalServer]:
    local = LocalServer()
    yield local
    local.close()


def test_wekinator_defaults() -> None:
    assert osc.DEFAULT_HOST == "127.0.0.1"
    assert (osc.INPUTS_ADDRESS, osc.INPUTS_PORT) == ("/wek/inputs", 6448)
    assert (osc.OUTPUTS_ADDRESS, osc.OUTPUTS_PORT) == ("/wek/outputs", 12000)


def test_factory_defaults() -> None:
    with osc.inputs_sender() as inputs, osc.outputs_sender() as outputs:
        assert (inputs.address, inputs.host, inputs.port) == ("/wek/inputs", "127.0.0.1", 6448)
        assert (outputs.address, outputs.host, outputs.port) == (
            "/wek/outputs",
            "127.0.0.1",
            12000,
        )
    with osc.OscSender() as default:
        assert (default.address, default.host, default.port) == ("/wek/inputs", "127.0.0.1", 6448)


def test_sends_address_and_values(server: LocalServer) -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, server.port) as sender:
        sender.send([0.0, 0.5, 1.0, 7.0])
    address, args = server.receive()
    assert address == "/wek/inputs"
    assert args == (0.0, 0.5, 1.0, 7.0)


def test_values_are_sent_as_floats(server: LocalServer) -> None:
    with osc.outputs_sender(host=LOCALHOST, port=server.port) as sender:
        sender.send([1, 2, 3])
    address, args = server.receive()
    assert address == "/wek/outputs"
    assert args == (1.0, 2.0, 3.0)
    assert all(type(arg) is float for arg in args)


def test_address_host_and_port_are_configurable(server: LocalServer) -> None:
    with osc.inputs_sender(address="/my/features", host=LOCALHOST, port=server.port) as sender:
        assert (sender.address, sender.host, sender.port) == (
            "/my/features",
            LOCALHOST,
            server.port,
        )
        sender.send((0.25,))
    assert server.receive() == ("/my/features", (0.25,))


def test_accepts_any_sequence(server: LocalServer) -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, server.port) as sender:
        sender.send([0.1, 0.2])
        sender.send((0.3, 0.4))
        sender.send(range(2))
    received = [server.receive()[1] for _ in range(3)]
    assert received == [
        pytest.approx((0.1, 0.2)),
        pytest.approx((0.3, 0.4)),
        (0.0, 1.0),
    ]


def test_count_is_fixed_by_first_message(server: LocalServer) -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, server.port) as sender:
        assert sender.count is None
        sender.send([0.0] * 49)
        assert sender.count == 49
        with pytest.raises(osc.ValueCountError, match="expects 49 values.*got 48"):
            sender.send([0.0] * 48)
        sender.send([1.0] * 49)
    first = server.receive()
    second = server.receive()
    assert len(first[1]) == 49
    assert second[1] == (1.0,) * 49


def test_value_count_error_is_a_value_error() -> None:
    assert issubclass(osc.ValueCountError, ValueError)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, 1e300])
def test_rejects_non_finite_values(bad: float) -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, 9) as sender:
        with pytest.raises(ValueError, match="value 1"):
            sender.send([0.0, bad])
        assert sender.count is None


def test_rejected_message_does_not_fix_count(server: LocalServer) -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, server.port) as sender:
        with pytest.raises(ValueError):
            sender.send([math.nan])
        sender.send([0.0, 1.0])
        assert sender.count == 2
    assert server.receive() == ("/wek/inputs", (0.0, 1.0))


def test_rejects_non_numbers() -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, 9) as sender:
        with pytest.raises(TypeError, match="value 0 is not a number"):
            sender.send(["loud"])  # type: ignore[list-item]


def test_rejects_empty_sequence() -> None:
    with osc.OscSender("/wek/inputs", LOCALHOST, 9) as sender:
        with pytest.raises(ValueError, match="empty"):
            sender.send([])


@pytest.mark.parametrize("address", ["", "wek/inputs"])
def test_rejects_invalid_address(address: str) -> None:
    with pytest.raises(ValueError, match="must start with '/'"):
        osc.OscSender(address, LOCALHOST, 9)


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_rejects_invalid_port(port: int) -> None:
    with pytest.raises(ValueError, match="port"):
        osc.OscSender("/wek/inputs", LOCALHOST, port)
