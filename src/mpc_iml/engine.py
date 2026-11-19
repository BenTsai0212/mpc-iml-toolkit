"""The engine: a long-running IML loop driven by OSC control messages (ADR 0004).

Front ends (Pure Data, Max, later an app) send control messages under `/mpciml/` to
the control port (default `127.0.0.1:6450`) and receive replies and state reports on
the reply port (default `127.0.0.1:6451`; `hello` can change it). While running, the
engine sends `/wek/inputs` and the active preset's outputs as in ADR 0002: every
declared output, OSC (`OscOutput`) and MIDI control changes (`MidiCcOutput`, on a
virtual port, or an existing port with `--midi-port`). An output that cannot be
opened is logged and skipped; the others keep working. `/mpciml/midi/learn` sends
one MIDI controller on its own so a DAW can learn it (protocol 1.1, ADR 0005).
`/mpciml/layout` tells a front end the active preset's number of targets and MIDI
controllers, so it can show the right controls (protocol 1.2, ADR 0006).
Protocol 1.3 (ADR 0007) adds kits and modules for presets with named outputs:
`kit/load` replaces the example set with a kit's generated takes, `pad/module`
changes one pad's module, both followed by automatic training, and
`pad/select/start` reports pad hits so a front end can select a pad on the MPC.
Protocol 1.4 (ADR 0008) adds MIDI clock sync, off unless `--clock`: the engine reads
clock from a DAW on a virtual input `mpc-iml clock` (or `--clock-port`), reports
`/mpciml/clock` and gives presets with a `clock` hook the grid position of pad hits.

Start it with `python -m mpc_iml.engine <data folder>`. The engine only writes inside
that folder: `examples/save` writes `<data folder>/<name>.jsonl`.

Gesture input is read continuously from one event source (the MPC, or a recording
with `--replay`), so the pad state is known before `record/start`. Recording keeps
the frames between `record/start` and `record/stop` as examples with the current
class or targets. The example set is also kept as one recording (ADR 0002 format)
for `examples/save`: each recorded frame is written as the MIDI events that give its
pad state, one frame interval apart, so loading the file gives the same examples,
also when the real-time frame loop dropped late frames during a take (#73). Takes
generated from a kit are kept apart (`GeneratedSet`) and written after the recorded
ones, as recording format version 2.

Threads: control messages are handled one at a time on the server thread; frames
are handled on the input thread; training runs on its own thread; MIDI clock arrives
on the clock input's thread. A lock keeps them consistent.
"""

import argparse
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import BlockingOSCUDPServer
from pythonosc.udp_client import UDPClient

from mpc_iml import __version__
from mpc_iml.clock import ClockAccess, ClockState, MidiClock, off_state
from mpc_iml.content import ContentError, Library, UnknownContentError, load_library
from mpc_iml.events import Event, ExampleEnd, ExampleStart, MidiEvent, MidiKind, RawMidiEvent
from mpc_iml.examples import ExampleError, ExampleSet
from mpc_iml.frames import (
    DEFAULT_RATE,
    PADS,
    Frame,
    PadState,
    bank_pad_to_note,
    frames,
    note_to_bank_pad,
    realtime_frames,
)
from mpc_iml.generation import GeneratedSet, split_generated, with_generated
from mpc_iml.loop import FanOut, IMLLoop, ValuesSender
from mpc_iml.midi_out import MidiCcSender, MidiOutputBackend, RtMidiOutBackend
from mpc_iml.osc import DEFAULT_HOST, INPUTS_ADDRESS, INPUTS_PORT, OscSender
from mpc_iml.presets import (
    RESERVED_NAMES,
    MidiCcOutput,
    OscOutput,
    Preset,
    PresetError,
    available_presets,
)
from mpc_iml.recording import Header, read_recording, write_recording
from mpc_iml.sources import (
    DEFAULT_PORT_MATCH,
    ClockedSource,
    ClockInput,
    ClockInputBackend,
    LiveSource,
    ReplaySource,
    RtMidiClockBackend,
)

__all__ = [
    "CONTROL_PORT",
    "PROTOCOL_VERSION",
    "REPLY_PORT",
    "ControlError",
    "Engine",
    "add_engine_options",
    "main",
    "run",
]

PROTOCOL_VERSION = (1, 4)
"""Control protocol version `(major, minor)` (ADR 0004; 1.1 in ADR 0005; 1.2 in ADR 0006;
1.3 in ADR 0007; 1.4 in ADR 0008)."""

CONTROL_PORT = 6450
"""Default port the engine listens on for control messages."""

REPLY_PORT = 6451
"""Default port the engine sends replies and state reports to."""

PREFIX = "/mpciml/"

IDLE, RECORDING, TRAINING, RUNNING = "idle", "recording", "training", "running"
_ALL = frozenset({IDLE, RECORDING, TRAINING, RUNNING})
_EDIT = frozenset({IDLE, TRAINING, RUNNING})

ALLOWED: Mapping[str, frozenset[str]] = {
    "hello": _ALL,
    "ping": _ALL,
    "state/get": _ALL,
    "examples/list": _ALL,
    "preset/list": _ALL,
    "record/start": frozenset({IDLE}),
    "record/stop": frozenset({RECORDING}),
    "class": _EDIT,
    "targets": _EDIT,
    "examples/delete": frozenset({IDLE, RUNNING}),
    "examples/clear": frozenset({IDLE, RUNNING}),
    "examples/load": frozenset({IDLE, RUNNING}),
    "examples/save": _EDIT,
    "train": frozenset({IDLE, RUNNING}),
    "run": frozenset({IDLE}),
    "stop": frozenset({IDLE, RECORDING, RUNNING}),
    "preset/load": frozenset({IDLE}),
    "midi/learn": frozenset({IDLE, TRAINING}),
    "kit/list": _ALL,
    "module/list": _ALL,
    "kit/load": frozenset({IDLE, RUNNING}),
    "pad/module": frozenset({IDLE, RUNNING}),
    "pad/select/start": _EDIT,
    "pad/select/stop": _EDIT,
}
"""The states in which each control message is accepted (ADR 0004, States; ADR 0005;
ADR 0007). `kit/load` and `pad/module` are also refused while a retrain runs."""

LEARN_SWEEP = (0, 32, 64, 96, 127)
"""The values `/mpciml/midi/learn` sends, upwards; the next message sends them downwards."""

_NAME = re.compile(r"[A-Za-z0-9_-]+", re.ASCII)

_CLOCK_BYTES = frozenset({0xF8, 0xFA, 0xFB, 0xFC, 0xF2})
"""MIDI clock, Start, Continue, Stop and Song Position Pointer."""

EventInput = ClockedSource | Iterable[Event]
"""Gesture input: a real-time source (live MPC, paced replay) or an event iterable."""


class ControlError(Exception):
    """A control message cannot be carried out; sent as `/mpciml/error`."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_count(args: Sequence[Any], low: int, high: int) -> None:
    if not low <= len(args) <= high:
        expected = str(low) if low == high else f"{low}-{high}"
        raise ControlError("bad_arguments", f"expected {expected} arguments, got {len(args)}")


def _int(value: Any) -> int:
    """An int argument: an OSC int32, or a float with a whole-number value.

    Pure Data sends numbers as floats unless the patch sets a type tag, so `1.0` is
    accepted as `1`; `1.5`, infinities and NaN are not.
    """
    if isinstance(value, bool):
        raise ControlError("bad_arguments", f"expected an int, got {value!r}")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ControlError("bad_arguments", f"expected an int, got {value!r}")


def _float(value: Any) -> float:
    """A finite number argument (OSC int32 or float)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ControlError("bad_arguments", f"expected a number, got {value!r}")
    if not math.isfinite(value):
        raise ControlError("bad_arguments", f"expected a finite number, got {value!r}")
    return float(value)


def _name(args: Sequence[Any]) -> str:
    """The single name argument: letters, digits, `-` and `_` only (ADR 0004)."""
    _check_count(args, 1, 1)
    value = args[0]
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ControlError(
            "bad_arguments", f"expected a name of letters, digits, '-' and '_', got {value!r}"
        )
    return value


def _transition(state: PadState, frame: Frame, t: float) -> list[Event]:
    """MIDI events at `t` that turn `state` into the pad state of `frame`.

    `state` is updated with the events. A pad's velocity cannot return to 0 once
    set, so a pad never hit at `frame` keeps any velocity set earlier in the
    recording (ADR 0004, clarification 10); everything else matches `frame`.
    """
    events: list[Event] = []

    def emit(kind: MidiKind, pad: int, value: int) -> None:
        event = MidiEvent(t, kind, 1, value, note=bank_pad_to_note(frame.bank, pad))
        state.apply(event)
        events.append(event)

    for pad in range(PADS):
        velocity, held = frame.velocity[pad], frame.held[pad]
        if velocity > 0 and (state.velocity[pad] != velocity or (held and not state.held[pad])):
            emit("note_on", pad, velocity)
        if state.held[pad] and not held:
            emit("note_off", pad, 0)
    if state.bank != frame.bank:
        hit = [pad for pad in range(PADS) if frame.velocity[pad] > 0]
        if hit:
            emit("note_on", hit[0], frame.velocity[hit[0]])
            if not frame.held[hit[0]]:
                emit("note_off", hit[0], 0)
    for pad in range(PADS):
        if state.pressure[pad] != frame.pressure[pad]:
            emit("poly_pressure", pad, frame.pressure[pad])
    return events


class Engine:
    """The IML loop behind the ADR 0004 control protocol.

    `source` is the gesture input (`None`: no input). `presets` lists the installed
    presets; the default reads the `mpc_iml.presets` entry points. `outputs_port`
    overrides the port of the preset's first `OscOutput`. `midi_port` sends MIDI
    control changes to the first existing output port whose name contains it,
    instead of a virtual port; `midi_backend` makes the MIDI output backend (tests
    pass a fake). Port 0 picks a free port for the control server (see
    `control_port`). `clock` turns on MIDI clock sync (ADR 0008): `start()` opens a
    virtual input, or the first input port whose name contains `clock_port`;
    `clock_backend` makes its backend (tests pass a fake).
    """

    def __init__(
        self,
        data_dir: Path | str,
        source: EventInput | None = None,
        preset: str = "demo",
        presets: Callable[[], Mapping[str, Preset]] = available_presets,
        host: str = DEFAULT_HOST,
        control_port: int = CONTROL_PORT,
        reply_host: str = DEFAULT_HOST,
        reply_port: int = REPLY_PORT,
        inputs_port: int = INPUTS_PORT,
        outputs_port: int | None = None,
        midi_port: str | None = None,
        midi_backend: Callable[[], MidiOutputBackend] = RtMidiOutBackend,
        rate: float = DEFAULT_RATE,
        log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
        clock: bool = False,
        clock_port: str | None = None,
        beats_per_bar: int = 4,
        clock_backend: Callable[[], ClockInputBackend] = RtMidiClockBackend,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._source = source
        self._presets = presets
        self._host = host
        self._control_port = control_port
        self._reply_host = reply_host
        self._reply = UDPClient(reply_host, reply_port)
        self._reply_port = reply_port
        self._inputs_port = inputs_port
        self._outputs_port = outputs_port
        self._midi_port = midi_port
        self._midi_backend = midi_backend
        self._rate = rate
        self._log = log
        self._lock = threading.RLock()
        self._closing = threading.Event()
        self._state = IDLE
        self._label: str | None = None
        self._targets: tuple[float, ...] | None = None
        self._take: list[Frame] = []
        self._timeline: list[Event] = []
        self._trained = False
        self._train_thread: threading.Thread | None = None
        self._input_thread: threading.Thread | None = None
        self._server: BlockingOSCUDPServer | None = None
        self._serving = False
        self._midi: list[MidiCcSender] = []
        self._midi_outputs: list[MidiCcOutput] = []
        self._generated: GeneratedSet | None = None
        self._library: Library | None = None
        self._selecting = False
        self._clock = MidiClock(beats_per_bar) if clock else None
        self._clock_port = clock_port
        self._clock_backend = clock_backend
        self._clock_input: ClockInput | None = None
        self._clock_access: ClockAccess | None = None
        self._clock_lock = threading.Lock()
        self._clock_reported: tuple[str, int, int] | None = None
        self._t0 = time.monotonic()
        try:
            found = self._find(preset)
        except ControlError as error:
            raise PresetError(error.message) from error
        self._preset = found
        self._examples = found.example_set()
        self._loop = self._build_loop(found, self._examples)
        self._attach_clock(found)
        self._handlers: dict[str, Callable[[list[Any]], None]] = {
            "hello": self._hello,
            "ping": self._ping,
            "state/get": lambda args: self._full_state(),
            "record/start": self._record_start,
            "record/stop": self._record_stop,
            "class": self._class,
            "targets": self._set_targets,
            "examples/delete": self._delete,
            "examples/clear": self._clear,
            "examples/save": self._save,
            "examples/load": self._load,
            "examples/list": self._list,
            "train": self._train,
            "run": self._run,
            "stop": self._stop,
            "preset/list": self._preset_list,
            "preset/load": self._preset_load,
            "midi/learn": self._midi_learn,
            "kit/list": self._kit_list,
            "kit/load": self._kit_load,
            "module/list": self._module_list,
            "pad/module": self._pad_module,
            "pad/select/start": self._select_start,
            "pad/select/stop": self._select_stop,
        }

    # Life cycle

    @property
    def state(self) -> str:
        """`idle`, `recording`, `training` or `running`."""
        return self._state

    @property
    def examples(self) -> ExampleSet:
        """The current example set (read it; change it with control messages)."""
        return self._examples

    @property
    def control_port(self) -> int:
        """The port the control server listens on (after `start()`)."""
        if self._server is None:
            return self._control_port
        return int(self._server.server_address[1])

    def start(self) -> None:
        """Create the data folder, open the clock input, bind the control port and
        start reading input. Raises when the clock input cannot be opened."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self._clock is not None:
            clock_input = ClockInput(self._on_clock_message, self._clock_port, self._clock_backend)
            clock_input.open()
            self._clock_input = clock_input
            self._log(
                f"MIDI clock: waiting on {clock_input.port_name!r}. In Live, turn on Sync "
                "for this port (Settings > Link, Tempo & MIDI) and press Play."
            )
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self.handle)
        self._server = BlockingOSCUDPServer((self._host, self._control_port), dispatcher)
        if self._source is not None:
            self._input_thread = threading.Thread(target=self._read_input, daemon=True)
            self._input_thread.start()

    def serve_forever(self) -> None:
        """Handle control messages until `close()` (or Ctrl-C in this thread)."""
        if self._server is None:
            raise RuntimeError("call start() first")
        self._serving = True
        try:
            self._server.serve_forever(poll_interval=0.05)
        finally:
            self._serving = False

    def close(self) -> None:
        """Stop serving, stop input, wait for training, and close every socket."""
        self._closing.set()
        if self._server is not None:
            if self._serving:
                self._server.shutdown()
            self._server.server_close()
        if self._clock_input is not None:
            self._clock_input.close()
        for thread in (self._input_thread, self._train_thread):
            if thread is not None:
                thread.join()
        close = getattr(self._source, "close", None)
        if callable(close):
            close()
        with self._lock:
            self._close_senders(self._loop)
            self._reply.close()

    # Control messages

    def handle(self, address: str, *args: Any) -> None:
        """Handle one control message; every problem becomes one `/mpciml/error`."""
        try:
            if address == PREFIX + "stop" and self._state == RUNNING:
                self._wait_for_training()
            with self._lock:
                self._dispatch(address, list(args))
        except ControlError as error:
            self._error(error.code, address, error.message)
        except Exception as error:  # the engine never crashes on a control message
            self._log(f"error handling {address}: {error!r}")
            self._error("bad_arguments", address, f"internal error: {error}")

    def _dispatch(self, address: str, args: list[Any]) -> None:
        command = address.removeprefix(PREFIX)
        if command == address:
            raise ControlError("unknown_message", f"unknown address {address}")
        if command.startswith("preset/") and command not in ALLOWED:
            self._preset_message(command.removeprefix("preset/"), args)
            return
        handler = self._handlers.get(command)
        if handler is None:
            raise ControlError("unknown_message", f"unknown address {address}")
        if self._state not in ALLOWED[command]:
            raise ControlError("wrong_state", f"not allowed while {self._state}")
        handler(args)

    def _hello(self, args: list[Any]) -> None:
        _check_count(args, 1, 2)
        major = _int(args[0])
        if len(args) == 2:
            port = _int(args[1])
            if not 0 < port < 65536:
                raise ControlError("bad_arguments", f"reply port must be 1-65535, got {port}")
            if port != self._reply_port:
                self._reply.close()
                self._reply = UDPClient(self._reply_host, port)
                self._reply_port = port
        if major != PROTOCOL_VERSION[0]:
            self._error(
                "version_mismatch",
                PREFIX + "hello",
                f"engine speaks protocol {PROTOCOL_VERSION[0]}.{PROTOCOL_VERSION[1]}, "
                f"client sent major {major}",
            )
        self._send("version", *PROTOCOL_VERSION, __version__)
        self._full_state()

    def _ping(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._send("pong")

    def _record_start(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        if self._label is None and self._targets is None:
            raise ControlError("bad_arguments", "send /mpciml/class or /mpciml/targets first")
        self._check_task(self._label, self._targets)
        self._take = []
        self._selecting = False
        self._set_state(RECORDING)

    def _record_stop(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        take, self._take = self._take, []
        for frame in take:
            self._examples.add(frame, self._label, self._targets)
        if take:
            self._append_take(take)
            if self._generated is not None:
                self._rebuild_examples()
        self._set_state(IDLE)
        self._counts()

    def _class(self, args: list[Any]) -> None:
        _check_count(args, 1, 1)
        if not isinstance(args[0], str):
            raise ControlError("bad_arguments", f"expected a string label, got {args[0]!r}")
        self._check_task(args[0], None)
        self._label, self._targets = args[0], None

    def _set_targets(self, args: list[Any]) -> None:
        if not args:
            raise ControlError("bad_arguments", "expected one or more target values")
        if any(isinstance(a, bool) or not isinstance(a, int | float) for a in args):
            raise ControlError("bad_arguments", f"target values must be numbers: {args!r}")
        targets = tuple(float(a) for a in args)
        if not all(math.isfinite(v) for v in targets):
            raise ControlError("bad_arguments", f"target values must be finite: {args!r}")
        self._check_task(None, targets)
        self._label, self._targets = None, targets

    def _delete(self, args: list[Any]) -> None:
        _check_count(args, 1, 1)
        label = args[0]
        if not isinstance(label, str):
            raise ControlError("bad_arguments", f"expected a string label, got {label!r}")
        self._examples.remove(label)
        self._timeline = [
            e for e in self._timeline if not (isinstance(e, ExampleStart) and e.label == label)
        ]
        self._timeline = _drop_unmatched_ends(self._timeline)
        self._counts()

    def _clear(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._examples.clear()
        self._timeline = []
        self._generated = None
        self._kit_and_pads()
        self._counts()

    def _save(self, args: list[Any]) -> None:
        name = _name(args)
        path = self.data_dir / f"{name}.jsonl"
        partial = self.data_dir / f".{name}.jsonl.partial"
        header = Header(settings={"preset": self._preset.name})
        if self._generated is not None:
            header = self._generated.header(header)
        write_recording(partial, header, with_generated(self._timeline, self._generated))
        os.replace(partial, path)

    def _load(self, args: list[Any]) -> None:
        name = _name(args)
        path = self.data_dir / f"{name}.jsonl"
        if not path.is_file():
            raise ControlError("not_found", f"no saved example set named {name!r}")
        examples = self._preset.example_set()
        try:
            recording = read_recording(path)
            recorded, generated = split_generated(recording, self._rate)
            examples.add_events(recording.events, self._rate)
        except (ValueError, ContentError) as error:
            raise ControlError("bad_arguments", f"cannot load {name!r}: {error}") from error
        if examples.examples:
            first = examples.examples[0]
            try:
                self._check_preset_task(first.label, first.targets)
            except ControlError as error:
                raise ControlError("bad_arguments", f"cannot load {name!r}: {error}") from error
        self._examples = examples
        self._loop.examples = examples
        self._timeline = recorded
        self._generated = generated
        self._kit_and_pads()
        self._counts()

    def _list(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        names = sorted(p.stem for p in self.data_dir.glob("*.jsonl") if _NAME.fullmatch(p.stem))
        self._send("examples/names", *names)

    def _train(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._check_not_training()
        self._start_training()

    def _check_not_training(self) -> None:
        """Refuse while a retrain runs; wait for a training thread that is finishing.

        In `idle` a training thread can still be alive for a moment after it set the
        state back to `idle`; it no longer needs the lock, so joining it is quick.
        """
        thread = self._train_thread
        if thread is None or not thread.is_alive():
            return
        if self._state == IDLE:
            thread.join()
            return
        raise ControlError("wrong_state", f"a retrain is already in progress ({self._state})")

    def _start_training(self) -> None:
        if not self._loop.backend_on:
            self._send("train/failed", "the model backend is off; Wekinator is the model")
            return
        try:
            data = self._examples.training_data()
        except ExampleError as error:
            self._send("train/failed", str(error))
            return
        if self._state == IDLE:
            self._set_state(TRAINING)
        self._train_thread = threading.Thread(
            target=self._fit, args=(self._loop, data), daemon=True
        )
        self._train_thread.start()

    def _run(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        if self._loop.model is None:
            raise ControlError("wrong_state", "no trained model; send /mpciml/train first")
        self._set_state(RUNNING)

    def _stop(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        if self._state == IDLE:
            return
        self._take = []
        self._set_state(IDLE)

    def _preset_list(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        try:
            names = sorted(self._presets())
        except PresetError as error:
            raise ControlError("not_found", str(error)) from error
        self._send("presets", *names)

    def _preset_load(self, args: list[Any]) -> None:
        name = _name(args)
        if name != self._preset.name:
            preset = self._find(name)
            self._close_senders(self._loop)
            self._preset = preset
            self._examples = preset.example_set()
            self._loop = self._build_loop(preset, self._examples)
            self._attach_clock(preset)
            self._timeline = []
            self._generated = None
            self._library = None
            self._label, self._targets = None, None
        self._selecting = False
        self._send("preset", self._preset.name, self._preset.version)
        self._layout()
        self._names()
        self._kit_and_pads()
        self._counts()
        self._report_trained()

    def _midi_learn(self, args: list[Any]) -> None:
        _check_count(args, 1, 1)
        output = _int(args[0])
        if not self._midi_outputs:
            raise ControlError("bad_arguments", f"preset {self._preset.name!r} has no MIDI output")
        count = max(len(o.controllers) for o in self._midi_outputs)
        if not 1 <= output <= count:
            raise ControlError("bad_arguments", f"output must be 1-{count}, got {output}")
        senders = [s for s in self._midi if output <= len(s.output.controllers)]
        if not senders:
            raise ControlError("bad_arguments", "MIDI output not open")
        index = output - 1
        for sender in senders:
            down = sender.last_value(index) == LEARN_SWEEP[-1]
            for value in reversed(LEARN_SWEEP) if down else LEARN_SWEEP:
                sender.send_controller(index, value)
        self._send("midi/sent", output, senders[0].output.controllers[index])

    def _kit_list(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._send("kits", *self._content().kit_names())

    def _module_list(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._send("modules", *self._content().module_ids())

    def _kit_load(self, args: list[Any]) -> None:
        name = _name(args)
        self._need_output_names()
        self._check_not_training()
        library = self._content()
        if name not in library.kits:
            other = self._kit_preset(name)
            if other is not None:
                raise ControlError(
                    "bad_arguments",
                    f"kit {name!r} is for preset {other!r}, not {library.preset.name!r}",
                )
            raise ControlError("not_found", f"unknown kit {name!r} for {library.preset.name!r}")
        try:
            generated = GeneratedSet.from_kit(library, name)
        except UnknownContentError as error:
            raise ControlError("not_found", str(error)) from error
        except ContentError as error:
            raise ControlError("bad_arguments", str(error)) from error
        self._timeline = []
        self._generated = generated
        self._rebuild_examples()
        self._kit_and_pads()
        self._counts()
        self._start_training()

    def _pad_module(self, args: list[Any]) -> None:
        _check_count(args, 2, 3)
        pad = _int(args[0])
        module = args[1]
        if not isinstance(module, str):
            raise ControlError("bad_arguments", f"expected a module id, got {module!r}")
        amount = _float(args[2]) if len(args) == 3 else 1.0
        self._need_output_names()
        if not 1 <= pad <= PADS:
            raise ControlError("bad_arguments", f"pad must be 1-{PADS}, got {pad}")
        if not 0.0 <= amount <= 1.0:
            raise ControlError("bad_arguments", f"amount must be 0-1, got {amount}")
        self._check_not_training()
        library = self._content()
        if module not in library.modules:
            raise ControlError(
                "not_found", f"unknown module {module!r} for {library.preset.name!r}"
            )
        if self._generated is None or self._generated.rest is None:
            raise ControlError("bad_arguments", "no resting values: load a kit first")
        try:
            generated = self._generated.assign(library, pad, module, amount)
        except UnknownContentError as error:
            raise ControlError("not_found", str(error)) from error
        except ContentError as error:
            raise ControlError("bad_arguments", str(error)) from error
        self._generated = generated
        self._rebuild_examples()
        self._pads()
        self._counts()
        self._start_training()

    def _select_start(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._selecting = True

    def _select_stop(self, args: list[Any]) -> None:
        _check_count(args, 0, 0)
        self._selecting = False

    def _preset_message(self, rest: str, args: list[Any]) -> None:
        name, _, control = rest.partition("/")
        address = PREFIX + "preset/" + rest
        if name in RESERVED_NAMES or not name:
            raise ControlError("unknown_message", f"unknown address {address}")
        if name != self._preset.name:
            raise ControlError("inactive_preset", f"preset {name!r} is not active")
        handler = self._preset.controls.get(control)
        if handler is None:
            raise ControlError("unknown_message", f"preset {name!r} has no control {control!r}")
        try:
            handler(args)
        except Exception as error:
            raise ControlError("bad_arguments", f"{control}: {error}") from error

    # Replies

    def _send(self, name: str, *args: int | float | str) -> None:
        builder = OscMessageBuilder(address=PREFIX + name)
        for arg in args:
            if isinstance(arg, str):
                builder.add_arg(arg, OscMessageBuilder.ARG_TYPE_STRING)
            elif isinstance(arg, int):
                builder.add_arg(arg, OscMessageBuilder.ARG_TYPE_INT)
            else:
                builder.add_arg(arg, OscMessageBuilder.ARG_TYPE_FLOAT)
        with self._lock:
            try:
                self._reply.send(builder.build())
            except OSError as error:
                self._log(f"cannot send {PREFIX + name}: {error}")

    def _error(self, code: str, address: str, message: str) -> None:
        self._send("error", code, address, message)

    def _set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self._send("state", state)

    def _counts(self) -> None:
        examples = self._examples.examples
        if examples and examples[0].targets is not None:
            self._send("counts", "", len(examples))
            return
        tally: dict[str, int] = {}
        for example in examples:
            if example.label is not None:
                tally[example.label] = tally.get(example.label, 0) + 1
        classes = sorted(self._examples.classes.items(), key=lambda item: item[1])
        pairs: list[int | float | str] = []
        for label, _ in classes:
            pairs += [label, tally.get(label, 0)]
        self._send("counts", *pairs)

    def _layout(self) -> None:
        """`/mpciml/layout`: the preset's targets (0 if not declared) and MIDI controllers."""
        midi = next((o for o in self._preset.outputs if isinstance(o, MidiCcOutput)), None)
        controllers = len(midi.controllers) if midi is not None else 0
        self._send("layout", self._preset.targets or 0, controllers)

    def _names(self) -> None:
        """`/mpciml/names`: the preset's output names (none when it has none)."""
        self._send("names", *(self._preset.output_names or ()))

    def _kit_and_pads(self) -> None:
        """`/mpciml/kit` (the kit the set started from, or `""`), then `/mpciml/pads`."""
        kit = self._generated.kit if self._generated is not None else None
        self._send("kit", kit or "")
        self._pads()

    def _pads(self) -> None:
        """`/mpciml/pads`: 16 × (module, amount); `""` and 1 for a pad without takes."""
        if self._generated is not None:
            assignments = self._generated.assignments()
        else:
            assignments = [("", 1.0)] * PADS
        values: list[int | float | str] = []
        for module, amount in assignments:
            values += [module, float(amount)]
        self._send("pads", *values)

    def _report_trained(self, always: bool = False) -> None:
        trained = self._loop.model is not None
        if always or trained != self._trained:
            self._trained = trained
            self._send("trained", int(trained))

    def _full_state(self) -> None:
        self._send("state", self._state)
        self._send("preset", self._preset.name, self._preset.version)
        self._layout()
        self._names()
        self._kit_and_pads()
        self._counts()
        self._report_trained(always=True)
        self._send_clock(self._clock.state() if self._clock is not None else off_state())

    def _send_clock(self, state: ClockState) -> None:
        """`/mpciml/clock`: status, bpm (0 when unknown), bar and beat (1-based, or 0)."""
        self._send("clock", state.status, float(state.bpm or 0.0), *_bar_beat(state))

    # Examples, presets and training

    def _find(self, name: str) -> Preset:
        try:
            presets = self._presets()
        except PresetError as error:
            raise ControlError("not_found", str(error)) from error
        if name not in presets:
            known = ", ".join(sorted(presets)) or "none"
            raise ControlError("not_found", f"unknown preset {name!r}; available: {known}")
        return presets[name]

    def _content(self) -> Library:
        """The active preset's kits and modules, read once per preset."""
        if self._library is None:
            try:
                self._library = load_library(self._preset)
            except ContentError as error:
                raise ControlError("not_found", str(error)) from error
        return self._library

    def _need_output_names(self) -> None:
        if self._preset.output_names is None:
            raise ControlError(
                "bad_arguments", f"preset {self._preset.name!r} has no named outputs, so no kits"
            )

    def _kit_preset(self, name: str) -> str | None:
        """The other installed preset that has a kit `name`, if any."""
        try:
            presets = self._presets()
        except PresetError:
            return None
        for preset in presets.values():
            if preset.name == self._preset.name or preset.output_names is None:
                continue
            try:
                if name in load_library(preset).kits:
                    return preset.name
            except ContentError:
                continue
        return None

    def _rebuild_examples(self) -> None:
        """Rebuild the example set from the recorded timeline and the generated takes."""
        examples = self._preset.example_set()
        examples.add_events(with_generated(self._timeline, self._generated, self._rate), self._rate)
        self._examples = examples
        self._loop.examples = examples

    def _check_preset_task(self, label: str | None, targets: tuple[float, ...] | None) -> None:
        """Reject a class or targets that the preset's declared `targets` rule out."""
        expected = self._preset.targets
        if expected is None:
            return
        if label is not None:
            raise ControlError(
                "bad_arguments", f"preset {self._preset.name!r} is regression; send targets"
            )
        if targets is not None and len(targets) != expected:
            raise ControlError(
                "bad_arguments",
                f"preset {self._preset.name!r} expects {expected} target values, "
                f"got {len(targets)}",
            )

    def _check_task(self, label: str | None, targets: tuple[float, ...] | None) -> None:
        """Reject a class or targets that cannot join the current examples."""
        self._check_preset_task(label, targets)
        examples = self._examples.examples
        if not examples:
            return
        first = examples[0]
        if label is not None and first.targets is not None:
            raise ControlError("bad_arguments", "the examples are regression; send targets")
        if targets is not None:
            if first.targets is None:
                raise ControlError("bad_arguments", "the examples are classification; send class")
            if len(targets) != len(first.targets):
                raise ControlError("bad_arguments", f"expected {len(first.targets)} target values")

    def _append_take(self, take: list[Frame]) -> None:
        """Append a recorded example to the timeline that `examples/save` writes.

        Frame `i` of the take is written at frame time `(k + i) / rate`, so replaying
        the timeline gives exactly the frames of the take, one per frame interval,
        whatever their times were: the real-time loop may have dropped frames in
        between (#73). Frame `k - 1` is outside every example.
        """
        rate = self._rate
        state = PadState()
        for event in self._timeline:
            state.apply(event)
        last = self._timeline[-1].t if self._timeline else None
        k = 0 if last is None else math.floor(last * rate) + 2
        self._timeline.append(ExampleStart(k / rate, self._label, self._targets))
        for i, frame in enumerate(take):
            self._timeline += _transition(state, frame, (k + i) / rate)
        self._timeline.append(ExampleEnd((k + len(take) - 0.5) / rate))

    def _build_loop(self, preset: Preset, examples: ExampleSet) -> IMLLoop:
        senders: list[ValuesSender] = []
        first_osc = True
        self._midi_outputs = [o for o in preset.outputs if isinstance(o, MidiCcOutput)]
        self._midi = []
        for output in preset.outputs:
            try:
                sender = self._open_output(output, first_osc)
                senders.append(sender)
                if isinstance(sender, MidiCcSender):
                    self._midi.append(sender)
            except Exception as error:
                self._log(f"output {output} not opened, continuing without it: {error}")
            first_osc = first_osc and not isinstance(output, OscOutput)
        outputs: ValuesSender | None = None
        if len(senders) == 1:
            outputs = senders[0]
        elif senders:
            outputs = FanOut(senders)
        inputs = OscSender(INPUTS_ADDRESS, DEFAULT_HOST, self._inputs_port)
        loop = preset.build_loop(examples, inputs=inputs, outputs=outputs)
        loop.rate = self._rate
        return loop

    def _open_output(self, output: OscOutput | MidiCcOutput, first_osc: bool) -> ValuesSender:
        if isinstance(output, OscOutput):
            port = output.port
            if first_osc and self._outputs_port is not None:
                port = self._outputs_port
            return OscSender(output.address, output.host, port)
        sender = MidiCcSender(output, self._midi_port, self._midi_backend)
        sender.open()
        self._log(f"MIDI control changes on {sender.port_name!r}")
        return sender

    @staticmethod
    def _close_senders(loop: IMLLoop) -> None:
        for sender in (loop.inputs, loop.outputs):
            if sender is not None:
                sender.close()

    def _fit(self, loop: IMLLoop, data: tuple[list[list[float]], list[list[float]]]) -> None:
        started = time.perf_counter()
        failure: str | None
        try:
            loop.train(data)
            failure = None
        except Exception as error:
            failure = str(error) or type(error).__name__
        with self._lock:
            if failure is not None:
                self._send("train/failed", failure)
            else:
                self._send("train/done", time.perf_counter() - started)
                self._report_trained()
            if self._state == TRAINING:
                self._set_state(IDLE)

    def _wait_for_training(self) -> None:
        thread = self._train_thread
        if thread is not None:
            thread.join()

    # Input

    def _read_input(self) -> None:
        try:
            for frame in self._frames():
                self._on_frame(frame)
        except Exception as error:
            self._log(f"input stopped: {error!r}")

    def _frames(self) -> Iterator[Frame]:
        source = self._source
        if isinstance(source, ClockedSource) and source.realtime:
            tapped = _Tap(source, self._on_event)
            yield from realtime_frames(tapped, self._rate, stop=self._closing.is_set)
        elif isinstance(source, Iterable):
            for frame in frames(self._tap(source), self._rate):
                if self._closing.is_set():
                    return
                yield frame

    def _tap(self, events: Iterable[Event]) -> Iterator[Event]:
        for event in events:
            self._on_event(event)
            yield event

    def _on_event(self, event: Event) -> None:
        """Feed clock bytes to the clock, give pad hits to the preset's clock hook, and
        report a pad hit (`/mpciml/pad/hit`, pads 1-16, any bank) while selecting."""
        if self._clock is not None:
            if isinstance(event, RawMidiEvent) and event.data[:1] and event.data[0] in _CLOCK_BYTES:
                self._clock_changed(self._clock.feed(event.data, event.t))
            access = self._clock_access
            if access is not None and isinstance(event, MidiEvent) and event.kind == "note_on":
                access.deliver(event)
        if (
            self._selecting
            and isinstance(event, MidiEvent)
            and event.kind == "note_on"
            and event.value > 0
            and event.note is not None
        ):
            self._send("pad/hit", note_to_bank_pad(event.note)[1] + 1)

    def _on_frame(self, frame: Frame) -> None:
        if self._clock is not None:
            self._clock_changed(self._clock.check(frame.t))
        with self._lock:
            if self._state == RECORDING:
                self._take.append(frame)
            elif self._state == RUNNING:
                try:
                    self._loop.step(frame)
                except Exception as error:
                    self._log(f"run step failed: {error!r}")

    # MIDI clock

    def _attach_clock(self, preset: Preset) -> None:
        """Give `preset` a new `ClockAccess` when sync is on and it has a clock hook."""
        self._clock_access = None
        if self._clock is None or preset.clock is None:
            return
        access = ClockAccess(self._clock, self._log)
        try:
            preset.clock(access)
        except Exception as error:
            self._log(f"preset {preset.name!r} clock hook failed, no clock: {error!r}")
            return
        self._clock_access = access

    def _clock_now(self) -> float | None:
        """Now, in the gesture source's time base (`None` before a replay starts)."""
        source = self._source
        if isinstance(source, ClockedSource):
            try:
                return source.now()
            except RuntimeError:
                return None
        return time.monotonic() - self._t0

    def _on_clock_message(self, data: bytes) -> None:
        """One message from the clock input (on its thread)."""
        t = self._clock_now()
        if t is not None and self._clock is not None:
            self._clock_changed(self._clock.feed(data, t))

    def _clock_changed(self, state: ClockState) -> None:
        """Report `state` if its status changed or, while running, its beat changed."""
        bar, beat = _bar_beat(state) if state.status == "running" else (-1, -1)
        key = (state.status, bar, beat)
        with self._clock_lock:
            if key == self._clock_reported:
                return
            self._clock_reported = key
        if state.status == "lost":
            self._log("MIDI clock lost: no tick for 0.5 s; waiting for the DAW")
        self._send_clock(state)


class _Tap:
    """A `ClockedSource` that passes every polled event to `on_event` first."""

    def __init__(self, source: ClockedSource, on_event: Callable[[Event], None]) -> None:
        self._source = source
        self._on_event = on_event

    @property
    def realtime(self) -> bool:
        return self._source.realtime

    def start(self) -> None:
        self._source.start()

    def now(self) -> float:
        return self._source.now()

    def poll(self) -> Event | None:
        event = self._source.poll()
        if event is not None:
            self._on_event(event)
        return event

    def sleep(self, seconds: float) -> None:
        self._source.sleep(seconds)

    def done(self) -> bool:
        return self._source.done()


def _bar_beat(state: ClockState) -> tuple[int, int]:
    """Bar and beat counted from 1 for replies, or (0, 0) before the first tick."""
    return (state.bar + 1, state.beat + 1) if state.tick >= 0 else (0, 0)


def _drop_unmatched_ends(events: list[Event]) -> list[Event]:
    """Remove `example_end` markers whose `example_start` was removed."""
    kept: list[Event] = []
    open_segment = False
    for event in events:
        if isinstance(event, ExampleStart):
            open_segment = True
        elif isinstance(event, ExampleEnd):
            if not open_segment:
                continue
            open_segment = False
        kept.append(event)
    return kept


def add_engine_options(parser: argparse.ArgumentParser) -> None:
    """Add the engine's options (all but the data folder) to `parser`."""
    parser.add_argument("--preset", default="demo", help="preset to start with (default demo)")
    parser.add_argument("--replay", help="read gestures from this recording instead of the MPC")
    parser.add_argument("--port", default=DEFAULT_PORT_MATCH, help="MIDI input port name contains")
    parser.add_argument("--host", default=DEFAULT_HOST, help="address to listen on")
    parser.add_argument("--control-port", type=int, default=CONTROL_PORT)
    parser.add_argument("--reply-port", type=int, default=REPLY_PORT)
    parser.add_argument("--inputs-port", type=int, default=INPUTS_PORT, help="/wek/inputs port")
    parser.add_argument("--outputs-port", type=int, help="override the preset's output port")
    parser.add_argument(
        "--midi-port",
        help="send MIDI CCs to the existing output port whose name contains this (e.g. IAC)"
        " instead of the virtual port",
    )
    parser.add_argument(
        "--clock",
        action="store_true",
        help="sync to MIDI clock from a DAW on the virtual input 'mpc-iml clock' (ADR 0008)",
    )
    parser.add_argument(
        "--clock-port",
        help="read MIDI clock from the existing input port whose name contains this"
        " (e.g. IAC) instead; implies --clock",
    )
    parser.add_argument(
        "--beats-per-bar",
        type=_beats_per_bar,
        default=4,
        help="quarter notes per bar for --clock (default 4)",
    )


def _beats_per_bar(value: str) -> int:
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {count}")
    return count


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mpc_iml.engine",
        description="The IML engine, controlled over OSC (ADR 0004; see the README).",
    )
    parser.add_argument("data", help="folder for saved example sets (created if missing)")
    add_engine_options(parser)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the engine until Ctrl-C."""
    return run(build_parser().parse_args(argv))


def run(args: argparse.Namespace, on_started: Callable[["Engine"], None] | None = None) -> int:
    """Run the engine from parsed options until Ctrl-C.

    `on_started` is called once the engine listens, for example to open a front end
    that says `hello` as soon as it opens.
    """
    source: LiveSource | ReplaySource
    if args.replay:
        source = ReplaySource(args.replay, realtime=True)
    else:
        source = LiveSource(port_match=args.port)
        try:
            source.open()
        except Exception as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
    try:
        engine = Engine(
            args.data,
            source,
            preset=args.preset,
            host=args.host,
            control_port=args.control_port,
            reply_port=args.reply_port,
            inputs_port=args.inputs_port,
            outputs_port=args.outputs_port,
            midi_port=args.midi_port,
            clock=args.clock or args.clock_port is not None,
            clock_port=args.clock_port,
            beats_per_bar=args.beats_per_bar,
        )
    except PresetError as error:
        print(f"error: {error}", file=sys.stderr)
        if isinstance(source, LiveSource):
            source.close()
        return 2
    try:
        engine.start()
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        engine.close()
        return 1
    print(
        f"Engine (protocol {PROTOCOL_VERSION[0]}.{PROTOCOL_VERSION[1]}) listening on "
        f"{args.host}:{engine.control_port}, replying to port {args.reply_port}, "
        f"preset {args.preset!r}, data in {args.data}. Ctrl-C stops."
    )
    try:
        if on_started is not None:
            on_started(engine)
        engine.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        engine.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
