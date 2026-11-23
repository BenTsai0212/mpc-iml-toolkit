"""`python -m mpc_iml.trial run` (#197): a whole trial without hardware.

The engine is either the real `Engine` in this process (for `EngineLink`) or a fake
handle that keeps the settings it gets. The MPC and the DAW are fakes: on the
first poll of each condition the DAW sends Start and one bar of clock, and the MPC
one pad hit. The musician is a scripted list of answers.
"""

import json
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from test_engine import Receiver
from test_ensemble import LAYER, START, Rig
from test_ensemble_learn import bar_of

from mpc_iml.engine import Engine
from mpc_iml.ensemble import Ensemble
from mpc_iml.recording import read_recording
from mpc_iml.trial.__main__ import build_parser
from mpc_iml.trial.run import (
    START_TEXT,
    TRIAL_CLOCK_NAME,
    ChildEngine,
    EngineLink,
    Musician,
    Settings,
    TickCounter,
    run,
    structure,
)
from mpc_iml.trial.session import read_session
from mpc_iml.trial.spec import load_trial, parse_trial

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


class EnsembleEngine:
    """A handle that gives the settings to an `Ensemble` with a data folder."""

    def __init__(self, data: Path) -> None:
        self.ensemble = Ensemble()
        self.ensemble.data_folder(data)

    def apply(self, settings: Settings) -> list[str]:
        controls = self.ensemble.controls()
        errors: list[str] = []
        for name, args in settings:
            try:
                controls[name](list(args))
            except ValueError as error:
                errors.append(f"{name}: {error}")
        return errors

    def close(self) -> None:
        pass


def trial_file(tmp_path: Path, example: Path = EXAMPLE) -> Path:
    data = json.loads(example.read_text(encoding="utf-8"))
    data["bars"] = 1
    data.pop("min_bars", None)
    path = tmp_path / "trial.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class PlayingEngine(FakeEngine):
    """An `Ensemble` on the simulated clock of `test_ensemble.Rig`, with the settings
    applied so far: `perform` presses pad 16 while Live is stopped, then plays two bars
    with a press, and gives the ensemble's log lines to the trial's `show` (#230)."""

    def __init__(self, show: Callable[[str], None]) -> None:
        super().__init__()
        self.show = show

    def perform(self) -> None:
        rig = Rig(melody=True, bass="loop")
        controls = rig.ensemble.controls()
        for settings in self.applied:
            for name, args in settings:
                controls[name](list(args))
        rig.hit(LAYER)
        rig.send(START)
        bar_of(rig, 0)
        bar_of(rig, 1, press=8)
        for line in rig.log:
            self.show(line)


class PlayingMpc(FakeMpc):
    """`FakeMpc` whose first poll also plays the engine."""

    def __init__(self, daw: FakeDaw, engine: PlayingEngine) -> None:
        super().__init__(daw)
        self.engine = engine

    def poll(self) -> bytes | None:
        if self.pending:
            self.engine.perform()
        return super().poll()


def play_trial(
    tmp_path: Path,
    answers: list[str],
    engine: FakeEngine | EnsembleEngine,
    example: Path = EXAMPLE,
    heard: Callable[[str], None] = lambda line: None,
) -> tuple[int, list[str]]:
    said: list[str] = []
    replies = iter(answers)
    done = threading.Event()

    def say(line: str) -> None:
        said.append(line)
        heard(line)
        if line.startswith("Done."):
            done.set()

    def enter() -> None:
        """Enter once the bars are played, as when the musician is told to."""
        assert done.wait(10)
        done.clear()

    musician = Musician(ask=lambda prompt: next(replies), say=say, enter=enter)
    daw = FakeDaw()
    trial = trial_file(tmp_path, example)
    args = build_parser().parse_args(["run", str(trial), str(tmp_path / "data")])
    args.seed = 0
    made: list[PlayingEngine] = []

    def factory(data: Path, log: Path, options: list[str], show: Callable[[str], None]) -> Any:
        if not isinstance(engine, PlayingEngine):
            return engine
        engine.show = show
        made.append(engine)
        return engine

    def mpc() -> FakeMpc:
        return PlayingMpc(daw, made[0]) if made else FakeMpc(daw)

    status = run(args, musician, factory, mpc, lambda: daw)
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


def test_the_guide_is_shown_once_before_the_first_condition_and_before_each(
    tmp_path: Path,
) -> None:
    """#241: `guide.start` after the setup text, `guide.condition` before every condition."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["guide"] = {"start": ["Lead the band.", "Change the groove."], "condition": "A new band."}
    guided = tmp_path / "guided.json"
    guided.write_text(json.dumps(data), encoding="utf-8")
    status, said = play_trial(tmp_path, SCORES + SCORES + ["ab"], FakeEngine(), guided)
    assert status == 0, said
    plays = [i for i, line in enumerate(said) if "press Play in Live" in line]
    assert len(plays) == 2
    assert said[: plays[0]][-6:] == [
        START_TEXT,
        "Lead the band.",
        "Change the groove.",
        "2 bands, up to 1 bars each.",
        "Band 1 of 2",
        "A new band.",
    ]
    assert said[plays[1] - 2 : plays[1]] == ["Band 2 of 2", "A new band."]
    assert said.count("Lead the band.") == 1 and said.count("A new band.") == 2


def test_a_trial_without_a_guide_shows_only_the_setup_text(tmp_path: Path) -> None:
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    del data["guide"]
    plain = tmp_path / "plain.json"
    plain.write_text(json.dumps(data), encoding="utf-8")
    status, said = play_trial(tmp_path, SCORES + SCORES + ["ab"], FakeEngine(), plain)
    assert status == 0, said
    first = next(i for i, line in enumerate(said) if "press Play in Live" in line)
    assert said[first - 3 : first] == [START_TEXT, "2 bands, up to 1 bars each.", "Band 1 of 2"]


def test_a_refused_setting_stops_before_playing(tmp_path: Path) -> None:
    status, said = play_trial(tmp_path, [], FakeEngine(refuse=True))
    assert status == 1 and said[0].startswith("error: the engine refused")
    (folder,) = (tmp_path / "data" / "trials").iterdir()
    assert not (folder / "session.jsonl").exists()


def test_the_learn_trial_leaves_no_learning_log_before_a_condition_plays(
    tmp_path: Path,
) -> None:
    """#217: the settings check sends each condition's `learn-log 1`; no log is left."""
    engine = EnsembleEngine(tmp_path / "data")
    logs: list[list[Path]] = []

    def heard(line: str) -> None:
        if "press Play" in line:
            logs.append(sorted((tmp_path / "data").glob("learn/log-*.jsonl")))
            assert dict(engine.ensemble.state())["learn-log"] == [1]

    answers = (["3"] * 6 + ["", ""]) * 3 + ["ABC"]
    learn = EXAMPLE.with_name("learn.json")
    status, said = play_trial(tmp_path, answers, engine, learn, heard)
    assert status == 0, said
    assert logs == [[], [], []]


IGNORED = "ensemble: pad 16 ignored, the clock is not running"


@pytest.mark.parametrize("status", [0, 1])
def test_the_trial_shows_the_lines_for_the_musician_while_a_condition_plays(
    tmp_path: Path, status: int
) -> None:
    """#230: the status lines with `status 1`, only the ignored presses with
    `status 0`; nothing else of the engine's log."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert data["base"]["status"] == [0]
    data["base"]["status"] = [status]
    example = tmp_path / "status.json"
    example.write_text(json.dumps(data), encoding="utf-8")
    engine = PlayingEngine(lambda line: None)
    result, said = play_trial(tmp_path, SCORES + SCORES + ["ab"], engine, example)
    assert result == 0, said
    lines = [line for line in said if line.startswith("ensemble: ")]
    statuses = [line for line in lines if line.startswith("ensemble: bar ")]
    assert lines.count(IGNORED) == 2, "one per condition"
    assert len(lines) == 2 + len(statuses)
    if status:
        assert statuses[:2] == [
            "ensemble: bar 0  Am7  groove -  bass -  melody -  16: -  15: -",
            "ensemble: bar 1  Am7  groove -  bass home (rule)  melody home (rule)  16: -  15: -",
        ]
        assert len(statuses) == 2 * 3, "two bar lines and a press, per condition"
    else:
        assert statuses == []
    play = [i for i, line in enumerate(said) if "press Play" in line]
    done = [i for i, line in enumerate(said) if line.startswith("Done.")]
    shown = [i for i, line in enumerate(said) if line.startswith("ensemble: ")]
    assert all(any(p < i < d for p, d in zip(play, done, strict=True)) for i in shown)


def test_the_child_engine_writes_every_line_to_the_log_and_shows_each_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#230: the engine's output goes through a pipe to `engine.log` and to `show`;
    a script stands in for the engine."""
    script = tmp_path / "engine.sh"
    script.write_text(f"#!/bin/sh\necho one\necho '{IGNORED}'\nexec sleep 30\n")
    script.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(script))
    monkeypatch.setattr(EngineLink, "connect", lambda self, wait=15.0: None)
    shown: list[str] = []
    both = threading.Event()

    def show(line: str) -> None:
        shown.append(line)
        if len(shown) == 2:
            both.set()

    log = tmp_path / "engine.log"
    engine = ChildEngine(tmp_path, log, [], show)
    assert both.wait(10)
    engine.close()
    assert shown == ["one", IGNORED]
    assert log.read_text() == f"one\n{IGNORED}\n"


def test_the_structure_is_shown_once_and_the_position_before_each_band(tmp_path: Path) -> None:
    """#243: the number of bands and their length after the start guide, then
    `Band k of n` before each condition's guide."""
    data = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["guide"] = {"start": "Lead the band.", "condition": "A new band."}
    guided = tmp_path / "guided.json"
    guided.write_text(json.dumps(data), encoding="utf-8")
    status, said = play_trial(tmp_path, SCORES + SCORES + ["ab"], FakeEngine(), guided)
    assert status == 0, said
    bands = [line for line in said if line.endswith(" bands, up to 1 bars each.")]
    assert bands == ["2 bands, up to 1 bars each."]
    assert said.index(bands[0]) == said.index("Lead the band.") + 1
    positions = [i for i, line in enumerate(said) if line.startswith("Band ")]
    assert [said[i] for i in positions] == ["Band 1 of 2", "Band 2 of 2"]
    assert all(said[i + 1] == "A new band." for i in positions)


def test_the_structure_line_gives_the_minimum_length_and_minutes_when_the_tempo_is_known() -> None:
    trial = load_trial(EXAMPLE.with_name("learn.json"))[0]
    assert (
        structure(trial, 3, 4, 90.0) == "3 bands, at least 100 bars (about 4 min at 90 BPM) each."
    )
    assert structure(trial, 3, 4, None) == "3 bands, at least 100 bars each."
    assert (
        structure(trial, 6, 4, 120.4) == "6 bands, at least 100 bars (about 3 min at 120 BPM) each."
    )
    assert structure(parse_trial(_with_bars(8)), 2, 4, 90.0) == "2 bands, up to 8 bars each."


def _with_bars(bars: int) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    data["bars"] = bars
    data.pop("min_bars")
    return data


class IdleMpc(FakeMpc):
    """`FakeMpc` that sets `idle` once its hit and the DAW's bar have all been read,
    so the bar is counted before the musician presses Enter."""

    def __init__(self, daw: FakeDaw, idle: threading.Event) -> None:
        super().__init__(daw)
        self.idle = idle

    def poll(self) -> bytes | None:
        data = super().poll()
        if data is None:
            self.idle.set()
        return data


def play_early(tmp_path: Path, min_bars: int, ends: list[str]) -> tuple[int, list[str], list[str]]:
    """A two-band trial of 2 bars, of which the DAW plays one; the musician presses
    Enter after it, answering the early-end question from `ends` (one list for both
    bands), then answers the questions."""
    data = _with_bars(2)
    data["min_bars"] = min_bars
    path = tmp_path / "early.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    said: list[str] = []
    prompts: list[str] = []
    idle = threading.Event()
    replies = iter(ends)
    scores = iter(SCORES + SCORES + ["ab"])

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies) if prompt.startswith("Only ") else next(scores)

    def enter() -> None:
        assert idle.wait(10)

    def mpc() -> FakeMpc:
        idle.clear()
        return IdleMpc(daw, idle)

    musician = Musician(ask=ask, say=said.append, enter=enter)
    daw = FakeDaw()
    args = build_parser().parse_args(["run", str(path), str(tmp_path / "data")])
    args.seed = 0
    status = run(args, musician, lambda *_: FakeEngine(), mpc, lambda: daw)
    return status, said, prompts


ASKED = "Only 1 bars so far (at least 2). End this band anyway? [y/N] "


def test_enter_before_min_bars_asks_and_only_y_ends_the_band(tmp_path: Path) -> None:
    """#243: `n` and an empty answer keep the band playing; `y` (any case) ends it,
    and the session marks it."""
    status, said, prompts = play_early(tmp_path, 2, ["n", "", "Y", "y"])
    assert status == 0, said
    assert [p for p in prompts if p.startswith("Only ")] == [ASKED] * 4
    assert "2 bands, at least 2 bars each." in said
    (folder,) = (tmp_path / "data" / "trials").iterdir()
    session = read_session(folder / "session.jsonl")
    assert [(c.bars, c.ended_early) for c in session.conditions] == [(1, True), (1, True)]


def test_enter_after_min_bars_ends_at_once(tmp_path: Path) -> None:
    status, said, prompts = play_early(tmp_path, 1, [])
    assert status == 0, said
    assert not any(p.startswith("Only ") for p in prompts)
    (folder,) = (tmp_path / "data" / "trials").iterdir()
    session = read_session(folder / "session.jsonl")
    assert [(c.bars, c.ended_early) for c in session.conditions] == [(1, False), (1, False)]
