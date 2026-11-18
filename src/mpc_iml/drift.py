"""Experiment A of RFC 0004: drift, the lowest step of AI initiative (#114).

While a pad is held the outputs follow the trained model as before. When every pad
has been released for `HOLD_FRAMES` (300 ms), the outputs do not fall back to the
resting sound: they glide slowly between points taken from the musician's example
targets. The next press hands control back to the model with a short crossfade
(`HANDBACK_FRAMES`, 150 ms), so neither the start of drift nor the hand-back jumps.

Drift runs inside the model (`DriftModel`), the one extension point the loop calls on
every frame, also while no pad is held; the engine, the loop and the protocol are
unchanged. The settings and the drift position live in one `DriftState` per preset
instance, shared by the controls and by every model the factory (`DriftModels`)
builds, so a retrain that swaps the model in while running continues from the same
position and the new example targets take effect from the next leg.

Timing counts `predict` calls at `frames.DEFAULT_RATE` (100 Hz), the rate the engine
always uses, so replays are deterministic.

Controls (`DriftState.controls`, provisional preset controls of ADR 0004, no state
replies):

- `drift/on 0|1` (default 0): the master switch. Off returns the inner model's
  prediction unchanged, which is today's output exactly. Turning it on starts in
  instrument (no drift on release) while the pad switch is active.
- `drift/range 0-1` (default 0.5): how far drift may move from where the musician let
  go towards the example targets (0 holds the release point).
- `drift/speed 0-1` (default 0.3): leg length, 20 s at 0 to 2 s at 1 (geometric), with
  ±30 % random variation per leg.
- `drift/pad 0-16` (default 16): the pad that switches between instrument and drift
  while drift is on (any bank). That pad is then only a switch: its pressure never
  reaches the model and it does not count as playing. 0 disables the pad switch, so
  drift is always active while `drift/on` is 1 and every pad plays.

The pad switch is detected from the features (pad `n` is feature `n - 1`, as in
`pressure_features`): the first frame with pressure on that pad toggles, and the
switch re-arms after the pad has reported no pressure for `HOLD_FRAMES`, so a light
hold that retriggers (#76) does not toggle twice. A quick flick may report no
pressure at all (see the `strikes.jsonl` fixture), so the switch needs a firm press.
"""

import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from mpc_iml.frames import DEFAULT_RATE, PADS
from mpc_iml.model import Model

__all__ = [
    "HANDBACK_FRAMES",
    "HOLD_FRAMES",
    "DriftModel",
    "DriftModels",
    "DriftState",
    "leg_seconds",
    "smoothstep",
]

HOLD_FRAMES = round(0.3 * DEFAULT_RATE)
"""Frames without pressure before drift starts (300 ms, longer than the 273 ms
retrigger gap of #76); also the re-arm time of the pad switch."""

HANDBACK_FRAMES = round(0.15 * DEFAULT_RATE)
"""Frames of the crossfade back to the model (150 ms)."""

SLOWEST, FASTEST = 20.0, 2.0
"""Leg length in seconds at `speed` 0 and 1."""

VARIATION = 0.3
"""Random variation of each leg's length (±30 %)."""


def smoothstep(x: float) -> float:
    """0 at 0, 1 at 1, with zero slope at both ends."""
    x = min(max(x, 0.0), 1.0)
    return x * x * (3.0 - 2.0 * x)


def leg_seconds(speed: float) -> float:
    """The mean leg length for `speed` 0-1: 20 s at 0 to 2 s at 1, geometric."""
    return float(SLOWEST * (FASTEST / SLOWEST) ** speed)


def _mix(a: Sequence[float], b: Sequence[float], amount: float) -> list[float]:
    return [x + (y - x) * amount for x, y in zip(a, b, strict=True)]


def _number(args: Sequence[float | int | str], low: float, high: float) -> float:
    if len(args) != 1:
        raise ValueError(f"expected one value, got {len(args)}")
    (value,) = args
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"expected a number, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"must be {low:g}-{high:g}, got {value}")
    return float(value)


def _whole(args: Sequence[float | int | str], low: int, high: int) -> int:
    value = _number(args, low, high)
    if value != int(value):
        raise ValueError(f"expected a whole number, got {value}")
    return int(value)


@dataclass
class _Leg:
    start: list[float]
    end: list[float]
    frames: int
    done: int = 0


@dataclass
class DriftState:
    """Drift settings and position, shared by the controls and the models."""

    seed: int | None = None
    on: bool = False
    range: float = 0.5
    speed: float = 0.3
    pad: int = PADS
    rng: random.Random = field(init=False, repr=False)
    drifting: bool = field(default=False, init=False)
    """With the pad switch active: True in drift, False in instrument."""
    last: list[float] | None = field(default=None, init=False)
    """The last output sent while on."""
    idle: int = field(default=0, init=False)
    """Frames since the last frame with pressure on a playing pad."""
    release: list[float] | None = field(default=None, init=False)
    """Where drift started; anchors are pulled towards it by `range`."""
    leg: _Leg | None = field(default=None, init=False)
    fade: tuple[list[float], int] | None = field(default=None, init=False)
    """The crossfade back to the model: its start and the frames done."""
    left_model: bool = field(default=False, init=False)
    """True after a held or drifting output, so the next model output fades in."""
    armed: bool = field(default=True, init=False)
    switch_idle: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        self.rng = random.Random(self.seed)

    @property
    def active(self) -> bool:
        """True when drift starts on release (on, and in drift or no pad switch)."""
        return self.on and (self.drifting or self.pad == 0)

    def controls(self) -> dict[str, Callable[[Sequence[float | int | str]], None]]:
        """The preset controls `drift/on`, `drift/range`, `drift/speed`, `drift/pad`."""
        return {
            "drift/on": self.set_on,
            "drift/range": self.set_range,
            "drift/speed": self.set_speed,
            "drift/pad": self.set_pad,
        }

    def set_on(self, args: Sequence[float | int | str]) -> None:
        on = bool(_whole(args, 0, 1))
        if on and not self.on:
            self._reset()
        self.on = on

    def set_range(self, args: Sequence[float | int | str]) -> None:
        self.range = _number(args, 0.0, 1.0)

    def set_speed(self, args: Sequence[float | int | str]) -> None:
        self.speed = _number(args, 0.0, 1.0)

    def set_pad(self, args: Sequence[float | int | str]) -> None:
        pad = _whole(args, 0, PADS)
        if pad != self.pad:
            self.pad = pad
            self.drifting = False
            self.armed = True
            self.switch_idle = 0

    def _reset(self) -> None:
        self.drifting = False
        self.last = None
        self.idle = 0
        self.release = None
        self.leg = None
        self.fade = None
        self.left_model = False
        self.armed = True
        self.switch_idle = 0

    def step(
        self,
        values: Sequence[float],
        predict: Callable[[Sequence[float]], list[float]],
        targets: Sequence[tuple[tuple[float, ...], int]],
    ) -> list[float]:
        """The output for one frame while on; `predict` is the inner model."""
        playing_values = list(values)
        if self.pad:
            index = self.pad - 1
            self._switch(playing_values[index] > 0)
            playing_values[index] = 0.0
        playing = any(v > 0 for v in playing_values)
        self.idle = 0 if playing else self.idle + 1

        if self.active and not playing and self.last is not None:
            output = self._drift(targets)
        else:
            output = self._follow(predict(playing_values))
        self.last = output
        return output

    def _switch(self, pressed: bool) -> None:
        if pressed:
            self.switch_idle = 0
            if self.armed:
                self.armed = False
                self.drifting = not self.drifting
                self.idle = 0
        else:
            self.switch_idle += 1
            if self.switch_idle >= HOLD_FRAMES:
                self.armed = True

    def _follow(self, model: list[float]) -> list[float]:
        """The model's prediction, crossfaded from the last output after drift or a hold."""
        self.release = None
        self.leg = None
        if self.fade is None and self.last is not None and self.left_model:
            self.fade = (self.last, 0)
        self.left_model = False
        if self.fade is None:
            return model
        start, done = self.fade
        done += 1
        if done >= HANDBACK_FRAMES:
            self.fade = None
            return model
        self.fade = (start, done)
        return _mix(start, model, smoothstep(done / HANDBACK_FRAMES))

    def _drift(self, targets: Sequence[tuple[tuple[float, ...], int]]) -> list[float]:
        """Hold the last output for `HOLD_FRAMES`, then glide between anchors."""
        assert self.last is not None
        self.left_model = True
        self.fade = None
        if self.idle <= HOLD_FRAMES:
            return self.last
        if self.release is None:
            self.release = self.last
        if self.leg is None or self.leg.done >= self.leg.frames:
            self.leg = _Leg(self.last, self._anchor(targets), self._leg_frames())
        self.leg.done += 1
        if self.leg.done >= self.leg.frames:
            return list(self.leg.end)
        return _mix(self.leg.start, self.leg.end, smoothstep(self.leg.done / self.leg.frames))

    def _anchor(self, targets: Sequence[tuple[tuple[float, ...], int]]) -> list[float]:
        assert self.release is not None
        if not targets:
            return list(self.release)
        vectors = [t for t, _ in targets]
        weights = [w for _, w in targets]
        (target,) = self.rng.choices(vectors, weights)
        if len(target) != len(self.release):
            return list(self.release)
        return _mix(self.release, target, self.range)

    def _leg_frames(self) -> int:
        seconds = leg_seconds(self.speed) * self.rng.uniform(1 - VARIATION, 1 + VARIATION)
        return max(1, round(seconds * DEFAULT_RATE))


class DriftModel:
    """A model that adds drift to an inner model (`mpc_iml.model.Model`).

    `fit` trains the inner model and keeps the distinct target vectors with their
    frame counts; `predict` returns the inner prediction unchanged while drift is off.
    """

    def __init__(self, inner: Model, state: DriftState) -> None:
        self.inner = inner
        self.state = state
        self.targets: list[tuple[tuple[float, ...], int]] = []

    def fit(self, inputs: Sequence[Sequence[float]], outputs: Sequence[Sequence[float]]) -> None:
        self.inner.fit(inputs, outputs)
        counts = Counter(tuple(float(v) for v in row) for row in outputs)
        self.targets = sorted(counts.items())

    def predict(self, values: Sequence[float]) -> list[float]:
        if not self.state.on:
            return self.inner.predict(values)
        return self.state.step(values, self.inner.predict, self.targets)


@dataclass(frozen=True)
class DriftModels:
    """A model factory: each model wraps a fresh inner model and shares `state`."""

    inner: Callable[[], Model]
    state: DriftState

    def __call__(self) -> DriftModel:
        return DriftModel(self.inner(), self.state)
