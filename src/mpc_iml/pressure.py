"""Built-in preset `pressure`: pad pressure to many synthesis parameters (#65).

Scenario 1 of RFC 0002. Pad pressure is mapped by demonstration to 8 synthesis
parameters at once (one-to-many regression):

- features: `pressure_features` (16 values: per pad, pressure, 0-1; no velocity),
  so the input rises from 0 with pressure, a very light hold that retriggers stays
  continuous (#76), and "rest right after playing" is rest (#43);
- model: the built-in `Regressor` (MLP), 8 outputs, targets 0-1;
- outputs: `/wek/outputs` on `127.0.0.1:12000` (8 floats, unscaled, for Pure
  Data), and MIDI control changes 20-27 on channel 1 of the virtual port
  `mpc-iml` (0-1 scaled to 0-127 and clamped), for a DAW synthesiser.

Record with `/mpciml/targets` and eight values, then `record/start` and
`record/stop`; train and run with the core messages. Its Pure Data front end is the
general `patches/mpc-iml.pd` in this package (ADR 0006).

Drift (experiment A of RFC 0004, `mpc_iml.drift`, #114) is a mode of this preset,
off by default: the model is a `DriftModel` around the `Regressor`, and the preset
controls `drift/on`, `drift/range`, `drift/speed` and `drift/pad` arrive as
`/mpciml/preset/pressure/drift/...`. With `drift/on 0` the output is the
`Regressor`'s prediction unchanged. The preset has no state replies; the drift
settings go back to their defaults whenever the preset is built again (the engine
builds it when it starts and when `preset/load` switches to it from another preset),
so a front end resends its values when it receives `/mpciml/preset pressure`.

It registers like any external preset, in `pyproject.toml`, through `make_preset`,
so each build has its own drift state:

    [project.entry-points."mpc_iml.presets"]
    pressure = "mpc_iml.pressure:make_preset"

Its outputs are named (`OUTPUT_NAMES`, ADR 0007), and its modules and kits are in
`mpc_iml/modules/pressure/` and `mpc_iml/kits/pressure/`, registered as `CONTENT`
in the entry point group `mpc_iml.content`.
"""

from mpc_iml import __version__
from mpc_iml.content import Content
from mpc_iml.drift import DriftModels, DriftState
from mpc_iml.examples import pressure_features
from mpc_iml.presets import MidiCcOutput, OscOutput, Preset
from mpc_iml.sklearn_backend import Regressor

TARGETS = 8
"""The number of synthesis parameters (model outputs)."""

CONTROLLERS = tuple(range(20, 20 + TARGETS))
"""MIDI CC 20-27: undefined in the MIDI spec, so they do not collide with
modulation, volume, pan or sustain in a DAW synthesiser."""

OUTPUT_NAMES = (
    "brightness",
    "resonance",
    "drive",
    "space",
    "motion",
    "pitch",
    "texture",
    "level",
)
"""The names of outputs 1-8 (CC 20-27), ADR 0007."""


def make_preset(seed: int | None = None) -> Preset:
    """Scenario 1 as the built-in preset `pressure`, with fresh drift state.

    `seed` makes drift repeatable (tests); `None` seeds it at random.
    """
    state = DriftState(seed=seed)
    return Preset(
        name="pressure",
        version=__version__,
        description="Pad pressure to 8 synthesis parameters (OSC and MIDI CC 20-27)",
        features=pressure_features,
        model_factory=DriftModels(Regressor, state),
        targets=TARGETS,
        outputs=(
            OscOutput(),
            MidiCcOutput(controllers=CONTROLLERS, channel=1, port_name="mpc-iml"),
        ),
        controls=state.controls(),
        patch="mpc_iml:patches/mpc-iml.pd",
        output_names=OUTPUT_NAMES,
    )


PRESET = make_preset()
"""One build of `pressure`, kept for existing imports; the entry point is `make_preset`."""

CONTENT = Content(preset="pressure", root="mpc_iml")
"""The built-in modules and kits for `pressure` (ADR 0007)."""
