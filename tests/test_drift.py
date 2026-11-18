"""Drift, experiment A of RFC 0004, as a mode of the `pressure` preset (#114).

Drift is checked on synthetic feature rows with a fake inner model, and on the
replayed `pressure_*.jsonl` recordings with the real `Regressor`; the controls go
through a running engine with fake MIDI. No hardware.
"""

import dataclasses
from collections.abc import Mapping, Sequence
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
import test_engine
from test_engine import Front, presets
from test_fixtures import load
from test_pressure import Collect, FakeMidiOut

from mpc_iml.drift import (
    HANDBACK_FRAMES,
    HOLD_FRAMES,
    DriftModel,
    DriftModels,
    DriftState,
    leg_seconds,
    smoothstep,
)
from mpc_iml.examples import pressure_features
from mpc_iml.frames import DEFAULT_RATE, Frame, frames
from mpc_iml.loop import IMLLoop
from mpc_iml.presets import PRESET_GROUP, Preset
from mpc_iml.pressure import PRESET, make_preset
from mpc_iml.sklearn_backend import Regressor
from mpc_iml.sources import ReplaySource

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

DATA = Path(__file__).parent / "data"
EXAMPLES = DATA / "pressure_examples.jsonl"
PERFORMANCE = DATA / "pressure_performance.jsonl"

TARGETS = [[0.0] * 8] * 10 + [[1.0] * 8] * 30 + [[0.2, 0.8] * 4] * 20
"""Three distinct example targets, weighted 10, 30 and 20 frames."""


class Fake:
    """An inner model whose 8 outputs all equal the sum of the features."""

    def __init__(self) -> None:
        self.seen: list[list[float]] = []

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        pass

    def predict(self, values: Sequence[float]) -> list[float]:
        self.seen.append(list(values))
        return [sum(values)] * 8


def press(pad: int = 1, value: float = 0.5) -> list[float]:
    row = [0.0] * 16
    row[pad - 1] = value
    return row


ZERO = [0.0] * 16


def drift_model(seed: int = 1, **settings: Any) -> tuple[DriftModel, Fake]:
    """A trained drift model, switched on, with `settings` (`pad` defaults to 0)."""
    state = DriftState(seed=seed)
    inner = Fake()
    model = DriftModels(lambda: inner, state)()
    model.fit([ZERO] * len(TARGETS), TARGETS)
    state.set_on([1])
    for name, value in {"pad": 0, **settings}.items():
        state.controls()[f"drift/{name}"]([value])
    return model, inner


def play(model: DriftModel, rows: Sequence[Sequence[float]]) -> list[list[float]]:
    return [model.predict(row) for row in rows]


def biggest_step(outputs: Sequence[Sequence[float]]) -> float:
    return max(
        max(abs(a - b) for a, b in zip(x, y, strict=True))
        for x, y in zip(outputs, outputs[1:], strict=False)
    )


# The preset


def test_registered_through_make_preset_with_fresh_state() -> None:
    entry = {e.name: e for e in entry_points(group=PRESET_GROUP)}["pressure"]
    assert entry.value == "mpc_iml.pressure:make_preset"
    first, second = make_preset(), make_preset()
    assert isinstance(first.model_factory, DriftModels)
    assert isinstance(second.model_factory, DriftModels)
    assert first.model_factory.state is not second.model_factory.state
    assert first.model_factory.inner is Regressor
    assert sorted(first.controls) == ["drift/on", "drift/pad", "drift/range", "drift/speed"]
    state = first.model_factory.state
    assert (state.on, state.range, state.speed, state.pad) == (False, 0.5, 0.3, 16)
    assert PRESET.name == "pressure" and isinstance(PRESET.model_factory, DriftModels)


@pytest.mark.parametrize(
    ("control", "value"),
    [
        ("on", 2),
        ("on", 0.5),
        ("on", "1"),
        ("range", -0.1),
        ("range", 1.5),
        ("speed", 2),
        ("pad", 17),
        ("pad", -1),
        ("pad", 1.5),
    ],
)
def test_controls_reject_bad_values(control: str, value: Any) -> None:
    state = DriftState()
    with pytest.raises(ValueError):
        state.controls()[f"drift/{control}"]([value])
    with pytest.raises(ValueError):
        state.controls()[f"drift/{control}"]([])
    assert (state.on, state.range, state.speed, state.pad) == (False, 0.5, 0.3, 16)


def test_leg_length_and_smoothstep() -> None:
    assert leg_seconds(0) == pytest.approx(20.0)
    assert leg_seconds(1) == pytest.approx(2.0)
    assert smoothstep(0) == 0 and smoothstep(1) == 1 and smoothstep(0.5) == 0.5


# The off switch: today's output exactly


def trained(factory: Any) -> tuple[IMLLoop, Collect]:
    outputs = Collect()
    preset = dataclasses.replace(PRESET, model_factory=factory)
    examples = preset.example_set()
    examples.add_recording(EXAMPLES)
    loop = preset.build_loop(examples, outputs=outputs)
    loop.train()
    return loop, outputs


@pytest.mark.parametrize("switched", [False, True])
def test_off_reproduces_the_plain_regressor_exactly(switched: bool) -> None:
    today, today_out = trained(Regressor)
    preset = make_preset(seed=1)
    assert isinstance(preset.model_factory, DriftModels)
    if switched:
        preset.controls["drift/on"]([1])
        preset.controls["drift/range"]([1.0])
        preset.controls["drift/on"]([0])
    drift, drift_out = trained(preset.model_factory)
    for path in (PERFORMANCE, DATA.parent / "fixtures" / "recordings" / "hold-pressure.jsonl"):
        today.run(ReplaySource(path, realtime=False))
        drift.run(ReplaySource(path, realtime=False))
    assert len(drift_out.values) > 500
    assert drift_out.values == today_out.values


def test_drift_continues_after_a_replayed_performance() -> None:
    preset = make_preset(seed=3)
    preset.controls["drift/on"]([1])
    preset.controls["drift/pad"]([0])
    preset.controls["drift/speed"]([1.0])
    loop, outputs = trained(preset.model_factory)
    played = list(frames(ReplaySource(PERFORMANCE, realtime=False)))
    last = played[-1]
    silence = [dataclasses.replace(last, t=last.t + (i + 1) / DEFAULT_RATE) for i in range(600)]
    for f in [*played, *silence]:
        loop.step(f)
    today, today_out = trained(Regressor)
    for f in [*played, *silence]:
        today.step(f)
    # Pads are held at the end of the sweep, so after the hand-back the output is the model's.
    sweep_end = 110
    assert outputs.values[sweep_end] == today_out.values[sweep_end]
    rest = today_out.values[-1]
    after = outputs.values[len(played) + HOLD_FRAMES + 200 :]
    assert any(max(abs(a - b) for a, b in zip(v, rest, strict=True)) > 0.05 for v in after)
    assert biggest_step(outputs.values[len(played) :]) < 0.02


# Drift and hand-back on synthetic rows


def test_release_holds_then_drifts_within_the_targets_without_jumps() -> None:
    model, _ = drift_model(range=1.0, speed=1.0)
    played = play(model, [press(1, 0.6)] * 20)
    assert played[-1] == [0.6] * 8
    released = play(model, [ZERO] * 3000)
    assert released[:HOLD_FRAMES] == [[0.6] * 8] * HOLD_FRAMES
    assert released[HOLD_FRAMES + 100] != [0.6] * 8
    assert biggest_step([played[-1], *released]) < 0.02
    lows = [min(0.6, 0.0, 0.2) for _ in range(8)]
    highs = [max(0.6, 1.0, 0.8) for _ in range(8)]
    for row in released:
        assert all(lo - 1e-9 <= v <= hi + 1e-9 for v, lo, hi in zip(row, lows, highs, strict=True))
    # It reached at least two of the example targets (range 1).
    reached = {tuple(round(v, 6) for v in row) for row in released}
    assert sum(t in reached for t in [(0.0,) * 8, (1.0,) * 8, (0.2, 0.8) * 4]) >= 2


def test_range_zero_keeps_the_release_point() -> None:
    model, _ = drift_model(range=0.0, speed=1.0)
    play(model, [press(2, 0.3)] * 5)
    assert play(model, [ZERO] * 1000) == [[0.3] * 8] * 1000


def test_a_short_gap_does_not_start_drift() -> None:
    model, inner = drift_model(range=1.0, speed=1.0)
    play(model, [press(1, 0.4)] * 10)
    gap = play(model, [ZERO] * 20)
    assert gap == [[0.4] * 8] * 20
    back = play(model, [press(1, 0.4)] * 30)
    assert back == [[0.4] * 8] * 30


def test_the_same_seed_gives_the_same_drift() -> None:
    rows = [press(1, 0.5)] * 10 + [ZERO] * 2000
    first, _ = drift_model(seed=7, range=1.0, speed=1.0)
    again, _ = drift_model(seed=7, range=1.0, speed=1.0)
    other, _ = drift_model(seed=8, range=1.0, speed=1.0)
    assert play(first, rows) == play(again, rows)
    assert play(drift_model(seed=7, range=1.0, speed=1.0)[0], rows) != play(other, rows)


def test_hand_back_crossfades_then_follows_the_model_exactly() -> None:
    model, _ = drift_model(range=1.0, speed=1.0)
    play(model, [press(1, 0.5)] * 10)
    drifting = play(model, [ZERO] * 700)
    assert drifting[-1] != [0.9] * 8
    back = play(model, [press(1, 0.9)] * 40)
    assert biggest_step([drifting[-1], *back[:HANDBACK_FRAMES]]) < 0.25
    assert back[HANDBACK_FRAMES - 2] != [0.9] * 8
    assert back[HANDBACK_FRAMES - 1 :] == [[0.9] * 8] * (40 - HANDBACK_FRAMES + 1)


def test_a_retrain_while_drifting_continues_from_the_same_position() -> None:
    state = DriftState(seed=2)
    factory = DriftModels(Fake, state)
    old = factory()
    old.fit([ZERO] * len(TARGETS), TARGETS)
    state.set_on([1])
    state.set_pad([0])
    state.set_speed([1.0])
    state.set_range([1.0])
    before = play(old, [press(1, 0.5)] * 5 + [ZERO] * 500)
    new = factory()
    new.fit([ZERO] * 2, [[0.0] * 8, [0.5] * 8])
    after = play(new, [ZERO] * 1500)
    assert biggest_step([before[-1], *after]) < 0.02
    assert after[-1] != before[-1]


# The pad switch


def test_on_starts_in_instrument_and_pad_16_toggles_drift() -> None:
    model, inner = drift_model(pad=16, range=1.0, speed=1.0)
    play(model, [press(1, 0.5)] * 5)
    # Instrument: today's behaviour, rest right after release.
    assert play(model, [ZERO] * 50) == [[0.0] * 8] * 50

    # Pad 16 switches to drift; it is not played (the model never sees it).
    seen = len(inner.seen)
    assert play(model, [press(16, 0.7)] * 10) == [[0.0] * 8] * 10
    assert all(row[15] == 0.0 for row in inner.seen[seen:])
    play(model, [ZERO] * 50)
    play(model, [press(1, 0.5)] * 20)
    released = play(model, [ZERO] * 800)
    assert released[:HOLD_FRAMES] == [[0.5] * 8] * HOLD_FRAMES
    assert released[-1] != [0.5] * 8

    # Pad 16 again: back to instrument, crossfading to the model without a jump.
    back = play(model, [press(16, 0.7)] * 30 + [ZERO] * 10)
    assert biggest_step([released[-1], *back]) < 0.25
    assert back[HANDBACK_FRAMES:] == [[0.0] * 8] * (40 - HANDBACK_FRAMES)


def test_pad_16_does_not_hand_back_while_drifting() -> None:
    model, inner = drift_model(pad=16, range=0.0)
    play(model, [press(16, 0.7)] + [ZERO] * 50 + [press(1, 0.5)] * 20)
    held = play(model, [ZERO] * 400)
    assert held[-1] == [0.5] * 8
    # Pad 16 switches back to instrument: the output fades from the drift point to the
    # model's rest without pad 16, never towards pad 16's pressure.
    seen = len(inner.seen)
    outputs = play(model, [press(16, 0.7)] * 30)
    assert all(row[15] == 0.0 for row in inner.seen[seen:])
    assert all(0.0 <= row[0] <= 0.5 for row in outputs)
    assert outputs[-1] == [0.0] * 8


def test_a_retriggering_hold_on_pad_16_toggles_once() -> None:
    model, _ = drift_model(pad=16, range=0.0)
    hold = [press(16, 0.02)] * 30 + [ZERO] * 20 + [press(16, 0.02)] * 30 + [ZERO] * 50
    play(model, hold)
    play(model, [press(1, 0.5)] * 20)
    # Drift (one toggle): the release is held instead of falling to rest.
    assert play(model, [ZERO] * 5) == [[0.5] * 8] * 5


def test_pad_zero_leaves_pad_16_a_normal_pad() -> None:
    model, inner = drift_model(pad=0, range=0.0)
    assert play(model, [press(16, 0.7)] * 5) == [[0.7] * 8] * 5
    assert inner.seen[-1][15] == 0.7
    # Drift is on without a switch: the release is held.
    assert play(model, [ZERO] * 50) == [[0.7] * 8] * 50


def test_off_after_drift_returns_to_the_model_at_once() -> None:
    model, inner = drift_model(range=1.0, speed=1.0)
    play(model, [press(1, 0.5)] * 5 + [ZERO] * 500)
    model.state.set_on([0])
    assert play(model, [ZERO] * 3) == [[0.0] * 8] * 3


def test_a_quick_flick_without_pressure_does_not_toggle() -> None:
    """`strikes.jsonl`: strikes without poly pressure leave every feature at 0."""
    rows = [pressure_features(f) for f in frames(load("strikes").events)]
    assert rows and all(v == 0.0 for row in rows for v in row)


# Through the engine


def test_engine_routes_drift_controls_and_resets_them_on_preset_load(start: Any) -> None:
    made: list[Preset] = []

    def found() -> Mapping[str, Preset]:
        made.append(dataclasses.replace(make_preset(), outputs=()))
        return presets(made[-1])

    front: Front = start(preset="pressure", presets=found, midi_backend=FakeMidiOut)
    state = made[0].model_factory.state  # type: ignore[union-attr]
    for control, value in [("on", 1), ("range", 0.8), ("speed", 1.0), ("pad", 0)]:
        assert front.ask(f"/mpciml/preset/pressure/drift/{control}", value) == []
    assert (state.on, state.range, state.speed, state.pad) == (True, pytest.approx(0.8), 1.0, 0)
    assert front.error("/mpciml/preset/pressure/drift/range", 2.0)[0] == "bad_arguments"
    assert front.error("/mpciml/preset/pressure/drift/on")[0] == "bad_arguments"
    assert front.error("/mpciml/preset/pressure/drift/nope", 1)[0] == "unknown_message"
    assert front.error("/mpciml/preset/demo/drift/on", 1)[0] == "inactive_preset"
    assert state.range == pytest.approx(0.8)

    front.send("/mpciml/preset/load", "demo")
    assert front.expect("/mpciml/preset")[0] == "demo"
    assert front.error("/mpciml/preset/pressure/drift/on", 1)[0] == "inactive_preset"
    front.send("/mpciml/preset/load", "pressure")
    assert front.expect("/mpciml/preset")[0] == "pressure"
    fresh = made[-1].model_factory.state  # type: ignore[union-attr]
    assert fresh is not state
    assert (fresh.on, fresh.range, fresh.speed, fresh.pad) == (False, 0.5, 0.3, 16)
    replies = front.ask("/mpciml/preset/pressure/drift/on", 1)
    assert "/mpciml/error" not in [address for address, _ in replies]
    assert fresh.on


def test_frame_rows_match_pressure_features() -> None:
    """Pad 16 of the switch is feature 16 of `pressure_features`, in any bank."""
    f = Frame(0.0, (0,) * 15 + (90,), (0,) * 16, (False,) * 16, 3)
    assert pressure_features(f)[15] > 0
