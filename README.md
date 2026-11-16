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

Phase 1 (Foundation), early. To try the whole loop, follow the
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

   ```bash
   uv run python -m mpc_iml.demo record examples.jsonl --no-full-level
   ```

   `--seconds` and `--countdown` change the timing. Run it again to start over.

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

The demo uses its own features (`played_features`, 32 values: per pad, velocity
while held and pressure) rather than the default 49, which keep a pad's last
velocity after it is released. It does not send `/wek/inputs`.

## Start a practice repository

`python -m mpc_iml.new` creates a project that depends on this toolkit instead of
copying it: a `pyproject.toml` pinning `mpc-iml-toolkit` to the git tag of the
running version, an empty model (`src/<package>/model.py`) to replace, a script that
trains on a recording and runs on a replay, a test, a sample recording and a short
README. The package name comes from the directory name (`--name` overrides it).

```bash
uv run python -m mpc_iml.new ../my-practice
```

No tag exists yet: the current version is `0.0.0` and the pin `v0.0.0` is not
installable until the first release is tagged. Until then, in the new project, point
the dependency at a local checkout with `uv add --editable <path to mpc-iml-toolkit>`,
then `uv sync`.

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

## Licence

[MIT](LICENSE). Optional extensions such as RAVE and nn~ have their own licences
(CC BY-NC 4.0, non-commercial only) and are never bundled with or required by the
toolkit. The licences of the runtime dependencies are listed in
[docs/licenses.md](docs/licenses.md).
