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
`record/stop`; train and run with the core messages. The preset has no preset
controls; its Pure Data front end is `patches/pressure.pd` in this package. It
registers like any external preset, in `pyproject.toml`:

    [project.entry-points."mpc_iml.presets"]
    pressure = "mpc_iml.pressure:PRESET"
"""

from mpc_iml import __version__
from mpc_iml.examples import pressure_features
from mpc_iml.presets import MidiCcOutput, OscOutput, Preset
from mpc_iml.sklearn_backend import Regressor

TARGETS = 8
"""The number of synthesis parameters (model outputs)."""

CONTROLLERS = tuple(range(20, 20 + TARGETS))
"""MIDI CC 20-27: undefined in the MIDI spec, so they do not collide with
modulation, volume, pan or sustain in a DAW synthesiser."""

PRESET = Preset(
    name="pressure",
    version=__version__,
    description="Pad pressure to 8 synthesis parameters (OSC and MIDI CC 20-27)",
    features=pressure_features,
    model_factory=Regressor,
    targets=TARGETS,
    outputs=(OscOutput(), MidiCcOutput(controllers=CONTROLLERS, channel=1, port_name="mpc-iml")),
    patch="mpc_iml:patches/pressure.pd",
)
"""Scenario 1 as the built-in preset `pressure`."""
