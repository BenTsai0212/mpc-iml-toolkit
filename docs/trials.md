# Blind comparison trials

A trial compares conditions of `ensemble` (named sets of its controls) without
telling the musician which one is playing (#197). It plays the conditions in a
counterbalanced order under code letters, records each one, asks the questions of
the trial file after each, then asks for a ranking and only then reveals the
letters. A report puts the scores next to a few measures from the recordings.

## Trial files

A trial file (format `mpc-iml-trial`) lists `bars` (length of each condition,
default 16), `base` (settings sent before every condition), the `conditions` and
the `questions`. Every control a condition sets must also be in `base`, so nothing
carries over from the condition before. The questions live in the file, so they
change without code. See [`examples/trial/rhythm.json`](../examples/trial/rhythm.json),
which compares `rhythm 0` with `rhythm 1` and asks five 1-5 questions and two open
questions.
Trials keep the modes fixed: the example files send `mode-pads 0` in `base`, so
pads 15 and 16 never switch the bass or melody mode during a condition (#216).
They also send `status 0`: the status line names the variations' sources and what
pads 16 and 15 do, which would tell the musician the learning mode (#230).

The optional `guide` (#241) is what the musician reads, in musical terms: how to
play, not what each control does. `guide.start` is shown once, after the setup
text and before the first condition; `guide.condition` before every condition's
"press Play" line. Each is one string or a list of strings (one line each); other
fields in `guide`, or values that are not text, are errors that name them. Keep
`guide.condition` the same for every condition, so it does not tell which one is
playing. The session file keeps the whole trial file, guide included. Trial files
without `guide` work as before; the field is optional, so the format stays
`format_version` 1. The example files have a guide.

The optional `min_bars` (#243) is the shortest each condition should be: a whole
number from 1 to `bars`. Pressing Enter before that many bars asks
`Only N bars so far (at least M). End this band anyway? [y/N]`; `y` ends the
condition, any other answer keeps it playing (the recording goes on while the
question waits). Enter after `min_bars` ends it at once, as before. The session
file's `condition` record has `ended_early: true` for a condition ended before
`min_bars`; sessions written before this field read as `false`. Without
`min_bars`, Enter ends a condition at once. Other values, or more than `bars`, are
errors that name it. `nod.json` sets 100 (of 240 bars), `groove.json` 64 (of 160),
`rhythm.json` 32 (of 32).

**Why**: in the learning trial of 2026-11-23 the musician skipped the second
condition (0 bars) and played the third for 25: he did not know in advance how many
conditions there were, so he was unsure whether to play each one fully, and only
one condition gave usable data. So the tool tells the structure (below), the
learning trial's guide starts with "give each one a full go", and `min_bars` keeps a
condition from ending too early by accident.

## Before a trial

Trials are played with the Ableton starter set (`assets/ableton/`), without Pure Data.

1. Close Pure Data: its group 8 shows the `ensemble` settings, and its connect
   button would take the engine's replies back from the trial.
2. In Live, fold the band's tracks so their notes are not visible.
3. In Live (Settings > Link, Tempo & MIDI), turn on Sync for both `mpc-iml clock`
   (read by the engine) and `mpc-iml trial clock` (read by the recorder). These
   ports appear once the trial has started. With an IAC bus instead, pass
   `--clock-port IAC` and send Sync to it.
4. Keep the transport stopped between conditions: settings are sent while it is
   stopped, so they apply at once.

## Running a trial

The trial starts the engine itself (do not start another one), with its log in
the session folder:

```bash
uv run python -m mpc_iml.trial run examples/trial/rhythm.json ~/mpc-iml-data
```

After the guide's start lines, the terminal shows the trial's structure, for example
`3 bands, at least 100 bars (about 4 min at 90 BPM) each.` (#243): the number of
conditions played (with `--repeats`, every repeat counts) and `min_bars`, in minutes
too when the recorder's clock already gives the tempo; without `min_bars`,
`up to <bars> bars each.` Before each condition it shows its position, for example
`Band 2 of 3`, then `guide.condition`. The tool adds these lines, so trial files do
not repeat them.

For each condition the terminal shows only its letter. Press Play in Live and play
for `bars` bars; then press Stop in Live and Enter (Enter also ends a condition
early; before `min_bars` it asks first). Then answer the questions: 1-5 answers are asked again until they are
valid, and text answers can be left empty. After the last condition, type the letters best first (for example
`BA`); then the conditions are revealed.

Options: `--seed N` (the order; by default the time), `--repeats N` (play the
order N times, every other time reversed), `--port` (MPC input name),
`--clock-port`, `--beats-per-bar`.

Each trial gets a folder `<data folder>/trials/<YYYYMMDD-HHMMSS>/` with
`session.jsonl` (written after each step, so a crash keeps what was answered),
one recording per condition (`A.jsonl`, `B.jsonl`; `A-2.jsonl` for a repeat) and
`engine.log`. Nothing is uploaded or committed; keep the data folder outside the
repository.

While a condition plays (from its "press Play" line until Enter), the terminal also
shows the engine's lines meant for the musician (#230): presses of pad 16 or 15
that did nothing because Live was stopped (`ensemble: pad 16 ignored, the clock is
not running`; the line names the pad, not the learning mode), and, only with
`status 1`, the status lines of
[the ensemble guide](ensemble.md#see-what-the-band-plays-and-what-the-pads-do).
The example files send `status 0`, so a blind trial shows only the ignored presses.
`engine.log` keeps every line, as before.

## Comparing learning modes

The learning trial is [`examples/trial/nod.json`](../examples/trial/nod.json)
([below](#learning-off-or-learning-from-nods)). The first learning trial (#196,
`examples/trial/learn.json`) compared `learn off`, `learn likes` and `learn demo`;
those modes were replaced by the nod (#250) and the file was removed. What it taught
still holds for any trial of learning modes:

**Keep a profile out of the comparison.** The engine reads the profile
`<data folder>/learn/ensemble.json` when it starts, and while `learn` is not `off`
it writes it at each phrase start. So that no condition starts from what an earlier
one (or your own practice) learned:

- `base` sends `learn off`, then `reset-learning`: every condition starts from the
  rules, whatever the profile held. The condition then sends its `learn` mode.
- Run trials with a data folder of their own (`~/mpc-iml-trials`, not your usual
  `~/mpc-iml-data`): a learning condition saves what it learned over that folder's
  profile, which would otherwise replace your "my band". Copy your `loops/` folder
  into it if you play your own loops.
- `base` sends `learn-log 0` and each condition `learn-log 1`, so each condition
  gets its own `<data folder>/learn/log-<time>.jsonl`, in play order. A log file
  is created at its first bar, so the settings check before the first condition
  leaves none (#217). Summarise each with `python -m mpc_iml.learn summary <log>`.

**Only the bass learns.** `base` sends `melody-mode still` (#233): the melody plays
its `home` line every bar at one brightness, whatever the drums do, while the bass
follows the kicks with its rules and learns as in `follow`. So the conditions differ
only in the bass, and the musician judges the learning by the bass alone. With
`follow` the melody also changed with the drums, which mixed two parts into one
score; `fixed` stops the bass from following too, so the bass played `home` every
bar and the condition could not be judged (#215's manual check).

**Guide the musician in terms of playing.** The trial shows the musician its guide
(`guide`, #241) instead of a description of the controls: lead the band as in a jam,
stay with a groove for a few phrases, tap pad 16 once "like a nod to the bass
player" when the bass plays something worth hearing again, change the groove to
change the bass, and later come back to a groove where you nodded. In the #215
checks the musician pressed rarely when unsure what a press does; guidance in terms
of playing lets them keep playing and press without having to understand the
engine. The guide is the same before every condition, so it does not reveal which
one is playing. Pad 15 does nothing here (`melody-mode still`, `mode-pads 0`), and
the guide names pad 16 only. The report's response measures are left empty beyond
64 bars.

## Following each bar or the groove

[`examples/trial/groove.json`](../examples/trial/groove.json) is the first trial of
#250: does the bass follow when the drummer changes groove? Both conditions play the
rules only (`learn off`, `new-groove rules`, `answer-after 2`); `follow-bar` sends
`follow-by bar` (as now) and `follow-groove` sends `follow-by groove`. 160 bars each,
at least 64:

```bash
uv run python -m mpc_iml.trial run examples/trial/groove.json ~/mpc-iml-trials
```

The guide asks the musician to hold a groove for a few phrases, change to a
different one, and play fills between grooves; there are no pads to press. Besides
the usual questions, `followed-change` asks "When I changed groove, the bass changed
with me". The matching count comes from the learn logs (`base` sends `learn-log 0`
and each condition `learn-log 1`, as above): `python -m mpc_iml.learn
summary <log>` lists each groove change and whether the bass variation changed with
it. Run this trial before the next one: its result decides whether the nod trial's
`follow-by groove` stays, or whether a later trial compares nods with `follow-by
bar`.

## Learning off or learning from nods

[`examples/trial/nod.json`](../examples/trial/nod.json) is the second trial of #250:
`learn-off` against `learn-nod`, 240 bars each, at least 100:

```bash
uv run python -m mpc_iml.trial run examples/trial/nod.json ~/mpc-iml-trials
```

- `base` sends `follow-by groove`, `answer-after 2`, `learn-group 0` and `new-groove
  rules`, so the two conditions differ only in `learn`. `learn-group 1` and
  `new-groove invite` are left for later trials, each against its default, so that
  every trial compares one thing.
- As [above](#comparing-learning-modes), `base` sends `learn off`, then `reset-learning`, so each
  condition starts with no nods, whatever the profile held, and `learn-log 0` with
  `learn-log 1` in each condition. Run it with a data folder of its own: `learn
  nod` saves its nods over that folder's profile.
- `melody-mode still`: only the bass learns from a nod.
- The guide keeps the nod wording of the first learning trial: tap pad 16 once on the last note
  of a phrase, like a nod to the bass player, and later come back to a groove where
  you nodded. Pad 16 nods with `learn nod` and does nothing with `learn off`
  (`mode-pads 0`), so this comparison, too, is not blind to the pad.
- `python -m mpc_iml.learn summary <log>` adds the `nods:` line: the nods, the
  grooves nodded and the bass bars played from a nod.

`measures --trial` replays a recording with the condition's `follow-by` and, with
`learn nod`, plays its pad 16 as the nod, as the engine did (`webdemo.sim.replay`).

## Reports

```bash
uv run python -m mpc_iml.trial report ~/mpc-iml-data/trials/20261122-140000 ~/mpc-iml-data/trials/20261123-140000
```

Pass session folders or their `session.jsonl` files, as many as you like. The
columns are tab-separated, so they paste into a sheet.

- **Per session**: one row per condition played, under its revealed name: the raw
  1-5 scores, the rank, and the measures of its recording, then the text answers.
- **Across sessions**: for each condition and question (and the rank), the raw
  scores in date order with their mean.
- **Consistent differences**: a pair is marked `consistent` on a question when one
  condition scored higher (for the rank, ranked better) in two or more sessions
  and lower in none.

The measures come from `mpc_iml.measures`, which also runs on one recording
(`python -m mpc_iml.measures <recording>`): hits, kicks and hats per bar,
syncopation, and pattern change from bar to bar. The response columns
(`band_changes`, `answered`, `response_bars`) are **exploratory**: they replay the
recording offline, which does not repeat surprises or load user loops, and depend
on a threshold. The replay plays your own progressions from `--data` (default
`mpc-iml-data`), #236; an unknown progression is an error that names it. `--no-measures` leaves the measures out.
