"""Running a blind trial (#197): `python -m mpc_iml.trial run <trial file> <data folder>`.

The trial starts the engine as a child process (`--preset ensemble --clock`, its
output in `engine.log` in the session folder) and claims its reply port with
`/mpciml/hello`, so neither the log nor the state replies show a condition. Every
condition's settings are checked once before playing. Then, in the seeded order:

1. `base` and the condition's settings go to the engine (while Live is stopped);
2. the musician plays; the MPC and MIDI clock are recorded to `<letter>.jsonl` on a
   second virtual clock input, `mpc-iml trial clock`, until `bars` bars from Start
   or Enter;
3. the questions of the trial file are asked, and a `condition` record is written.

Last come the ranking and the reveal. The terminal only shows code letters until then.
"""

import argparse
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Protocol

from pythonosc.osc_message import OscMessage
from pythonosc.udp_client import SimpleUDPClient

from mpc_iml import __version__
from mpc_iml.events import Event, RawMidiEvent
from mpc_iml.osc import DEFAULT_HOST
from mpc_iml.recording import Header as RecordingHeader
from mpc_iml.sources import (
    CLOCK_BYTES,
    DEFAULT_PORT_MATCH,
    ClockInput,
    ClockInputBackend,
    LiveSource,
    MidiInputBackend,
    PortNotFoundError,
    RtMidiClockBackend,
    record,
)
from mpc_iml.trial.order import letters, trial_order
from mpc_iml.trial.session import (
    SESSION_FILE,
    ConditionRecord,
    Header,
    SessionWriter,
    git_commit,
    session_folder,
)
from mpc_iml.trial.spec import Arg, Question, Trial, TrialError, load_trial

__all__ = [
    "PREFIX",
    "TRIAL_CLOCK_NAME",
    "ChildEngine",
    "EngineLink",
    "LinkError",
    "Musician",
    "Settings",
    "TickCounter",
    "add_run_parser",
    "run",
]

PREFIX = "/mpciml/"
CONTROL = PREFIX + "preset/ensemble/"
TRIAL_CLOCK_NAME = "mpc-iml trial clock"
TICKS_PER_BEAT = 24
START, TICK = 0xFA, 0xF8
START_TEXT = (
    "Before playing: close Pure Data (its group 8 shows the settings), fold the band's "
    "tracks in Live, and turn on Sync for both 'mpc-iml clock' and "
    f"'{TRIAL_CLOCK_NAME}' (Settings > Link, Tempo & MIDI)."
)

Settings = list[tuple[str, tuple[Arg, ...]]]
Message = tuple[str, list[Any]]


class LinkError(Exception):
    """The engine does not answer."""


class EngineLink:
    """OSC to the engine's control port; replies come to a socket of its own."""

    def __init__(self, control_port: int, host: str = DEFAULT_HOST) -> None:
        self.control_port = control_port
        self._client = SimpleUDPClient(host, control_port)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((DEFAULT_HOST, 0))
        self.port: int = self._sock.getsockname()[1]

    def ask(self, messages: Sequence[Message], timeout: float = 5.0) -> list[Message]:
        """Send `messages`, then `ping`; return the replies before the `pong`."""
        for address, args in messages:
            self._client.send_message(address, args)
        self._client.send_message(PREFIX + "ping", [])
        replies: list[Message] = []
        deadline = time.monotonic() + timeout
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise LinkError(f"no reply from the engine in {timeout} s")
            self._sock.settimeout(left)
            try:
                message = OscMessage(self._sock.recv(65536))
            except TimeoutError:
                continue
            if message.address == PREFIX + "pong":
                return replies
            replies.append((message.address, list(message.params)))

    def connect(self, wait: float = 15.0) -> None:
        """Say `hello` with this link's port until the engine answers (it may be starting)."""
        deadline = time.monotonic() + wait
        while True:
            try:
                self.ask([(PREFIX + "hello", [1, self.port])], timeout=0.5)
                return
            except LinkError:
                if time.monotonic() >= deadline:
                    raise

    def apply(self, settings: Settings) -> list[str]:
        """Send `ensemble` controls; return the engine's error messages, if any."""
        replies = self.ask([(CONTROL + name, list(args)) for name, args in settings])
        return [" ".join(map(str, args)) for address, args in replies if address.endswith("error")]

    def close(self) -> None:
        self._sock.close()


class EngineHandle(Protocol):
    def apply(self, settings: Settings) -> list[str]: ...

    def close(self) -> None: ...


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.bind((DEFAULT_HOST, 0))
        return int(sock.getsockname()[1])


class ChildEngine:
    """`python -m mpc_iml.engine` as a child process, its output in `log`."""

    def __init__(self, data: Path, log: Path, options: Sequence[str]) -> None:
        self._log: IO[bytes] = log.open("wb")
        self.link = EngineLink(free_port())
        command = [sys.executable, "-m", "mpc_iml.engine", str(data), "--preset", "ensemble"]
        command += ["--control-port", str(self.link.control_port)]
        command += ["--reply-port", str(self.link.port), *options]
        self._process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT)
        try:
            self.link.connect()
        except LinkError:
            self.close()
            raise LinkError(f"the engine did not start; see {log}") from None

    def apply(self, settings: Settings) -> list[str]:
        return self.link.apply(settings)

    def close(self) -> None:
        self._process.terminate()
        try:
            self._process.wait(5)
        except subprocess.TimeoutExpired:
            self._process.kill()
        self.link.close()
        self._log.close()


class TickCounter:
    """Counts Timing Clock ticks from the first Start; `done` after `limit` ticks."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.ticks = 0
        self.started = False

    def see(self, data: bytes) -> None:
        if data[:1] == bytes([START]):
            self.started = True
        elif data[:1] == bytes([TICK]) and self.started:
            self.ticks += 1

    @property
    def done(self) -> bool:
        return self.ticks >= self.limit


@dataclass
class Musician:
    """The terminal: `ask` reads a line, `say` prints one, `enter` waits for Enter."""

    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    enter: Callable[[], object] = input


def ask_question(question: Question, musician: Musician) -> int | str:
    while True:
        answer = musician.ask(f"{question.text} ({question.scale}): ").strip()
        if question.scale == "text":
            return answer
        if answer in {"1", "2", "3", "4", "5"}:
            return int(answer)
        musician.say("Please type a whole number 1-5.")


def ask_ranking(codes: Sequence[str], musician: Musician) -> list[str]:
    while True:
        answer = list(musician.ask(f"Rank {''.join(codes)}, best first: ").strip().upper())
        if sorted(answer) == sorted(codes):
            return answer
        musician.say(f"Please type each of {' '.join(codes)} once, for example {''.join(codes)}.")


@dataclass
class Rig:
    """What a trial plays on: the engine, the MPC input (a backend per condition) and
    `sources`, the source being recorded, which the recorder's clock injects into."""

    engine: EngineHandle
    mpc: Callable[[], MidiInputBackend | None]
    port: str
    options: dict[str, Any]
    sources: list[LiveSource] = field(default_factory=list)


def play(rig: Rig, path: Path, limit: int, musician: Musician) -> int:
    """Record one condition to `path`; return the ticks counted from Start."""
    counter = TickCounter(limit)
    ended = threading.Event()
    source = LiveSource(port_match=rig.port, backend=rig.mpc())
    source.open()
    rig.sources[:] = [source]

    def wait_enter() -> None:
        musician.enter()
        ended.set()

    waiter = threading.Thread(target=wait_enter, daemon=True)
    waiter.start()
    try:
        events = source.events(stop=lambda: counter.done or ended.is_set())
        record(_counted(events, counter.see), path, RecordingHeader())
    finally:
        rig.sources.clear()
        source.close()
    if not ended.is_set():
        musician.say("Done. Press Stop in Live, then Enter.")
        waiter.join()
    return counter.ticks


def _counted(events: Iterator[Event], see: Callable[[bytes], None]) -> Iterator[Event]:
    for event in events:
        if isinstance(event, RawMidiEvent):
            see(event.data)
        yield event


def run_trial(
    trial: Trial, content: dict[str, Any], args: argparse.Namespace, rig: Rig, musician: Musician
) -> int:
    """Play a whole trial into `args.folder`; 0 on success."""
    seed, repeats, beats_per_bar = args.seed, args.repeats, args.beats_per_bar
    for condition in trial.conditions:
        if errors := rig.engine.apply(trial.messages(condition)):
            musician.say(f"error: the engine refused a setting of {condition.name}: {errors}")
            return 1
    order = trial_order(len(trial.conditions), seed, repeats)
    codes = letters(order)
    commit, dirty = git_commit(Path(__file__).parent)
    header = Header(
        date=datetime.now().astimezone().isoformat(timespec="seconds"),
        commit=commit,
        dirty=dirty,
        version=__version__,
        trial_file=args.trial,
        trial=content,
        seed=seed,
        repeats=repeats,
        order=[codes[i] for i in order],
        mapping={codes[i]: trial.conditions[i].name for i in codes},
        engine=rig.options,
    )
    writer = SessionWriter(args.folder / SESSION_FILE, header)
    musician.say(START_TEXT)
    limit = trial.bars * beats_per_bar * TICKS_PER_BEAT
    played: dict[str, int] = {}
    for position, index in enumerate(order):
        letter = codes[index]
        played[letter] = played.get(letter, 0) + 1
        name = letter if played[letter] == 1 else f"{letter}-{played[letter]}"
        errors = rig.engine.apply(trial.messages(trial.conditions[index]))
        musician.say(f"Condition {letter}: press Play in Live ({trial.bars} bars, Enter ends).")
        ticks = play(rig, args.folder / f"{name}.jsonl", limit, musician)
        bars = ticks // (beats_per_bar * TICKS_PER_BEAT)
        musician.say(f"Condition {letter}: {bars} bars. Questions:")
        scores: dict[str, int] = {}
        answers: dict[str, str] = {}
        for question in trial.questions:
            answer = ask_question(question, musician)
            if isinstance(answer, int):
                scores[question.id] = answer
            else:
                answers[question.id] = answer
        writer.condition(
            ConditionRecord(letter, position, f"{name}.jsonl", bars, scores, answers, errors)
        )
    ranking = ask_ranking(sorted(header.mapping), musician)
    writer.ranking(ranking)
    musician.say("The conditions were:")
    for letter in sorted(header.mapping):
        musician.say(f"  {letter}: {header.mapping[letter]}")
    musician.say(f"Session: {writer.path}")
    return 0


def add_run_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("trial", help="trial file (format mpc-iml-trial)")
    parser.add_argument("data", help="the engine's data folder; sessions go to <data>/trials/")
    parser.add_argument("--seed", type=int, default=None, help="order seed (default: the time)")
    parser.add_argument("--repeats", type=int, default=1, help="play the order this many times")
    parser.add_argument("--port", default=DEFAULT_PORT_MATCH, help="MPC input port name contains")
    parser.add_argument(
        "--clock-port",
        default=None,
        help="read clock from the input port containing this text (e.g. IAC) for both the "
        f"engine and the recorder, instead of 'mpc-iml clock' and '{TRIAL_CLOCK_NAME}'",
    )
    parser.add_argument("--beats-per-bar", type=int, default=4, help="quarter notes per bar")


EngineFactory = Callable[[Path, Path, list[str]], EngineHandle]


def run(
    args: argparse.Namespace,
    musician: Musician | None = None,
    engine: EngineFactory = ChildEngine,
    mpc: Callable[[], MidiInputBackend | None] = lambda: None,
    clock_backend: Callable[[], ClockInputBackend] = RtMidiClockBackend,
) -> int:
    """`trial run`: returns the exit status."""
    musician = musician or Musician()
    if args.repeats < 1 or args.beats_per_bar < 1:
        print("error: --repeats and --beats-per-bar must be at least 1", file=sys.stderr)
        return 2
    try:
        trial, content = load_trial(Path(args.trial))
    except TrialError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    data = Path(args.data)
    if args.seed is None:
        args.seed = int(time.time())
    options = ["--clock", "--port", args.port, "--beats-per-bar", str(args.beats_per_bar)]
    if args.clock_port is not None:
        options += ["--clock-port", args.clock_port]
    args.folder = session_folder(data, datetime.now())
    sources: list[LiveSource] = []

    def on_clock(message: bytes) -> None:
        if message and message[0] in CLOCK_BYTES:
            for source in list(sources):
                source.inject(message)

    clock = ClockInput(on_clock, args.clock_port, clock_backend, name=TRIAL_CLOCK_NAME)
    try:
        clock.open()
    except PortNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        handle = engine(data, args.folder / "engine.log", options)
    except LinkError as error:
        clock.close()
        print(f"error: {error}", file=sys.stderr)
        return 1
    try:
        recorder = {"options": options, "recorder_clock": clock.port_name}
        rig = Rig(handle, mpc, args.port, recorder, sources)
        return run_trial(trial, content, args, rig, musician)
    except PortNotFoundError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    finally:
        handle.close()
        clock.close()
