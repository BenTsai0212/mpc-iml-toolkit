"""`python -m mpc_iml.trial run` (#197): a whole trial without hardware.

The engine is either the real `Engine` in this process (for `EngineLink`) or a fake
handle that keeps the settings it gets. The MPC and the DAW are fakes: on the
first poll of each condition the DAW sends Start and one bar of clock, and the MPC
one pad hit. The musician is a scripted list of answers.
"""

import json
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_engine import Receiver

from mpc_iml.engine import Engine
from mpc_iml.recording import read_recording
from mpc_iml.trial.__main__ import build_parser
from mpc_iml.trial.run import TRIAL_CLOCK_NAME, EngineLink, Musician, Settings, TickCounter, run
from mpc_iml.trial.session import read_session

EXAMPLE = Path(__file__).parent.parent / "examples" / "trial" / "rhythm.json"
BAR = [b"\xfa"] + [b"\xf8"] * 96
"""Start and one 4/4 bar of Timing Clock."""


@pytest.fixture
def link(tmp_path: Path) -> Iterator[tuple[EngineLink, Receiver]]:
    old = Receiver()
    engine = Engine(tmp_path / "data", None, preset="ensemble", control_port=0, reply_port=old.port)
    engine.start()
    thread = threading.Thread(target=engine.serve_forever, daemon=True)
    thread.start()
    made = EngineLink(engine.control_port)
    yield made, old
    made.close()
    engine.close()
    thread.join(10)
    old.close()


def test_link_claims_the_reply_port_and_reports_refused_settings(link: Any) -> None:
    made, old = link
    made.connect()
    assert made.apply([("rhythm", (1,)), ("surprise", (0,))]) == []
    errors = made.apply([("rhythm", (9,))])
    assert len(errors) == 1 and errors[0].startswith("bad_arguments")
    old.sock.settimeout(0.2)
    with pytest.raises(TimeoutError):
        old.sock.recv(65536)


def test_ticks_are_counted_from_start() -> None:
    counter = TickCounter(2)
    for data in [b"\xf8", b"\xfa", b"\xf8", b"\x90\x24\x10", b"\xf8"]:
        counter.see(data)
    assert counter.ticks == 2 and counter.done


class FakeDaw:
    """The recorder's clock input: `play` sends Start and a bar to the callback."""

    def __init__(self) -> None:
        self.opened = ""
        self.callback: Callable[[bytes], None] | None = None

    def port_names(self) -> list[str]:
        return []

    def open(self, index: int) -> None:
        raise AssertionError("the trial opens a virtual port")

    def open_virtual(self, name: str) -> None:
        self.opened = name

    def set_callback(self, callback: Callable[[bytes], None]) -> None:
        self.callback = callback

    def close(self) -> None:
        pass

    def play(self) -> None:
        assert self.callback is not None
        for data in BAR:
            self.callback(data)


class FakeMpc:
    """One pad hit; the DAW plays when it is first polled."""

    def __init__(self, daw: FakeDaw) -> None:
        self.daw = daw
        self.pending = [b"\x90\x24\x40"]

    def port_names(self) -> list[str]:
        return ["MPC Sample"]

    def open(self, index: int) -> None:
        pass

    def poll(self) -> bytes | None:
        if self.pending:
            self.daw.play()
            return self.pending.pop()
        return None

    def close(self) -> None:
        pass


class FakeEngine:
    def __init__(self, refuse: bool = False) -> None:
        self.applied: list[Settings] = []
        self.refuse = refuse

    def apply(self, settings: Settings) -> list[str]:
        self.applied.append(settings)
        return ["bad_arguments rhythm"] if self.refuse else []

    def close(self) -> None:
        pass


def trial_file(tmp_path: Path) -> Path:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["bars"] = 1
    path = tmp_path / "trial.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def play_trial(tmp_path: Path, answers: list[str], engine: FakeEngine) -> tuple[int, list[str]]:
    said: list[str] = []
    replies = iter(answers)
    done = threading.Event()

    def say(line: str) -> None:
        said.append(line)
        if line.startswith("Done."):
            done.set()

    def enter() -> None:
        """Enter once the bars are played, as when the musician is told to."""
        assert done.wait(10)
        done.clear()

    musician = Musician(ask=lambda prompt: next(replies), say=say, enter=enter)
    daw = FakeDaw()
    args = build_parser().parse_args(["run", str(trial_file(tmp_path)), str(tmp_path / "data")])
    args.seed = 0
    status = run(args, musician, lambda *_: engine, lambda: FakeMpc(daw), lambda: daw)
    assert daw.opened == TRIAL_CLOCK_NAME
    return status, said


SCORES = ["4", "7", "3", "5", "2", "1", "on the fill", ""]
"""One condition's answers: five scores (7 is asked again), then two texts."""


def test_a_whole_trial(tmp_path: Path) -> None:
    engine = FakeEngine()
    status, said = play_trial(tmp_path, SCORES + SCORES + ["ba"], engine)
    assert status == 0
    reveal = said.index("The conditions were:")
    assert not any("rhythm-" in line for line in said[:reveal])
    assert said[reveal + 1 :][:2] == ["  A: rhythm-0", "  B: rhythm-1"]
    assert "Please type a whole number 1-5." in said
    assert len(engine.applied) == 4 and engine.applied[-1][-1] == ("rhythm", (1,))
    (folder,) = (tmp_path / "data" / "trials").iterdir()
    session = read_session(folder / "session.jsonl")
    assert session.header.order == ["A", "B"] and session.header.seed == 0
    assert session.ranking == ("B", "A")
    first = session.conditions[0]
    assert first.recording == "A.jsonl" and first.bars == 1
    assert first.scores == {"heard-me": 4, "leading": 3, "mine": 5, "sounds-good": 2, "fun": 1}
    assert first.answers == {"heard-moment": "on the fill", "broken-moment": ""}
    events = read_recording(folder / "B.jsonl").events
    assert sum(1 for e in events if getattr(e, "data", b"") == b"\xf8") == 96


def test_a_refused_setting_stops_before_playing(tmp_path: Path) -> None:
    status, said = play_trial(tmp_path, [], FakeEngine(refuse=True))
    assert status == 1 and said[0].startswith("error: the engine refused")
    (folder,) = (tmp_path / "data" / "trials").iterdir()
    assert not (folder / "session.jsonl").exists()
