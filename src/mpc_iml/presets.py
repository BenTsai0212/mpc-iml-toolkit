"""Plugin interface for presets (RFC 0002, Issue #63).

A preset bundles what the existing extension points already take: a feature
function (`ExampleSet(features=...)`), a model factory (`IMLLoop(model_factory=...)`),
optional fixed class numbers, and a declarative output mapping. It adds a name, a
version, an optional front-end patch and a provisional control hook.

Presets are discovered through the entry point group `mpc_iml.presets`. Each entry
point refers to a `Preset` or to a zero-argument callable returning one. The
built-in presets register the same way, in this package's `pyproject.toml`:

    [project.entry-points."mpc_iml.presets"]
    demo = "mpc_iml.demo:PRESET"

So an external package adds a preset by declaring an entry point in its own
`pyproject.toml`, without changing the toolkit.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import EntryPoint, entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable

from mpc_iml.examples import ExampleSet, FeatureFn, default_features
from mpc_iml.loop import IMLLoop
from mpc_iml.model import ModelFactory
from mpc_iml.osc import DEFAULT_HOST, OUTPUTS_ADDRESS, OUTPUTS_PORT, OscSender

__all__ = [
    "PRESET_GROUP",
    "ControlHandler",
    "MidiCcOutput",
    "OscOutput",
    "Output",
    "Preset",
    "PresetError",
    "available_presets",
    "get_preset",
    "scale_to_cc",
]

PRESET_GROUP = "mpc_iml.presets"
"""The entry point group presets are registered in."""

_NAME = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")

ControlHandler = Callable[[Sequence[float | int | str]], None]
"""Provisional (ADR 0004): handles the arguments of one preset control message."""


class PresetError(Exception):
    """A preset is invalid, cannot be loaded, is duplicated or is unknown."""


@dataclass(frozen=True)
class OscOutput:
    """Model outputs sent as OSC floats; the defaults are Wekinator's outputs."""

    address: str = OUTPUTS_ADDRESS
    host: str = DEFAULT_HOST
    port: int = OUTPUTS_PORT

    def sender(self) -> OscSender:
        """A new sender for this output."""
        return OscSender(self.address, self.host, self.port)


def scale_to_cc(value: float, low: float = 0.0, high: float = 1.0) -> int:
    """Scale `value` from `low`-`high` to a MIDI CC value 0-127, clamped and rounded."""
    if high == low:
        raise ValueError(f"range must not be empty: {low}-{high}")
    fraction = (value - low) / (high - low)
    return round(min(max(fraction, 0.0), 1.0) * 127)


@dataclass(frozen=True)
class MidiCcOutput:
    """Model outputs sent as MIDI control changes, one controller per output value.

    Declaration and scaling only: the sender that opens a virtual MIDI port comes
    with the first preset that needs it (#65). `ranges` gives the input range of
    each value (default 0-1 for all).
    """

    controllers: tuple[int, ...]
    channel: int = 1
    port_name: str = "mpc-iml"
    ranges: tuple[tuple[float, float], ...] | None = None

    def __post_init__(self) -> None:
        if not self.controllers:
            raise ValueError("at least one controller is needed")
        if any(not 0 <= c <= 127 for c in self.controllers):
            raise ValueError(f"controllers must be 0-127: {self.controllers}")
        if not 1 <= self.channel <= 16:
            raise ValueError(f"channel must be 1-16: {self.channel}")
        if self.ranges is not None and len(self.ranges) != len(self.controllers):
            raise ValueError("ranges must have one (low, high) per controller")

    def messages(self, values: Sequence[float]) -> list[bytes]:
        """The control change messages (3 bytes each) for one prediction."""
        if len(values) != len(self.controllers):
            raise ValueError(f"expected {len(self.controllers)} values, got {len(values)}")
        ranges = self.ranges or ((0.0, 1.0),) * len(self.controllers)
        status = 0xB0 | (self.channel - 1)
        return [
            bytes([status, controller, scale_to_cc(value, low, high)])
            for controller, value, (low, high) in zip(self.controllers, values, ranges, strict=True)
        ]


Output = OscOutput | MidiCcOutput


@dataclass(frozen=True)
class Preset:
    """A named bundle of features, model and outputs, loaded as a plugin.

    - `name`: unique key, lower case letters, digits and hyphens.
    - `features`, `classes`: passed to `ExampleSet`.
    - `model_factory`: passed to `IMLLoop`; `None` means Wekinator is the model.
    - `outputs`: where predictions go; `build_loop` sends to the first `OscOutput`.
    - `patch`: the front-end patch as `"<package>:<path inside the package>"`.
    - `controls`: **provisional until ADR 0004 is accepted.** Maps a control name to
      a handler. Under the ADR 0004 plan (#62) a control `<control>` will be
      addressed as `/mpciml/preset/<name>/<control>` and forwarded only to the
      active preset; nothing dispatches it yet (#64), and its type may change.
    """

    name: str
    version: str
    description: str = ""
    features: FeatureFn = default_features
    model_factory: ModelFactory | None = None
    classes: Mapping[str, int] | None = None
    outputs: tuple[Output, ...] = (OscOutput(),)
    controls: Mapping[str, ControlHandler] = field(default_factory=dict)
    patch: str | None = None

    def __post_init__(self) -> None:
        if not _NAME.fullmatch(self.name):
            raise PresetError(
                f"preset name must be lower case letters, digits and hyphens: {self.name!r}"
            )
        if self.patch is not None and ":" not in self.patch:
            raise PresetError(f"patch must be '<package>:<path>': {self.patch!r}")

    def example_set(self) -> ExampleSet:
        """An empty `ExampleSet` with this preset's features and classes."""
        return ExampleSet(features=self.features, classes=self.classes)

    def build_loop(
        self,
        examples: ExampleSet | None = None,
        inputs: OscSender | None = None,
        outputs: OscSender | None = None,
    ) -> IMLLoop:
        """An `IMLLoop` for this preset (not trained yet).

        `outputs` defaults to a sender for the first declared `OscOutput`, if any.
        """
        if outputs is None:
            osc = next((o for o in self.outputs if isinstance(o, OscOutput)), None)
            outputs = osc.sender() if osc is not None else None
        return IMLLoop(
            self.model_factory,
            examples=examples if examples is not None else self.example_set(),
            inputs=inputs,
            outputs=outputs,
        )

    def patch_path(self) -> Traversable | None:
        """The front-end patch inside its package, or `None` when there is none."""
        if self.patch is None:
            return None
        package, _, path = self.patch.partition(":")
        return files(package).joinpath(path)


def _origin(entry: EntryPoint) -> str:
    dist = entry.dist.name if entry.dist is not None else "unknown distribution"
    return f"entry point {entry.name!r} ({entry.value}) of {dist}"


def _load(entry: EntryPoint) -> Preset:
    try:
        obj = entry.load()
        if callable(obj) and not isinstance(obj, Preset):
            obj = obj()
    except Exception as error:
        raise PresetError(f"cannot load {_origin(entry)}: {error}") from error
    if not isinstance(obj, Preset):
        raise PresetError(f"{_origin(entry)} is not a Preset: {type(obj).__name__}")
    return obj


def available_presets(group: str = PRESET_GROUP) -> dict[str, Preset]:
    """Load every preset registered in `group`, by name.

    Raises `PresetError` when an entry point fails to load, is not a `Preset`, or
    has the same name as another one, so a broken plugin is not silently missing.
    """
    presets: dict[str, Preset] = {}
    origins: dict[str, str] = {}
    for entry in entry_points(group=group):
        preset = _load(entry)
        if preset.name in presets:
            raise PresetError(
                f"two presets named {preset.name!r}: {origins[preset.name]} and {_origin(entry)}"
            )
        presets[preset.name] = preset
        origins[preset.name] = _origin(entry)
    return presets


def get_preset(name: str, group: str = PRESET_GROUP) -> Preset:
    """The preset called `name`; raises `PresetError` when there is none."""
    presets = available_presets(group)
    if name not in presets:
        known = ", ".join(sorted(presets)) or "none"
        raise PresetError(f"unknown preset {name!r}; available: {known}")
    return presets[name]
