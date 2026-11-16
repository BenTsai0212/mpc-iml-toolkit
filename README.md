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

Phase 1 (Foundation), early. So far the toolkit has:

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
  regressor (`mpc_iml.sklearn_backend`).

Formats are in [ADR 0002](docs/adr/0002-recording-and-osc-formats.md). The run loop
is not implemented yet, and the package is not published. Interfaces
will change without notice until the first release (`v0.1.0`).

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

CI (`.github/workflows/ci.yml`, job `checks`) runs the workflow tool tests
(`npm test --prefix tools/workflow`) followed by the commands above.

## Project workflow

Work is planned in GitHub Issues and implemented by coding agents in pull requests
that a human reviews and merges. The rules for agents are in [AGENTS.md](AGENTS.md).
The workflow documents under [`docs/workflow/`](docs/workflow/), and `AGENTS.md`
itself, are written in Traditional Chinese; Issues, pull requests and commits are in
English.

## Licence

[MIT](LICENSE). Optional extensions such as RAVE and nn~ have their own licences
(CC BY-NC 4.0, non-commercial only) and are never bundled with or required by the
toolkit.
