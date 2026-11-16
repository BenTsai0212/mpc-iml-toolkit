English | [繁體中文](README.zh-TW.md)

# mpc-iml-toolkit

A base toolkit for interactive machine learning (IML) with an Akai MPC Sample and a
Mac. The MPC is used over USB as a gesture controller (velocity and polyphonic
aftertouch on the 16 pads) and as an audio interface; models run on the Mac.

The toolkit covers the shared plumbing of the IML loop: record examples, train, run
in real time, then edit the examples and train again. Each IML practice (a research
question, a piece, a teaching unit) lives in its own repository and depends on a
pinned version of this toolkit, swapping inputs, models and outputs through
extension points instead of editing the toolkit.

The core is Python: MIDI input via `python-rtmidi`, models via `scikit-learn`, and
output over OSC to any synthesiser, Max, Pure Data or nn~. See
[RFC 0001](docs/rfcs/0001-project-charter.md) for the project charter and
[ADR 0001](docs/adr/0001-technology-choices.md) for the technology choices.

## Status

`v0.1.0` is the first release (see the [changelog](CHANGELOG.md)); interfaces may
still change in 0.x. Phase 1 (Foundation). To try the whole loop, follow the
[reference example](#reference-example). So far the toolkit has:

- an OSC sender (`mpc_iml.osc`) that follows Wekinator's defaults (`/wek/inputs`
  on port 6448, `/wek/outputs` on port 12000);
- a typed event model for MIDI messages and example markers (`mpc_iml.events`);
- reading and writing recordings as JSON Lines (`mpc_iml.recording`);
- frames computed from events, with 49 OSC input values per frame
  (`mpc_iml.frames`);
- event sources (`mpc_iml.sources`): live MIDI input from the MPC over
  `python-rtmidi` and replay of recordings, interchangeable downstream, with MIDI
  decoding in `mpc_iml.midi`;
- a recorder for live input:

  ```bash
  uv run python -m mpc_iml.record out.jsonl --duration 5 --firmware 1.3.0 --no-full-level
  ```

  Without `--duration` it records until Ctrl-C.
- training examples from the `example_start` / `example_end` segments of
  recordings, with stable class numbers (`mpc_iml.examples`);
- a model extension point (`mpc_iml.model.Model`: `fit` and `predict`) and
  built-in scikit-learn models, a 1-nearest-neighbour classifier and an MLP
  regressor (`mpc_iml.sklearn_backend`);
- the IML loop (`mpc_iml.loop.IMLLoop`): train on examples, then run an event
  source through frames and the model, sending features to `/wek/inputs` and
  predictions to `/wek/outputs`. Examples can be edited and the model retrained
  without restarting. With `model_factory=None` the built-in backend is off and
  only `/wek/inputs` is sent, so Wekinator can act as the model:

  ```python
  from mpc_iml.loop import IMLLoop
  from mpc_iml.osc import inputs_sender, outputs_sender
  from mpc_iml.recording import read_recording
  from mpc_iml.sklearn_backend import Classifier

  loop = IMLLoop(Classifier, inputs=inputs_sender(), outputs=outputs_sender())
  loop.examples.add_recording("examples.jsonl")
  loop.train()
  loop.run(read_recording("performance.jsonl").events)
  ```

  A recording's events run as fast as possible. A real-time source (`LiveSource`
  or `ReplaySource(..., realtime=True)`) runs on its clock: one frame every
  1 / rate seconds (10 ms at 100 Hz) whether or not MIDI arrives, so a held pad
  keeps sending. If a step takes longer than a frame interval, late frames are
  dropped: the next frame is the latest one due and includes every event up to its
  time, and `loop.dropped_frames` counts the skipped frames. `duration` and `stop`
  end the run:

  ```python
  from mpc_iml.sources import LiveSource

  with LiveSource() as source:
      loop.run(source, duration=60)
  ```

  `mpc_iml.frames.realtime_frames` gives the same real-time frames without the loop.

Formats are in [ADR 0002](docs/adr/0002-recording-and-osc-formats.md). The package
is not published. Interfaces
will change without notice until the first release (`v0.1.0`).

## Reference example

A minimal end-to-end run of the IML loop, from a fresh Mac: record a few examples
on the pads, train the built-in 1-nearest-neighbour model, and run it live. It has
three classes on pad 1 (bottom left, bank A): **rest** (no pads), **soft** (pad 1
held lightly) and **hard** (pad 1 held firmly). The model sends the class number to
`/wek/outputs` on `127.0.0.1:12000`: 1 rest, 2 soft, 3 hard. The code is
`src/mpc_iml/demo.py`.

You need an MPC Sample, a USB cable, and a Mac with a terminal (Terminal.app).

1. Install [uv](https://docs.astral.sh/uv/) with its official installer, then open
   a new terminal window so that `uv` is found:

   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

2. Get the toolkit and install it (uv also installs Python 3.12 if needed):

   ```bash
   git clone https://github.com/BenTsai0212/mpc-iml-toolkit.git
   cd mpc-iml-toolkit
   uv sync
   ```

   If macOS asks to install the command line developer tools for `git`, accept
   and run `git clone` again afterwards.

3. Set up the MPC Sample: connect it to the Mac over USB, then in its MIDI
   settings set **MIDI Port** to **USB** and **Pad MIDI Out** to **Always**, and
   turn **Full Level** off (with Full Level on every velocity is 127, so soft and
   hard cannot be told apart).

4. Start the receiver in its own terminal window and leave it open. It prints a
   line each time the class changes:

   ```bash
   cd mpc-iml-toolkit
   uv run python -m mpc_iml.demo listen
   ```

   Optional, to hear the result: install [Pure Data](https://puredata.info)
   (vanilla; the patch was written for Pd 0.54) from its website or with
   `brew install --cask pd`, open `examples/reference/receiver.pd` and turn the
   volume up. Soft plays 220 Hz, hard 440 Hz, rest is silent. Pd and the terminal
   receiver cannot both listen on port 12000: to use Pd, close the terminal
   receiver with Ctrl-C (or run both on different ports with `--osc-port`).

5. Record the examples in the first window. For each class the terminal says what
   to do and counts down 3 seconds, then records 3 seconds: for **rest** do not
   touch the pads; for **soft** press and hold pad 1 lightly before the countdown
   ends and keep holding until the next prompt; for **hard** do the same, firmly.
   Make soft and hard clearly different, for example a light fingertip touch and a
   firm press with the whole finger. When the terminal says "Release pad 1 now.",
   let go of the pad before the next countdown.

   ```bash
   uv run python -m mpc_iml.demo record examples.jsonl --no-full-level
   ```

   The receiver stays silent while you record: it only reacts in step 6
   (`demo run`). `--seconds` and `--countdown` change the timing. Run it again to
   start over.

6. Train and run live. The command trains on `examples.jsonl`, then reads the pads
   until Ctrl-C. Hold pad 1 lightly, then firmly, then let go: the receiver shows
   2 soft, 3 hard, 1 rest.

   ```bash
   uv run python -m mpc_iml.demo run examples.jsonl
   ```

Without an MPC, the same example runs from recordings in `tests/data/` (the replay
path that CI tests). Start the receiver as in step 4, then:

```bash
uv run python -m mpc_iml.demo run tests/data/demo_examples.jsonl --replay tests/data/demo_performance.jsonl
```

The replay plays soft, hard and rest in about 2.5 seconds. `--replay` also takes
your own recording from `python -m mpc_iml.record`. If the MPC is not found, the
command lists the MIDI input ports it sees; `--port` picks another port by part of
its name.

The demo uses the feature set `mpc_iml.examples.played_features` (32 values: per
pad, velocity while held, else 0, then pressure) rather than the default 49, which
keep a pad's last velocity after it is released. It does not send `/wek/inputs`.

### Feature sets for playing

The default features (`mpc_iml.examples.default_features`) are the 49 `/wek/inputs`
values of ADR 0002. They keep a pad's last velocity after `Note Off`, so a "rest"
frame right after playing looks like the last hit, and a model trained on them can
answer with the last sound instead of rest. For models that react while you play,
use `played_features`: a released pad gives 0, so rest right after playing is rest.
Pass it where features are taken, for example `ExampleSet(features=played_features)`
or a preset's `features=`. The presets `demo` and `pressure` use it; the 49
`/wek/inputs` values do not change.

## Run the engine

The engine is a long-running IML loop that a front end (Pure Data, Max, later an
app) drives with OSC control messages; the protocol is
[ADR 0004](docs/adr/0004-engine-control-protocol.md). Start it with a folder for
its saved example sets, with the MPC connected as in the
[reference example](#reference-example):

```bash
uv run python -m mpc_iml.engine my-data
```

It listens for control messages on `127.0.0.1:6450`, sends replies and state reports
to `127.0.0.1:6451`, and starts with the preset `demo` (`--preset` picks another).
While running it sends the preset's features to `/wek/inputs` (port 6448) and its
model outputs to the preset's output (`/wek/outputs` on port 12000 for `demo`).
`--control-port`, `--reply-port`, `--inputs-port` and `--outputs-port` change the
ports. Without an MPC, `--replay <recording>` plays a recording once in real time
instead:

```bash
uv run python -m mpc_iml.engine my-data --replay tests/fixtures/recordings/hold-pressure.jsonl
```

A session from a front end: `/mpciml/hello 1` (the engine answers with its version
and full state; integer arguments such as the version and reply port also accept a
whole-number float like `1.0`, so plain Pure Data messages work without a type tag), `/mpciml/class soft`, `/mpciml/record/start`, play,
`/mpciml/record/stop`, then `/mpciml/train`, `/mpciml/run` and `/mpciml/stop`.
`/mpciml/examples/save <name>` writes `my-data/<name>.jsonl` (an ADR 0002
recording); the engine writes nothing outside that folder. Every message gets a
reply, a state report or an `/mpciml/error`. Ctrl-C stops the engine: input and
sockets are closed and a training in progress is finished first.

## Play the pressure preset

The built-in preset `pressure` (`src/mpc_iml/pressure.py`, scenario 1 of
[RFC 0002](docs/rfcs/0002-platform-positioning.md)) maps pad pressure and velocity to
8 synthesis parameters at once. You show it a few gestures, each with the 8 values
it should produce, and it learns the mapping in between (one-to-many regression,
the built-in MLP). It uses `played_features`. While running it sends:

- `/wek/outputs` with 8 floats to `127.0.0.1:12000`, for Pure Data or any OSC
  receiver (unscaled: usually 0-1, sometimes slightly outside);
- MIDI control changes 20-27 on channel 1 (output 1 is CC 20, output 8 is CC 27),
  scaled from 0-1 to 0-127, to a virtual MIDI port named `mpc-iml`, for a DAW
  synthesiser. A CC is sent only when its value changes, and nothing is sent
  outside `running`.

You need the setup of the [reference example](#reference-example) (steps 1-3) and
[Pure Data](https://puredata.info) (vanilla 0.54 or later) for the front end.

1. Start the engine with the preset and leave the window open:

   ```bash
   uv run python -m mpc_iml.engine my-data --preset pressure
   ```

   On macOS the port `mpc-iml` now appears in every MIDI app as an input. To use
   the IAC bus instead, turn it on in Audio MIDI Setup (Window > Show MIDI Studio,
   double-click IAC Driver, tick "Device is online") and add `--midi-port IAC`. If
   the MIDI port cannot be opened, the engine says so and keeps sending OSC.

2. Open the front end `src/mpc_iml/patches/pressure.pd` in Pure Data. It says
   `hello` to the engine and loads the preset; the state box shows `idle` and the
   Pd window prints every reply (`mpc-iml: …`). Click `hello` again if you
   started the engine after the patch.

3. Record a few examples. For each one: set the 8 target sliders `t1`-`t8` on the
   left (0-1) to the sound you want, hold the gesture on the pads, click `record`
   (it sends the targets, then starts recording), keep holding for about two
   seconds, and click `stop_recording`. Start with rest (no pads, targets for
   silence), then for example pad 1 held lightly and pad 1 held firmly, each with
   its own targets. Several pads and other pressures work the same way.

4. Click `train`. The state goes to `training`, then back to `idle`, and `trained`
   shows 1. Click `run` and play: the sliders `o1`-`o8` on the right follow the
   model, and the MIDI CCs follow them. `stop` ends running. `save` and `load`
   keep the examples in `my-data/pressure-examples.jsonl`.

The patch shows `/wek/outputs` by listening on port 12000, and only one program can
listen on a port. To drive a Pd synth with OSC instead, start the engine with
`--outputs-port <port>` and let the synth listen on that port (the patch's output
sliders then stay still), or close this patch and send the control messages from
your own.

### Map the MIDI CCs in a DAW

`mpc-iml` sends only CC 20-27 on channel 1, no notes; the notes that play the
synthesiser come from the MPC Sample itself. The port exists only while the engine
runs, so start the engine before you open the DAW's MIDI settings. Turn on the
input `mpc-iml` (or the IAC bus) for remote control, then map CC 20-27 on channel 1
to synthesiser parameters:

- **Ableton Live**: in Settings > Tempo & MIDI, in the Input Ports table, turn on
  **Track** for the MPC Sample, and turn on **Remote** (Track off) for `mpc-iml`.
  Leave the track's MIDI input on the MPC Sample (or All Ins); setting it to
  `mpc-iml` gives no sound, because that port sends no notes. Enter MIDI Map Mode
  (Cmd-M), click a parameter, send its CC, and leave MIDI Map Mode.
- **Logic Pro**: select the parameter, choose Logic Pro > Control Surfaces > Learn
  Assignment for "<parameter>" (Cmd-L), send its CC, and turn Learn off.
- DAWs that let you type a CC number for a mapping: enter 20-27 directly.

While the model runs, all 8 CCs move together, so MIDI learn may catch the wrong
one. Learn one CC at a time: train a quick model with two examples whose targets
differ only in the output you want (for example rest with all 0, and pad 1 with
only `t3` at 1, for CC 22), run it, press pad 1, map, and repeat. Then load or
record your real examples and train again; the mappings stay.

Known limitation: while a pad is held very lightly, the MPC Sample (firmware 1.3.0)
sends `Note Off` when the pressure reaches its minimum and a new `Note On` 70-273 ms
later. With `played_features` the pad counts as released in between, so the outputs
can dip briefly during a very light hold. Hold a little more firmly; smoothing may
follow if playing shows it matters.

## Write a preset

A preset bundles a feature function, a model, optional fixed class numbers and an
output mapping under a name, and is loaded as a plugin (RFC 0002). The reference
example is the built-in preset `demo` (`mpc_iml.demo.PRESET`). An external package
adds a preset without changing the toolkit:

1. Define a `Preset` (`src/mpc_iml/presets.py`) in your package:

   ```python
   from mpc_iml.presets import MidiCcOutput, OscOutput, Preset

   PRESET = Preset(
       name="my-preset",
       version="0.1.0",
       description="One line for listings",
       features=my_features,
       model_factory=MyModel,
       outputs=(OscOutput(), MidiCcOutput(controllers=(20, 21))),
       patch="my_package:patches/main.pd",
   )
   ```

   `features` and `classes` are what `ExampleSet(features=..., classes=...)` takes,
   and `model_factory` is what `IMLLoop` takes (`None`: Wekinator is the model).
   `OscOutput` defaults to `/wek/outputs` on `127.0.0.1:12000`. `MidiCcOutput`
   declares one CC number per output value, scaled from `ranges` (default 0-1) to
   0-127; the engine sends them while `running` (`mpc_iml.midi_out`, see the
   [pressure preset](#play-the-pressure-preset)). `patch` is the front-end patch inside your package, as
   `<package>:<path>`. `name` is lower case letters, digits and hyphens; `list` and
   `load` are reserved for core messages (ADR 0004) and raise `PresetError`.

2. Register it in your package's `pyproject.toml`; the entry point may also name a
   function that returns a `Preset`:

   ```toml
   [project.entry-points."mpc_iml.presets"]
   my-preset = "my_package:PRESET"
   ```

3. Once the package is installed next to the toolkit, `available_presets()` lists
   it and `get_preset("my-preset").build_loop()` returns an `IMLLoop` with its
   features, model and first `OscOutput`. A preset that fails to load, is not a
   `Preset` or reuses a name raises `PresetError`.

`controls` (a control name mapped to a handler) is **provisional until ADR 0004 is
accepted**: the engine forwards `/mpciml/preset/<name>/<control>` to the handler of
`<control>`, with the message's arguments, only while `<name>` is the active preset.
Its type may change.

`tests/plugins/` holds a complete example package, and `tests/test_presets.py`
installs it and runs it on a recorded fixture.

## Start a practice repository

`python -m mpc_iml.new` creates a project that depends on this toolkit instead of
copying it: a `pyproject.toml` pinning `mpc-iml-toolkit` to the git tag of the
running version, an empty model (`src/<package>/model.py`) to replace, a script that
trains on a recording and runs on a replay, a test, a sample recording and a short
README. The package name comes from the directory name (`--name` overrides it).

```bash
uv run python -m mpc_iml.new ../my-practice
```

In the new project, `uv sync` installs the pinned release. To work against a local
checkout of the toolkit instead, run `uv add --editable <path to mpc-iml-toolkit>`
in the new project, then `uv sync`.

## Development

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 if needed)
and Node.js 22 for the workflow tool tests.

```bash
uv sync --locked
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

Tests marked `@pytest.mark.hardware` need a connected MPC Sample and are skipped by
default. Run them with the MPC connected:

```bash
uv run pytest -m hardware
```

The pad test waits 10 seconds for a quick press and release of pad A01: tap the pad,
do not hold it.

CI (`.github/workflows/ci.yml`, job `checks`) runs on Ubuntu and macOS
(`ubuntu-latest` and `macos-latest`). On each, it runs the workflow tool tests
(`npm test --prefix tools/workflow`) followed by the commands above; hardware tests
stay skipped.

## Project workflow

Work is planned in GitHub Issues and implemented by coding agents in pull requests
that a human reviews and merges. The rules for agents are in [AGENTS.md](AGENTS.md).
The workflow documents under [`docs/workflow/`](docs/workflow/), and `AGENTS.md`
itself, are written in Traditional Chinese; Issues, pull requests and commits are in
English.

## Citing

If you use the toolkit in research, please cite it. The citation metadata is in
[CITATION.cff](CITATION.cff); GitHub shows it as "Cite this repository" on the
repository page. A version number and release date are added at the first release.

## Licence

[MIT](LICENSE). Optional extensions such as RAVE and nn~ have their own licences
(CC BY-NC 4.0, non-commercial only) and are never bundled with or required by the
toolkit. The licences of the runtime dependencies are listed in
[docs/licenses.md](docs/licenses.md).
