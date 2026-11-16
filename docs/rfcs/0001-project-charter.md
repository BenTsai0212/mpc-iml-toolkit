# RFC 0001: Project charter

- Status: Accepted
- Date: 2026-11-15
- Related: ADR 0001 (technology choices and adoption method, to be written)
- Amended: 2026-11-15, third Phase 1 gate added (#5)
- Amended: 2026-11-16, gesture input narrowed to the pads after the hardware check (#15)

## Summary

mpc-iml-toolkit is a base toolkit for interactive machine learning (IML) with an
Akai MPC Sample and a Mac. The MPC is used over USB as a gesture controller and
audio interface; models run on the Mac. The toolkit does no research of its own:
each IML practice (a research question, a piece, a teaching unit) lives in its own
repository and builds on this toolkit.

## Problem and users

IML work follows a loop: record examples, train, run in real time, then edit the
examples and train again. Each new experiment tends to rebuild the same plumbing:
reading the controller, recording and replaying data, wiring a model to an output.
That slows down experiments and makes results hard to reproduce.

Users:

- The author, for future research practice repositories (aiming at NIME submissions).
- After the repository goes public: NIME and IML researchers, musicians and teachers
  who own an MPC Sample and a Mac.

Cost of being wrong: this is a research tool, and errors do not harm others. But once
public, frequently changing interfaces, or documentation and examples that do not
reproduce, would force practice repositories and community users to keep adapting,
and would weaken the reproducibility of published papers.

## Proposal

The toolkit provides shared capabilities (exact scope to be refined in ADRs):

- **Hardware connection**: the MPC Sample as a USB gesture input (velocity and
  polyphonic aftertouch on the 16 pads) and as an audio interface. With the official
  firmware (v1.3.0) the knobs, encoder and fader send nothing over USB MIDI (#10).
- **IML loop**: record examples → train → run in real time → edit examples and retrain.
- **Data**: one consistent format to record, store and replay example data.
- **Extension points**: practice repositories can swap inputs, models and outputs
  (synthesisers, samplers, external tools) without modifying the toolkit.
- **A minimal reference example** that proves the whole loop works end to end.

How practice repositories adopt the toolkit (for example an installable package, a
GitHub template repository, or both), and how they keep up with toolkit updates, is
decided in ADR 0001.

### Validation scenarios

The toolkit does not implement these; they are used to check that its extension
points can support them:

1. Pad pressure mapped to many synthesis parameters (one-to-many mapping).
2. Personalised time-series gesture recognition.
3. A small-data sound classifier (beatboxing to trigger the MPC).
4. Navigating the latent space of a neural audio model (such as RAVE) with IML.
5. Multimodal input (hand tracking from the Mac camera plus the pads).
6. A comparison study: designing by demonstration vs. asking an LLM in natural
   language to write the mapping code.

## Non-goals

- Specific research experiments and user studies (these belong in practice repositories).
- SD card modifications and unofficial firmware.
- Running models on the MPC itself.
- Supporting other controllers.

Research data (recordings, performance data, interviews) is never committed to this
repository.

## Phases and gates

Each phase is one Epic; the board's Phase field marks which phase an Issue belongs to.

### Phase 1: Foundation

Hardware connection, IML loop, data format, extension points and the minimal
reference example; adoption method decided (ADR 0001).

Gates:

- Following the README, a person with an MPC Sample and a Mac gets the reference
  example running within one hour (verified by the author on a clean environment).
- A new practice repository implements a new scenario (1 or 3) without modifying
  toolkit code.
- A practice repository swaps in a different IML backend (for example a model
  served by Wekinator over OSC instead of the built-in one) without modifying
  toolkit code.

### Phase 2: Public release

Licence, complete documentation, the pre-publish checklist, then switching the
repository to public.

Gates:

- The pre-publish checklist passes in full.
- After going public, a fresh clone runs the reference example by following the README.

### Phase 3: Research-ready

Check the extension points against the remaining scenarios (2, 4, 5, 6) and
stabilise the interface (for example a 1.0 release with a written versioning policy).

Gates:

- Each scenario has at least one practice repository showing it works, or a written
  explanation of why it is not supported.
- The author's NIME research repository depends on a released version that a paper
  can cite.

## Open questions

- Whether the knobs, encoder and fader can become inputs once an official SDK is
  available (details expected in January 2027).
- Technology choices (ADR 0001). Candidates: Wekinator (OSC), FluCoMa (Max / Pure
  Data), Python (python-rtmidi, scikit-learn), RapidLib, RAVE with nn~.
- Adoption method and update path for practice repositories (ADR 0001).
- Licence, chosen together with the licences of dependencies (ADR 0001).
- Example data format and versioning policy.
