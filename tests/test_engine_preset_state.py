"""Engine protocol 1.5: preset state replies (ADR 0009, #153).

As in `test_engine.py`, each test starts an engine on free ports and talks OSC to
it. The presets here are test presets with a `state` hook.
"""

import dataclasses
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest
import test_engine
from test_engine import Front, Message

from mpc_iml.clock import ClockAccess
from mpc_iml.demo import PRESET as DEMO
from mpc_iml.engine import PROTOCOL_VERSION
from mpc_iml.presets import Preset, StateReplies

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

PREFIX = "/mpciml/preset/stateful/"


class Stateful:
    """A test preset's state: a mode and a level, with controls and a clock hook."""

    def __init__(self) -> None:
        self.mode = "a"
        self.level = 1
        self.accesses: list[ClockAccess] = []

    def state(self) -> StateReplies:
        return [("mode", [self.mode, "a"]), ("level", [self.level]), ("choices", ["a", "b"])]

    def set_level(self, args: Sequence[Any]) -> None:
        (self.level,) = args

    def fail(self, args: Sequence[Any]) -> None:
        raise ValueError("no")

    def preset(self, **changes: Any) -> Preset:
        base = Preset(
            name="stateful",
            version="0.1",
            controls={"level": self.set_level, "fail": self.fail},
            clock=self.accesses.append,
            state=self.state,
        )
        return dataclasses.replace(base, **changes)


def installed(*extra: Preset) -> Callable[[], Mapping[str, Preset]]:
    found = {"demo": DEMO}
    found.update({p.name: p for p in extra})
    return lambda: found


def replies_of(messages: list[Message]) -> list[Message]:
    return [m for m in messages if m[0].startswith(PREFIX)]


def until_pong(front: Front) -> list[Message]:
    front.send("/mpciml/ping")
    return front.replies.until("/mpciml/pong")[:-1]


EXPECTED = [
    (PREFIX + "mode", ["a", "a"]),
    (PREFIX + "level", [1]),
    (PREFIX + "choices", ["a", "b"]),
]


def test_the_protocol_is_1_5() -> None:
    assert PROTOCOL_VERSION == (1, 5)


def test_full_state_ends_with_the_preset_state_after_clock(start: Any) -> None:
    stateful = Stateful()
    front = start(preset="stateful", presets=installed(stateful.preset()))
    replies = front.ask("/mpciml/state/get")
    addresses = [m[0] for m in replies]
    clock = addresses.index("/mpciml/clock")
    assert addresses[: clock + 1] == [
        "/mpciml/state",
        "/mpciml/preset",
        "/mpciml/layout",
        "/mpciml/names",
        "/mpciml/kit",
        "/mpciml/pads",
        "/mpciml/counts",
        "/mpciml/trained",
        "/mpciml/clock",
    ]
    assert replies[clock + 1 :] == EXPECTED


def test_preset_load_sends_the_state_last(start: Any) -> None:
    stateful = Stateful()
    front = start(presets=installed(stateful.preset()))
    replies = front.ask("/mpciml/preset/load", "stateful")
    assert replies[0] == ("/mpciml/preset", ["stateful", "0.1"])
    assert replies[-len(EXPECTED) :] == EXPECTED
    assert len(replies_of(replies)) == len(EXPECTED)


def test_a_control_that_succeeds_sends_the_new_state(start: Any) -> None:
    stateful = Stateful()
    front = start(preset="stateful", presets=installed(stateful.preset()))
    replies = front.ask(PREFIX + "level", 3)
    assert replies == [EXPECTED[0], (PREFIX + "level", [3]), EXPECTED[2]]


def test_a_control_that_fails_sends_only_the_error(start: Any) -> None:
    stateful = Stateful()
    front = start(preset="stateful", presets=installed(stateful.preset()))
    replies = front.ask(PREFIX + "fail")
    assert [m[0] for m in replies] == ["/mpciml/error"]
    assert replies[0][1][0] == "bad_arguments"


def test_report_sends_the_state_again(start: Any) -> None:
    stateful = Stateful()
    front = start(preset="stateful", presets=installed(stateful.preset()))
    (access,) = stateful.accesses
    stateful.mode = "b"
    access.report()
    assert until_pong(front) == [(PREFIX + "mode", ["b", "a"]), *EXPECTED[1:]]


def test_report_from_a_preset_no_longer_loaded_sends_nothing(start: Any) -> None:
    stateful = Stateful()
    front = start(preset="stateful", presets=installed(stateful.preset()))
    (old,) = stateful.accesses
    front.ask("/mpciml/preset/load", "demo")
    old.report()
    assert until_pong(front) == []
    front.ask("/mpciml/preset/load", "stateful")
    old.report()
    assert until_pong(front) == []
    stateful.accesses[-1].report()
    assert until_pong(front) == EXPECTED


def test_a_preset_without_state_sends_no_preset_replies(start: Any) -> None:
    stateful = Stateful()
    plain = stateful.preset(state=None)
    front = start(preset="stateful", presets=installed(plain))
    assert front.ask("/mpciml/state/get")[-1][0] == "/mpciml/clock"
    assert front.ask(PREFIX + "level", 2) == []
    stateful.accesses[-1].report()
    assert until_pong(front) == []


def test_a_state_hook_that_raises_sends_nothing_and_is_logged(start: Any) -> None:
    lines: list[str] = []

    def broken() -> StateReplies:
        raise RuntimeError("broken")

    front = start(
        preset="stateful",
        presets=installed(Stateful().preset(state=broken)),
        log=lines.append,
    )
    assert front.ask("/mpciml/state/get")[-1][0] == "/mpciml/clock"
    assert any("state failed" in line for line in lines)
    assert front.state() == "idle"


@pytest.mark.parametrize(
    "bad",
    [
        ("Upper", [1]),
        ("with space", [1]),
        ("flag", [True]),
        ("nan", [float("nan")]),
        ("list", [[1, 2]]),
        ("short",),
        "not-a-pair",
    ],
)
def test_invalid_replies_are_skipped_and_logged(start: Any, bad: Any) -> None:
    lines: list[str] = []
    preset = Stateful().preset(state=lambda: [bad, ("ok", [1, 0.5, "x"])])
    front = start(preset="stateful", presets=installed(preset), log=lines.append)
    replies = front.ask("/mpciml/state/get")
    assert replies_of(replies) == [(PREFIX + "ok", [1, 0.5, "x"])]
    assert any("state reply skipped" in line for line in lines)
