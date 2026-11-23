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
Trials keep the modes fixed: both example files send `mode-pads 0` in `base`, so
pads 15 and 16 never switch the bass or melody mode during a condition (#216).
Both also send `status 0`: the status line names the variations' sources and what
pads 16 and 15 do, which would tell the musician the learning mode (#230).

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

For each condition the terminal shows only its letter. Press Play in Live and play
for `bars` bars; then press Stop in Live and Enter (Enter also ends a condition
early). Then answer the questions: 1-5 answers are asked again until they are
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

[`examples/trial/learn.json`](../examples/trial/learn.json) compares `learn off`,
`learn likes` and `learn demo` (#196), about 10 minutes each (240 bars at 90 BPM;
Enter ends a condition early):

```bash
uv run python -m mpc_iml.trial run examples/trial/learn.json ~/mpc-iml-trials
```

**Keep a profile out of the comparison.** The engine reads the profile
`<data folder>/learn/ensemble.json` when it starts, and while `learn` is not `off`
it writes it at each phrase start. So that no condition starts from what an earlier
one (or your own practice) learned:

- `base` sends `learn off`, then `reset-learning`: every condition starts from the
  rules, whatever the profile held. The condition then sends its `learn` mode.
- Run trials with a data folder of their own (`~/mpc-iml-trials` above, not your
  usual `~/mpc-iml-data`): the `likes` and `demo` conditions save what they learned
  over that folder's profile, which would otherwise replace your "my band". Copy
  your `loops/` folder into it if you play your own loops.
- `base` sends `learn-log 0` and each condition `learn-log 1`, so each condition
  gets its own `<data folder>/learn/log-<time>.jsonl`, in play order. A log file
  is created at its first bar, so the settings check before the first condition
  leaves none (#217). Summarise each with `python -m mpc_iml.learn summary <log>`.

**Only the bass learns.** `base` sends `melody-mode still` (#233): the melody plays
its `home` line every bar at one brightness, whatever the drums do, while the bass
follows the kicks with its rules and learns as in `follow`. So the three conditions
differ only in the bass, and the musician judges the learning by the bass alone. With
`follow` the melody also changed with the drums (and learned), which mixed two parts
into one score; `fixed` stops the bass from following too, so the bass played `home`
every bar and the condition could not be judged (#215's manual check).

This comparison is not blind to the pads: pad 16 is like in `likes`, chooses the
wanted bass variation in `demo`, and does nothing in `off`
(`mode-pads 0`). Before the trial, tell the musician: press 16 whenever you like
what the band plays (the bass); press again to hear
the next variation; whatever you chose goes back by itself at the end of the
4-bar phrase, and then the band plays what it learned (#215). Pad 15 does nothing
here (`melody-mode still`; the terminal shows `ensemble: pad 15 ignored, the melody
is still`), so tell the musician to press 16 only. The report's response
measures are left empty beyond 64 bars.

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
