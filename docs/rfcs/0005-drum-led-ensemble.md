# RFC 0005: Drum-led ensemble

- Status: Proposed
- Date: 2026-11-19
- Related: RFC 0001, RFC 0002, RFC 0003, RFC 0004, ADR 0002, ADR 0004, #113, #130
- Amended: 2026-11-21 (#174)

> **Amendment (2026-11-21, #174).** Steps 1–4 are built and have been played
> several times. In those trials the band felt like an effects processor rather
> than a partner when what it played was unrelated to what the musician played.
> The direction is unchanged; this amendment:
>
> - adds principles 7–12 (follow by variation, reflexive content, representation,
>   surprise within the grammar, a small control budget, visible intent);
> - marks steps 1–4 as done and replaces steps 5–6 with a new build order;
> - adds the section "Scope rules";
> - adds two questions on reflexive content and on a preview of the next bar;
> - updates the gate in "Phases and gates" and the step-5 open question to the new
>   steps.

## Summary

RFC 0004 proposed improvising with the AI, with the musician deciding how much
initiative it has. Trying existing AI improvisation systems with finger drumming on
the MPC Sample showed what is missing: the AI did not share the musician's sense of
beat or style, so its answers did not sound related to what was played.

This RFC proposes a specific direction for the high-initiative end of the spectrum:
a **drum-led ensemble**. The musician plays drums on the pads, and the AI plays
bass and melody that follow the drums, inside a style framework that the musician
and the AI share. The musician leads the ensemble by how they play. The RFC sets
the principles, the order in which to build it, and the core changes it needs.

It replaces experiment C of RFC 0004 ("response"). Experiments A and B are
unchanged.

## Problem and users

The users are the same as in RFC 0002 and RFC 0003: musicians who play a little and
want to improvise, starting from something that sounds good at once.

Three existing systems were played with the MPC Sample for this RFC:

| System | What it does | What was missing |
| --- | --- | --- |
| Notochord (Homunculus) | Event-level generative MIDI that plays along | No beat grid; responses did not relate to the playing |
| Continuator (Pachet's Python reimplementation) | Learns the player's phrases and continues them after a pause | Learns the order of pads, not their position in the bar; answers came after a fixed pause rather than on the beat |
| GrooveTransformer VST | Turns the player's rhythm into a full drum loop, updated at bar boundaries | Follows the player's timing but not the style: in a hip-hop pattern it did not keep the snare on beats 2 and 4, and ignores which pad was hit |

Each step added something (turn-taking, then a beat grid), and each was judged more
musical than the last, but none was felt to understand the music. The common
finding: **an AI partner needs the same framework as the musician** — beat, bar and
style — and its freedom has to sit inside that framework.

## Background

### Shared framework in improvisation

- In improvisation research, Pressing calls the shared framework the *referent*: a
  formal scheme or guiding image, usually common knowledge among the players, that
  they generate and edit material against. Idiomatic improvisation (jazz on a tune,
  a hip-hop groove) depends on it.
- In human-computer improvisation, systems derived from OMax and the Continuator
  mostly target free, unpulsed improvisation. ImproteK (IRCAM) adds a *scenario*
  (pulse and chord progression) written in advance, for idiomatic music.
- Musicians who play with such systems tend to ask for more musical competence, and
  a recent survey of 184 live music agents notes that many systems do not specify
  their musical context and assume a fixed tempo.

### Drums leading pitched parts

- Generating bass from drums exists as an offline task (for example a sequence
  model that turns a two-bar drum loop into a bass line in a given dance style;
  BassNet; DAW "session players" that follow another track's rhythm).
- Live systems where a drummer leads already exist, but in other forms: free
  improvisation with machine agents (LL), a drummer setting the tempo of
  pre-arranged parts (B-Keeper, BeatSeeker), and a robot marimba that answers a
  partner's rhythm and harmony (Shimon).
- Real-time accompaniment systems mostly go the other way (a human plays melody,
  the AI adds chords or drums), or accompany any input without centring on a
  drummer.
- A system that is **led by finger drumming, aware of style, responds live with
  bass and melody, and uses a framework defined by the musician** was not found.
  This is the gap this RFC addresses.

## Proposal

### Principles

1. **Shared framework (referent).** The AI plays inside a framework the musician
   can hear: a tempo and bar grid, a key and chord progression (or a melodic loop),
   and a style skeleton for the drums. The framework is fixed or chosen before
   playing; the musician changes what happens inside it.
2. **Skeleton and variation.** Each style has a skeleton (for example in boom bap:
   kick on beat 1, snare on beats 2 and 4, steady hats). The AI's freedom applies
   only outside the skeleton. How much it varies is a control the musician
   understands, from "keep the skeleton" to "vary more". This is the initiative
   spectrum of RFC 0004 applied to this setting.
3. **Bar-level timing.** The AI listens to a bar and answers in the next bar, at a
   bar boundary, aligned to the beat. It does not react note by note and does not
   wait for a pause measured in seconds. This is how a bass player follows a
   drummer, and it leaves a whole bar for computation.
4. **Pad identity matters.** The engine knows which pad plays which role (kick,
   snare, hat and so on). The AI's input is not a single rhythm line; which drum was
   hit is part of what it listens to.
5. **The musician defines the framework.** Starting points (RFC 0003) provide a
   framework that plays at once. With demonstrations (the IML loop of RFC 0001) the
   musician can define their own: "this is my groove", "with this kind of drums,
   play this kind of bass".
6. **Causality first.** The musician must hear that their drumming changed the
   band. Simple, legible relations come before rich generation.
7. **Follow by variation, not subtraction.** A sparse bar never reduces the band
   to a skeleton. The drums choose which full line plays and which ornaments it
   gets. When the drums stop, the band carries on and only fades after a while
   (built in #158).
8. **Reflexive content.** At least part of what the band plays comes from the
   musician: lines they wrote or chose, or material transformed from their own
   drumming (repetition with variation). Content fixed by the system is a default,
   not the goal.
9. **Representation is an aesthetic choice.** Content formats must be able to hold
   timing offsets (swing, microtiming) and non-chord tones, not only quantized
   chord tones. When a format makes some music easier to express than other
   music, the ADR that defines it says so.
10. **Surprise within the grammar.** Surprises keep to the style's grammar (for
    example a bass fill at the end of a phrase). Surprises that ignore the
    musician's material or the harmony are off by default.
11. **A small control budget.** At most two controls are meant to be changed while
    playing; everything else is a good default. A new performance control says
    which existing one it replaces.
12. **Intent can be seen.** Where a front end exists, it can show what the band
    will do in the next bar.

### What to build, in order

| Step | What | Why first | Status |
| --- | --- | --- | --- |
| 1 | Tempo sync with the DAW, bar position, capture tagged by bar and grid step, scheduling at bar boundaries | Everything else depends on it | Done (#130) |
| 2 | Pad roles: map pads to drum roles in kits | Input for the skeleton and for the generators | Done (#138) |
| 3 | Rule-based bass: bass notes fall on the kick positions of the last bar, pitches follow a fixed chord progression | No model needed; the clearest causality; a baseline for later steps | Done (#138, #148) |
| 4 | Melodic loop that follows the drums: choose among prepared loops, or change their filter or density, from features of the drumming (density, velocity, which pads) | Scenario 2 of the platform discussion; uses the existing CC output | Done (#144, #153, #158, #159) |
| 5 | Loops as editable data, with import from a DAW MIDI file (#173), meeting the representation principle (principle 9) | Reflexive content and every later step need content the musician can write and change | |
| 6 | Rhythm transformation: the band's rhythm is a transformation (not a copy) of the musician's last bar or bars, with pitches from the chords and the musician's own lines, following 4- or 8-bar phrases | The first step where the band plays material derived from the musician (principle 8) | |
| 7 | Listening layer: per-bar features beyond counts (change in density, accents, similarity to the previous phrase), and leading or following that moves with the musician's volume and density | Gives steps 6 and 8 richer input than hit counts | |
| 8 | Learning, smallest first: preset weights, then explicit likes while playing, then learning from playing; shared weights can be saved as a profile | Tests whether learning adds to the rules, starting from what is easiest to understand | |
| 9 | Two-way leading: the melody also influences the drums | Last; depends on what steps 5–8 show | |

Steps 5–9 are ordered by dependency, not by date.

Each step is played by the decision maker for at least 10 minutes, with a note on
how it felt, and kept, changed or dropped, as in RFC 0004.

### Core changes

RFC 0004 does not allow core protocol changes in Phase 2.7. This RFC allows the
following, each decided through its own Issue and, where the protocol changes, an
ADR:

- a clock in the engine (tempo, beat and bar position, transport state) — #130;
- note output from `midi_out` (today it sends only CC);
- pad roles in kit files (ADR 0007 format);
- any new OSC messages these need, as a new protocol version.

Large dependencies (for example a deep-learning framework for step 8) stay optional
extras, as in RFC 0004.

### Scope rules

- No new front ends, protocol versions or interfaces unless one of the steps above
  needs them. The decision maker lifts this rule.
- The repository contains only content the project owns or that has a clear
  licence. Samples and clips a musician imports stay on their machine and are
  never committed or uploaded.
- A change that alters the sound is accepted after it has been played under a
  fixed trial procedure and recorded, not after a single impression.

### Questions this direction explores

These are recorded to guide the steps; they are answered by playing and, later, by
study outside the toolkit (RFC 0001).

- Which features of finger drumming (kick positions, density, velocity, pad choice)
  make the musician feel they are leading the ensemble, while the result stays in
  style?
- Does a framework the musician defined (by demonstration) make the AI feel more
  "like listening to me" than a preset one?
- How should the AI's freedom be limited to the space outside the skeleton?
- Does reflexive content (the musician's own lines, or their drumming
  transformed) make the band feel more "like listening to me" than content the
  system wrote?
- Does a visible preview of the next bar change that feeling?

## Non-goals

- Audio generation as the main output; the AI sends notes and CC. An audio
  generative model may be used later as a sound source, not as the core.
- Note-by-note reaction faster than a bar.
- A framework the AI invents on its own (free, unpulsed improvisation).
- User studies inside the toolkit.
- Everything listed as a non-goal in RFC 0001 to RFC 0004.

## Phases and gates

This RFC stays within **Phase 2.7** (Epic #113) and replaces experiment C there.

- Steps 1–4 make up the first version. Gate: from `uv run mpc-iml`, with the
  Ableton starter set or the Pure Data patch, the decision maker plays drums on the
  pads and hears bass and a melodic loop follow at bar boundaries, for at least 10
  minutes, and records the result.
- Steps 5–9 follow the order above (amendment of 2026-11-21, after the first
  version was played). Each is played and recorded under a fixed trial procedure
  before it is kept (see "Scope rules").

## Open questions

- Which clock source (MIDI clock, Ableton Link, or both), and its licence (#130).
- How the framework is set: a few built-in styles, the musician's demonstrations,
  or both; and how a style skeleton is represented in kit and module files.
- Which features of the drumming drive the bass and the melodic loop in steps 3–4.
- Whether the chord progression or melodic loop is part of a kit, a module, or a
  new content type.
- How pad roles relate to the existing pad selection and modules (ADR 0007).
- For step 8: the learning method, its licence and size, and how the musician's
  likes and playing shape it.
