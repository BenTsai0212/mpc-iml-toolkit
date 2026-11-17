"""Engine protocol 1.3: kits, modules and pad selection (ADR 0007, #100).

As in `test_engine.py`, each test starts an engine on free ports and talks OSC to
it. The preset is `pressure` with its built-in kits and modules; its outputs are
removed so no MIDI port is opened, and `gated` variants wait for the test before
training finishes. Pad hits come from the recorded MPC fixtures (`SteppedReplay`).
"""

import dataclasses
import threading
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

import pytest
import test_engine
from test_engine import (
    FIXTURES,
    HOLD,
    STATES,
    TIMEOUT,
    Front,
    Message,
    SteppedReplay,
    presets,
    record_steps,
)

from mpc_iml.content import load_library
from mpc_iml.engine import ALLOWED
from mpc_iml.frames import PADS
from mpc_iml.generation import GeneratedSet, with_generated
from mpc_iml.presets import Preset
from mpc_iml.pressure import OUTPUT_NAMES
from mpc_iml.pressure import PRESET as PRESSURE
from mpc_iml.recording import read_recording
from mpc_iml.sklearn_backend import Regressor

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

STRIKES = FIXTURES / "strikes.jsonl"
"""One strike on each of pads 1-7 (notes 36-42), from t = 3.3 s to 4.9 s."""
BANKS = FIXTURES / "banks.jsonl"
"""Pad 1 struck in banks A, B and H, at t = 2.1 s, 3.6 s and 6.1 s."""

KITS = ["filter-play", "ambient-space", "texture-lab"]
MODULES = [
    "none",
    "bend",
    "bite",
    "brighten",
    "darken",
    "distance",
    "grain",
    "push",
    "swell",
    "wobble",
]
FILTER_PLAY = (
    ["brighten"] * 4 + ["bite"] * 4 + ["darken"] * 4 + ["wobble", "wobble", "bend", "none"]
)
"""The modules of `filter-play`, pads 1-16 (ADR 0007)."""


class GateRegressor:
    """A regressor whose training waits until the gate is open."""

    opened = threading.Event()

    def __init__(self) -> None:
        self._model = Regressor()

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        assert GateRegressor.opened.wait(TIMEOUT)
        self._model.fit(inputs, outputs)

    def predict(self, values: Sequence[float]) -> list[float]:
        return self._model.predict(values)


PRESSURE_QUIET = dataclasses.replace(PRESSURE, outputs=())
"""`pressure` with its kits and modules, but no OSC or MIDI outputs."""
PRESSURE_GATED = dataclasses.replace(PRESSURE_QUIET, model_factory=GateRegressor)
OTHER = Preset(name="other", version="1", model_factory=Regressor, targets=1, output_names=("one",))
"""A preset with named outputs but no kits or modules."""


def quiet() -> Mapping[str, Preset]:
    return presets(PRESSURE_QUIET, OTHER)


def gated() -> Mapping[str, Preset]:
    return presets(PRESSURE_GATED, OTHER)


@pytest.fixture(autouse=True)
def _open_gate() -> Iterator[None]:
    GateRegressor.opened.set()
    yield
    GateRegressor.opened.set()


def addresses(replies: list[Message]) -> list[str]:
    return [address for address, _ in replies]


def reply(replies: list[Message], address: str) -> list[Any]:
    found = [args for a, args in replies if a == address]
    assert len(found) == 1, replies
    return found[0]


def pads(modules: Sequence[str], amounts: Mapping[int, float] | None = None) -> list[Any]:
    """The `/mpciml/pads` arguments for `modules` on pads 1-16."""
    values: list[Any] = []
    for pad, module in enumerate(modules, start=1):
        values += [module, (amounts or {}).get(pad, 1.0)]
    return values


def library_set(kit: str) -> GeneratedSet:
    return GeneratedSet.from_kit(load_library(PRESSURE), kit)


def kit_loaded(front: Front, kit: str = "filter-play") -> list[Message]:
    """Load `kit` and wait for its automatic training; return every reply."""
    front.send("/mpciml/kit/load", kit)
    return front.replies.until("/mpciml/train/done")


def trained_after(front: Front, address: str, *args: Any) -> list[Message]:
    """Send a message that trains automatically; return every reply up to `train/done`."""
    front.send(address, *args)
    return front.replies.until("/mpciml/train/done")


def settle(front: Front) -> None:
    """Wait until a training started from `idle` is back in `idle`."""
    assert front.state() == "idle"


# Lists and names


def test_kit_and_module_lists(start: Any) -> None:
    front = start(preset="pressure", presets=quiet)
    front.send("/mpciml/kit/list")
    assert front.expect("/mpciml/kits") == KITS
    front.send("/mpciml/module/list")
    assert front.expect("/mpciml/modules") == MODULES


@pytest.mark.parametrize(("preset", "modules"), [("demo", []), ("other", ["none"])])
def test_lists_without_content(start: Any, preset: str, modules: list[str]) -> None:
    """No names without output names; with names but no content, only `none`."""
    front = start(preset=preset, presets=quiet)
    assert front.ask("/mpciml/kit/list") == [("/mpciml/kits", [])]
    assert front.ask("/mpciml/module/list") == [("/mpciml/modules", modules)]


def test_full_state_order_with_names(start: Any) -> None:
    front = start(preset="pressure", presets=quiet)
    replies = front.ask("/mpciml/state/get")
    assert replies == [
        ("/mpciml/state", ["idle"]),
        ("/mpciml/preset", ["pressure", PRESSURE.version]),
        ("/mpciml/layout", [8, 0]),
        ("/mpciml/names", list(OUTPUT_NAMES)),
        ("/mpciml/kit", [""]),
        ("/mpciml/pads", ["", 1.0] * PADS),
        ("/mpciml/counts", []),
        ("/mpciml/trained", [0]),
    ]


def test_preset_load_sends_names_kit_and_pads_after_layout(start: Any) -> None:
    front = start(presets=quiet)
    replies = front.ask("/mpciml/preset/load", "pressure")
    assert addresses(replies) == [
        "/mpciml/preset",
        "/mpciml/layout",
        "/mpciml/names",
        "/mpciml/kit",
        "/mpciml/pads",
        "/mpciml/counts",
    ]
    assert reply(replies, "/mpciml/names") == list(OUTPUT_NAMES)
    kit_loaded(front)
    settle(front)
    replies = front.ask("/mpciml/preset/load", "demo")
    assert reply(replies, "/mpciml/names") == []
    assert reply(replies, "/mpciml/kit") == [""]
    assert reply(replies, "/mpciml/pads") == ["", 1.0] * PADS


# kit/load and pad/module


def test_kit_load_replaces_the_set_and_trains(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source, preset="pressure", presets=quiet)
    front.send("/mpciml/targets", *[0.5] * 8)
    source.advance(180)
    record_steps(front, source)

    replies = kit_loaded(front)
    expected = library_set("filter-play")
    assert addresses(replies) == [
        "/mpciml/kit",
        "/mpciml/pads",
        "/mpciml/counts",
        "/mpciml/state",
        "/mpciml/train/done",
    ]
    assert reply(replies, "/mpciml/kit") == ["filter-play"]
    assert reply(replies, "/mpciml/pads") == pads(FILTER_PLAY)
    assert reply(replies, "/mpciml/counts") == ["", expected.frame_count()]
    assert reply(replies, "/mpciml/state") == ["training"]
    assert front.expect("/mpciml/trained") == [1]
    assert front.expect("/mpciml/state") == ["idle"]

    examples = PRESSURE.example_set()
    examples.add_events(with_generated([], expected))
    assert front.engine.examples.examples == examples.examples


def test_kit_load_with_an_amount_in_the_kit(start: Any) -> None:
    front = start(preset="pressure", presets=quiet)
    replies = kit_loaded(front, "ambient-space")
    expected = library_set("ambient-space")
    assert reply(replies, "/mpciml/pads") == [
        value for module, amount in expected.assignments() for value in (module, amount)
    ]


def test_pad_module_replaces_one_pad_and_keeps_recorded_takes(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source, preset="pressure", presets=quiet)
    kit_loaded(front)
    settle(front)
    front.send("/mpciml/targets", *[0.75] * 8)
    source.advance(180)
    recorded = record_steps(front, source)[1] - library_set("filter-play").frame_count()
    assert recorded > 0

    replies = trained_after(front, "/mpciml/pad/module", 2, "push", 0.5)
    assert addresses(replies) == [
        "/mpciml/pads",
        "/mpciml/counts",
        "/mpciml/state",
        "/mpciml/train/done",
    ]
    modules = list(FILTER_PLAY)
    modules[1] = "push"
    assert reply(replies, "/mpciml/pads") == pads(modules, {2: 0.5})
    expected = library_set("filter-play").assign(load_library(PRESSURE), 2, "push", 0.5)
    assert reply(replies, "/mpciml/counts") == ["", recorded + expected.frame_count()]
    kept = [e for e in front.engine.examples.examples if e.targets == (0.75,) * 8]
    assert len(kept) == recorded
    settle(front)

    # The amount defaults to 1, a whole-number float is a pad; the kit name stays.
    replies = trained_after(front, "/mpciml/pad/module", 2.0, "bite")
    assert reply(replies, "/mpciml/pads")[2:4] == ["bite", 1.0]
    settle(front)
    assert front.ask("/mpciml/state/get")[3:5] == [
        ("/mpciml/names", list(OUTPUT_NAMES)),
        ("/mpciml/kit", ["filter-play"]),
    ]


def test_pad_module_while_running_retrains_and_keeps_running(start: Any) -> None:
    front = start(preset="pressure", presets=gated)
    kit_loaded(front)
    settle(front)
    front.send("/mpciml/run")
    assert front.expect("/mpciml/state") == ["running"]
    GateRegressor.opened.clear()
    replies = front.ask("/mpciml/pad/module", 16, "wobble")
    assert addresses(replies) == ["/mpciml/pads", "/mpciml/counts"]
    # A second change during the retrain is refused (ADR 0007, option 6).
    assert front.error("/mpciml/pad/module", 15, "bite") == ("wrong_state", "/mpciml/pad/module")
    assert front.error("/mpciml/kit/load", "texture-lab") == ("wrong_state", "/mpciml/kit/load")
    GateRegressor.opened.set()
    assert front.expect("/mpciml/train/done")[0] >= 0
    assert front.state() == "running"
    front.send("/mpciml/kit/load", "texture-lab")
    assert front.expect("/mpciml/kit") == ["texture-lab"]
    assert front.expect("/mpciml/train/done")[0] >= 0
    assert front.state() == "running"


def test_pad_module_needs_resting_values(start: Any) -> None:
    front = start(preset="pressure", presets=quiet)
    code, _ = front.error("/mpciml/pad/module", 1, "bite")
    assert code == "bad_arguments"
    front.send("/mpciml/pad/module", 1, "bite")
    message = front.expect("/mpciml/error")[2]
    assert "load a kit first" in message


@pytest.mark.parametrize(
    ("address", "args", "code"),
    [
        ("/mpciml/kit/load", ["missing"], "not_found"),
        ("/mpciml/kit/load", [], "bad_arguments"),
        ("/mpciml/kit/load", ["a/b"], "bad_arguments"),
        ("/mpciml/pad/module", [1, "missing"], "not_found"),
        ("/mpciml/pad/module", [0, "bite"], "bad_arguments"),
        ("/mpciml/pad/module", [17, "bite"], "bad_arguments"),
        ("/mpciml/pad/module", [1.5, "bite"], "bad_arguments"),
        ("/mpciml/pad/module", [1, "bite", 1.5], "bad_arguments"),
        ("/mpciml/pad/module", [1, "bite", -0.1], "bad_arguments"),
        ("/mpciml/pad/module", [1, "bite", "x"], "bad_arguments"),
        ("/mpciml/pad/module", [1, 2], "bad_arguments"),
        ("/mpciml/pad/module", [1], "bad_arguments"),
        ("/mpciml/kit/list", [1], "bad_arguments"),
        ("/mpciml/module/list", [1], "bad_arguments"),
        ("/mpciml/pad/select/start", [1], "bad_arguments"),
    ],
)
def test_errors_with_a_kit_loaded(start: Any, address: str, args: list[Any], code: str) -> None:
    front = start(preset="pressure", presets=quiet)
    kit_loaded(front)
    settle(front)
    assert front.error(address, *args) == (code, address)


@pytest.mark.parametrize("preset", ["demo", "reg"])
def test_presets_without_output_names_refuse_kit_messages(start: Any, preset: str) -> None:
    front = start(preset=preset, presets=quiet)
    assert front.error("/mpciml/kit/load", "filter-play")[0] == "bad_arguments"
    assert front.error("/mpciml/pad/module", 1, "bite")[0] == "bad_arguments"


def test_a_kit_for_another_preset_is_bad_arguments(start: Any) -> None:
    front = start(preset="other", presets=quiet)
    assert front.error("/mpciml/kit/load", "texture-lab") == ("bad_arguments", "/mpciml/kit/load")
    assert front.error("/mpciml/kit/load", "nowhere") == ("not_found", "/mpciml/kit/load")
    assert front.error("/mpciml/pad/module", 1, "bite") == ("not_found", "/mpciml/pad/module")


# Clear, save and load


def test_examples_clear_clears_the_assignments(start: Any) -> None:
    front = start(preset="pressure", presets=quiet)
    kit_loaded(front)
    settle(front)
    replies = front.ask("/mpciml/examples/clear")
    assert replies == [
        ("/mpciml/kit", [""]),
        ("/mpciml/pads", ["", 1.0] * PADS),
        ("/mpciml/counts", []),
    ]
    code, _ = front.error("/mpciml/pad/module", 1, "bite")
    assert code == "bad_arguments"


def test_save_and_load_restore_kit_and_pad_assignments(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source, preset="pressure", presets=quiet)
    kit_loaded(front, "texture-lab")
    settle(front)
    trained_after(front, "/mpciml/pad/module", 3, "swell", 0.25)
    settle(front)
    front.send("/mpciml/targets", *[0.1] * 8)
    source.advance(180)
    record_steps(front, source)
    before = list(front.engine.examples.examples)
    state = front.ask("/mpciml/state/get")

    assert front.ask("/mpciml/examples/save", "mine") == []
    saved = read_recording(front.engine.data_dir / "mine.jsonl")
    assert saved.header.format_version == 2
    assert (saved.header.kit, saved.header.combine) == ("texture-lab", "add")

    front.ask("/mpciml/examples/clear")
    replies = front.ask("/mpciml/examples/load", "mine")
    assert addresses(replies) == ["/mpciml/kit", "/mpciml/pads", "/mpciml/counts"]
    assert reply(replies, "/mpciml/kit") == ["texture-lab"]
    assert reply(replies, "/mpciml/pads") == reply(state, "/mpciml/pads")
    assert reply(replies, "/mpciml/pads")[4:6] == ["swell", 0.25]
    assert reply(replies, "/mpciml/counts") == reply(state, "/mpciml/counts")
    assert front.engine.examples.examples == before

    # The loaded resting values let pad/module work without a kit/load.
    replies = trained_after(front, "/mpciml/pad/module", 1, "none")
    assert reply(replies, "/mpciml/pads")[:2] == ["none", 1.0]


def test_a_set_without_generated_takes_is_saved_as_version_1(start: Any) -> None:
    source = SteppedReplay(HOLD)
    front = start(source, preset="pressure", presets=quiet)
    front.send("/mpciml/targets", *[0.1] * 8)
    source.advance(180)
    record_steps(front, source)
    front.ask("/mpciml/examples/save", "plain")
    assert read_recording(front.engine.data_dir / "plain.jsonl").header.format_version == 1
    replies = front.ask("/mpciml/examples/load", "plain")
    assert reply(replies, "/mpciml/kit") == [""]
    assert reply(replies, "/mpciml/pads") == ["", 1.0] * PADS


# Pad selection


def hits(front: Front) -> list[int]:
    """The pads reported since the last reply read, up to a `ping`."""
    front.send("/mpciml/ping")
    replies = front.replies.until("/mpciml/pong")
    return [args[0] for address, args in replies if address == "/mpciml/pad/hit"]


def test_pad_select_reports_hits_until_stop(start: Any) -> None:
    source = SteppedReplay(STRIKES)
    front = start(source, presets=quiet)
    source.advance(340)  # past pad 1's strike at 3.31 s: not selecting yet
    assert front.ask("/mpciml/pad/select/start") == []
    source.advance(60)  # pads 2 and 3, at 3.58 s and 3.85 s
    assert hits(front) == [2, 3]
    assert front.ask("/mpciml/pad/select/stop") == []
    source.advance(30)  # pad 4 at 4.10 s: not reported
    assert hits(front) == []
    assert front.ask("/mpciml/pad/select/start") == []
    source.advance(60)  # pads 5-7
    assert hits(front) == [5, 6, 7]


def test_pad_hit_from_any_bank(start: Any) -> None:
    source = SteppedReplay(BANKS)
    front = start(source, presets=quiet)
    front.ask("/mpciml/pad/select/start")
    source.advance(650)
    assert hits(front) == [1, 1, 1]


@pytest.mark.parametrize("ending", ["record/start", "preset/load"])
def test_selection_ends_on_record_start_and_preset_load(start: Any, ending: str) -> None:
    source = SteppedReplay(STRIKES)
    front = start(source, presets=quiet)
    front.send("/mpciml/class", "soft")
    front.ask("/mpciml/pad/select/start")
    source.advance(340)
    assert hits(front) == [1]
    args = ["demo"] if ending == "preset/load" else []
    front.ask(f"/mpciml/{ending}", *args)
    source.advance(160)
    assert hits(front) == []


def test_selection_reads_input_while_training(start: Any) -> None:
    source = SteppedReplay(STRIKES)
    front = start(source, preset="pressure", presets=gated)
    front.ask("/mpciml/pad/select/start")
    GateRegressor.opened.clear()
    front.send("/mpciml/kit/load", "filter-play")
    assert front.expect("/mpciml/state") == ["training"]
    source.advance(340)
    assert hits(front) == [1]
    GateRegressor.opened.set()
    front.expect("/mpciml/train/done")


# States


def enter(front: Front, state: str) -> None:
    """Bring a fresh `pressure` engine with a kit into `state`."""
    kit_loaded(front)
    settle(front)
    if state == "recording":
        front.send("/mpciml/targets", *[0.5] * 8)
        front.send("/mpciml/record/start")
    elif state == "training":
        GateRegressor.opened.clear()
        front.send("/mpciml/train")
    elif state == "running":
        front.send("/mpciml/run")
    assert front.state() == state


ARGS: dict[str, list[Any]] = {"kit/load": ["filter-play"], "pad/module": [1, "bite"]}
TABLE = {
    "kit/list": "✓✓✓✓",
    "module/list": "✓✓✓✓",
    "kit/load": "✓✗✗✓",
    "pad/module": "✓✗✗✓",
    "pad/select/start": "✓✗✓✓",
    "pad/select/stop": "✓✗✓✓",
}
"""ADR 0007's state table; columns idle, recording, training, running."""


def test_the_table_matches_the_engine() -> None:
    assert {m: {s for s, c in zip(STATES, row, strict=True) if c == "✓"} for m, row in
            TABLE.items()} == {m: set(ALLOWED[m]) for m in TABLE}  # fmt: skip


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize("message", sorted(TABLE))
def test_state_table(start: Any, state: str, message: str) -> None:
    front = start(preset="pressure", presets=gated)
    enter(front, state)
    address = f"/mpciml/{message}"
    replies = front.ask(address, *ARGS.get(message, []))
    errors = [args for a, args in replies if a == "/mpciml/error"]
    if TABLE[message][STATES.index(state)] == "✗":
        assert [e[:2] for e in errors] == [["wrong_state", address]]
        assert front.state() == state
    else:
        assert errors == []
    GateRegressor.opened.set()
    if message in ARGS and state in ("idle", "running"):
        if "/mpciml/train/done" not in addresses(replies):
            front.expect("/mpciml/train/done")
