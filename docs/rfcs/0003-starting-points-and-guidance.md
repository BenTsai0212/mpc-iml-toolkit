# RFC 0003: Starting points and guidance

- Status: Accepted
- Date: 2026-11-17
- Related: RFC 0002, ADR 0004, ADR 0005, ADR 0006, #61, #66, #76, #78, #86

## Summary

The Phase 2.5 gate passed: following the README, a musician went from `uv sync` to
playing the `pressure` preset with all 8 CCs mapped in about 7 minutes (#66). The
same test showed what is still hard. Before anything sounds, the musician has to
decide what to demonstrate, pad by pad, and then decide what the outputs should
control in the DAW. These are the barriers that interactive machine learning tools
for music have long met: demonstration assumes that the person already knows what
they want.

This RFC changes the default experience from "demonstrate from nothing" to "start
from something that plays, then make it your own". It adds four ideas that build on
one another:

1. **Named outputs**: each preset names its outputs (for `pressure`: brightness,
   resonance, drive, space, motion, pitch, texture, level).
2. **Modules**: a module is a behaviour such as "brighter as you press". It
   generates examples for one pad, so it is a demonstration the musician does not
   have to record.
3. **Starter kits**: a kit is a resting sound plus a module on each of the 16
   pads. Loading a kit generates its examples and trains, so it plays at once.
4. **DAW starting points**: an Ableton Live set whose Instrument Rack macros carry
   the output names, and a Max for Live option that drives those macros directly.

Demonstration stays at the centre: it becomes the way to change and personalise a
starting point, and recording from nothing remains available.

## Problem and users

The users are those of RFC 0002, with the primary group being electronic musicians
who work in Max, Pure Data or a DAW. Within that group, this RFC is for those with
less experience in sound design or mapping, and for anyone who wants an idea
quickly rather than a blank page.

Observed on hardware (#66, #76, #78):

- Recording four examples on one pad is fine; deciding what to record for 16 pads,
  and setting 8 target sliders for each, is not.
- Mapping 8 CCs is quick with the learn buttons (#78), but choosing which
  parameters and effects to map takes exploration that the tool does not support.

## Proposal

### Default experience

1. Choose a starter kit. The engine generates the kit's examples and trains; the
   musician presses `run` and plays.
2. To change a pad: hit it on the MPC Sample to select it in the front end, then
   either choose another module (the engine regenerates that pad's examples and
   retrains) or record demonstrations on it, which are trained together with the
   module's examples.
3. Save the result as one's own example set.

Recording from nothing, as today, stays available as an advanced route.

### Named outputs

- A preset may declare a name for each output. Front ends show the names instead of
  `t1`-`t8` and `o1`-`o8`; the CC numbers do not change.
- `pressure` declares, in CC order 20-27: brightness, resonance, drive, space,
  motion, pitch, texture, level.
- Modules, kits, the DAW set and the README mapping guide all use these names.

### Modules

- A module describes, for one pad, how the named outputs change as pressure goes
  from the lightest touch to full pressure (for example "brightness rises").
- A module **generates examples**: synthetic takes of that pad at several pressure
  levels, with the targets the behaviour defines, written in the ADR 0002 recording
  format. They are trained together with any recorded demonstrations, saved and
  loaded like any other examples, and so reproducible.
- A module may also generate examples for pads pressed together, to guide how the
  model combines behaviours. The details are left to the implementation plan.
- A pad can have no module ("none"): it plays its note and changes nothing.
- First library (9 modules, names to be finalised in English in the ADR):

| Module | As pressure rises |
| --- | --- |
| Brighten | brightness up |
| Darken | brightness down |
| Bite | brightness and resonance up |
| Push | drive and level up |
| Distance | space up, brightness slightly down |
| Wobble | motion up |
| Bend | pitch up |
| Grain | texture up, drive slightly up |
| Swell | level and space up |

### Starter kits

- A kit is a resting value for each named output plus one module per pad.
- First kits: **Filter play** (brightness and resonance; the first kit a new user
  sees), **Texture lab** (drive, texture, motion), **Ambient space** (space, swell,
  distance).
- Loading a kit generates its examples and trains, so it plays at once.

### Data and extension

- Modules and kits are data files (JSON) shipped with a preset. External packages
  can add modules and kits for a preset, in the same plugin spirit as RFC 0002.
- The engine protocol gains messages to list and load kits, list modules, assign a
  module to a pad, and report which pad was hit while selecting. This is protocol
  1.3, recorded in a new ADR (0007), a minor change under ADR 0004's rules. Front
  ends (ADR 0006) gain a kit chooser and a pad editor; the shared front-end spec is
  updated in the same ADR.

### DAW starting points

- **Ableton Live starter set**: one MIDI track fed by the MPC Sample, an Instrument
  Rack with a synthesiser and effects, eight macros named after the outputs and
  each mapped to suitable parameters, and the macros mapped to CC 20-27. It uses
  only devices built into Live where possible. The author builds it in Live from a
  checklist (which parameter and range each macro controls); it is not generated.
- **Max for Live direct control**: the device (#86) gains an option to drive Macro
  1-8 of the next Instrument Rack on its track from the outputs, with no MIDI
  mapping. Because a controlled macro cannot be moved by hand, the option has an
  on/off switch. This revisits #86's decision to leave `live.remote~` out of the
  first version: with fixed macro targets, no parameter picker is needed. The CC
  route stays for other DAWs.
- The README gets a table of suggested mappings for the eight named outputs, for
  DAWs other than Live.

### Research

- These starting points make the comparison of scenario 6 richer: demonstrating
  from nothing, starting from a kit and editing, composing with modules, and (in
  Phase 3) describing in text for an LLM to generate examples.
- The engine may keep an **interaction log** (kit loaded, module assigned,
  demonstration recorded, and so on) for studies. It is off by default and must be
  turned on explicitly, it is written only to the user's own data folder, it never
  enters the repository, and its use in research is reviewed first, as for all
  research data.

## Non-goals

- Generating sounds or synthesiser patches; the tool shapes how existing
  parameters respond to the pads.
- Kits or modules for presets other than `pressure` in the first version.
- Templates for DAWs other than Ableton Live (a mapping table instead).
- A cloud service or sharing platform for kits.
- Everything listed as a non-goal in RFC 0001 and RFC 0002.

## Phases and gates

This RFC adds **Phase 2.6: Starting points**, between Phase 2.5 and Phase 3.

Gates:

- A musician without experience of the tool plays from a starter kit within 5
  minutes of `uv run mpc-iml`, and replaces the module on one pad.
- With the Ableton starter set and the Max for Live device, a musician plays with no
  MIDI mapping at all.
- Protocol 1.3 and the updated front-end spec are recorded in ADR 0007.

## Open questions

- How a module's pressure curve is described (fixed shapes, or points with
  interpolation), and whether a module has an amount control.
- How many generated examples a module writes, and how they are weighted against
  recorded demonstrations.
- How combined presses are generated, and whether kits can declare them.
- The exact resting values and module assignments of the three kits.
- Whether named outputs and modules should later extend to classification presets.
- The format and content of the interaction log, decided before any study.
