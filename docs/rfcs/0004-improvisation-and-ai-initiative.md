# RFC 0004: Improvisation and AI initiative

- Status: Accepted
- Date: 2026-11-17
- Related: RFC 0001, RFC 0002, RFC 0003, ADR 0002, ADR 0004, #96
- Amended: 2026-11-17, experiment B is taught with pads instead of knobs (#116)
- Amended: 2026-11-19, experiment C is replaced by RFC 0005 (drum-led ensemble)

## Summary

So far the platform treats the model as an instrument: the musician demonstrates,
and the model turns pad pressure into sound exactly as taught. The model never acts
on its own. RFC 0002 names "collaborating with AI" as part of what musicians should
experience, but nothing in the platform yet lets the AI take part.

This RFC proposes that collaboration means **improvising with the AI**, and frames
it as a single idea: **the musician decides how much initiative the AI has**. At
one end the AI is an instrument (today's presets). Further along it moves on its own
when the musician lets go, learns while the musician plays, or answers with notes of
its own. The musician stays in charge throughout; what changes is how much they
hand over.

The RFC adds three experiments along this spectrum, built as presets so that the
core does not change, and a phase in which the decision maker plays each one and
decides whether to keep, change or drop it. Direction is found by playing, as in
RFC 0002.

## Background

Real-time improvisation with an AI partner is an established topic at NIME and in
related venues: systems where the machine proposes ideas and adapts to the
performer in the moment, small models that start empty and are trained and
forgotten during a performance, and low-latency generative MIDI models played from
key and pad controllers. Most of these are systems built for one piece or one
study. What this platform can add is:

- the AI's behaviour comes from the musician's own demonstrations, not from a large
  pretrained corpus alone;
- it runs on a commodity controller (the MPC Sample) and a Mac, from starting points
  that play at once (RFC 0003);
- the amount of initiative is something the musician sets, rather than a fixed
  property of the system.

Commercial instruments that present AI as a creative partner are also appearing,
and the ones that are well received keep the performer in control. An AI that only
transforms a sound is easily seen as one more effect; the experiments below aim at
an AI that responds to what the musician taught it.

## The initiative spectrum

| Initiative | The AI… | Built by |
| --- | --- | --- |
| None | follows the demonstrated mapping exactly | Existing presets (`pressure`) |
| Low | moves on its own when the musician lets go, and yields when they play | Experiment A |
| Medium | keeps learning from the musician while they play, and takes over a gesture | Experiment B |
| High | answers the musician with notes of its own, shaped by what they played | Experiment C |

The six scenarios of RFC 0001 sit at "none"; this RFC extends the platform to the
right without changing them.

## Proposal

### Common rules

- Each experiment is a **preset**, using the plugin entry point of RFC 0002. Where
  possible it reuses the `pressure` preset's features, named outputs and kits
  (RFC 0003), so a musician can start from a kit they know.
- Engine messages an experiment needs live in its own subtree
  `/mpciml/preset/<name>/…`, which ADR 0004 reserves for presets. The core protocol
  does not change in this RFC. If an experiment is kept, any message worth sharing
  is promoted to the core protocol through a new ADR.
- Output goes where it goes today: CC 20-27 on the virtual port `mpc-iml`, and for
  experiment C also notes on the same port, so the Ableton starter set (RFC 0003)
  keeps working.
- Any new dependency that is large (for example a deep-learning framework) is an
  optional extra, so `uv sync` stays light for everyone else.

### Experiment A: drift (low initiative)

- While a pad is pressed, the outputs follow the trained model as today.
- When all pads are released, the outputs do not return to the resting sound;
  instead they wander slowly through the space of the musician's examples (for
  example between the target values of recorded and generated examples).
- Pressing again hands control back smoothly, without a jump.
- Controls: how far and how fast the AI may wander; an off switch that restores
  today's behaviour.
- No new dependency.

### Experiment B: live learning (medium initiative)

- One hand teaches and the other plays. A group of **teacher pads** (for example
  pads 13-16) drive outputs directly with their pressure, like faders, and are not
  inputs to the model. The other pads are played as usual. The MPC Sample's knobs,
  encoder and fader cannot be the teacher: on firmware 1.3.0 they send nothing over
  USB MIDI (RFC 0001, ADR 0002).
- While a teacher pad is held, each moment becomes an example: the features of the
  played pads as inputs, and the outputs as the teacher pads set them as targets.
- The model retrains in the background every few seconds on a rolling window, so it
  keeps up with the musician and gradually forgets older behaviour.
- When the musician releases the teacher pads, the model takes over: the played
  pads now move the outputs the way the teacher hand was just moving them.
- Controls: which pads teach and which outputs each one drives; window length (how
  quickly it forgets); freeze (stop learning and keep the current model); save the
  window as an example set (ADR 0002 format).
- Everything runs on the MPC Sample alone and builds on the existing recording and
  training; no new dependency expected.

### Experiment C: response (high initiative)

> Replaced by [RFC 0005](0005-drum-led-ensemble.md) (drum-led ensemble); the text
> below is kept as it was accepted.

- The AI answers the musician's phrases with MIDI notes of its own, sent to the same
  virtual port, using a low-latency generative MIDI model.
- **Condition:** the response must be shaped by the musician, not only by the
  model's training corpus. For example, the pitches, density and velocities it may
  use are drawn from what the musician played or demonstrated, and pad pressure
  steers it while it plays. A pretrained model that ignores the musician is out of
  scope.
- It is an optional extra (`mpc-iml[improv]` or similar). The model's licence,
  download size and latency on the Mac are checked in the implementation plan
  before any code is written.
- It starts only after A and B have been played and decided, and only if the
  decision maker still wants it then.

### Later: one initiative control

If at least two experiments are kept, a later step combines them behind a single
control (a knob on the MPC Sample or a slider in the front end) that moves along the
spectrum. This is not part of the first version.

### Front ends

Each experiment adds a small group to the Pure Data reference patch for its own
controls, following the shared front-end spec (ADR 0006, ADR 0007) as an optional
group. Max for Live support is optional.

## Non-goals

- Generating audio or synthesiser patches; the AI moves parameters and, in C, sends
  notes.
- An AI that performs without the musician, or that the musician cannot stop.
- Cloud models or LLMs in the real-time loop.
- Changing the core protocol in this phase.
- User studies; experiments are judged by the decision maker playing them.
- Everything listed as a non-goal in RFC 0001, RFC 0002 and RFC 0003.

## Phases and gates

This RFC adds **Phase 2.7: Improvisation experiments**, after the Phase 2.6 gate and
before Phase 3. Experiments are built and played in order A, B, C.

Gate for each experiment:

- It runs from `uv run mpc-iml` with the Ableton starter set or the Pure Data patch.
- The decision maker plays it for at least 10 minutes and records a short note on
  how it felt in its Issue.
- The decision maker decides: keep, change or drop.

Gate for the phase: A and B have been played and decided, and a decision on C has
been made (build it, postpone it or drop it).

## Open questions

- Experiment A: what "wandering" means precisely (random walk, moving between
  examples, following the shape of the last gesture), and how the hand-back avoids
  jumps.
- Experiment B: how many teacher pads, and how they drive 8 outputs (one output
  each, or one pad moving several outputs along a direction the musician chooses);
  window length and retraining interval; whether moments without a teacher pad add
  examples.
- Experiment C: which model; how the musician's playing constrains it; how
  turn-taking works (call and response, or playing together).
- Whether experiments are separate presets or modes of `pressure`.
- Whether the interaction log of RFC 0003 should record initiative changes, decided
  before any study.
