# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Until 1.0, interfaces may still change between 0.x releases.

## [0.1.0] - 2026-11-16

First release: the shared plumbing of the interactive machine learning loop with an
Akai MPC Sample and a Mac.

### Added

- Input: live MIDI input from the MPC over `python-rtmidi` and replay of
  recordings, interchangeable downstream (`mpc_iml.sources`), with MIDI decoding
  (`mpc_iml.midi`) and a typed event model for MIDI messages and example markers
  (`mpc_iml.events`).
- Recording: recordings as JSON Lines (`mpc_iml.recording`, format in ADR 0002)
  and a recorder for live input (`python -m mpc_iml.record`).
- Frames: pad mapping and frames computed from events, 49 OSC input values per
  frame, with a real-time frame clock for live input (`mpc_iml.frames`).
- OSC: a sender that follows Wekinator's defaults, `/wek/inputs` on port 6448 and
  `/wek/outputs` on port 12000 (`mpc_iml.osc`).
- IML loop: training examples from the marked segments of recordings
  (`mpc_iml.examples`), a model extension point (`mpc_iml.model.Model`), built-in
  scikit-learn models (`mpc_iml.sklearn_backend`), and the loop that trains, runs
  and retrains without restarting, or sends only `/wek/inputs` so Wekinator can
  act as the model (`mpc_iml.loop.IMLLoop`).
- Practice-repository template: `python -m mpc_iml.new <directory>` creates a
  project that pins this toolkit to the git tag of the running version.
- Reference example: `python -m mpc_iml.demo`, with an optional Pure Data receiver
  (`examples/reference/receiver.pd`).
- `CITATION.cff` for citing the toolkit.

### Known gaps

- The one-hour README test (#27) has not been done yet.
- The Pure Data patch of the reference example has not been verified (#24).
- Light holds retrigger on the MPC (#43).

[0.1.0]: https://github.com/BenTsai0212/mpc-iml-toolkit/releases/tag/v0.1.0
