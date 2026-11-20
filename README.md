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

`v0.1.0` is the first release (see the [changelog](CHANGELOG.md)); interfaces may
still change in 0.x. Phase 1 (Foundation). To try the whole loop, follow the
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

  Without `--duration` it records until Ctrl-C. `--clock` also records MIDI clock
  from a DAW on the virtual input `mpc-iml clock` (or `--clock-port IAC`, as for the
  engine; see [Sync to the DAW's tempo](#sync-to-the-daws-tempo-midi-clock)), in the
  same file and time base as the pads, as raw `midi` events. Other messages on that
  port are dropped. Without clock, pads are still recorded and a line says so after
  2 s.
- a grid read-back for such a recording: one tab-separated line per pad hit with
  time, bar, step, pad (`A01` to `H16`), velocity and offset from the step in ms
  (`-` while the clock was not running), and a summary on standard error. It uses
  the engine's `MidiClock` (`mpc_iml.clock.tag_recording`):

  ```bash
  uv run python -m mpc_iml.grid out.jsonl --beats-per-bar 4 --resolution 16
  ```

  `--resolution` is `16` (default), `8` or `16t` (16th triplets).
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

Formats are in [ADR 0002](docs/adr/0002-recording-and-osc-formats.md); a recording
with takes generated from modules is `format_version` 2
([ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md)),
and recordings without them are still version 1. The package
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
   Make soft and hard clearly different, for example a light fingertip touch and a
   firm press with the whole finger. When the terminal says "Release pad 1 now.",
   let go of the pad before the next countdown.

   ```bash
   uv run python -m mpc_iml.demo record examples.jsonl --no-full-level
   ```

   The receiver stays silent while you record: it only reacts in step 6
   (`demo run`). `--seconds` and `--countdown` change the timing. Run it again to
   start over.

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

The demo uses the feature set `mpc_iml.examples.played_features` (32 values: per
pad, velocity while held, else 0, then pressure) rather than the default 49, which
keep a pad's last velocity after it is released. It does not send `/wek/inputs`.

### Feature sets for playing

The default features (`mpc_iml.examples.default_features`) are the 49 `/wek/inputs`
values of ADR 0002. They keep a pad's last velocity after `Note Off`, so a "rest"
frame right after playing looks like the last hit, and a model trained on them can
answer with the last sound instead of rest. For models that react while you play,
use `played_features`: a released pad gives 0, so rest right after playing is rest.
Pass it where features are taken, for example `ExampleSet(features=played_features)`
or a preset's `features=`. The preset `demo` uses it; the 49 `/wek/inputs` values
do not change.

For an instrument played by pressure alone, `pressure_features` (16 values: per
pad, pressure, 0-1) leaves out velocity and the held flag, so a press adds nothing
until the MPC reports pressure and the input rises from 0. The preset `pressure`
uses it.

## Play in 20 minutes

The path for musicians: one command starts the engine and opens the Pure Data front
end, and everything after that is clicks in the patch. You start from a kit that
already plays (RFC 0003, ADR 0007), change it pad by pad, and add your own
demonstrations on top. This walkthrough uses the preset `pressure` (pad pressure to
8 synthesis parameters, details in [Play the pressure preset](#play-the-pressure-preset));
the front end works the same way with every preset (ADR 0006), and group 2 **Kit**
is inactive for presets without kits. The 20 minutes are counted from `uv sync`.

Before you start: steps 1-3 of the [reference example](#reference-example) (uv, the
toolkit with `uv sync`, the MPC Sample connected and set up), and
[Pure Data](https://puredata.info) vanilla 0.54 or later, from its website or with
`brew install --cask pd`. Open Pure Data once after installing it, so macOS opens
`.pd` files with it.

1. In the `mpc-iml-toolkit` folder, start everything with one command and leave
   the terminal window open:

   ```bash
   uv run mpc-iml
   ```

   The engine starts with its data folder `mpc-iml-data` and opens the front end
   `src/mpc_iml/patches/mpc-iml.pd` in Pure Data. If the patch does not open, the
   command prints its path: open that file from Pure Data (File > Open). Ctrl-C in
   the terminal stops the engine.

2. The patch connects by itself: in group 1 **Connect**, the version and `state`
   `idle` appear, and the installed presets are listed as buttons. If they stay
   empty, click `connect`. Click the preset button `pressure`. Group 2 **Kit** now
   lists the kits (`filter-play` first) and the modules, group 3 **Teach** shows the
   target sliders labelled with the output names (`brightness` to `level`), group 7
   **Outputs** the outputs with the same names and the learn buttons `l1`-`l8`, and
   group 6 **Library** the name `pressure-examples`.

3. Start from a kit: in group 2 **Kit**, click `filter-play`. The engine replaces
   the examples with the kit's generated examples and trains: `kit` shows
   `filter-play`, the state goes to `training` and back to `idle`, and `trained`
   turns on in group 5 **Model**. Click `run` and play: pads 1-4 brighten, pads 5-8
   add bite (brightness and resonance), pads 9-12 darken, pads 13-14 wobble, pad 15
   bends the pitch and pad 16 changes nothing. The outputs in group 7 follow the
   model, and the engine sends MIDI CC 20-27 on the virtual port `mpc-iml`.

4. Map the CCs in your DAW: click `stop`, map them one at a time with `l1`-`l8`
   while the state is `idle`, as in [Map the MIDI CCs in a DAW](#map-the-midi-ccs-in-a-daw),
   then click `run` again and play the synthesiser from the MPC Sample. With
   Ableton Live 12, the [Ableton Live starter set](#ableton-live-starter-set) has
   the mappings already: open it instead and skip the mapping.

5. Change a pad: turn on `select_pad` in group 2 and hit a pad on the MPC Sample.
   `pad` shows its number, `module` its module, and `amount` how strongly the module
   acts. Click another module (for example `wobble`), or move `amount` and let go:
   the engine replaces only that pad's generated examples and retrains, and keeps
   running if it was. You can also type a pad number (1-16) into `pad` instead of
   hitting it. A change while a retrain is still in progress gets an error on the
   status line; wait for the retrain to finish. Turn `select_pad` off when you are
   done (`record` turns it off too).

6. Add demonstrations on top: click `stop`, set the target sliders in group 3 to
   the sound you want for a gesture, hold the gesture on the pads, click `record`
   in group 4 **Examples**, keep holding for about two seconds, and click
   `stop_recording`. Click `train`, then `run`. A demonstration trains together
   with the pad's module: a short one nudges the module's sound, one of 2-3 seconds
   outweighs it.

7. Click `save` in group 6 **Library** to keep the examples, with the kit and the
   pads' modules, in `mpc-iml-data/pressure-examples.jsonl`; next time, `load`
   brings them back.

Errors from the engine (for example a button clicked in the wrong state) appear on
the status line in group 9 **Messages**, not only in the Pd window.

**Recording from nothing** (the advanced route): instead of a kit, click `clear`
in group 4 **Examples** (it also clears the kit) and record every example
yourself. For each one: set the target sliders (0-1) to the sound you want, hold
the gesture on the pads, click `record`, keep holding for about two seconds, and
click `stop_recording`. Record four examples in this order: rest (no pad touched,
targets set to silence), the lightest touch on pad 1 (targets close to rest), a
light press, and a hard press, each with its own targets. The counts show how many
examples you have. Then click `train`, and `run` when `trained` is on.

Options of `uv run mpc-iml`: a folder name after the command uses another data
folder (`uv run mpc-iml my-data`); `--no-patch` starts only the engine, for the
[Max for Live device](#use-the-max-for-live-device) or your own front end; the other
options are those of the engine (`--preset`, `--replay`, `--midi-port IAC`, the
ports; see [Run the engine](#run-the-engine)).

If something does not work while you play, see [Troubleshooting](#troubleshooting).

## Run the engine

The engine is a long-running IML loop that a front end (Pure Data, Max, later an
app) drives with OSC control messages; the protocol is
[ADR 0004](docs/adr/0004-engine-control-protocol.md), version 1.1 in
[ADR 0005](docs/adr/0005-engine-protocol-1-1-midi-learn.md), 1.2 in
[ADR 0006](docs/adr/0006-engine-protocol-1-2-layout-and-front-ends.md), 1.3 in
[ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md), 1.4 in
[ADR 0008](docs/adr/0008-engine-protocol-1-4-midi-clock-sync.md) and 1.5 (preset state
replies) in
[ADR 0009](docs/adr/0009-engine-protocol-1-5-preset-state-and-ensemble-group.md). Start it with a folder for
its saved example sets, with the MPC connected as in the
[reference example](#reference-example):

```bash
uv run python -m mpc_iml.engine my-data
```

It listens for control messages on `127.0.0.1:6450`, sends replies and state reports
to `127.0.0.1:6451`, and starts with the preset `demo` (`--preset` picks another).
While running it sends the preset's features to `/wek/inputs` (port 6448) and its
model outputs to the preset's output (`/wek/outputs` on port 12000 for `demo`).
`--control-port`, `--reply-port`, `--inputs-port` and `--outputs-port` change the
ports. Without an MPC, `--replay <recording>` plays a recording once in real time
instead:

```bash
uv run python -m mpc_iml.engine my-data --replay tests/fixtures/recordings/hold-pressure.jsonl
```

A session from a front end: `/mpciml/hello 1` (the engine answers with its version
and full state; integer arguments such as the version and reply port also accept a
whole-number float like `1.0`, so plain Pure Data messages work without a type tag), `/mpciml/class soft`, `/mpciml/record/start`, play,
`/mpciml/record/stop`, then `/mpciml/train`, `/mpciml/run` and `/mpciml/stop`.
`/mpciml/examples/save <name>` writes `my-data/<name>.jsonl` (an ADR 0002
recording); the engine writes nothing outside that folder. Every message gets a
reply, a state report or an `/mpciml/error`. For a preset with MIDI output,
`/mpciml/midi/learn <output>` (1 for its first controller), in `idle` or `training`,
sends a short sweep on that one controller so a DAW can learn it, and answers
`/mpciml/midi/sent <output> <controller>`. With the preset, the engine reports
`/mpciml/layout <targets> <controllers>`: the preset's number of target values (0 for
classification) and MIDI controllers (0 without MIDI output), so a front end shows
the right controls. Ctrl-C stops the engine: input and
sockets are closed and a training in progress is finished first.

Protocol 1.3 adds kits for presets with named outputs (`pressure`; see
[Named outputs, modules and kits](#named-outputs-modules-and-kits)). The full state
and `preset/load` also send `/mpciml/names` (the output names), `/mpciml/kit` (the
kit the set started from, or `""`) and `/mpciml/pads` (16 pairs of module and
amount). `/mpciml/kit/list` and `/mpciml/module/list` answer `/mpciml/kits` and
`/mpciml/modules`. `/mpciml/kit/load filter-play` replaces the example set with the
kit's generated takes and trains; `/mpciml/pad/module <pad> <module> [amount]`
changes one pad (1-16), keeps recorded demonstrations and trains again (both in
`idle`, or in `running` when no retrain is in progress). Between
`/mpciml/pad/select/start` and `/mpciml/pad/select/stop` (or `record/start` or
`preset/load`) each pad hit on the MPC is reported as `/mpciml/pad/hit <pad>`.
`examples/clear` also clears the kit; `examples/save` writes a set with generated
takes as recording format version 2, and `examples/load` restores its kit and pad
assignments.

The reference front end for every preset is the Pure Data patch
`src/mpc_iml/patches/mpc-iml.pd` (vanilla 0.54 or later, no externals; ADR 0006).
Start the engine, then open the patch: it connects on open (click `connect` after
restarting the engine), lists the installed presets as buttons, and adapts to the
loaded one: class buttons for `demo`, target sliders `t1`-`t8` and learn buttons
`l1`-`l8` for `pressure`. Errors from the engine appear on its status line.
`uv run mpc-iml` starts the engine and opens this patch in one step
([Play in 20 minutes](#play-in-20-minutes)).

### Sync to the DAW's tempo (MIDI clock)

Protocol 1.4 lets the engine follow the tempo, bar and beat of a DAW that sends MIDI
clock (ADR 0008). Sync is off unless you start the engine with `--clock`:

```bash
uv run mpc-iml --clock
```

The engine then opens a virtual MIDI input called `mpc-iml clock`, which the DAW
lists as an output. Start the engine before the DAW, or turn the port off and on
again in the DAW's MIDI settings.

- **Live** (any edition): in Settings > Link, Tempo & MIDI > MIDI Ports, turn on
  **Sync** for the output `mpc-iml clock`, and set MIDI Clock Type to **Song** so
  that Live sends the song position.
- **Logic**: in File > Project Settings > Synchronization > MIDI, turn on Transmit
  MIDI Clock to `mpc-iml clock`, with Song Position Pointer.

`--clock-port IAC` reads clock from an existing input port whose name contains the
text instead (it implies `--clock`). `--beats-per-bar 3` sets the bar length in
quarter notes (default 4; MIDI clock carries no meter). The engine reports
`/mpciml/clock <status> <bpm> <bar> <beat>` on every status change and once per beat
while the DAW plays, and at the end of the full state. The status is `off` without
`--clock`, `waiting` until the first tick, `running`, `stopped` after Stop, and
`lost` when no tick has arrived for 0.5 s; bar and beat count from 1 (0 before the
first tick). Pad input, recording, training and running never wait for the clock.

To check that notes from the engine land on the beat, send `/mpciml/clock/test 1`:
from the next bar, the engine plays note 72 on beat 1 and note 60 on the other beats
(one 16th long) on the `mpc-iml` MIDI output. Arm a MIDI track on input `mpc-iml`
with any instrument to hear it; `/mpciml/clock/test 0` stops it. In the Pure Data
front end, group 9 **Messages** shows the clock line (status, BPM, bar and beat), and
the `test` toggle next to it sends `/mpciml/clock/test`. Stop in the DAW
ends sounding notes, and the pattern starts again on the next bar after Play or
Continue. If the notes sound late, `--clock-lead-ms 10` sends scheduled notes 10 ms
early (or use Live's MIDI Clock Sync Delay).

## Play the pressure preset

The built-in preset `pressure` (`src/mpc_iml/pressure.py`, scenario 1 of
[RFC 0002](docs/rfcs/0002-platform-positioning.md)) maps pad pressure to
8 synthesis parameters at once. You show it a few gestures, each with the 8 values
it should produce, and it learns the mapping in between (one-to-many regression,
the built-in MLP). It uses `pressure_features`, so strike velocity has no effect.
While running it sends:

- `/wek/outputs` with 8 floats to `127.0.0.1:12000`, for Pure Data or any OSC
  receiver (unscaled: usually 0-1, sometimes slightly outside);
- MIDI control changes 20-27 on channel 1 (output 1 is CC 20, output 8 is CC 27),
  scaled from 0-1 to 0-127, to a virtual MIDI port named `mpc-iml`, for a DAW
  synthesiser. A CC is sent only when its value changes, and nothing is sent
  outside `running`.

You need the setup of the [reference example](#reference-example) (steps 1-3) and
[Pure Data](https://puredata.info) (vanilla 0.54 or later) for the front end.

1. Start the engine with the preset and the front end, and leave the terminal window
   open:

   ```bash
   uv run mpc-iml --preset pressure
   ```

   On macOS the port `mpc-iml` now appears in every MIDI app as an input. To use
   the IAC bus instead, turn it on in Audio MIDI Setup (Window > Show MIDI Studio,
   double-click IAC Driver, tick "Device is online") and add `--midi-port IAC`. If
   the MIDI port cannot be opened, the engine says so and keeps sending OSC.

2. The command opens the front end `src/mpc_iml/patches/mpc-iml.pd` in Pure Data
   (if it does not, open the path it prints with File > Open). The patch connects
   by itself: group 1 **Connect** shows the version and `state` `idle`, and with
   `pressure` loaded, group 2 **Kit** lists the kits and modules, group 3 **Teach**
   shows the target sliders labelled `brightness` to `level`, and group 7
   **Outputs** the learn buttons `l1`-`l8`. Click `connect` if you restarted the
   engine after the patch. To start from a kit instead of recording, follow
   steps 3-5 of [Play in 20 minutes](#play-in-20-minutes).

3. Record a few examples (group 4 **Examples**). For each one: set the 8 target
   sliders (0-1) to the sound you want, hold the gesture on the pads,
   click `record` (it sends the targets, then starts recording), keep holding for
   about two seconds, and click `stop_recording`. Start with rest (no pads, targets
   for silence), then for example pad 1 held lightly and pad 1 held firmly, each
   with its own targets. Several pads and other pressures work the same way. For a
   continuous light end, also record the lightest touch you can hold (pad 1 resting
   on the pad, barely pressed) with targets close to rest, so the model maps the
   lightest pressure near rest rather than far from it. To start again (for
   example after recording in the wrong order), click `clear`: it deletes all
   examples in the engine, and saved files are not touched. It works in `idle` and
   `running`, and the counts show the new numbers.

4. Click `train` (group 5 **Model**). The state goes to `training`, then back to
   `idle`, and `trained` turns on. Click `run` and play: the output sliders in
   group 7 follow the model, and the MIDI CCs follow them. `stop` ends running.
   `save` and `load` (group 6 **Library**) keep the examples in
   `mpc-iml-data/pressure-examples.jsonl`.

The patch shows `/wek/outputs` by listening on port 12000, and only one program can
listen on a port. To drive a Pd synth with OSC instead, start the engine with
`--outputs-port <port>` and let the synth listen on that port (the patch's output
sliders then stay still), or close this patch and send the control messages from
your own.

### Map the MIDI CCs in a DAW

`mpc-iml` sends only CC 20-27 on channel 1, no notes; the notes that play the
synthesiser come from the MPC Sample itself. The port exists only while the engine
runs, so start the engine before you open the DAW's MIDI settings. Turn on the
input `mpc-iml` (or the IAC bus) for remote control, then map CC 20-27 on channel 1
to synthesiser parameters:

- **Ableton Live**: in Settings > Tempo & MIDI, in the Input Ports table, turn on
  **Track** for the MPC Sample, and turn on **Remote** (Track off) for `mpc-iml`.
  Leave the track's MIDI input on the MPC Sample (or All Ins); setting it to
  `mpc-iml` gives no sound, because that port sends no notes. Enter MIDI Map Mode
  (Cmd-M), click a parameter, send its CC, and leave MIDI Map Mode.
- **Logic Pro**: select the parameter, choose Logic Pro > Control Surfaces > Learn
  Assignment for "<parameter>" (Cmd-L), send its CC, and turn Learn off.
- DAWs that let you type a CC number for a mapping: enter 20-27 directly.

Suggested mappings for the eight outputs of `pressure`, for any DAW and a typical
subtractive synthesiser. The ranges are starting points; adjust them by ear. The
[Ableton Live starter set](#ableton-live-starter-set) is a worked example.

| Output | CC | What it is for | Suggested target on a typical subtractive synth | Suggested range |
| --- | --- | --- | --- | --- |
| `brightness` | 20 | How open or dark the sound is | Filter cutoff | About 80 Hz to 16 kHz |
| `resonance` | 21 | How sharply the filter rings at the cutoff | Filter resonance | 0 to about 85 % |
| `drive` | 22 | Grit and added harmonics | Saturation or distortion amount | 0 to about 50 % |
| `space` | 23 | How distant or roomy the sound is | Reverb send or wet | 0 to 60 % |
| `motion` | 24 | How much the sound moves | LFO depth to pan, filter or amplitude | 0 to about 50 % |
| `pitch` | 25 | Bending the pitch; the resting value is the middle | Pitch or detune | About -2 to +2 semitones, or ±20 cents of detune |
| `texture` | 26 | Noise and roughness | Noise level or waveshape | Noise 0 to about 30 %, or the full waveshape range |
| `level` | 27 | How loud the sound is | Output gain | About -24 dB to 0 dB |

While the model runs, all 8 CCs move together, so MIDI learn would catch whichever
comes first. Map them one at a time with the `learn` buttons `l1`-`l8` in the patch
instead, while the engine is not running (`state` shows `idle`):

1. In the DAW, start MIDI learn for the parameter that output 1 should control.
2. Click `l1` in the patch. The engine sends only CC 20, sweeping 0 to 127; the DAW
   learns it. Clicking again sweeps back down, which also checks the mapping.
3. Leave MIDI learn, and repeat for `l2` (CC 21) to `l8` (CC 27).

`l3` sends CC 22, as `t3` and `o3` are output 3. From your own front end, send
`/mpciml/midi/learn 3` for the same. While running, the message gets the error
`wrong_state`; click `stop` first. You can map before or after recording examples;
the mappings stay when you train again.

What you get at the light end (#76):

- A slow, light press starts from rest and rises with pressure. The MPC Sample
  reports pressure about 70 ms after the pad is touched, so the outputs start
  moving then; before that they stay at rest.
- While a pad is held very lightly, the MPC Sample (firmware 1.3.0) sends `Note Off`
  when the pressure reaches its minimum and a new `Note On` 70-273 ms later. Since
  the preset ignores velocity and the held flag, the input only goes from the last
  pressure (1-3 of 127) to 0 and back, the same as easing off, so the outputs stay
  close to where they were instead of dropping to rest.
- A quick tap without sustained pressure barely registers.

The outputs are not smoothed; smoothing may follow if playing shows it matters.

### Drift (experiment A)

Drift is the first experiment of RFC 0004 (#114), a mode of `pressure` that is off
by default. While a pad is held the outputs follow the model as usual. When every
pad has been released for 300 ms, the outputs do not fall back to rest: they glide
slowly between points taken from your examples (the kit's rest and modules and your
own takes), starting from where you let go. The next press hands control back to
the model with a 150 ms crossfade, so nothing jumps.

The controls are preset messages to the engine's control port (6450). The Pure Data
patch has no group for them yet, so send them from any OSC client:

| Message | Values | Default | Meaning |
| --- | --- | --- | --- |
| `/mpciml/preset/pressure/drift/on` | 0 or 1 | 0 | Master switch; 0 is exactly today's behaviour |
| `/mpciml/preset/pressure/drift/range` | 0-1 | 0.5 | 0 stays where you let go; 1 reaches your example targets |
| `/mpciml/preset/pressure/drift/speed` | 0-1 | 0.3 | One glide takes about 20 s at 0 and 2 s at 1 (±30 %) |
| `/mpciml/preset/pressure/drift/pad` | 0-16 | 16 | The pad that switches between instrument and drift; 0 for none |

- With `drift/on 1`, pad 16 (any bank) switches between **instrument** (no drift on
  release, as today) and **drift**; turning drift on starts in instrument. Pad 16 is
  then only a switch: it makes no sound, even if the kit gives it a module. Press it
  **firmly**: the switch reacts to the pad's pressure, and a quick flick may send
  none. After a press, the pad must rest for 300 ms before the next press counts,
  so a light hold that retriggers does not switch twice. Nothing shows which of the
  two you are in; listen after releasing.
- With `drift/pad 0`, pad 16 plays like the others and drift is active whenever
  `drift/on` is 1.
- The engine does not reply with the drift settings. They go back to the defaults
  when `pressure` is loaded from another preset or the engine starts, so send them
  again after `/mpciml/preset pressure`. Bad values get `/mpciml/error bad_arguments`.
- Turning `drift/on` off returns to the model at once, without a crossfade.

## Play the ensemble preset

The built-in preset `ensemble` (`src/mpc_iml/ensemble.py`, the first step of
[RFC 0005](docs/rfcs/0005-drum-led-ensemble.md), #138, #144, #148) plays a bass and a
melody that follow your drums. There is no model and nothing to train: you play
drums on the MPC Sample as usual. With `--clock`, a bass loop plays over a fixed
chord progression, and your **kicks** in each bar shape the next bar of the loop
([below](#the-bass-loop)). The bass plays one note at a time, as MIDI notes on
**channel 2** of the virtual port `mpc-iml`. A short melodic loop also plays over the
same chords on **channel 3**, and how you play each bar shapes the next bar of the
melody ([below](#the-melody-loop)). It plays in any engine state; you do not need to
click `run`.

Each pad has a role. The defaults are a boom-bap layout (pad 1 is bottom left; the
same in every bank):

| Pads | 1 | 2 | 3 | 4 |
| --- | --- | --- | --- | --- |
| 1-4 | kick | snare | hat (closed) | hat (open) |
| 5-8 | kick | snare (clap or rim) | hat | other |
| 9-16 | other | other | other | other |

Only `kick` drives the bass, so put the kick on pad 1 or 5 of your MPC program.
Pad 16 switches the bass mode (below) and plays no bass; pad 15 switches the
melody (below).

The bass has three modes:

- **loop** (the default, needs `--clock`): a bass loop that keeps playing, and the
  kicks of each bar change the next bar ([The bass loop](#the-bass-loop)).
- **rule**: the rule-based bass of #138, one note on the root of the chord for each
  kick, in two layers (below). It is the "cause only" bass to compare the loop with.
- **off**: no bass.

The rule bass has two layers, and you can turn each one on or off with the
controls `immediate` and `bar` ([Ensemble controls](#ensemble-controls)) to compare
them:

- **immediate**: a kick plays a bass note at once, with the chord of the bar it
  falls in. A harder hit plays louder (velocity 1-127 becomes 50-120). The note
  ends 2 sixteenths later (`length`), or after 0.25 s while the DAW is not playing.
- **bar** (needs `--clock`): each kick at a position in one bar plays a bass note
  at the same position in the **next** bar, on that bar's chord. Last bar's kicks
  come back one bar later; a bar without kicks gives a bar without bass. Hits
  before the first clock tick are ignored.
- **both** (the default): at most one bass note per 16th. If you play a kick near
  a note that the bar layer is about to play, your kick plays and the echo is
  dropped. If the echo has already sounded, your kick plays no bass. With a steady
  pattern you hear the immediate layer; where you leave a kick out, last bar's
  kick fills it in.

The chords come from one of two progressions: `minor-two` (default: Am7 for
2 bars, then Fmaj7 for 2 bars) and `minor-four` (Dm7, Gm7, Bbmaj7, A7, one bar
each). The bass plays in octave 1 (A1 is MIDI note 33). With Live's MIDI Clock Type
set to **Song**, Live's bar 1 is the start of the progression.

### Set up Live for the bass

1. Start the engine with the preset and the clock, and leave the terminal window
   open. The Pure Data front end also opens and shows the modes in group 8
   **Ensemble** ([below](#the-ensemble-group-in-pure-data)); `ensemble` needs none
   of its controls, and `--no-patch` leaves it closed:

   ```bash
   uv run mpc-iml --preset ensemble --clock
   ```

2. In Live, in Settings > Link, Tempo & MIDI > MIDI Ports, turn on **Sync** for the
   output `mpc-iml clock` with MIDI Clock Type **Song** (as in
   [Sync to the DAW's tempo](#sync-to-the-daws-tempo-midi-clock)), and **Track** for
   the input `mpc-iml`.
3. Add a MIDI track with a bass instrument (for example a bass preset of Live's
   Drift). Set MIDI From to `mpc-iml` and the channel below it to **Ch. 2**, and
   set Monitor to **In**.
4. Press Play in Live and play a pattern with the kick on pad 1. Stop in Live ends
   the bass note that is sounding and drops the notes still to come.

Press **pad 16** to cycle the bass loop → rule → off. The terminal shows the new
mode (`ensemble: bass loop`, `ensemble: bass rule` or `ensemble: bass off`), and so
does group 8 **Ensemble** of the patch (`next` at once, `now` from the bar line). It
applies from the next bar line (at once while Live is stopped). The preset starts
in loop.

Without `--clock`, `ensemble` still loads and the bass plays a note on each kick
(the immediate layer, also in loop mode), always with the first chord and 0.25 s
notes; the bass loop, the bar layer and the melody are off, and the engine prints
`ensemble: no MIDI clock (start with --clock); bass loop, bar layer and melody off, bass plays on each kick`.
With `--clock`, the rule bass plays the same way while the DAW is stopped or before
it starts, and the bass loop waits for Live to play.

### The bass loop

With `--clock` and Live playing, the bass in loop mode plays a loop written in
chord tones, like the melody ([below](#the-melody-loop)), so it follows each chord of
the progression. Its approach and passing notes aim at the **next** bar's chord: a
half step or a whole step below the next root, leading into the chord change. There
are two loops:

- `boom` (default): a 1-bar boom-bap line with rests: the root on beat 1 and the
  fifth on beat 3, a ghost note, the root an octave up and an approach note into
  the next bar.
- `walk`: a 2-bar line with more motion, a passing note and approach notes.

Each note of a loop has a level 1-3: level 1 notes are the skeleton (in `boom`, the
root and the fifth, so even a sparse bar sounds like a bass line), levels 2 and 3 fill it in.

**The kick changes the loop once per bar.** The bass listens to **kick** pads only.
At each bar line, the kicks of the bar that just ended set the whole next bar:

| Your kicks in the last bar | The next bar of the bass |
| --- | --- |
| Number of kicks | **Density**: 1-2 kicks play the skeleton only, 3-4 add level 2, 5 or more play every note. |
| Average kick velocity | **Loudness**: velocity 1-127 becomes 50-120. |
| Positions of the kicks | **Accents**: a bass note within one 16th of where you played a kick keeps its full velocity; the other notes play at 0.8 of it, so the line locks to your kick pattern. |

When you stop playing kicks, one bar without kicks keeps the skeleton, and two in a
row stop the bass; it comes back at the bar after your next kick. A bar of only
snare and hats counts as a bar without kicks, so the bass thins out under a
breakdown while the melody keeps playing. After Start in Live, the bass waits for
your first kick. Hits on pads 15 and 16 do not count.

Pad 15 (below) also switches the bass loop between **follow** and **fixed**: fixed
plays every note of the loop at velocity 100 with no accents, whatever the kicks
do. Pad 15's **off** turns off only the melody; the bass loop stays fixed until
the next press of pad 15 brings back follow.

### The melody loop

With `--clock` and Live playing, `ensemble` loops a short melody over the chord
progression, as MIDI notes on **channel 3** of `mpc-iml`
(`src/mpc_iml/melody.py`). The notes are written as chord tones (root, third,
fifth, seventh), so the loop follows each chord, also when it changes from minor to
major. There are two loops:

- `keys` (default): a sparse 2-bar keys riff.
- `pluck`: a 1-bar 8th-note arpeggio.

The melody starts in octave 4 (A4 is MIDI note 69). Each note of a loop has a level
1-3: level 1 notes are the loop's skeleton, levels 2 and 3 fill it in.

**The drums change the loop once per bar.** At each bar line, the hits of the bar
that just ended set the whole next bar; nothing changes in the middle of a bar.
Three things in your playing each change one thing you can hear:

| Your last bar | The next bar of the melody |
| --- | --- |
| Number of hits (all pads) | **Density**: 1-4 hits play the skeleton only, 5-10 add level 2, 11 or more play every note. Kick and snare give the skeleton; add 8th hats to fill the loop in. |
| Average velocity | **Loudness**: velocity 1-127 becomes 50-120, as for the bass. |
| Hits on `hat` pads | **Brightness**: CC 74 on channel 3 at the bar line, from 40 with no hats to 127 with 16 or more. Map it to a filter or brightness knob in Live. |

When you stop playing, one empty bar keeps the skeleton under the break, and two
empty bars in a row stop the melody; it comes back at the bar after your next hit.
After Start in Live, the melody waits for your first hit. Hits on pads 15 and 16
do not count.

Press **pad 15** to cycle follow → fixed → off. **fixed** plays every note of the
melody loop at velocity 100 and sends no CC, and every note of the bass loop at
velocity 100 with no accents, whatever the drums do, so you can compare it with
**follow**. **off** turns off the melody only (the bass loop stays fixed). The
terminal shows the new mode (`ensemble: melody follow`, `ensemble: melody fixed` or
`ensemble: melody off`), as does group 8 **Ensemble** of the patch, and it applies
from the next bar line. The preset starts in follow.

To hear the melody in Live, add a second MIDI track with a keys instrument (for
example an electric piano or a pluck preset of Drift). Set MIDI From to `mpc-iml`,
the channel to **Ch. 3**, and Monitor to **In**. Map CC 74 to the instrument's
filter cutoff: click **MIDI** at the top right, click the filter knob, hit pads on
`hat` pads with Live playing (the CC goes out at the next bar line), and click
**MIDI** again. Stop in Live ends the melody notes that are sounding.

### The Ensemble group in Pure Data

Group 8 **Ensemble** of the patch (`src/mpc_iml/patches/mpc-iml.pd`, ADR 0009), in
the column right of group 7 **Outputs**, shows what `ensemble` plays and switches
its modes, loops and progression with clicks. Load `ensemble` with its preset button
in group 1 **Connect**, or start with `--preset ensemble`. The whole patch fits a
14-inch MacBook screen without scrolling (1490 × 840).

| In the group | What it does |
| --- | --- |
| `bass`: `loop`, `rule`, `off` | Sets the bass mode. `now` shows the mode playing, `next` the one asked for. |
| `melody`: `follow`, `fixed`, `off` | Sets the melody mode (`melody-mode`), with `now` and `next` as for the bass. |
| `bass loop`, `melody loop` | Up to 4 buttons, labelled with the loops the engine lists (`boom`, `walk`; `keys`, `pluck`); the box under them shows the one selected. |
| `progression` | Up to 4 buttons labelled with the progressions (`minor-two`, `minor-four`), and the one selected. |
| `octave`, `melody octave` | Number boxes for the bass octave (0-3) and the melody octave (2-6). |
| `roles` | The role of each pad, read only, 4 rows of 4 like the pads (13-16 on top). |

As the label next to the heading says, changes start at the next bar line while
Live plays. A press of pad 15 or 16 on the MPC shows up in the group too: `next`
changes at once, `now` at the bar line where the mode starts playing; while Live
is stopped both change at once. Without `--clock` the melody's `now` stays `off`,
because the melody does not play.

The group is always there. While another preset is loaded, its boxes show `-` (the
octave boxes keep their last number), and a click puts `inactive_preset` on the
status line in group 9 **Messages**: load `ensemble` first. The pad roles, the MIDI
channels, `length`, `immediate`, `bar`, `filter-cc` and the pads that cycle the modes
stay OSC only ([Ensemble controls](#ensemble-controls)). The Max for Live device
has no Ensemble group.

### Ensemble controls

The controls are preset messages to the engine's control port (6450). Group 8
**Ensemble** of the Pure Data patch ([above](#the-ensemble-group-in-pure-data))
sends the most used ones; send the others from any OSC client:

| Message | Values | Default | Meaning |
| --- | --- | --- | --- |
| `/mpciml/preset/ensemble/bass` | `loop`, `rule` or `off` | `loop` | The bass mode |
| `/mpciml/preset/ensemble/bass-loop` | `boom` or `walk` | `boom` | The bass loop |
| `/mpciml/preset/ensemble/immediate` | 0 or 1 | 1 | The immediate layer of the rule bass |
| `/mpciml/preset/ensemble/bar` | 0 or 1 | 1 | The bar layer of the rule bass |
| `/mpciml/preset/ensemble/progression` | `minor-two` or `minor-four` | `minor-two` | The chord progression |
| `/mpciml/preset/ensemble/octave` | 0-3 | 1 | Octave of the bass (A1 at 1) |
| `/mpciml/preset/ensemble/length` | 1-16 | 2 | Note length of the rule bass in 16ths |
| `/mpciml/preset/ensemble/channel` | 1-16 | 2 | MIDI channel of the bass |
| `/mpciml/preset/ensemble/role` | pad 1-16, then `kick`, `snare`, `hat` or `other` | the table above | The role of one pad, in every bank |
| `/mpciml/preset/ensemble/layer-pad` | 0-16 | 16 | The pad that cycles the bass mode; 0 for none |
| `/mpciml/preset/ensemble/melody-mode` | `follow`, `fixed` or `off` | `follow` | The melody mode in one message (sets `melody` and `follow`); `off` also drops the notes still to come |
| `/mpciml/preset/ensemble/melody` | 0 or 1 | 1 | The melody; 0 also drops the notes still to come |
| `/mpciml/preset/ensemble/loop` | `keys` or `pluck` | `keys` | The melody loop |
| `/mpciml/preset/ensemble/follow` | 0 or 1 | 1 | 1: the drums change the bass and melody loops; 0: fixed |
| `/mpciml/preset/ensemble/melody-octave` | 2-6 | 4 | Octave of the melody (A4 at 4) |
| `/mpciml/preset/ensemble/melody-channel` | 1-16 | 3 | MIDI channel of the melody and its CC |
| `/mpciml/preset/ensemble/filter-cc` | 0-127 | 74 | The brightness CC; 0 for none |
| `/mpciml/preset/ensemble/melody-pad` | 0-16 | 15 | The pad that cycles the melody; 0 for none |

The settings go back to the defaults when `ensemble` is loaded again or the engine
starts. Bad values get `/mpciml/error bad_arguments`, and messages for `ensemble`
while another preset is loaded get `inactive_preset`. The bass mode and the melody
controls apply from the next bar line.

**State replies** (protocol 1.5, ADR 0009): the engine sends `ensemble`'s whole state
to the reply port (6451) as `/mpciml/preset/ensemble/<reply>` messages after
`preset/load`, in the full state (`hello`, `state/get`), after each control that
succeeds, after a press of pad 15 or 16, and at a bar line where the playing bass or
melody mode changes:

| Reply | Arguments |
| --- | --- |
| `bass` | next and playing mode (`loop`, `rule`, `off`) |
| `melody-mode` | next and playing mode (`follow`, `fixed`, `off`) |
| `bass-loop`, `loop`, `progression` | the selected name |
| `bass-loops`, `loops`, `progressions` | the names to choose from |
| `octave`, `melody-octave`, `channel`, `melody-channel`, `length`, `filter-cc`, `layer-pad`, `melody-pad`, `immediate`, `bar` | the value (`immediate` and `bar` as 0 or 1) |
| `roles` | 16 roles, pads 1-16 |

The names and arguments are versioned by the preset version (ADR 0004).

### Compare the layers

The manual check for #138, with the MPC Sample, Live set up as above, and a tempo
around 90 BPM:

1. Press pad 16 once, so the terminal shows `ensemble: bass rule`.
2. Play a boom-bap pattern (kick on pad 1, snare on pad 2, hats on pad 3) for
   5 minutes in each layer setting: **immediate** only (send `bar 0`), **bar** only
   (`immediate 0`, `bar 1`), and **both** (`immediate 1`, `bar 1`), with the
   controls above.
3. After each, write one row:

   | Mode | Fun (1-5) | Sounds like me (1-5) | Notes |
   | --- | --- | --- | --- |
   | immediate | | | Timing; did the bass follow the kicks? |
   | bar | | | |
   | both | | | |

4. Press Stop in Live while the bass is playing, and check that no note keeps
   sounding.

### Check the melody

The manual check for #144, with the MPC Sample, Live set up for the bass and the
melody as above (bass on Ch. 2, keys on Ch. 3 with CC 74 mapped to its filter),
Sync on for `mpc-iml clock` with MIDI Clock Type **Song**, and
`uv run mpc-iml --preset ensemble --clock`:

1. 5 minutes with the melody **following** (the terminal shows
   `ensemble: melody follow`): alternate sparse bars (kick and snare only) and busy
   bars (8th or 16th hats, hard hits), and drop out for one bar and for two bars.
2. 5 minutes with the melody **fixed** (pad 15 once), with the same patterns.
3. After each, write one row:

   | Melody | Fun (1-5) | Sounds like me (1-5) | Notes |
   | --- | --- | --- | --- |
   | follow | | | Were the density, loudness and brightness changes heard as caused by the drums? Did the one-bar delay feel natural? Did stopping after two empty bars feel right? |
   | fixed | | | |

4. Press Stop in Live while both play, and check that no note keeps sounding on
   either channel.

### Check the bass loop

The manual check for #148: does the musician lead the band when the bass and the
melody have musical content that the drums steer? It compares **both** (content and
cause), **content only** (the loops fixed) and **cause only** (the rule bass). Set up
the MPC Sample and Live as for [Check the melody](#check-the-melody) and run
`uv run mpc-iml --preset ensemble --clock`, at a tempo around 90 BPM.

Use the same boom-bap patterns in each trial, about 5 minutes each: sparse bars
(kick and snare only), busy bars (16th hats, 4-5 kicks, hard hits), then one bar and
two bars without drums.

| Trial | Setting | Compares |
| --- | --- | --- |
| 1. Both | The defaults: `ensemble: bass loop`, `ensemble: melody follow` | Content **and** cause |
| 2. Content only | Pad 15 once: `ensemble: melody fixed` (both loops fixed) | Content without cause |
| 3. Cause only | Pad 16 once: `ensemble: bass rule`; pad 15 once more: `ensemble: melody off` | The #138 bass alone |

1. Play the three trials in order and check the terminal after each pad press.
2. After each, write one row:

   | Trial | Fun (1-5) | Sounds like me (1-5) | Notes |
   | --- | --- | --- | --- |
   | both | | | Did you feel you were leading the band? Were the bass's density, loudness and accents heard as caused by the kick? Did the bass thinning on a bar without kicks feel right? |
   | content only | | | |
   | cause only | | | |

3. Press Stop in Live while the bass and the melody play, and check that no note
   keeps sounding on channel 2 or 3.

### Check the Ensemble group

The manual check for #153, with Live set up as above, Sync on for `mpc-iml clock`,
and `uv run mpc-iml --clock` (the patch opens):

1. Click the preset button `ensemble` in group 1. Group 8 **Ensemble** shows the
   defaults: bass `loop`/`loop`, melody `follow`/`follow`, `boom`, `keys`,
   `minor-two`, octaves 1 and 4, and the roles of the table above. The whole patch
   is visible without scrolling, and no boxes overlap.
2. Press Play in Live. From the patch, click every bass mode, bass loop, melody mode,
   melody loop and progression, and change both octaves. Check that `next` changes
   at once and `now` at the following bar line, and that what you hear matches.
3. Press pad 16 and pad 15 on the MPC Sample through all their modes, and check the
   same in the group.
4. Click `connect` in group 1: the group shows the same state again.
5. Click the preset button `pressure`: the group shows `-`, and a click in it gives
   `inactive_preset` on the status line.
6. Check that the Pd window shows no red errors.

## Ableton Live starter set

A Live set that plays the `pressure` preset with no mapping step (RFC 0003, #104),
in [`assets/ableton/`](assets/ableton):

- `mpc-iml-starter.als`: one MIDI track `mpc-iml` (input All Ins, Monitor Auto)
  with an Instrument Rack whose eight macros are named after the `pressure`
  outputs and already mapped to CC 20-27 on channel 1 from the port `mpc-iml`;
- `mpc-iml-starter.adg`: the same Instrument Rack on its own: Drift, Saturator,
  Auto Pan-Tremolo, Reverb and Utility.

It needs Ableton Live 12, Standard or Suite. It uses only devices built into Live,
with no Max for Live, no samples and no third-party plug-ins. It was built and
played in Live 12.4 Standard.

1. Start the engine first, so the port `mpc-iml` exists, and leave the terminal
   window open:

   ```bash
   uv run mpc-iml
   ```

2. Open `assets/ableton/mpc-iml-starter.als` in Live.
3. In Settings > Tempo & MIDI, in the Input Ports table, turn on **Track** for the
   MPC Sample, and turn on **Remote** (Track off) for `mpc-iml`. Live keeps these
   settings, so this is needed only once.
4. In the Pure Data front end, click the preset `pressure`, load a kit in group 2
   **Kit** (for example `filter-play`), wait for `trained`, click `run` and play the
   MPC Sample. The macros follow the pressure.

The macros (macro 0 to 127; channel 1, port `mpc-iml`):

| Macro | Name | CC | Parameter | Range |
| --- | --- | --- | --- | --- |
| 1 | brightness | 20 | Drift low-pass frequency | 80 Hz to 16 kHz |
| 2 | resonance | 21 | Drift low-pass resonance | 0 to 0.85 |
| 3 | drive | 22 | Saturator Drive | 0 dB to 18 dB |
| 4 | space | 23 | Reverb Dry/Wet | 0 % to 60 % |
| 5 | motion | 24 | Auto Pan-Tremolo LFO Amount | 0 % to 60 % |
| 6 | pitch | 25 | Drift Osc 2 Detune | -0.50 to +0.50 (centre in tune, the kits' resting pitch 0.5) |
| 7 | texture | 26 | Drift Noise Gain | -inf dB to -10 dB |
| 8 | level | 27 | Utility Output Gain | -24 dB to 0 dB |

Fixed settings: Drift filter type II (24 dB), filter envelope modulation (Freq
Mod, Env 2) 0 %, Osc 2 saw; Saturator Dry/Wet 100 %; Auto Pan-Tremolo rate 4 Hz;
Reverb decay 3.00 s. The kits' resting values are still provisional, so the sound
at rest may change.

The rack `mpc-iml-starter.adg` can be dragged into another set, but it does not
carry the CC mappings: they are stored only in the `.als`. In another set, map the
macros as in [Map the MIDI CCs in a DAW](#map-the-midi-ccs-in-a-daw).

## Troubleshooting

What to check first when something does not work while you play. Errors from the
engine appear on the status line in group 9 **Messages** of the patch.

| Symptom | What to check |
| --- | --- |
| No sound | The DAW track's MIDI input is the MPC Sample (or All Ins), not `mpc-iml`: that port sends only CCs and the `ensemble` bass and melody, not the drums. The track's Monitor is In or Auto. On the MPC Sample, **MIDI Port** is **USB** and **Pad MIDI Out** is **Always** (step 3 of the [reference example](#reference-example)). |
| Sound, but the parameters or macros do not move | The engine is running and the front end's `state` shows `running` (click `run`). In Live, `mpc-iml` has **Remote** on in Settings > Tempo & MIDI. If the DAW was opened before the engine, the port `mpc-iml` did not exist yet: after starting the engine, restart the DAW (or turn the port off and on again in its MIDI settings). |
| Mappings lost or wrong | Click `stop` so that `state` shows `idle`, then map one CC at a time with `l1`-`l8`, as in [Map the MIDI CCs in a DAW](#map-the-midi-ccs-in-a-daw). In Live, the [Ableton Live starter set](#ableton-live-starter-set) has the mappings already. |
| The patch does not respond | Click `connect`. If that does not help, close the patch, stop the engine with Ctrl-C in the terminal and run `uv run mpc-iml` again. |
| The engine stopped, or the MPC Sample does not respond | Reconnect the USB cable, stop `uv run mpc-iml` with Ctrl-C and start it again, then click the preset (for example `pressure`), load a kit and click `run` again. |
| `ensemble` plays no bass | The bass track's MIDI From is `mpc-iml`, **Ch. 2**, and **Track** is on for the input `mpc-iml` in Live's settings. The kick is on pad 1 or 5. The bass loop needs `--clock` and Live playing, waits for your first kick after Start and stops after two bars without kicks. Pad 16 may have switched the bass to `rule` or `off` (group 8 **Ensemble** and the terminal show the mode); see [Play the ensemble preset](#play-the-ensemble-preset). |
| `ensemble` plays no melody | The engine runs with `--clock` and Live is playing with Sync on for `mpc-iml clock`. The keys track's MIDI From is `mpc-iml`, **Ch. 3**. The melody waits for your first hit after Start and stops after two empty bars. Pad 15 may have switched it off (group 8 **Ensemble** shows `off`, the terminal `ensemble: melody off`); see [The melody loop](#the-melody-loop). |
| `wrong_state` on the status line after changing a module or `amount` | A retrain is in progress; wait a moment and try again. |
| A light hold or a quick tap barely changes the sound | See the notes on the light end (#76) at the end of [Map the MIDI CCs in a DAW](#map-the-midi-ccs-in-a-daw), in [Play the pressure preset](#play-the-pressure-preset). |

## Use the Max for Live device

The Max for Live device lets you record, train, run and map the model without
leaving Ableton Live. It has the 7 groups of ADR 0006 with the button names and
order of the Pure Data front end, but not yet group 2 **Kit** of ADR 0007 or
group 8 **Ensemble** of ADR 0009 (Pure Data only), so the patch's groups 3-7 and 9
are the device's groups 2-7, and the recording route of
[Play in 20 minutes](#play-in-20-minutes) applies to it; only the start and the
install differ. The device has not been checked in Live yet (#86).

You need Live Suite, or Live Standard with Max for Live, the setup of the
[reference example](#reference-example) (steps 1-3), and the Live settings of
[Map the MIDI CCs in a DAW](#map-the-midi-ccs-in-a-daw) (**Track** on for the MPC
Sample, **Remote** on for `mpc-iml`).

The device is a Max MIDI Effect: it goes on the MPC Sample's MIDI track in front of
the instrument and passes the pads' MIDI through unchanged. It talks to the engine
over OSC on the same ports as the Pure Data front end (6450, 6451 and 12000), so
only one of the two can run at a time: close `mpc-iml.pd` while the
device is in your Live set. It uses standard Max objects only, no externals.

### Install the device

The repository has the device's source, `src/mpc_iml/patches/mpc-iml.maxpat` (a Max
patcher generated by `tools/m4l/build_device.py`). Until a ready-made `mpc-iml.amxd`
is added, build the device from it once:

1. In Live's browser, under Max for Live, drag **Max MIDI Effect** onto the MPC
   Sample's MIDI track, in front of the instrument.
2. Click the device's edit button to open it in Max. Select all the objects that are
   already there (Cmd-A) and delete them: they pass MIDI through, which the device
   does itself.
3. In Max, open `src/mpc_iml/patches/mpc-iml.maxpat` (File > Open), select all
   (Cmd-A), copy (Cmd-C), close it, and paste (Cmd-V) into the device's window.
4. In the Patcher Inspector of the device's window, turn on **Open in
   Presentation**, so Live shows the controls instead of the wiring.
5. Save as `mpc-iml.amxd` (File > Save As), for example in your User Library, and
   close Max. Next time, drag `mpc-iml.amxd` from the User Library onto a track.

### Play with the device

1. In the `mpc-iml-toolkit` folder, start only the engine and leave the terminal
   window open:

   ```bash
   uv run mpc-iml --no-patch
   ```

   Add `--preset pressure` to start with that preset; you can also choose it in the
   device.

2. Open your Live set with the device on the MPC Sample's track. The device connects
   when it loads: in group 1 **Connect**, the protocol and engine version, the preset
   and `state` `idle` appear. If they stay at `-`, click `connect` (for example after
   restarting the engine); `ping` checks that the engine answers. Choose the preset
   from the menu.

3. Group 2 **Teach** adapts to the preset. For `pressure`: the target sliders
   `t1`-`t8`. For a classification preset such as `demo`: the `class` field and the
   class buttons `c1`-`c8`.

4. Record, train and run as in "Recording from nothing" of
   [Play in 20 minutes](#play-in-20-minutes), with `record` and `stop recording` in
   group 3 **Examples** and `train`, `run` and `stop` in group 4 **Model**. Group 6
   **Outputs** shows the model's outputs `o1`-`o8` as bars (for `demo`, the
   predicted class).

5. Map the CCs one at a time while the state is `idle`: in Live, enter MIDI Map Mode
   (Cmd-M), click the parameter that output 1 should control, click `l1` in the
   device, and leave MIDI Map Mode. The device shows `output 1 on CC 20`. Repeat
   with `l2`-`l8`. Then click `run` and play the instrument from the MPC Sample.

6. In group 5 **Library**, `save` keeps the examples under the name in the `name`
   field (`pressure-examples` by default) in the engine's data folder `mpc-iml-data`;
   `load` brings them back, and `list` shows the saved names.

Errors from the engine appear on the status line in group 7 **Messages**, not only
in the Max window. The device does not map outputs to Live parameters by itself (no
`live.remote~`): the engine's CCs on `mpc-iml` stay the way to control parameters,
also in other DAWs.

## Write a preset

A preset bundles a feature function, a model, optional fixed class numbers and an
output mapping under a name, and is loaded as a plugin (RFC 0002). The reference
example is the built-in preset `demo` (`mpc_iml.demo.PRESET`). An external package
adds a preset without changing the toolkit:

1. Define a `Preset` (`src/mpc_iml/presets.py`) in your package:

   ```python
   from mpc_iml.presets import MidiCcOutput, OscOutput, Preset

   PRESET = Preset(
       name="my-preset",
       version="0.1.0",
       description="One line for listings",
       features=my_features,
       model_factory=MyModel,
       outputs=(OscOutput(), MidiCcOutput(controllers=(20, 21))),
       patch="my_package:patches/main.pd",
   )
   ```

   `features` and `classes` are what `ExampleSet(features=..., classes=...)` takes,
   and `model_factory` is what `IMLLoop` takes (`None`: Wekinator is the model).
   `OscOutput` defaults to `/wek/outputs` on `127.0.0.1:12000`. `MidiCcOutput`
   declares one CC number per output value, scaled from `ranges` (default 0-1) to
   0-127; the engine sends them while `running` (`mpc_iml.midi_out`, see the
   [pressure preset](#play-the-pressure-preset)). `patch` is the front-end patch inside your package, as
   `<package>:<path>`. `name` is lower case letters, digits and hyphens; `list` and
   `load` are reserved for core messages (ADR 0004) and raise `PresetError`.

2. Register it in your package's `pyproject.toml`; the entry point may also name a
   function that returns a `Preset`:

   ```toml
   [project.entry-points."mpc_iml.presets"]
   my-preset = "my_package:PRESET"
   ```

3. Once the package is installed next to the toolkit, `available_presets()` lists
   it and `get_preset("my-preset").build_loop()` returns an `IMLLoop` with its
   features, model and first `OscOutput`. A preset that fails to load, is not a
   `Preset` or reuses a name raises `PresetError`.

`controls` (a control name mapped to a handler) is **provisional until ADR 0004 is
accepted**: the engine forwards `/mpciml/preset/<name>/<control>` to the handler of
`<control>`, with the message's arguments, only while `<name>` is the active preset.
Its type may change.

`clock` is **provisional** too (ADR 0008): a function that the engine calls with a
`mpc_iml.clock.ClockAccess` each time it loads the preset, with or without
`--clock`. It reads `state()` and `position(t)`, and `on_hit(callback)` receives each
pad hit placed on the grid as a `GridHit` (bar, 16th step and offset from the step)
while the DAW plays. `on_pad(callback)` receives every pad hit as a `PadHit`, in any
clock status and without `--clock`; its `grid` is the `GridHit` while the DAW plays,
otherwise `None`. `send_now(messages)` sends notes and other MIDI messages at once on
the `mpc-iml` port; with `--clock` the notes it starts end on Stop like scheduled
ones. With `--clock`, `scheduler` (a `mpc_iml.clock.Scheduler`, otherwise `None`)
sends them at a bar and step: `note(bar, step, note, velocity, length_steps)`,
`at(bar, step, messages)` and `at_next_bar(messages, n)`; `cancel(handle)` drops one.
Loading another preset drops what is still scheduled and ends sounding notes.
`report()` asks the engine to send the preset's state again (below); it does nothing
once another preset has loaded.

`state` is **provisional** too (ADR 0009): a function that returns the preset's
current state as (reply name, arguments) pairs, with names in lower case letters,
digits and hyphens and arguments as ints, floats or strings. The engine sends each
pair as `/mpciml/preset/<name>/<reply>` after `preset/load`, in the full state after
`clock`, after each preset control that succeeds, and when the preset calls
`report()`, for example after a pad press that changed a mode. The engine calls
`state` while holding its lock, so do not call `report()` while holding a lock your
controls also take. `ensemble` is the example.

`tests/plugins/` holds a complete example package, and `tests/test_presets.py`
installs it and runs it on a recorded fixture.

### Named outputs, modules and kits

A regression preset may name its outputs with `output_names` (one per target, lower
case letters, digits and hyphens). Only presets with names get modules and kits
([ADR 0007](docs/adr/0007-engine-protocol-1-3-kits-modules-and-pad-selection.md)):
a **module** moves some named outputs as a pad is pressed, and a **kit** is a
resting sound plus a module on each of the 16 pads. `pressure` names its outputs
`brightness`, `resonance`, `drive`, `space`, `motion`, `pitch`, `texture` and
`level` (CC 20-27), and comes with 9 modules and the kits `filter-play` (default),
`texture-lab` and `ambient-space` (`src/mpc_iml/modules/pressure/`,
`src/mpc_iml/kits/pressure/`; resting values are provisional until a hardware
playtest). The engine loads a kit with `/mpciml/kit/load` and changes a pad with
`/mpciml/pad/module` ([Run the engine](#run-the-engine)).

Another package adds modules and kits, also to a preset it does not define, by
putting JSON files in `<root>/modules/<preset>/<name>.json` and
`<root>/kits/<preset>/<name>.json` and registering a `Content`:

```toml
[project.entry-points."mpc_iml.content"]
my-content = "my_package:CONTENT"
```

where `CONTENT = Content(preset="pressure", root="my_package:content")`.
`mpc_iml.content.load_library(preset)` lists them, and
`mpc_iml.generation.GeneratedSet.from_kit(library, "filter-play")` generates a
kit's training examples; `tests/plugins/mpc_iml_example_content/` is an example.

## Start a practice repository

`python -m mpc_iml.new` creates a project that depends on this toolkit instead of
copying it: a `pyproject.toml` pinning `mpc-iml-toolkit` to the git tag of the
running version, an empty model (`src/<package>/model.py`) to replace, a script that
trains on a recording and runs on a replay, a test, a sample recording and a short
README. The package name comes from the directory name (`--name` overrides it).

```bash
uv run python -m mpc_iml.new ../my-practice
```

In the new project, `uv sync` installs the pinned release. To work against a local
checkout of the toolkit instead, run `uv add --editable <path to mpc-iml-toolkit>`
in the new project, then `uv sync`.

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

The pad test waits 10 seconds for a quick press and release of pad A01: tap the pad,
do not hold it.

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

## Citing

If you use the toolkit in research, please cite it. The citation metadata is in
[CITATION.cff](CITATION.cff); GitHub shows it as "Cite this repository" on the
repository page. A version number and release date are added at the first release.

## Licence

[MIT](LICENSE). Optional extensions such as RAVE and nn~ have their own licences
(CC BY-NC 4.0, non-commercial only) and are never bundled with or required by the
toolkit. The licences of the runtime dependencies are listed in
[docs/licenses.md](docs/licenses.md).
