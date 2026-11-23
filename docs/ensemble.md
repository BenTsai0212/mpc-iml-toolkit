# The ensemble guide

English | [繁體中文](ensemble.zh-TW.md)

The guide to the built-in `ensemble` preset, moved from the [README](../README.md) (#212).

## Play the ensemble preset

The built-in preset `ensemble` (`src/mpc_iml/ensemble.py`, the first step of
[RFC 0005](rfcs/0005-drum-led-ensemble.md), #138, #144, #148, #158) plays a bass and a
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

The chords come from a chord progression: `minor-two` (default: Am7 for
2 bars, then Fmaj7 for 2 bars) or `minor-four` (Dm7, Gm7, Bbmaj7, A7, one bar
each), or one of five hip-hop progressions (#236):

| Progression | Chords (bars) |
| --- | --- |
| `dark-minor` | Cm7 (2), Dbmaj7 (2): a dark i–♭II loop |
| `lofi-descent` | Fmaj7, Em7, Dm7, Cmaj7 (1 each): a lo-fi descent |
| `minor-turn` | Bm7b5 (1), E7 (1), Am7 (2): a minor ii–V–i |
| `soul-minor` | Am7 (2), Dm7 (2): a soul i–iv |
| `two-five-one` | Dm7 (1), G7 (1), Cmaj7 (2): a ii–V–I |

Every loop plays on every progression: loop notes are chord tones. The chord
qualities are `m7`, `maj7`, `7` and `m7b5` (root, minor third, flat fifth, minor
seventh). The bass plays in octave 1 (A1 is MIDI note 33). With Live's MIDI Clock Type
set to **Song**, Live's bar 1 is the start of the progression. Each progression
is a progression file (`mpc-iml-progression`, ADR 0011) in the package;
`uv run python -m mpc_iml.progressions list` prints them with their chords, and
`uv run python -m mpc_iml.progressions check <file>` checks one.

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
   [Sync to the DAW's tempo](../README.md#sync-to-the-daws-tempo-midi-clock)), and **Track** for
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
are six loops:

- `boom` (default): a 1-bar boom-bap line with rests: the root on beat 1 and the
  fifth on beat 3, a ghost note, the root an octave up and an approach note into
  the next bar.
- `walk`: a 2-bar line with more motion, a passing note and approach notes.
- `knock`: a 2-bar boom-bap line on root, fifth and a ghost seventh (#232).
- `lazy`: a 2-bar lo-fi line that sits a little behind the beat (#232).
- `soul`: a 2-bar melodic line up to the octave and back, with a chromatic walk up (#232).
- `sub`: a 2-bar half-time line of long roots with an octave pop, like an 808 (#232).

Each loop has three **variations**, each a complete bass line (#158): `home` (the
loop as described above), `push` (anticipations: notes a 16th early that answer
pushed kicks) and `drive` (8ths in `boom`, a quarter-note walk in `walk`). Each
variation has a full line (level 1) and **ornaments** (level 2: ghost notes and
passing notes) on top, so a sparse bar never drops to a skeleton.

**The kick changes the loop once per bar.** The bass listens to **kick** pads only.
At each bar line, the kicks of the bar that just ended set the whole next bar:

| Your kicks in the last bar | The next bar of the bass |
| --- | --- |
| Positions and number of kicks | **Variation**: 5 or more kicks play `drive`; else a kick off the quarter-note grid (a pushed or syncopated kick) plays `push`; else (1-4 kicks on the beat) `home`. |
| Number of kicks | **Ornaments**: 3 or more kicks add the ornaments to the full line. |
| Average kick velocity | **Loudness**: velocity 1-127 becomes 50-120. |
| Positions of the kicks | **Accents**: a bass note within one 16th of where you played a kick keeps its full velocity; the other notes play at 0.8 of it, so the line locks to your kick pattern. |

A bar without kicks (also a bar of only snare and hats) follows the `no-drums`
setting ([When the drums stop](#when-the-drums-stop)): by default the bass keeps
playing its `home` line. After Start in Live, the bass waits for your first kick.
Hits on pads 15 and 16 do not count.

Pad 15 (below) also switches the bass loop between **follow** and **fixed**: fixed
plays every note of the `home` variation (the same notes as before #158) at
velocity 100 with no accents, whatever the kicks do. Pad 15's **off** turns off
only the melody; the bass loop stays fixed until the next press of pad 15 brings
back follow.

### The melody loop

With `--clock` and Live playing, `ensemble` loops a short melody over the chord
progression, as MIDI notes on **channel 3** of `mpc-iml`
(`src/mpc_iml/melody.py`). The notes are written as chord tones (root, third,
fifth, seventh), so the loop follows each chord, also when it changes from minor to
major. There are six loops:

- `keys` (default): a sparse 2-bar keys riff.
- `pluck`: a 1-bar 8th-note arpeggio.
- `rhodes`: 2 bars of Rhodes chords (third, seventh and ninth together) (#232).
- `flute`: a 2-bar lead motif of third, ninth and root (#232).
- `horns`: short soul horn hits, two notes at a time (#232).
- `bells`: a high, sparse lo-fi bell figure, a little behind the beat (#232).

The hip-hop loops (`knock` to `bells`) also play notes outside the chord tones: a
ninth (the root a whole step up) and approach notes; the variations below describe
`keys` and `pluck`, the others are described in their loop files. In `rhodes` and
`horns` several notes start together; they all sound, and the surprise `passing`
moves every note of a chord on the last step.

The melody starts in octave 4 (A4 is MIDI note 69). As the bass, each loop has three
variations, each a complete line with ornaments on top (#158): `home` (the loop as
described above), `open` (longer notes: in `keys` a question in the first bar and an
answer an octave up, in `pluck` a quarter-note arpeggio reaching up to a held
seventh) and `busy` (short stabs on the off-8ths in `keys`, a 16th arpeggio over two
octaves in `pluck`).

**The drums change the loop once per bar.** At each bar line, the hits of the bar
that just ended set the whole next bar; nothing changes in the middle of a bar:

| Your last bar | The next bar of the melody |
| --- | --- |
| Number of hits (all pads) and the hats | **Variation**: a hat on an odd 16th (16th hats) or 14 or more hits play `busy`; 5 or fewer hits (space in the drums) play `open`; else `home`. |
| Number of hits | **Ornaments**: 8 or more hits add the ornaments to the full line. |
| Average velocity | **Loudness**: velocity 1-127 becomes 50-120, as for the bass. |
| Hits on `hat` pads | **Brightness**: CC 74 on channel 3 at the bar line, aiming from 48 with no hats to 110 with 16 or more, and moving at most 24 from one bar to the next, so a sudden change spreads over a few bars (#218). Map it to a filter or brightness knob in Live. |

So kick and snare alone give the more melodic `open` line, 8th hats the `home`
line with its ornaments, and 16th hats `busy`. An empty bar follows `no-drums`
([When the drums stop](#when-the-drums-stop)). After Start in Live, the melody
waits for your first hit. Hits on pads 15 and 16 do not count.

Press **pad 15** to cycle follow → fixed → off. **fixed** plays every note of the
melody loop's `home` variation at velocity 100 and sends no CC, and every note of
the bass loop's `home` at velocity 100 with no accents, whatever the drums do (the
same notes as before #158, with no surprises), so you can compare it with
**follow**. **off** turns off the melody only (the bass loop stays fixed). The
terminal shows the new mode (`ensemble: melody follow`, `ensemble: melody fixed` or
`ensemble: melody off`), as does group 8 **Ensemble** of the patch, and it applies
from the next bar line. The preset starts in follow.

**still** (#233, the control `melody-mode still`, for trials and practice) keeps the
melody steady while the bass follows: the melody loop plays its `home` variation
every bar at velocity 100 with its ornaments, and sends the brightness CC at one
value (79) at each bar line, whatever the drums do, also in bars without drums (it
never fades or stops; `no-drums` and `fade-bars` apply to the bass only). The bass
follows the kicks as in follow, with its rules, learning, wants and pad 16. Learning
chooses no melody variation: a like credits the bass only, and with `learn demo`
pad 15 and `want melody` do nothing (the terminal shows `ensemble: pad 15 ignored,
the melody is still`). Pad 15 does not cycle to still: from still it goes on to
fixed, then off and follow. `chose` and the status line give `still` for the
melody.

To hear the melody in Live, add a second MIDI track with a keys instrument (for
example an electric piano or a pluck preset of Drift). Set MIDI From to `mpc-iml`,
the channel to **Ch. 3**, and Monitor to **In**. Stop in Live ends the melody notes
that are sounding.

Map CC 74 to the instrument's filter cutoff with **learn CC** (#159). While Live
plays, the melody's notes on channel 3 reach Live before the CC at each bar line,
so MIDI Map Mode would catch a note instead:

1. Stop Live (the engine keeps running).
2. In Live, click **MIDI** at the top right (or press Cmd-M), then click the filter
   knob of the keys instrument.
3. Click **learn_CC** in group 8 **Ensemble** of the patch (or send
   `/mpciml/preset/ensemble/learn-cc`). It sends only CC 74 on channel 3 (the label
   next to it shows `CC 74 ch 3`), as a short sweep, and nothing else. Do not hit
   pads while mapping: a kick plays a bass note even while Live is stopped.
4. Click **MIDI** again. Clicking **learn_CC** once more sweeps the knob back down,
   which also checks the mapping.

Then start Live and play `hat` pads: the filter moves at the next bar line. While
Live plays, `learn-cc` gets `/mpciml/error bad_arguments`.

### When the drums stop

When you stop playing, the band keeps going and hands the focus to the melody, as a
drummer who drops out for a few bars would expect (#158). The control `no-drums`
([Ensemble controls](#ensemble-controls)) sets what the loops play in bars without
drums (bars without kicks, for the bass):

| `no-drums` | Bars without drums |
| --- | --- |
| `lead` (default) | The melody plays its `open` variation with ornaments (a line that leads forward); the bass plays its `home` line without ornaments, to make room. |
| `hold` | Both keep the variation and ornaments of the last bar with drums. |
| `thin` | The rule from before #158, to compare: one empty bar plays the loop's skeleton (in `boom`, the root and the fifth), two in a row stop it. |

With `lead` and `hold`, the loops keep the loudness of your last bar with drums for
`fade-bars` empty bars (default 8); the last two of them fade (0.7, then 0.4 of
that velocity), and then the loops stop. `fade-bars 0` never stops. The brightness
CC stays where it was. The loops come back at the bar after your next hit, with the
variation that bar chooses. Fixed mode always plays.

### A little surprise

The last bar of each 4-bar phrase has a 1 in 2 chance of one change you did not
ask for (#158). With `surprise 1` (the default, #178) it is a bass **fill** on beat 4
(a 16th run of root, fifth, octave and an approach note into the next bar).
`surprise 2` adds the two melody surprises: the melody an **octave** up for that
bar, or a **passing** note (the melody's last note of the bar half a step below a
chord tone of the next bar). The terminal shows each one
(`ensemble: surprise fill in bar 7`). Surprises come only in bars that follow your
drums or keep playing without them, not in fixed mode, with `no-drums thin` or in
a fading bar. With the rule bass there is no fill, and with the melody off only the
fill. `surprise 0` turns them off. The choice is
random, with a new seed each time `ensemble` is loaded.

### Teach the band with likes

With `learn likes` (#196; send `/mpciml/preset/ensemble/learn likes` before you
play), the band learns which variation you want for each way of drumming. It
starts from the rules above and still tries other variations now and then. Pad 16
is then **like**: press it while the band plays something you like, and that
choice becomes more likely the next time you drum that way. A press in the first
beat of a bar likes the bar before. The terminal shows each like
(`ensemble: like bar 12 bass push/beat>push melody mid/8ths>home`) and, at the
start of each phrase, what changed (`ensemble: learned bass push/beat>drive (rule
push)`). Choices you stop liking drift back to the rules. Set the bass mode before
playing, since pad 16 no longer cycles it, and send `learn off` to play the rules
again. What is learned is kept in your profile ([Keep what the band
learned](#keep-what-the-band-learned)).

### Teach the band by showing it

With `learn demo` (#196), you show the band what you want, as in Wekinator. Pad 16
chooses the bass variation you want and pad 15 the melody variation (#215):

- **Keep:** the first press keeps the variation playing now ("this one"). Nothing
  changes in the sound, and the way you drummed in the bar before, which the band
  is answering, becomes an example at once. In the first beat of a bar the press
  keeps the bar before, as a like does. In a bar where that loop is silent (no
  kicks for the bass, no drums for the melody), it keeps what the rules choose.
- **Next:** each further press moves to that loop's next variation (`home`,
  `push`, `drive` for the bass; `home`, `open`, `busy` for the melody), from the
  next bar line.
- **Back to `auto` by itself:** the choice lasts to the end of the 4-bar phrase,
  or to the end of the next phrase when fewer than 2 complete bars of this one are
  left. You do not press anything to come back.

The terminal shows each press and the bar where it ends (`ensemble: want bass push
(kept) to bar 16`, `ensemble: want bass drive (next) to bar 16`) and each return
(`ensemble: want bass auto (phrase end), plays model (tree)`). While a variation is
chosen, the band plays it, and every bar you drum with it becomes an example:
"this way of drumming wants this variation". Bars without drums, and bars where you
pressed again, are not used. In `auto` the band plays what it learned from your
examples (a small decision tree, retrained after each example: `ensemble: trained
bass tree, 9 examples`). Until it has at least 4 examples of 2 variations, the
ways of drumming you marked play what you marked there (the most common, or the
latest on a tie), and other drumming plays the rules (`plays model (marked
contexts, 1 label)`): drumming the same way again brings back what you kept. Keep
what you like in different ways of drumming to teach the tree. Show
a few bars of each way of drumming you use. Set the bass and melody modes before
playing, since pads 15 and 16 no longer cycle them. The examples are kept in your
profile.

### See what the band plays and what the pads do

With `status 1` (the default, #230) the terminal shows one line at each bar line
while Live plays, and again after each press of pad 16 or 15:

```text
ensemble: bar 12  bass drive (rule)  melody home (rule)  16: keep drive  15: keep home
```

- the bar (counted from 0 at Start);
- the bass and melody variation playing in it and where each choice came from:
  `rule`, `bandit` (`learn likes`), `model` or `want` (`learn demo`), `still` for the
  melody in `melody-mode still` (#233); `-` when that loop is silent;
- what pad 16 and pad 15 do if you press them now: `keep <variation>` and
  `next <variation>` with `learn demo`, `like` with `learn likes`, the mode they
  switch to (`bass rule`, `melody fixed`) with `mode-pads 1`, and `-` when the pad
  does nothing (`mode-pads 0`, or pad 15 with `learn demo` and `melody-mode still`).
  In the first beat of a bar a keep keeps the bar
  before, as described above.

A press of pad 16 or 15 that does nothing because the clock is not running (Live
is stopped, or the count-in) is shown as `ensemble: pad 16 ignored, the clock is not
running`, also with `status 0`. The status line only shows: it changes nothing that
plays. `status 0` turns it off; trials send it ([Blind comparison trials](trials.md)).

### Keep what the band learned

What the band learned, the likes' weights and your examples, is your profile ("my
band", #196): one file, `mpc-iml-data/learn/ensemble.json`, in the engine's data
folder. `ensemble` reads it when it is loaded, and while `learn` is `likes` or
`demo` it saves it at the start of each 4-bar phrase (`ensemble: saved the profile
…`), so you lose at most a phrase. `save-profile` saves it now, `load-profile`
reads it again, and `reset-learning` goes back to the rules (the file changes at
the next save). A file that cannot be read is skipped with a log line, the reply
`profile-errors` is 1, the rules play, and it is not overwritten until you send
`save-profile`. See what was learned without the engine:

```bash
uv run python -m mpc_iml.learn show
```

It prints, for each way of drumming, the rules' choice and the learned weights,
with `*` where the band learned something else, and the decision tree your
examples trained, as rules. Give it a path to show another profile. The profile
stays on your computer: the toolkit never uploads it, and `mpc-iml-data/` is in the
`.gitignore` of this repo and of `python -m mpc_iml.new` projects.

To compare `learn off`, `likes` and `demo` in a trial, send `learn-log 1` before
you play (#196). Each bar then adds a line to a new file
`mpc-iml-data/learn/log-<time>.jsonl`: the way you drummed (its context), what each
loop played and where it came from (`rule`, `bandit`, `model`, `want`), what the
rules would have chosen, whether you liked the bar, and the examples it added. It
does not change what plays. `learn-log 0` finishes the file (when the engine
quits, the last two bars are not written). `bar` counts from song start, as in a
`record --clock` recording, so the two join by bar. Summarise a log:

```bash
uv run python -m mpc_iml.learn summary mpc-iml-data/learn/log-20261122-140509.jsonl
```

It prints, for each `learn` mode, the bars, how many you liked, how often each
loop's variation differed from the rules, and your examples per variation.

The trial file [`examples/trial/learn.json`](../examples/trial/learn.json) plays
`learn off`, `likes` and `demo` as three conditions of a blind trial (#197), each
starting from the rules and with its own log; see
[docs/trials.md](trials.md#comparing-learning-modes) for how to run it and keep
your profile out of it.

### Write your own bass line

The loops are loop files (ADR 0010): the loops above are built
in, and you can add your own without changing the toolkit (#173). Write a line in
Live, turn it into a loop file, and play it:

1. In Live, make a MIDI clip of 1, 2 or 4 bars that starts on a bar line, and write
   the bass line in it over the chords of `minor-two`: **Am7** for 2 bars, then
   **Fmaj7** for 2 bars (or `minor-four`: Dm7, Gm7, B♭maj7, A7, one bar each). Write
   it around A1 (MIDI note 33), the bass's default octave; the melody's is A4. Play
   it as you like: notes off the grid, ghost notes and notes outside the chord are
   kept.
2. Right-click the clip and choose **Export MIDI Clip…**, for example `my-boom.mid`.
3. In the toolkit folder, turn it into a loop file. The name is lower case letters,
   digits and hyphens:

   ```bash
   uv run python -m mpc_iml.loops import my-boom.mid --part bass --name my-boom
   ```

   This writes `mpc-iml-data/loops/my-boom.json`, the data folder of
   `uv run mpc-iml`, and prints how the notes were read: chord tones, approach notes
   into the next chord, other notes, and notes off the grid (kept as an `offset`).
   Each note is stored as a chord tone, so the line follows the chords when you
   change the progression. Add `--progression minor-four` if you wrote it over
   `minor-four`, `--start-bar 2` if the clip starts on the Fmaj7, and
   `--ornament-below 60` to make notes quieter than velocity 60 ornaments (played
   only when you play busier drums).
4. The clip is the `home` variation. To add the variations for pushed kicks and for
   busy kicks, write two more clips and add them to the same file:

   ```bash
   uv run python -m mpc_iml.loops import my-boom-push.mid --variation push --into mpc-iml-data/loops/my-boom.json
   uv run python -m mpc_iml.loops import my-boom-drive.mid --variation drive --into mpc-iml-data/loops/my-boom.json
   ```

   A variation you leave out plays `home`. A melody uses `--part melody` and the
   variations `open` and `busy`.
5. Click **reload** in group 8 **Ensemble** ([below](#the-ensemble-group-in-pure-data))
   and choose the line with `<` `>` next to `bass loop`. The engine also reads the
   folder each time `ensemble` is loaded. A file that cannot be used is skipped: the
   terminal names the file and the reason, and `errors` in group 8 counts the
   skipped files. `uv run python -m mpc_iml.loops check mpc-iml-data/loops/my-boom.json`
   checks a file without the engine.

To start from a built-in line, export it as a clip, drag it into Live and change it:
`uv run python -m mpc_iml.loops export boom boom.mid` (add `--variation push` for
another variation). The kick rules, the ornaments and the bass fill work on your
lines as on the built-in ones.

### The Ensemble group in Pure Data

Group 8 **Ensemble** of the patch (`src/mpc_iml/patches/mpc-iml.pd`, ADR 0009), in
the column right of group 7 **Outputs**, shows what `ensemble` plays and switches
its modes, loops and progression with clicks. Load `ensemble` with its preset button
in group 1 **Connect**, or start with `--preset ensemble`. The whole patch fits a
14-inch MacBook screen without scrolling (1490 × 840).

| In the group | What it does |
| --- | --- |
| `bass`: `loop`, `rule`, `off` | Sets the bass mode. `now` shows the mode playing, `next` the one asked for. |
| `melody`: `follow`, `fixed`, `off` | Sets the melody mode (`melody-mode`), with `now` and `next` as for the bass. `still` (#233) has no button; `now` and `next` show it when set by the control. |
| `bass loop`, `melody loop` | `<` and `>` choose the previous or next loop the engine lists (the built-in loops by name; then installed and your own loops), and the box under them shows the one selected. |
| `reload`, `errors` | `reload` reads your loop files again (`reload-loops`, [Write your own bass line](#write-your-own-bass-line)); `errors` shows how many were skipped (`loop-errors`). |
| `progression` | `<` and `>` choose the previous or next progression the engine lists (`minor-two`, `minor-four`, then the others by name), and the box under them shows the one selected. |
| `octave`, `melody octave` | Number boxes for the bass octave (0-3) and the melody octave (2-6). |
| `roles` | The role of each pad, read only, 4 rows of 4 like the pads (13-16 on top). |
| `learn_CC`, `CC`, `ch` | Sends `learn-cc` to map the brightness CC in Live ([The melody loop](#the-melody-loop)); `CC` and `ch` show the CC and channel it sends on (`filter-cc`, `melody-channel`). |

As the label next to the heading says, changes start at the next bar line while
Live plays. A press of pad 15 or 16 on the MPC shows up in the group too: `next`
changes at once, `now` at the bar line where the mode starts playing; while Live
is stopped both change at once. Without `--clock` the melody's `now` stays `off`,
because the melody does not play.

The group is always there. While another preset is loaded, its boxes show `-` (the
octave boxes keep their last number), and a click puts `inactive_preset` on the
status line in group 9 **Messages**: load `ensemble` first. The pad roles, the MIDI
channels, `length`, `immediate`, `bar`, `filter-cc`, the pads that cycle the modes,
`no-drums`, `fade-bars` and `surprise` stay OSC only ([Ensemble controls](#ensemble-controls)). The Max for Live device
has no Ensemble group.

### Ensemble controls

The controls are preset messages to the engine's control port (6450). Group 8
**Ensemble** of the Pure Data patch ([above](#the-ensemble-group-in-pure-data))
sends the most used ones; send the others from any OSC client:

| Message | Values | Default | Meaning |
| --- | --- | --- | --- |
| `/mpciml/preset/ensemble/bass` | `loop`, `rule` or `off` | `loop` | The bass mode |
| `/mpciml/preset/ensemble/bass-loop` | a bass loop's name (a built-in loop such as `walk` or `knock`, or your own) | `boom` | The bass loop |
| `/mpciml/preset/ensemble/bass-loop-step` | 1 or -1 | - | The next or previous bass loop of `bass-loops`, wrapping around |
| `/mpciml/preset/ensemble/immediate` | 0 or 1 | 1 | The immediate layer of the rule bass |
| `/mpciml/preset/ensemble/bar` | 0 or 1 | 1 | The bar layer of the rule bass |
| `/mpciml/preset/ensemble/progression` | a progression's name (`progressions`) | `minor-two` | The chord progression |
| `/mpciml/preset/ensemble/progression-step` | 1 or -1 | - | The next or previous progression of `progressions`, wrapping around |
| `/mpciml/preset/ensemble/octave` | 0-3 | 1 | Octave of the bass (A1 at 1) |
| `/mpciml/preset/ensemble/length` | 1-16 | 2 | Note length of the rule bass in 16ths |
| `/mpciml/preset/ensemble/channel` | 1-16 | 2 | MIDI channel of the bass |
| `/mpciml/preset/ensemble/role` | pad 1-16, then `kick`, `snare`, `hat` or `other` | the table above | The role of one pad, in every bank |
| `/mpciml/preset/ensemble/layer-pad` | 0-16 | 16 | The pad that cycles the bass mode; 0 for none |
| `/mpciml/preset/ensemble/melody-mode` | `follow`, `fixed`, `off` or `still` | `follow` | The melody mode in one message (sets `melody` and `follow`); `off` also drops the notes still to come; `still` (#233): the melody plays `home` while the bass follows |
| `/mpciml/preset/ensemble/melody` | 0, 1 or `still` | 1 | The melody; 0 also drops the notes still to come, 1 turns it on in the mode it had, `still` turns it on in `melody-mode still` |
| `/mpciml/preset/ensemble/loop` | a melody loop's name (a built-in loop such as `pluck` or `rhodes`, or your own) | `keys` | The melody loop |
| `/mpciml/preset/ensemble/loop-step` | 1 or -1 | - | The next or previous melody loop of `loops`, wrapping around |
| `/mpciml/preset/ensemble/reload-loops` | none | - | Reads the loop files in `<data folder>/loops/` again; a changed loop plays from the next bar line |
| `/mpciml/preset/ensemble/follow` | 0 or 1 | 1 | 1: the drums change the bass and melody loops; 0: fixed; either ends `still` |
| `/mpciml/preset/ensemble/melody-octave` | 2-6 | 4 | Octave of the melody (A4 at 4) |
| `/mpciml/preset/ensemble/melody-channel` | 1-16 | 3 | MIDI channel of the melody and its CC |
| `/mpciml/preset/ensemble/filter-cc` | 0-127 | 74 | The brightness CC; 0 for none |
| `/mpciml/preset/ensemble/melody-pad` | 0-16 | 15 | The pad that cycles the melody; 0 for none |
| `/mpciml/preset/ensemble/learn-cc` | none | - | Sends only the brightness CC on the melody channel (0, 32, 64, 96, 127, then downwards on the next message) so a DAW can map it; refused while the clock runs or when `filter-cc` is 0 |
| `/mpciml/preset/ensemble/no-drums` | `lead`, `hold` or `thin` | `lead` | What both loops play in bars without drums ([When the drums stop](#when-the-drums-stop)) |
| `/mpciml/preset/ensemble/fade-bars` | 0-32 | 8 | Empty bars before the loops stop (the last two fade); 0 never stops |
| `/mpciml/preset/ensemble/surprise` | 0-2 (0 off, 1 the bass fill only, 2 also the melody surprises) | 1 | The surprises at the end of each 4-bar phrase ([A little surprise](#a-little-surprise)) |
| `/mpciml/preset/ensemble/rhythm` | 0, 1 or 2 | 0 | 1: the bass line's notes move to the kicks of the last bar (plain in the first bar of each 4-bar phrase, then moved, displaced by a 16th in the last); 2: also the melody's notes, to the snares and hats of the last bar (plain in the first bar of each phrase); 0: the lines as written. The default was 1 until #194: in the manual check the moved bass sometimes sounded off the beat in steady styles such as hip-hop |
| `/mpciml/preset/ensemble/learn` | `off`, `likes` or `demo` | `off` | `likes`: each loop's variation comes from what your likes taught it, starting from the rules, and pad 16 is **like** instead of cycling the bass mode (set the bass mode before playing); `demo`: pads 16 and 15 choose the bass and melody variation you want, and `auto` plays what your examples taught ([Teach the band by showing it](#teach-the-band-by-showing-it)); `off`: the rules (#196) |
| `/mpciml/preset/ensemble/like` | none | - | As pad 16 with `learn likes`: likes what the band plays in this bar (in the first beat, the bar before); refused with `learn off` or while the clock is not running |
| `/mpciml/preset/ensemble/want` | `bass` or `melody`, then `auto` or one of its variations | `auto` | With `learn demo`: the variation you want that loop to play and learn, until you send `auto` (unlike pads 16 and 15, it does not end at the phrase end, #215); refused unless `learn demo` |
| `/mpciml/preset/ensemble/save-profile` | none | - | Saves what was learned to `learn/ensemble.json` in the data folder now ([Keep what the band learned](#keep-what-the-band-learned)) |
| `/mpciml/preset/ensemble/load-profile` | none | - | Reads that profile again; refused when it is missing or cannot be read |
| `/mpciml/preset/ensemble/reset-learning` | none | - | Back to the rules: forgets the likes' weights and the examples (the file changes at the next save) |
| `/mpciml/preset/ensemble/learn-log` | 0 or 1 | 0 | 1: writes a line per bar to a new `learn/log-<time>.jsonl` in the data folder, to compare the learning modes; 0: finishes it ([Keep what the band learned](#keep-what-the-band-learned)) |
| `/mpciml/preset/ensemble/mode-pads` | 0 or 1 | 1 | 1: pads 15 and 16 cycle the melody and bass modes; 0: they keep the modes (still like in `learn likes` and want in `learn demo`), as trials send ([Blind comparison trials](trials.md)) |
| `/mpciml/preset/ensemble/status` | 0 or 1 | 1 | 1: a status line in the terminal at each bar line, with the variations playing, their source and what pads 16 and 15 do now ([See what the band plays and what the pads do](#see-what-the-band-plays-and-what-the-pads-do)); 0: none, as trials send. Presses ignored without a running clock are shown either way |

The settings go back to the defaults when `ensemble` is loaded again or the engine
starts. Bad values get `/mpciml/error bad_arguments`, and messages for `ensemble`
while another preset is loaded get `inactive_preset`. The bass mode and the melody
controls apply from the next bar line.

**State replies** (protocol 1.5, ADR 0009): the engine sends `ensemble`'s whole state
to the reply port (6451) as `/mpciml/preset/ensemble/<reply>` messages after
`preset/load`, in the full state (`hello`, `state/get`), after each control that
succeeds, after a press of pad 15 or 16, and at a bar line where the playing bass or
melody mode, a playing variation or a playing transformation changes:

| Reply | Arguments |
| --- | --- |
| `bass` | next and playing mode (`loop`, `rule`, `off`) |
| `melody-mode` | next and playing mode (`follow`, `fixed`, `off`, `still`) |
| `bass-loop`, `loop`, `progression` | the selected name |
| `bass-loops`, `loops`, `progressions` | the names to choose from (loops: built-in, then installed, then yours, each by name; progressions: `minor-two`, `minor-four`, then the other built-in ones by name, then installed ones) |
| `octave`, `melody-octave`, `channel`, `melody-channel`, `length`, `filter-cc`, `layer-pad`, `melody-pad`, `immediate`, `bar` | the value (`immediate` and `bar` as 0 or 1) |
| `roles` | 16 roles, pads 1-16 |
| `no-drums` | the value (`lead`, `hold`, `thin`) |
| `fade-bars`, `surprise` | the value (`surprise` as 0-2) |
| `variation` | the bass variation and the melody variation playing (`-` when that loop is silent, not a loop, or there is no `--clock`) |
| `loop-errors` | how many of your loop files were skipped at the last read |
| `rhythm` | the value (0, 1 or 2) |
| `transform` | the bass and the melody transformation playing (`plain`, `lock`, `answer`, `backbeat`; `-` when that loop is silent, not a loop, or there is no `--clock`) |
| `learn` | the learning mode (`off`, `likes`, `demo`) |
| `likes` | the likes that credited a choice since `ensemble` was loaded |
| `chose` | where the bass and the melody variation playing came from (`rule`, `bandit`, `model`, `want`, `still` for the melody in `melody-mode still`; `-` when that loop is silent, not a loop, or there is no `--clock`) |
| `learned` | up to 4 `<part>:<context>><variation>` whose learned top choice differs from the rules (`-` for none) |
| `want` | the bass and the melody variation you want with `learn demo` (`auto` for none) |
| `examples` | the bass and the melody examples shown with `learn demo`, with those of the profile |
| `profile-errors` | 1 when the profile could not be read at the last try, else 0 |
| `learn-log` | 1 while the per-bar log is written, else 0 |
| `mode-pads` | 1 while pads 15 and 16 switch the modes, else 0 |
| `status` | 1 while the status line is shown, else 0 |

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
melody as above (bass on Ch. 2, keys on Ch. 3 with CC 74 mapped to its filter with
**learn_CC**, [The melody loop](#the-melody-loop)),
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

### Check the variations

The manual check for #158: does following the drums by variation, instead of by
dropping notes, make playing with the band more fun? It repeats the three trials of
[Check the bass loop](#check-the-bass-loop) with the same setup, the same boom-bap
patterns (sparse bars, busy bars, then one bar and two bars without drums) and about
5 minutes each. The defaults are `no-drums lead`, `fade-bars 8` and `surprise 1`.

1. **Both**: the defaults (`ensemble: bass loop`, `ensemble: melody follow`). Also
   try an off-beat kick (for example on the "and" of beat 2), 16th hats, and a
   longer stop of 10 bars or more.
2. **Content only**: pad 15 once (`ensemble: melody fixed`).
3. **Cause only**: pad 16 once (`ensemble: bass rule`); pad 15 once more
   (`ensemble: melody off`).
4. After each, write one row:

   | Trial | Fun (1-5) | Sounds like me (1-5) | Notes |
   | --- | --- | --- | --- |
   | both | | | Did the bass feel like a full bass line in sparse bars? Did stopping the drums hand the focus to the melody, and what happened after 8 empty bars? Did changing the drums (an off-beat kick, 16th hats, a sparse bar) lead to audibly different music? Were the phrase-end surprises welcome or distracting? |
   | content only | | | |
   | cause only | | | |

5. Optional: one more pass of trial 1 with `no-drums thin` or `surprise 0`, to
   compare.
6. Press Stop in Live while the bass and the melody play, and check that no note
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

### Try it without hardware

A small web page plays the real `ensemble` rules on a drum grid you fill in, so
anyone can hear how the drums choose what the band plays, without an MPC, Live or a
MIDI clock (#166). It needs the optional `demo` extra (Gradio):

```bash
uv sync --extra demo
uv run python -m mpc_iml.webdemo
```

Open the address it prints (`http://127.0.0.1:7860`). Each row of the grid is one
drum of one bar (kick, snare, hat; 0 is no hit, 1-127 the velocity). Pick an example
or place hits, choose the settings, and press **Play**. The page renders the drums,
bass and keys with a small synth and shows a table: the drums of each bar and the
variation, ornaments, velocity and brightness the band chose for the bar after it.
The **rhythm** setting is the instrument's `rhythm` (#189): `off` (the default,
#194) plays the lines as written, with `bass` the bass line's notes move to the last
bar's kicks, and with `bass and melody` the melody's also move to the snares and hats.
The table's `transform` column names the bass's and the melody's transformation
(`plain`, `lock`, `answer`, `backbeat`; `-` when silent), and `took` the drums each
moved line took and the steps its notes moved to, for example `kick 1 7 11 → bass 7`.
In the piano roll, moved notes are a lighter shade of their part's colour. Play the
same grid with `bass` to hear the moved line next to the plain one.
The **melody mode** setting also offers `still` (#233): the keys play `home` every
bar while the bass follows, and the table shows the melody as `(still)`.
The same grid and seed always sound the same. Below the table, a piano roll shows
the drums, bass and keys, and **MIDI file** downloads the song (drums on channel 10,
bass on 2, keys on 3 with the brightness CC 74) to open in a DAW.

The **learn** setting (#196) shows the band learning over the grid: with `likes`,
list the bars whose answer you like (for example `2 3 7`); with `demo`, list from
which bar's answer each part wants a variation (for example `1 bass push, 6 bass
home, 10 bass auto`: from bar 10 the decision tree plays), or list in which bar's
answer you press pad 16 (`bass`) or 15 (`melody`), as you would while drumming
(#215; for example `1 bass, 1 bass, 5 bass`: keep the variation playing, then the
next one, until the phrase ends, then keep what plays over the busier drums of bar
5). The **wants** field sends the control `want`, which holds until `auto`; a press
lasts to the end of its phrase. The table's `context` column gives the way each bar
was drummed, for the bass and the melody, and `chose` where each choice came from
(`rule`, `bandit`, `model`, `want`; `liked` for a liked answer, `pressed bass` for a
press). The **learning** box lists the likes, the presses and their phrase ends,
trained trees and what was learned. The demo has no data folder, so it never saves a
profile.

The **variations** tab (#221) plays new variations grown from a line, next to the
line itself, so you can judge whether they sound like yours before anything reaches
the band. Pick a loop: a built-in one, the name of one of your loops in the **data
folder** (`mpc-iml-data` by default), a path to a loop file, or an uploaded loop
file. Choose the variation, **novelty** (0 keeps the source, 0.2 the default stays
close, 1 is freer), the **corpus** the generator learns from (`source`, `own` your
loops of the same part, `all` every loop of the part), the number of candidates and
the seed, then press **Generate**. The source and each candidate play over the
progression and tempo at the top of the page, with a plain boom-bap drum pattern
under them (untick **drums** for the line alone), each with its own audio and piano
roll. The table below gives each one's provenance: the source, the seed, the
distance (changed notes, and their share of the source's notes) and every change.
Tick **blind** to shuffle the source and the candidates under letters `A`, `B`, …;
the table shows `?` until you press **Reveal**. The same loop and settings always
give the same candidates; `uv run python -m mpc_iml.vargen <loop> --midi` writes them
as clips for Live. The tab only reads loop files and writes nothing.

The **recording** tab plays a recording made with `python -m mpc_iml.record --clock`
instead: the band answers it exactly as the engine would have, at the recording's
tempo, from the clock's Start to the next Stop, at most 64 bars. Pads 1 and 5 are
kicks, 2 and 6 snares, 3, 4 and 7 hats (any bank). A second table lists each pad hit
on the grid, as `python -m mpc_iml.grid` prints it.

To let a teammate open it from another computer, add `--share`: Gradio makes a
temporary public link (valid for 72 hours, while the demo runs) through its share
servers. Only share when you mean to; the default is local only.

The demo turns Gradio's usage analytics off (it sets `GRADIO_ANALYTICS_ENABLED` to
`False` unless you already set it), so it sends nothing to Gradio by itself.
`--share` still goes through Gradio's share servers.
