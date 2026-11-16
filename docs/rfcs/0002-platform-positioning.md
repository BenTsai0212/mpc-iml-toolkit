# RFC 0002: Platform positioning

- Status: Accepted
- Date: 2026-11-16
- Related: RFC 0001, ADR 0001, ADR 0002, ADR 0003, #43

## Summary

RFC 0001 defined mpc-iml-toolkit as a base toolkit that does no IML practice of its
own; every practice lives in a separate repository. This RFC widens that position.
The repository becomes a **platform**: the existing toolkit is its core, and on top
of it the platform adds an engine that musicians control from their own patching
environment, a set of built-in **presets** (playable IML instruments that are also
reference implementations), and an optional LLM mapping feature that uses the
user's own model.

One-line position: for electronic musicians who work in Max, Pure Data or a DAW,
plug in an MPC Sample, choose a preset, train your own mapping by demonstration,
and play it. Researchers can change, extend or fork the same code.

## Problem and users

A toolkit that only connects the MPC Sample to a model is easy to replace: any
general MIDI-to-ML bridge covers most of it. What is harder to replace is a set of
worked IML instruments, each usable on stage and each readable as a reference for
research. The platform also needs an interface that people who do not write Python
can use, because the comparison study in scenario 6 depends on such participants.

Users, in priority order:

1. **Primary: electronic musicians who already use Max, Pure Data or a DAW.** They
   accept one setup step in a terminal (`uv sync`), then work entirely in their
   patching or DAW environment.
2. **Secondary: researchers.** They use the Python API, the extension points and
   the recording and replay tools that already exist, and they can build new
   presets or fork the platform.
3. **Later: musicians who do not use any programming or patching environment.** A
   standalone app is the next stage. This RFC only keeps the path open (see the
   engine below); it does not build the app.

## Proposal

### Layers

| Layer | Contents | Who changes it |
| --- | --- | --- |
| Core | Input, data format, model interface, IML loop (v0.1.0) | Platform maintainers; kept stable |
| Engine | OSC control protocol, state reporting, loading and switching presets | Platform maintainers |
| Presets | Features, model settings, output mapping and a front-end patch per scenario | Built-in; others can contribute |
| Front ends | Reference Pure Data patch, then a Max for Live device, later an app | Reference versions here; anyone can build others |
| Practice repositories | Research experiments, user studies, personal pieces | Their own repositories |

### Engine and control protocol

Today the IML loop is driven from the terminal (`demo record`, `demo run`). The
engine turns it into a long-running process that receives control messages over
OSC (start and stop recording, set the class or target, train, run, switch preset)
and reports its state back. Front ends only send and receive these messages.

The control protocol is a versioned, documented interface, recorded in an ADR in
the same way ADR 0002 records the recording and OSC data formats. Because every
front end speaks the same protocol, a future app is one more front end and the
engine does not need to be rewritten.

### Presets

The platform ships presets for scenarios 1, 4 and 6 of RFC 0001, built in this
order:

1. **Scenario 1, one-to-many pressure mapping.** The first preset and the entry
   point. Besides OSC, it also sends MIDI CC on a virtual MIDI port so that it can
   drive a DAW synthesiser before the Max for Live front end exists.
2. **Scenario 4, RAVE latent space.** The engine sends latent coordinates; sound is
   produced by `nn~` in Max or Pure Data.
3. **Scenario 6, demonstration vs. LLM.** The preset and its front end are the
   instrument; the study itself (participants, questionnaires, analysis) belongs in
   a practice repository.

Presets live in this repository but are loaded through a plugin interface, and the
built-in presets register through the same interface. An external package can
therefore add a preset without modifying the platform, and a built-in preset can
later move out without changing the architecture.

A preset is accepted into this repository when it:

1. Is useful beyond one paper or one piece.
2. Uses only the platform's public interfaces.
3. Ships recorded fixtures and replay tests, so CI runs without an MPC.
4. Contains no research data (participant data, personal recordings).
5. Is documented in both README languages, including how to use its front end.

### Front ends

The reference front end is a Pure Data patch, because Pure Data is free and anyone
can reproduce a result with it. A Max for Live device follows, built against the
same control protocol.

### Two ways to build on the platform

| Route | For | How | Keeping up with updates |
| --- | --- | --- | --- |
| Extend (recommended) | A new preset, a research practice | Install the platform as a package in your own repository and register presets through the plugin interface | Upgrade the package version |
| Fork | Changing the platform itself | Fork this repository | Merge upstream changes yourself |

Both routes can contribute back: mature presets by pull request, platform
improvements by picking changes out of a fork.

### LLM mapping

The platform provides LLM-assisted mapping as an optional feature, using the
user's own model.

- **Providers.** One provider interface with a few built-in adapters (for example
  Anthropic and OpenAI-compatible endpoints). Cloud API keys are the default; local
  models are supported through Ollama, which the user installs. The platform does
  not bundle or download model weights; it provides a command that checks the setup
  and pulls a recommended model, and documents the hardware it needs. LLM
  dependencies are an optional extra.
- **Design time only.** The LLM produces a mapping before playing, or between
  phrases and sections; it is never called inside the real-time loop. Millisecond
  response comes from the IML models and RAVE.
- **Declarative output.** The LLM produces a declarative mapping (features to
  output parameters, with ranges and curves), validated against a schema before the
  engine runs it. A mapping trained by demonstration can be exported to the same
  object, so scenario 6 compares like with like, and a person can demonstrate first
  and then ask the LLM to revise. Generating executable code is out of scope for
  now (see open questions).
- **Keys.** API keys live in environment variables or a local, git-ignored
  configuration file. They are never committed, never written to recordings and
  never sent over OSC.
- **Data sent to providers.** By default only the text description and the schema
  of features and parameters are sent. Sending recorded gesture data requires an
  explicit opt-in by the user.
- **Reproducibility.** Each generation records the provider, model name and
  version, prompt, response and resulting mapping. Results are reproduced from the
  stored mapping, not by calling the model again.

This amends scenario 6 of RFC 0001. Instead of asking an LLM in natural language
to write the mapping code, the comparison is between designing by demonstration
and asking an LLM in natural language to produce a declarative mapping. Whether
the LLM may also generate code remains an open question.

### Hardware scope

Releases support the MPC Sample only, which is the only controller the maintainers
can test. Other controllers (for example MPE controllers) may be added in later
versions based on demand; this RFC does not change the RFC 0001 non-goal.

## Non-goals

- A standalone app for musicians who do not use a patching or DAW environment
  (next stage).
- Controllers other than the MPC Sample.
- Bundling or hosting LLM models, or providing API keys.
- Calling an LLM inside the real-time loop.
- Research experiments and user studies (still in practice repositories).
- Everything listed as a non-goal in RFC 0001.

## Phases and gates

This RFC adds a phase between Phase 2 (Public release) and Phase 3
(Research-ready) of RFC 0001.

### Phase 2.5: Platform

Engine and control protocol, the scenario 1 preset with the Pure Data front end,
the plugin interface for presets, then the Max for Live front end.

Gates:

- After `uv sync`, a musician opens the reference front end and is playing the
  scenario 1 preset within 20 minutes, without typing any other command.
- A preset in an external package registers through the plugin interface and runs
  without modifying the platform.
- The control protocol is documented in an ADR with a version number.

Phase 3 then covers the scenario 4 and scenario 6 presets, the LLM mapping
feature (before scenario 6) and the interface stabilisation already planned in
RFC 0001.

The Phase 1 gate "a new practice repository implements a new scenario (1 or 3)
without modifying toolkit code" is replaced by the plugin gate above. Scenario 1
becomes a built-in preset, and any scenario, including 3, can meet the plugin
gate as a preset in an external package.

## Open questions

- Whether to rename the repository and package, or split the core into its own
  package, now that it is a platform. To be decided after the control protocol ADR.
- Whether LLM mapping should ever produce executable code, and if so with what
  sandbox and review step.
- The exact schema of the declarative mapping object, and how demonstration-trained
  models (for example an MLP) are exported to it or represented beside it.
- How the default features (#43) change for the scenario 1 preset.
- Which local model to recommend, and the minimum Mac hardware for it.
