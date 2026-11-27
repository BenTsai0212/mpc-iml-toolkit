"""Built-in preset `ensemble`: a bass and a melody that follow the drums (RFC 0005).

No model: each pad has a role (`kick`, `snare`, `hat`, `other`; `DEFAULT_ROLES` is a
boom-bap layout, any bank) and only `kick` drives the bass. The bass is monophonic,
on the `mpc-iml` port, channel 2 by default, over a fixed progression (a progression
file, #236: `minor-two` by default, see `mpc_iml.progressions`), in one of three
modes (`bass`):

- `loop` (default, #148, needs `--clock`): a bass loop of chord tones (`bass`) that
  keeps playing; at each bar line the kicks of the bar that ended set the next bar
  (#158): their positions choose the variation and the accents, their number whether
  the ornaments play, their average velocity the loudness (`bass.bass_variation`,
  `bass.bass_ornaments`, `bass.accent`, its own `melody.Follower`). Without a
  running clock it falls back to the immediate layer below;
- `rule` (#138): the root of the current chord, in two layers that can be switched
  on and off on their own, to compare them;
- `off`: no bass.

The two layers of `rule`:

- **immediate**: a kick sounds a bass note at once, with the chord of the hit's bar
  (the first chord when the clock is not running or the bar is negative), velocity
  1-127 mapped to 50-120, ending `length` 16ths later on the grid (or after
  `NOTE_SECONDS` without a running clock);
- **bar** (needs `--clock`): each kick at step `s` of bar `b` schedules a note at
  step `s` of bar `b + 1`, with that bar's chord: last bar's kicks echoed. Hits with
  a negative bar are ignored.

With both on there is one note per step slot and the first one wins: a live kick
within one step of a pending echo cancels it and plays; when the echo has already
sounded, the kick plays no bass.

A melody layer (#144, needs `--clock`) loops a few bars of chord tones (`melody`)
on channel 3 by default. At each bar line (`ClockAccess.on_bar`) the drums of the
bar that ended set the next bar: the hits its variation (below), their average
velocity its loudness and the hat hits a brightness CC (`melody.Follower`). Hits on
the layer pad and the melody pad do not count.

Both loops follow by variation (#158): the drums choose one of three complete lines
of the loop (`melody.melody_variation`, `bass.bass_variation`) and whether its
ornaments play, so a sparse bar never drops to a skeleton. Bars without drums
(without kicks, for the bass) follow `no-drums`: `lead` (default) plays the
melody's `open` line with ornaments and the bass's `home` line, `hold` keeps the
last choice, both at the last velocity until `fade-bars` empty bars (the last two
fade), and `thin` is #144's rule (the skeleton after one empty bar, silence after
two).

Controls (provisional preset controls, ADR 0004; defaults return when the preset is
built again): `bass loop|rule|off`, `bass-loop <name>`,
`progression <name>`, `progression-step 1|-1` (#236: the next or previous of
`progressions`, wrapping around), `octave 0-3`, `channel 1-16`, `role <pad 1-16> <role>`,
`layer-pad 0-16` (default 16: that pad cycles the bass loop, rule, off, and plays
no bass; 0 turns it off), for `rule` only `immediate 0|1`, `bar 0|1` and
`length 1-16`, and for the melody `melody 0|1`, `loop <name>`, `follow 0|1` (both
loops), `melody-octave 2-6`, `melody-channel 1-16`, `filter-cc 0-127` (0 is off)
and `melody-pad 0-16` (default 15: that pad cycles follow, fixed, off; follow and
fixed apply to both loops, off only to the melody), and `melody-mode
follow|fixed|off|still` (#153: `melody` and `follow` in one message; `still`, #233,
below), and `learn-cc` (#159,
no arguments: sends only the brightness CC on the melody channel, `LEARN_CC_SWEEP`
upwards and on the next call downwards, so a DAW in MIDI map mode learns the CC and
not a note; refused while the clock is `running` and when `filter-cc` is 0), and for
both loops `no-drums lead|hold|thin` and `fade-bars 0-32` (default 8, 0: never
stop; #158), and `surprise 0-2` (#158, #178: at the last bar of each 4-bar
phrase, with probability 1/2, a change the musician did not ask for, only in bars
that follow the drums or keep playing without them; 0 is off, 1, the default, only
the bass fill, 2 the bass fill, the melody an octave up or a passing note; seeded
with `Ensemble(seed=…)`, a fresh seed in each `make_preset`), and `rhythm 0-2`
(#189, default 1: 0 off, 1 the bass, 2 the bass and the melody). Bass mode and melody
changes apply from the next bar line (at once while the clock is not running);
`melody 0` and `melody-mode off` also drop the pending notes.

With `melody-mode still` (#233, also `melody still`; a setting for trials and
practice that pad 15 does not cycle to: from it a press goes on to `fixed`, and
`follow 0|1` ends it) the melody plays its `home` line every bar at
`FIXED_VELOCITY`, also without drums, and sends the brightness CC at
`STILL_BRIGHTNESS`, while the bass follows as in `follow`. Learning chooses no melody
variation (a like credits the bass only); with `learn demo` pad 15 does nothing
(`ensemble: pad 15 ignored, the melody is still`) and `want melody` is refused.
`chose` gives `still` for the melody.

State replies (`Preset.state`, ADR 0009, #153): `bass` and `melody-mode` give the
mode asked for (next) and the one playing, the other replies the current settings
(`Ensemble.state`). The preset asks the engine to send them again
(`ClockAccess.report()`) after a press of the layer pad or the melody pad, and at a
bar line where the playing bass or melody mode, a playing variation (the reply
`variation`, #158) or a playing transformation (the reply `transform`, #189)
changes.

The loops are loop files (#173, ADR 0010): the built-in ones (`boom`, `walk`, `keys`,
`pluck`, #232's hip-hop loops) live in `mpc_iml/loops/ensemble/` (as `CONTENT`), and installed
packages add more through the `mpc_iml.content` entry point group. A note's timing
`offset` moves it from its step by a fraction of a 16th, rounded to a clock tick; a
note cannot sound before the bar line its bar is planned at. Musicians' own loops
are read from `<data folder>/loops/*.json` (`Preset.data_folder`) when the preset
loads and on `reload-loops`; a bad file is skipped with a log line and counted in
the reply `loop-errors`. User progressions (#236) are read from
`<data folder>/progressions/*.json` at the same times and counted in
`progression-errors`. `bass-loop-step 1|-1` and `loop-step 1|-1` move to the
next or previous loop of the lists (built-in, installed, then user loops).

Rhythm transformation (#189, RFC 0005 step 6, `rhythm`): off by default
(`rhythm 0`, #194: in the manual check the moved bass sometimes sounded off the
beat in steady styles, where the bass's grid position is part of the skeleton).
With `rhythm 1` (a setting, not changed while playing) the bass's rhythm comes
from the kicks of the last bar. The variation the kicks chose keeps its notes and pitches,
and its onsets move to the kicks (`rhythm.lock`, `rhythm.answer`), the skeleton
and the approach notes staying put. The phrase shapes it (`rhythm.bass_stage`):
its first bar plays the line as written, the next two `lock`, the last `answer`,
where the surprise fill still takes the last beat. The kicks of the phrase are
remembered (`rhythm.Memory`): a bar close to them keeps their rhythm, and with
`no-drums hold` a bar without kicks answers it. Bars that do not follow, `thin`'s
skeleton and `rhythm 0` play the line as written. The plan of each bar
(`Ensemble.plans`) carries its `transform` and what it took (`rhythm.Taken`), the
reply `transform` gives both loops' transformation, and each phrase start logs the
motif (`ensemble: rhythm motif kick 0 6 10`).

With `rhythm 2` the melody follows too (`rhythm.backbeat`): in the same phrase
bars as the bass's `lock` and `answer`, its onsets move to the snares and hats of
the last bar (its own `rhythm.Memory`, the same rules for bars without them), and
each phrase start logs that motif too (`ensemble: rhythm motif snare 4 12 hat 0 2`).
The melody's surprises (`octave`, `passing`) apply to the moved notes.

Learning (#196, RFC 0005 step 8, `learn`): `learn off` (default) plays the rules
above, exactly as before #196. With `learn likes` (a setting, not changed while
playing; set the bass mode before playing) each loop's variation comes from its
`learn.Learner` instead of the rules, in a context of the last bar's drums
(`learn.context`), drawn from its own seeded generator (`Ensemble(seed=…)`), only in
bars that follow the drums (kicks, for the bass). Pad 16 (the layer pad) is then
**like** instead of cycling the bass mode, as is the control `like`: it credits both
loops' choices in the bar playing, or in the bar before when pressed in its first
beat (`learn.liked_bar`). Once per phrase the weights move back towards the rules
(`Learner.forget`), and the contexts whose top choice changed are logged
(`ensemble: learned bass push/beat>drive (rule push)`). The replies `learn`,
`likes` (credited likes in this build), `chose` (`rule` or `bandit` for each loop
in the bar playing, `-` when it is silent) and `learned` (up to 4
`<part>:<context>><arm>` that differ from the rules, `-` for none).

With `learn demo` the musician shows what they want (#196, `learn.Demonstrations`):
pads 16 (bass) and 15 (melody) choose the wanted variation instead of cycling the
modes (#215). In `auto` a press keeps the variation chosen for the bar playing (the
bar before in its first beat, `learn.liked_bar`; the rules' choice where the loop
is silent) and adds the example of the drums that bar answered; a further press
moves to the part's next variation, without `auto`. A pad's `want` goes back to
`auto` at the next phrase start, or the one after when fewer than `WANT_MIN_BARS`
complete bars are left (`ensemble: want bass push (kept) to bar 16`). The control
`want bass|melody <want>` sets a `want` that holds until it sends `auto`. A loop with a wanted
variation plays it in each bar that follows the drums, and each complete bar with
drums (kicks, for the bass) that wanted the same variation from its bar line to the
next adds an example (the bar's `learn.features` mapped to that variation); the
loop's decision tree is retrained at that bar line, after the next bar is planned
(`ensemble: trained bass tree, 9 examples`). With `auto` the loop plays the
tree's prediction. While it has fewer than `learn.MIN_EXAMPLES` examples or only
one variation among them, drums in a marked context (one with examples) play their
most common variation, and other drums the rules (#215; `ensemble: want bass auto
(phrase end), plays model (marked contexts, 1 label)`). `chose` then gives `want`, `model` or
`rule`, and the replies `want` (bass, melody) and `examples` (bass, melody) follow
`learned`.

With `learn likes` and `learn-loops 1` (#196 PR 5, default 0, a setting) the loops
are learned too (`learn.LoopLearner`): at each phrase start, in a bar that follows
the drums, each part draws the loop it plays in that phrase among its loops
(built-in, installed and user loops, and the selected one), starting from the
selected loop (`bass-loop`, `loop`, which do not change). The variation is still
drawn each bar. A like also credits the loop heard, by name; a user loop joins at
its starting weight on `reload-loops`, and one whose file is gone plays to the end
of its phrase and keeps its weights. Selecting a loop plays it from the next bar
line, until the next phrase start draws again. A phrase start that changes the loop logs it
(`ensemble: bass loop walk from bar 8 (selected boom)`), and the replies
`learn-loops` and `playing-loops` (bass, melody, `-` when silent) follow
`profile-errors`. With `learn-loops 0`, or `learn` not `likes`, the selected loops
play, as before.

What was learned is the profile (#196, `learn_profile`): the likes' weights, the
loops' weights and the examples in `<data folder>/learn/ensemble.json`, read when
the preset gets its data folder and on `load-profile`, written on `save-profile`
and, while `learn` is not `off`, at each phrase start. `reset-learning` goes back to
the rules in memory. A profile that cannot be read is logged, the reply
`profile-errors` (after `examples`) is 1, and the phrase starts do not overwrite it
until a `save-profile`.

With `learn-log 1` (#196 PR 4b, default 0, needs a data folder) each bar's context,
choice, its source, the rules' choice, likes, wants and examples are written to
`<data folder>/learn/log-<time>.jsonl` (`learn_log.BarLog`), in every `learn` mode
and without changing what plays; the file is created at the first bar (#217). Each
line also has the groove of the bar before (#245, `groove_record`).
`learn-log 0` writes the lines still waiting and closes it. The reply `learn-log`
follows `playing-loops`.

With `mode-pads 0` (#216, default 1, a setting) pads 15 and 16 switch neither the
melody mode nor the bass mode, in every `learn` mode, and send no reply: a trial's
condition then keeps the modes its settings give. Pad 16 is still a like with
`learn likes`, and pads 15 and 16 still set `want` with `learn demo`. The reply
`mode-pads` follows `learn-log`.

With `status 1` (#230, default 1, a setting) each bar line while the clock runs logs
a status line for the musician (`status_line`): the bar, its chord (#236), its
groove (#245), each loop's variation and where it came from (`chose`), and what pads
16 and 15 do now (`pad_action`), for example `ensemble: bar 12  Am7  groove 2 (bar
5)  bass drive (rule)  melody home (rule)  16: keep drive  15: keep home`; a press
of pad 16 or 15 while the clock runs logs it again. A press of pad 16 or 15 that
does nothing because the clock is not running logs `ensemble: pad 16 ignored, the
clock is not running`, also with `status 0`; the line names the pad, not the learn
mode, so a blind trial stays blind. `for_musician` tells these lines from the others
(`trial run` shows them). The reply `status` follows `mode-pads`.

At each bar line, after every choice, the bar before goes to a `grooves.Tracker`
(#245) when it is complete; an incomplete bar (after Start, or a lost clock) ends
the groove, and the grooves seen stay as long as the preset is loaded. The status
line shows the live decision after the chord (`groove_text`: `groove 2 (bar 5)`,
`fill`, `groove free`, or `groove -`), and so does the learn log.

The tracker runs before the choices (#250); it uses no random generator, so with
`follow-by bar` (the default, a setting) nothing that plays reads it. With
`follow-by groove` (#250, ADR 0009 "Amendment: learning by groove") the decision on
the bar before sets the bar that starts:

- after a **groove bar** the rules choose both loops' variation and level from the
  groove's prototype (`groove_choices`), so the variation holds while the groove
  holds; velocities, the brightness CC, `no-drums` and the rhythm transformation
  still come from the bar played;
- after a **fill bar** (also the first bar of a new groove, which is answered from
  the bar after its confirmation) the loops keep the groove's choice and the bass
  plays `bass.bass_fill` where it may carry a surprise (`BarPlan.surprise`), `chose`
  `fill`; that bar draws no surprise. With `answer-after 1` (default 2, a setting) a
  fill bar is answered by the per-bar rules instead, with no fill;
- after a free bar, before the first groove and without drums, the per-bar rules.

With `learn nod` (#250, ADR 0009 "The nod") pad 16 is the **nod** instead of cycling
the bass mode, as is the control `nod`. A nod refers to the bar `learn.liked_bar`
gives; at the bar line after that bar, when the tracker's decision on it is known,
`grooves.nods.nod_groove` gives the groove it counts for, and the bass variation
played in the bar it names is kept for that groove (`grooves.nods.NodMemory`; `ensemble:
nod bar 16 -> groove 2 (bar 8), bass push`, or why nothing was learned). From then on,
in a groove bar (the bar after one the tracker gave to a groove, not a fill; with
`follow-by groove` also the bar that answers a fill, which keeps its fill figure) that
follows the kicks the bass plays, in this order: the groove's nod (`chose` `nod`);
with `learn-group 1` (default 0, a setting) the nod of the nearest nodded groove
within `GROUP_DISTANCE`, drawn once per section with `GROUP_SHARE` (`group`); with
`new-groove invite` (default `rules`, a setting) a variation other than the rules'
one for the groove's prototype, drawn once per groove (`invite`); else the rules.
When the tracker confirms a groove with a nod, `ensemble: groove 2 back, bass push
(nod)` is logged. These lines are not `for_musician`. With `learn nod` the replies
`likes` and `learned` count the nods that kept a variation and list `bass:groove
<id>><variation>`. Only the bass learns. The nods are kept in the profile (format
version 2) and saved at each phrase start; a groove confirmed in a later session finds
its stored nod by its two starting bars (`ensemble: groove 2 back, bass push (nod from
profile)`). A version 1 profile (from `likes` and `demo`) is renamed once to
`learn/ensemble-v1.json` and the band starts with no nods. The learn log's line of a
nodded bar has its `nod` (`{"bar", "groove", "variation", "from"}`).

The replies `follow-by`, `learn-group`, `new-groove` and `answer-after` follow
`progression-errors`, and the learn log's header has these settings.

The catch (#290, `catch 0|1|2`, default 0, a setting): when the drummer leaves a
groove they held, the keys answer in the next bar with the rhythm the drummer just
played (`catch.answers`: the tracker's decision on the bar that just ended is a fill
of a groove, the `catch.CATCH_HOLD` bars before it bars of that groove, and it has
`catch.CATCH_MIN` hits on pads other than 15 and 16), with the clock running and the
melody following. The melody's notes of that bar are `catch.catch_notes`: the
rhythm of those hits (`catch.drummed`; with `catch 2`, the comparison for trials,
the steps of the next variation instead, `catch.written`), an accent on step 0 and
the pitches of the variation the melody would play. That bar draws no surprise,
the bass plays no fill (`follow-by groove`) and `rhythm 2` does not move the
melody. The melody's `chose` is `catch`, `ensemble: catch bar 12 answers bar 11,
steps 0 3 6 10` is logged, and the learn log's line has `catch` (`null`, or
`{"bar", "steps"}`). `catch 0` runs none of this. The reply `catch` follows
`answer-after`, and the learn log's header has it.
"""

import contextlib
import datetime
import random
import sys
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from mpc_iml import __version__
from mpc_iml.bass import (
    BASS_VARIATIONS,
    bass_fill,
    bass_note_velocity,
    bass_ornaments,
    bass_variation,
)
from mpc_iml.catch import answers as catch_answers
from mpc_iml.catch import catch_notes, drummed, written
from mpc_iml.clock import (
    SIXTEENTHS,
    TICKS_PER_BEAT,
    BarStart,
    ClockAccess,
    GridHit,
    PadHit,
    Scheduled,
)
from mpc_iml.content import Content
from mpc_iml.frames import PADS
from mpc_iml.grooves import Decision as GrooveDecision
from mpc_iml.grooves import Groove, Pattern, Tracker
from mpc_iml.grooves import pattern as groove_pattern
from mpc_iml.grooves.nods import Nod, NodMemory, nod_groove
from mpc_iml.learn import (
    CONTEXTS,
    PARTS,
    WANTS,
    Demonstrations,
    Example,
    Learner,
    LoopLearner,
    features,
    liked_bar,
    rule_choice,
)
from mpc_iml.learn import context as learn_context
from mpc_iml.learn_log import BarLog, log_path
from mpc_iml.learn_profile import (
    OLD_PROFILE,
    PROFILE,
    OldProfile,
    Profile,
    apply_profile,
    read_profile,
    write_profile,
)
from mpc_iml.loops import USER_FOLDER, LoopLibrary, load_loops, load_user_loops
from mpc_iml.melody import (
    BRIGHTNESS,
    NO_DRUMS,
    ORNAMENTS,
    PHRASE,
    BarPlan,
    Follower,
    Loop,
    LoopNote,
    brightness,
    loop_pitch,
    melody_ornaments,
    melody_variation,
    octave_up,
    passing,
    surprise,
)
from mpc_iml.presets import ControlHandler, Preset
from mpc_iml.progressions import (
    DEFAULT,
    Chord,
    Progression,
    load_progressions,
    load_user_progressions,
)
from mpc_iml.progressions import USER_FOLDER as PROGRESSION_FOLDER
from mpc_iml.rhythm import (
    MIN_HITS,
    Memory,
    Motif,
    Shaped,
    Taken,
    answer,
    backbeat,
    bass_stage,
    fixed_steps,
    lock,
    motif,
)

__all__ = [
    "ANSWER_AFTER",
    "BASS_MODES",
    "CONTENT",
    "DEFAULT_ROLES",
    "FOLLOW_BY",
    "LEARN_CC_SWEEP",
    "LEARN_MODES",
    "MELODY_MODES",
    "MELODY_SETTINGS",
    "NEW_GROOVE",
    "NO_CLOCK",
    "NOTE_SECONDS",
    "ROLES",
    "STATUS_PREFIX",
    "STILL_BRIGHTNESS",
    "WANT_MIN_BARS",
    "Chord",
    "Ensemble",
    "Progression",
    "bass_velocity",
    "for_musician",
    "groove_choices",
    "groove_record",
    "groove_text",
    "make_preset",
]

ROLES = ("kick", "snare", "hat", "other")

CONTENT = Content(preset="ensemble", root="mpc_iml")
"""The built-in loop and progression files for `ensemble` (ADR 0010, ADR 0011)."""

BASS_MODES = ("loop", "rule", "off")
"""The bass modes, in the order the layer pad cycles them; `loop` is the default."""

MELODY_MODES = ("follow", "fixed", "off")
"""The melody modes, in the order the melody pad cycles them; `follow` is the default."""

MELODY_SETTINGS = (*MELODY_MODES, "still")
"""The values of the control `melody-mode`: the modes and `still` (#233), a setting for
trials and practice that the melody pad does not cycle to (it goes on to `fixed`)."""

STILL_BRIGHTNESS = round(sum(BRIGHTNESS) / 2)
"""The brightness CC value `melody-mode still` sends at each bar line (#233): the middle
of `BRIGHTNESS`, so the melody keeps one colour."""

LEARN_MODES = ("off", "likes", "demo", "nod")
"""The learning modes (#196, #250); `off`, the rules, is the default."""

NEW_GROOVE = ("rules", "invite")
"""What the bass plays in a groove with no nod (`new-groove`, #250): the rules, or a
different variation drawn once per groove to invite a nod."""

KEPT_BARS = 4
"""How many bars of decisions, patterns and bass variations `learn nod` keeps (#250)."""

FOLLOW_BY = ("bar", "groove")
"""What the loops' variations follow (`follow-by`, #250): each bar, or the groove."""

ANSWER_AFTER = (1, 2)
"""After how many bars of a different pattern the bass answers it (`answer-after`,
#250): 2 waits for the tracker (a fill, or a new groove at its second bar)."""

LEARNED_REPLY = 4
"""At most this many contexts in the reply `learned`."""

WANT_MIN_BARS = 2
"""A `want` set by pad 16 or 15 (`learn demo`, #215) lasts to the next phrase start,
or to the one after it when fewer than this many complete bars would be left."""

STATUS_PREFIX = "ensemble: bar "
"""The start of a status line (`status 1`, #230)."""

IGNORED = " ignored, the clock is not running"
"""The end of the line of a press that does nothing without a running clock (#230)."""

IGNORED_STILL = " ignored, the melody is still"
"""The end of the line of a press of pad 15 that does nothing because the melody is
still (`learn demo`, #233)."""

NO_CLOCK = (
    "ensemble: no MIDI clock (start with --clock); bass loop, bar layer and melody off,"
    " bass plays on each kick"
)

DEFAULT_ROLES = ("kick", "snare", "hat", "hat") + ("kick", "snare", "hat", "other") + ("other",) * 8
"""Roles of pads 1-16 (pad 1 bottom left): kick on 1 and 5, snare on 2 and 6."""

NOTE_SECONDS = 0.25
"""Length of an immediate note without a running clock."""

STEPS_PER_BEAT = 4
"""The bass works on 16ths."""

LEARN_CC_SWEEP = (0, 32, 64, 96, 127)
"""The values `learn-cc` sends, upwards; the next call sends them downwards (as the
engine's `/mpciml/midi/learn`, ADR 0005)."""


def for_musician(line: str) -> bool:
    """Whether `line` of the ensemble's log is for the musician while playing (#230):
    a status line or an ignored press."""
    return line.startswith(STATUS_PREFIX) or (
        line.startswith("ensemble: ") and line.endswith((IGNORED, IGNORED_STILL))
    )


def groove_text(decision: GrooveDecision | None) -> str:
    """The groove field of the status line (#245): `groove <id> (bar <position>)`,
    `fill`, `groove free`, or `groove -` (no groove yet, no drums, the clock not
    running)."""
    if decision is None:
        return "groove -"
    if decision.fill:
        return "fill"
    if decision.free:
        return "groove free"
    if decision.groove is None:
        return "groove -"
    return f"groove {decision.groove} (bar {decision.position})"


def groove_record(decision: GrooveDecision | None) -> dict[str, object]:
    """The `groove` field of a learn log line (#245): the live decision on the bar
    before, `id` and `position` `null` outside a groove."""
    if decision is None:
        return {"id": None, "position": None, "fill": False, "free": False}
    return {
        "id": decision.groove,
        "position": decision.position,
        "fill": decision.fill,
        "free": decision.free,
    }


def groove_choices(p: Pattern) -> tuple[tuple[str, int], tuple[str, int]]:
    """The rules' bass and melody choices (variation, level) for a groove's prototype
    `p` (#250): the same rules as for a bar, reading the prototype's kicks, its kick,
    snare and hat hits, and its hats."""
    kicks = sorted(p.kick)
    hits = len(p.kick) + len(p.snare) + len(p.hat)
    return (
        (bass_variation(kicks), bass_ornaments(len(kicks))),
        (melody_variation(hits, sorted(p.hat)), melody_ornaments(hits)),
    )


def bass_velocity(velocity: int) -> int:
    """A kick velocity 1-127 mapped linearly to 50-120."""
    return round(50 + (min(max(velocity, 1), 127) - 1) * 70 / 126)


class _Timer(Protocol):
    def start(self) -> None: ...
    def cancel(self) -> None: ...


TimerFactory = Callable[[float, Callable[[], None]], _Timer]


@dataclass
class _Echo:
    tick: int
    note: int
    off_tick: int
    on: Scheduled
    off: Scheduled


class Ensemble:
    """The settings and bass state of one build of `ensemble`.

    `attach` is the preset's clock hook and `controls` its controls. Pad hits arrive
    on the engine's input thread, controls on the OSC thread and timers on their
    own, so the state is guarded by a lock.
    """

    def __init__(
        self,
        log: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
        timer: TimerFactory = threading.Timer,
        seed: int | None = None,
        library: LoopLibrary | None = None,
        progressions: Mapping[str, Progression] | None = None,
    ) -> None:
        self._library = load_loops() if library is None else library
        self._progressions = dict(load_progressions() if progressions is None else progressions)
        self.progressions = dict(self._progressions)
        """The progressions by name: built-in, installed, then user ones (#236, ADR 0011)."""
        self.progression_errors = 0
        """How many user progression files were skipped at the last read (#236)."""
        self._folder: Path | None = None
        self.loop_errors = 0
        """How many user loop files were skipped at the last read (#173)."""
        self.bass_loops = self._library.played("bass")
        """The bass loops by name, in library order (#173)."""
        self.loops = self._library.played("melody")
        """The melody loops by name, in library order (#173)."""
        self.bass = "loop"
        self._bass_active = "loop"
        self.bass_loop = self.bass_loops["boom"]
        self._bass_follower = Follower(("home", 1))
        self._bass_notes: list[Scheduled] = []
        self.immediate = True
        self.bar = True
        self.progression = self.progressions[DEFAULT]
        self.octave = 1
        self.length = 2
        self.channel = 2
        self.roles = list(DEFAULT_ROLES)
        self.layer_pad = 16
        self.melody = True
        self.loop = self.loops["keys"]
        self.follow = True
        self.still = False
        """The melody plays `home` while the bass follows (`melody-mode still`, #233)."""
        self.melody_octave = 4
        self.melody_channel = 3
        self.filter_cc = 74
        self.melody_pad = 15
        self.mode_pads = True
        """Pads 15 and 16 switch the modes (`mode-pads`, #216)."""
        self.status = True
        """Log a status line at each bar line (`status`, #230)."""
        self._learn_down = False
        self._melody_playing = "follow"
        self._follower = Follower(("open", ORNAMENTS))
        self.no_drums = "lead"
        self.fade_bars = 8
        self.surprise = 1
        self.rhythm = 0
        self._memory = Memory()
        self._melody_memory = Memory()
        self._transforms = ("-", "-")
        self._random = random.Random(seed)
        self._seed = seed
        self._bar_log: BarLog | None = None
        """The per-bar log while `learn-log 1` (#196 PR 4b)."""
        self._grooves = Tracker()
        """Follows the drummer's grooves (#245); it changes nothing that plays."""
        self._groove: GrooveDecision | None = None
        """The tracker's decision on the bar before the last bar line, if any."""
        self.follow_by = "bar"
        """Whether the variations follow each bar or the groove (`follow-by`, #250)."""
        self.answer_after = 2
        """`answer-after` (#250): with 1 a fill bar is answered by the per-bar rules."""
        self.learn_group = False
        """`learn-group` (#250): a groove with no nod may play the nod of its group."""
        self.new_groove = "rules"
        """`new-groove` (#250): what a groove with no nod plays with `learn nod`."""
        self.catch = 0
        """`catch` (#290): 1 the keys answer a groove's fill, 2 the comparison."""
        self._caught: dict[str, object] | None = None
        """The catch of the bar that started at the last bar line (`{"bar", "steps"}`)."""
        self._nods = NodMemory(seed=seed)
        """The nods kept (`learn nod`, #250)."""
        self._invite_random = random.Random(None if seed is None else f"invite {seed}")
        self._invites: dict[int, str] = {}
        """Groove id -> the variation drawn to invite a nod (`new-groove invite`)."""
        self._sections: dict[tuple[int, int], Nod | None] = {}
        """(groove id, section start) -> the group's nod drawn for that section, or
        `None` when the draw gave nothing (`learn-group 1`)."""
        self._decisions: dict[int, GrooveDecision] = {}
        """Bar -> the tracker's decision on it, the last `KEPT_BARS` bars."""
        self._patterns: dict[int, Pattern] = {}
        """Bar -> its groove pattern, the last `KEPT_BARS` bars."""
        self._bass_played: dict[int, str] = {}
        """Bar -> the bass variation played in it (`-`: none), the last `KEPT_BARS`."""
        self._nodded: set[int] = set()
        """Nodded bars whose decision is not known yet."""
        self._bar_line = -1
        """The bar that started at the last bar line."""
        self.learn = "off"
        self.likes = 0
        """Likes that credited a choice, in this build (#196)."""
        learn_seed = None if seed is None else f"learn {seed}"
        self._learners = {p: Learner(p, random.Random(learn_seed)) for p in PARTS}
        self._heard: dict[int, dict[str, tuple[str, str, str]]] = {}
        """Bar -> part -> (context, arm, loop) the learners chose for it, the last few
        bars; the loop is `""` unless `learn-loops`."""
        self._tops = {p: {c: self._learners[p].top(c) for c in CONTEXTS[p]} for p in PARTS}
        """The top arm of each context at the last `learned` log."""
        self._demos = {p: Demonstrations(p) for p in PARTS}
        self.learn_loops = False
        """Whether `learn likes` also chooses the loop at each phrase start (#196 PR 5)."""
        loops_seed = None if seed is None else f"learn-loops {seed}"
        self._loop_learners = {p: LoopLearner(p, random.Random(loops_seed)) for p in PARTS}
        self._chosen: dict[str, Loop | None] = {p: None for p in PARTS}
        """The loop the loop learner chose for each part in this phrase, if any."""
        self._loop_names = ("-", "-")
        self.wants = {p: "auto" for p in PARTS}
        """The variation the musician wants for each part with `learn demo` (#196)."""
        self._bar_wants: dict[str, str] | None = None
        """`wants` at the last bar line: what the bar playing was planned with."""
        self._want_ends: dict[str, int | None] = {p: None for p in PARTS}
        """The bar line where a pad's `want` goes back to `auto` (#215); `None` while
        the part is in `auto` or its `want` came from the control."""
        self._answers: dict[int, dict[str, tuple[tuple[float, ...], str, bool]]] = {}
        """Bar -> part -> (features of the drums it answers, the variation chosen
        for it, whether the part plays it), the last few bars (#215)."""
        self._profile: Path | None = None
        self._data: Path | None = None
        """The engine's data folder (`Preset.data_folder`)."""
        self.profile_errors = 0
        """1 when the profile could not be read at the last try, else 0 (#196)."""
        self._autosave = True
        """False after a bad profile, so a phrase start does not overwrite it."""
        self._chose = ("-", "-")
        self._variations = ("-", "-")
        self._plans: dict[str, BarPlan | None] = {"bass": None, "melody": None}
        self._melody_notes: list[Scheduled] = []
        self._log = log
        self._timer = timer
        self._lock = threading.RLock()
        self._access: ClockAccess | None = None
        self._off: bytes | None = None
        self._off_handle: Scheduled | _Timer | None = None
        self._echoes: list[_Echo] = []

    @property
    def plans(self) -> dict[str, BarPlan | None]:
        """The plans of the bar that started at the last bar line, for `bass` and
        `melody` (read-only, a copy; #166): what each loop plays in it, `None` when
        it does not play (no running clock, the bass not in `loop`, the melody off).
        Not an OSC reply; the web demo reads it to show what the rules chose."""
        with self._lock:
            return dict(self._plans)

    def attach(self, access: ClockAccess) -> None:
        """The `Preset.clock` hook: listen to every pad hit."""
        self._access = access
        access.on_pad(self.on_pad)
        access.on_bar(self.on_bar)
        if access.scheduler is None:
            self._log(NO_CLOCK)

    def on_pad(self, hit: PadHit) -> None:
        if self._on_pad(hit):
            self._report()

    def _on_pad(self, hit: PadHit) -> bool:
        """Handle a pad hit; `True` when it changed a mode, to report."""
        with self._lock:
            pads = {p for p in (self.layer_pad, self.melody_pad) if p}
            if hit.pad + 1 not in pads:
                self._bass_hit(hit)
                return False
            stopped = hit.grid is None or hit.grid.bar < 0
            if stopped and not self._switches(hit.pad + 1):
                self._log(f"ensemble: pad {hit.pad + 1}{IGNORED}")
                return False
            changed = self._mode_pad(hit)
            if self.status and not stopped:
                assert hit.grid is not None
                self._log(self.status_line(hit.grid.bar))
            return changed

    def _switches(self, pad: int) -> bool:
        """Whether a press of `pad` (16 or 15) switches a mode now (`learn off`, or
        pad 15 with `learn likes`, while `mode-pads 1`): the only press that does
        something while the clock is not running."""
        if pad == self.layer_pad:
            return self.learn == "off" and self.mode_pads
        return self.learn != "demo" and self.mode_pads

    def pad_action(self, pad: int) -> str:
        """What a press of `pad` (16 or 15) does now, for the status line (#230):
        `bass rule` (the mode it switches to), `like`, `keep <variation>`,
        `next <variation>` or `-` (nothing)."""
        with self._lock:
            part = "bass" if pad == self.layer_pad else "melody"
            if part == "melody" and self.learn == "demo" and self._still():
                return "-"
            if self.learn == "demo":
                want = self.wants[part]
                if want == "auto":
                    return f"keep {self._keeps(part)}"
                arms = WANTS[part][1:]
                return f"next {arms[(arms.index(want) + 1) % len(arms)]}"
            if part == "bass" and self.learn == "likes":
                return "like"
            if part == "bass" and self.learn == "nod":
                return "nod"
            if not self.mode_pads:
                return "-"
            if part == "bass":
                return f"bass {BASS_MODES[(BASS_MODES.index(self.bass) + 1) % len(BASS_MODES)]}"
            mode = "follow" if self._still() else self._melody_mode()
            return f"melody {MELODY_MODES[(MELODY_MODES.index(mode) + 1) % len(MELODY_MODES)]}"

    def _keeps(self, part: str) -> str:
        """The variation a press in `auto` keeps (after the first beat): the one
        chosen for the bar playing, the rules' where the loop is silent (#215)."""
        answers = self._answers.get(max(self._answers, default=0), {})
        return answers.get(part, ((), "", False))[1] or WANTS[part][1]

    def status_line(self, bar: int) -> str:
        """The status line of `bar` (#230): its chord (#236), each loop's variation
        and its source (`chose`), and what pads 16 and 15 do now."""
        with self._lock:
            parts = []
            for i, part in enumerate(PARTS):
                variation, source = self._variations[i], self._chose[i]
                parts.append(f"{part} {variation}" + ("" if variation == "-" else f" ({source})"))
            pads = [f"{p}: {self.pad_action(p)}" for p in (self.layer_pad, self.melody_pad) if p]
            chord = self.progression.chord_name(bar)
            groove = groove_text(self._groove)
            return "  ".join([f"{STATUS_PREFIX}{bar}", chord, groove, *parts, *pads])

    def _mode_pad(self, hit: PadHit) -> bool:
        """Pad 16 or 15: like, want or switch a mode; `True` when it did, to report."""
        with self._lock:
            if self.layer_pad and hit.pad == self.layer_pad - 1:
                if self.learn == "likes":
                    grid = hit.grid
                    self._like(None if grid is None else (grid.bar, grid.step))
                elif self.learn == "nod":
                    grid = hit.grid
                    self._nod(None if grid is None else (grid.bar, grid.step))
                elif self.learn == "demo":
                    self._pad_want("bass", hit.grid)
                elif self.mode_pads:
                    self._cycle()
                else:
                    return False
                return True
            if self.learn == "demo" and self._still():
                self._log(f"ensemble: pad {self.melody_pad}{IGNORED_STILL}")
                return False
            if self.learn == "demo":
                self._pad_want("melody", hit.grid)
            elif self.mode_pads:
                self._cycle_melody()
            else:
                return False
            return True

    def _bass_hit(self, hit: PadHit) -> None:
        """The bass of a pad hit (`rule`, or `loop` without a running clock)."""
        with self._lock:
            if self.roles[hit.pad] != "kick" or self._access is None:
                return
            scheduler = self._access.scheduler
            rule = self._bass_active == "rule"
            fallback = self._bass_active == "loop" and scheduler is None
            if not (rule or fallback):
                return
            grid = hit.grid if hit.grid is not None and hit.grid.bar >= 0 else None
            velocity = bass_velocity(hit.velocity)
            if grid is not None and rule and self.bar and scheduler is not None:
                self._echo(grid.bar + 1, grid.step, velocity)
            if self.immediate or fallback:
                bar, step = (grid.bar, grid.step) if grid is not None else (0, None)
                self._play(bar, step, velocity)

    def on_bar(self, start: BarStart) -> None:
        """Plan the bass loop and the melody of the bar that starts now from the drums
        of the last one; report when the playing bass or melody mode, a playing
        variation or a playing transformation changes."""
        with self._lock:
            playing = self._playing()
            self._plan(start)
            self._melody_playing = self._melody_mode()
            changed = playing != self._playing()
            if self.status and start.bar >= 0 and self._running():
                self._log(self.status_line(start.bar))
        if changed:
            self._report()

    def _playing(self) -> tuple[object, ...]:
        """What a bar line reports when it changes: the playing modes, variations and
        transformations."""
        learned = tuple(self._learned())
        return (
            self._bass_active,
            self._melody_playing,
            self._variations,
            self._transforms,
            self._chose,
            learned,
            tuple(self.wants.values()),
            tuple(len(d.examples) for d in self._demos.values()),
            self._loop_names if self.learn_loops else (),
        )

    def _report(self) -> None:
        """Ask the engine to send the state again (outside the lock, ADR 0009)."""
        if self._access is not None:
            self._access.report()

    def _plan(self, start: BarStart) -> None:
        with self._lock:
            self._apply_bass()
            skip = {p - 1 for p in (self.layer_pad, self.melody_pad) if p}
            drums = [h for h in start.hits if h.pad not in skip]
            kicks = [h for h in drums if self.roles[h.pad] == "kick"]
            hats = [h.step for h in drums if self.roles[h.pad] == "hat"]
            self._track_groove(start, drums)
            if self.learn == "nod":
                self._resolve_nods(start.bar)
                self._groove_back()
            answer = self._groove_answer()
            if answer is None:
                bass_choice = (bass_variation([h.step for h in kicks]), bass_ornaments(len(kicks)))
                melody_choice = (melody_variation(len(drums), hats), melody_ornaments(len(drums)))
            else:
                bass_choice, melody_choice = groove_choices(self._prototype())
            rules = {"bass": bass_choice[0], "melody": melody_choice[0]}
            plays = self._follows(drums, bool(kicks))
            ended = self._end_wants(start.bar)
            chose, source = self._choose(start.bar, drums, plays)
            learned = self._groove_learned(answer, plays)
            if learned is not None:
                bass_choice = (learned[0], bass_choice[1])
                source = {**source, "bass": learned[1]}
            if "bass" in chose:
                bass_choice = (chose["bass"], bass_choice[1])
            if "melody" in chose:
                melody_choice = (chose["melody"], melody_choice[1])
            bass_plan = self._bass_follower.plan_bar(
                [h.velocity for h in kicks],
                bass_choice,
                None,
                start.complete,
                self.follow,
                self.no_drums,
                self.fade_bars,
            )
            melody_plan = self._follower.plan_bar(
                [h.velocity for h in drums],
                melody_choice,
                brightness(len(hats)),
                start.complete,
                self._melody_follows(),
                self.no_drums,
                self.fade_bars,
            )
            if self._still():
                melody_plan = replace(melody_plan, cc=STILL_BRIGHTNESS)
            caught = bool(self.catch) and self._catches(start, melody_plan)
            fill = answer == "fill" and bass_plan.surprise and "bass" not in chose and not caught
            # A fill answer or a catch is the bar's change: it draws no surprise (#250, #290).
            extra = (
                None
                if answer == "fill" or caught
                else self._surprise(start.bar, bass_plan, melody_plan)
            )
            heard = motif(drums, self.roles)
            bass = self._plan_bass(start, bass_plan, kicks, heard, fill or extra == "fill")
            if fill and bass != "-":
                source = {**source, "bass": "fill"}
            melody = self._plan_melody(start, melody_plan, heard, extra, caught)
            if caught and melody != "-":
                source = {**source, "melody": "catch"}
            self._variations = (bass, melody)
            self._bar_line = start.bar
            self._bass_played[start.bar] = bass
            self._loop_names = (
                "-" if bass == "-" else self._playing_loop("bass").name,
                "-" if melody == "-" else self._playing_loop("melody").name,
            )
            self._chose = (
                "-" if bass == "-" else source.get("bass", "rule"),
                "-"
                if melody == "-"
                else "still"
                if self._still()
                else source.get("melody", "rule"),
            )
            self._transforms = (
                self._transform_of(self._plans["bass"]),
                self._transform_of(self._plans["melody"]),
            )
            if self.learn == "demo" and start.complete:
                self._demonstrate(start.bar, drums, plays, ended)
            if self.learn == "demo":
                self._answers = {b: a for b, a in self._answers.items() if b >= start.bar - 2}
                self._answers[start.bar] = {
                    "bass": (
                        tuple(features("bass", drums, self.roles)),
                        bass_choice[0],
                        "bass" in plays,
                    ),
                    "melody": (
                        tuple(features("melody", drums, self.roles)),
                        melody_choice[0],
                        "melody" in plays,
                    ),
                }
            self._bar_wants = dict(self.wants)
            if self._bar_log is not None:
                self._log_bar(start, drums, rules)
            if self.learn != "off" and start.bar > 0 and start.bar % PHRASE == 0:
                self._autosave_profile()

    def _track_groove(self, start: BarStart, drums: Sequence[GridHit]) -> None:
        """The groove of the bar before (#245), before the choices (#250; it draws no
        random numbers): a complete bar goes to the tracker; an incomplete one
        (Start, lost) ends the groove."""

        # Keep the last bars; after a Stop and Start the bars may count from 0 again.
        def kept(b: int) -> bool:
            return start.bar - KEPT_BARS < b < start.bar

        self._decisions = {b: d for b, d in self._decisions.items() if kept(b)}
        self._patterns = {b: p for b, p in self._patterns.items() if kept(b)}
        self._bass_played = {b: v for b, v in self._bass_played.items() if kept(b)}
        if start.complete and start.bar >= 1:
            p = groove_pattern(drums, self.roles)
            self._groove = self._grooves.observe(start.bar - 1, p)
            self._decisions[start.bar - 1] = self._groove
            self._patterns[start.bar - 1] = p
        else:
            self._grooves.stop()
            self._groove = None

    def _catches(self, start: BarStart, plan: BarPlan) -> bool:
        """Whether the melody plays a catch in the bar that starts now (#290): with the
        clock running and the melody on and following a playing variation, after a
        bar that left a groove held for `catch.CATCH_HOLD` bars."""
        if self._access is None or self._access.scheduler is None:
            return False
        if not self.melody or not self._melody_follows():
            return False
        if plan.variation is None or plan.skeleton:
            return False
        before = [self._decisions.get(start.bar - i) for i in (2, 3)]
        return catch_answers(self._groove, before, start.hits)

    def _groove_answer(self) -> str | None:
        """How the bar that starts now answers the groove with `follow-by groove`
        (#250): `groove` after a groove bar, `fill` after a fill bar (`answer-after
        2`), `None` for the per-bar rules (`follow-by bar`, free, no groove yet, no
        drums, or a fill bar with `answer-after 1`)."""
        decision = self._groove
        if self.follow_by != "groove" or decision is None or decision.groove is None:
            return None
        if not decision.fill:
            return "groove"
        return "fill" if self.answer_after == 2 else None

    def _prototype(self) -> Pattern:
        """The prototype of the groove of the last decision (#245)."""
        decision = self._groove
        assert decision is not None and decision.groove is not None
        return self._groove_of(decision.groove).prototype

    def _groove_of(self, groove: int) -> Groove:
        """The tracker's groove `groove` now (#245)."""
        return next(g for g in self._grooves.grooves if g.id == groove)

    def _nod(self, at: tuple[int, int] | None) -> None:
        """A nod at (bar, step) of the clock (`None`: not running), `learn nod` (#250):
        it refers to the bar `learn.liked_bar` gives, and is resolved at once when the
        tracker's decision on that bar is known, else at the bar line after it."""
        if at is None:
            self._log(f"ensemble: pad {self.layer_pad}{IGNORED}")
            return
        bar = liked_bar(*at)
        if bar < self._bar_line:
            self._resolve_nod(bar)
        else:
            self._nodded.add(bar)

    def _resolve_nods(self, bar: int) -> None:
        """At the bar line `bar`: resolve the nods on the bars before it."""
        for nodded in sorted(b for b in self._nodded if b < bar):
            self._nodded.discard(nodded)
            self._resolve_nod(nodded)

    def _resolve_nod(self, bar: int) -> None:
        """The nod on `bar`: the groove it counts for (`nods.nod_groove`) keeps the
        bass variation played in the bar learned, and plays it from the next bar line
        in its groove bars."""
        target = nod_groove(bar, self._decisions.get(bar), self._decisions.get(bar - 1))
        variation = None
        if target.learn_bar is not None:
            variation = self._bass_played.get(target.learn_bar, "-")
        if self._bar_log is not None:
            kept = None if variation == "-" else variation
            self._bar_log.nod(bar, target.groove, kept, target.from_)
        if target.groove is None or variation is None:
            self._log(f"ensemble: nod bar {bar}, no groove to count for")
            return
        if variation == "-":
            self._log(f"ensemble: nod bar {bar}, no bass to keep")
            return
        groove = self._groove_of(target.groove)
        self._nods.nod(
            target.groove,
            groove.prototype,
            groove.features,
            variation,
            self._playing_loop("bass").name,
            datetime.date.today().isoformat(),
        )
        self.likes += 1
        if target.from_ == "bar":
            decision = self._decisions[bar]
            where = f"bar {bar} -> groove {target.groove} (bar {decision.position})"
        else:
            where = f"bar {bar} (fill) -> groove {target.groove} (ended bar {target.ended})"
        self._log(f"ensemble: nod {where}, bass {variation}")

    def _groove_back(self) -> None:
        """When the tracker confirms a groove that has a nod (in this session, or a
        stored one its two starting bars match), log that the bass plays it."""
        decision = self._groove
        if decision is None or not decision.new or decision.groove is None:
            return
        assert decision.start is not None
        first = self._patterns.get(decision.start)
        second = self._patterns.get(decision.bar)
        had = self._nods.bound(decision.groove) is not None
        if had or first is None or second is None:
            nod = self._nods.bound(decision.groove)
        else:
            nod = self._nods.match(decision.groove, first, second)
        if nod is not None:
            how = "nod" if had else "nod from profile"
            self._log(f"ensemble: groove {decision.groove} back, bass {nod.variation} ({how})")

    def _groove_learned(self, answer: str | None, plays: set[str]) -> tuple[str, str] | None:
        """The bass variation and its source in a groove bar with `learn nod` (#250),
        in this order: the groove's `nod`, its `group`'s nod (`learn-group 1`), an
        `invite` (`new-groove invite`); `None` for the rules. A groove bar is the bar
        after one the tracker gave to a groove; with `follow-by groove` also the bar
        after a fill bar it answers with a fill (`answer`)."""
        decision = self._groove
        if self.learn != "nod" or "bass" not in plays or decision is None:
            return None
        if decision.groove is None or (decision.fill and answer != "fill"):
            return None
        groove = decision.groove
        variation = self._nods.variation(groove)
        if variation is not None:
            return variation, "nod"
        if self.learn_group:
            assert decision.start is not None
            nod = self._group_nod(groove, decision.start)
            if nod is not None:
                return nod.variation, "group"
        if self.new_groove == "invite":
            return self._invite(groove), "invite"
        return None

    def _group_nod(self, groove: int, start: int) -> Nod | None:
        """The nod of the group of `groove` this section plays, drawn once per section
        (`nods.NodMemory.group`, `GROUP_SHARE`)."""
        key = (groove, start)
        if key not in self._sections:
            self._sections = {k: v for k, v in self._sections.items() if k[0] != groove}
            nod = self._nods.group(groove, self._groove_of(groove).prototype)
            drawn = nod if nod is not None and self._nods.draw(nod) else None
            self._sections[key] = drawn
            if nod is not None:
                of = self._nods.groove_of(nod)
                name = "a stored nod" if of is None else str(of)
                if drawn is not None:
                    self._log(
                        f"ensemble: groove {groove} group of {name}, bass {nod.variation} (group)"
                    )
                else:
                    fallback = "invite" if self.new_groove == "invite" else "rules"
                    self._log(f"ensemble: groove {groove} group of {name}, {fallback} (group draw)")
        return self._sections[key]

    def _invite(self, groove: int) -> str:
        """The variation that invites a nod in `groove`: drawn once per groove among the
        bass variations other than the rules' for its prototype (`new-groove invite`)."""
        if groove not in self._invites:
            (rule, _), _ = groove_choices(self._groove_of(groove).prototype)
            others = [v for v in BASS_VARIATIONS if v != rule]
            self._invites[groove] = self._invite_random.choice(others)
            self._log(f"ensemble: groove {groove} new, bass {self._invites[groove]} (invite)")
        return self._invites[groove]

    def _log_bar(self, start: BarStart, drums: Sequence[GridHit], rules: dict[str, str]) -> None:
        """Add the bar that starts now to the per-bar log (`learn_log`)."""
        assert self._bar_log is not None
        choice: dict[str, dict[str, object] | None] = {}
        for i, part in enumerate(PARTS):
            plan = self._plans[part]
            playing = plan is not None and plan.variation is not None
            choice[part] = (
                {"loop": self._loop_names[i], "variation": plan.variation, "level": plan.level}
                if plan is not None and playing
                else None
            )
        record = {
            "bar": start.bar,
            "t": start.state.t_tick,
            "learn": self.learn,
            "context": {p: learn_context(p, drums, self.roles) for p in PARTS},
            "choice": choice,
            "source": dict(zip(PARTS, self._chose, strict=True)),
            "rule": rules,
            "want": dict(self.wants),
            "groove": groove_record(self._groove),
            "catch": self._caught,
        }
        try:
            self._bar_log.bar(record)
        except OSError as error:
            self._log(f"ensemble: stopped the learn log: {error}")
            self._close_log()

    def _follows(self, drums: Sequence[GridHit], kicks: bool) -> set[str]:
        """The loops whose next bar follows the drums of the last one: with a running
        clock and `follow`, the bass in `loop` after kicks, the melody after drums."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is None or not self.follow:
            return set()
        plays = {
            "bass": self._bass_active == "loop" and kicks,
            "melody": self.melody and not self.still and bool(drums),
        }
        return {part for part in PARTS if plays[part]}

    def _choose(
        self, bar: int, drums: Sequence[GridHit], plays: set[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """The learned variation of each loop in `plays` (the loops that follow the
        drums of the last bar in `bar`), and where it came from (`chose`); none with
        `learn off`, the rules for the others (#196)."""
        if not self._learning_loops():
            self._chosen = {p: None for p in PARTS}
        if self.learn == "demo":
            return self._choose_demo(drums, plays)
        if self.learn != "likes":
            return {}, {}
        if bar % PHRASE == 0:
            for learner in self._learners.values():
                learner.forget()
            if self.learn_loops:
                for loop_learner in self._loop_learners.values():
                    loop_learner.forget()
            self._log_learned()
        heard: dict[str, tuple[str, str, str]] = {}
        for part in PARTS:
            if part in plays:
                context = learn_context(part, drums, self.roles)
                if self.learn_loops and bar % PHRASE == 0:
                    self._choose_loop(part, context, bar)
                loop = self._playing_loop(part).name if self.learn_loops else ""
                heard[part] = (context, self._learners[part].choose(context), loop)
        self._heard = {b: h for b, h in self._heard.items() if b >= bar - 2}
        self._heard[bar] = heard
        return {part: arm for part, (_, arm, _) in heard.items()}, {p: "bandit" for p in heard}

    def _learning_loops(self) -> bool:
        """Whether the loop learners choose the loops (`learn likes`, `learn-loops 1`)."""
        return self.learn == "likes" and self.learn_loops

    def _selected(self, part: str) -> Loop:
        """The loop the musician selected for `part` (`bass-loop`, `loop`)."""
        return self.bass_loop if part == "bass" else self.loop

    def _playing_loop(self, part: str) -> Loop:
        """The loop `part` plays: the loop learner's choice for this phrase while
        learning loops, else the selected one."""
        chosen = self._chosen[part]
        return chosen if chosen is not None and self._learning_loops() else self._selected(part)

    def _choose_loop(self, part: str, context: str, bar: int) -> None:
        """At the phrase start `bar`: draw the loop `part` plays in this phrase among
        its listed loops and the selected one (#196 PR 5)."""
        selected = self._selected(part)
        loops = dict(self.bass_loops if part == "bass" else self.loops)
        loops.setdefault(selected.name, selected)
        before = self._playing_loop(part).name
        name = self._loop_learners[part].choose(context, list(loops), selected.name)
        self._chosen[part] = loops[name]
        if name != before:
            self._log(f"ensemble: {part} loop {name} from bar {bar} (selected {selected.name})")

    def _choose_demo(
        self, drums: Sequence[GridHit], plays: set[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """With `learn demo`: the wanted variation, else the model's prediction or,
        before a model is trained, the marked context's variation (#215)."""
        chose: dict[str, str] = {}
        source: dict[str, str] = {}
        for part in PARTS:
            if part not in plays:
                continue
            if self.wants[part] != "auto":
                chose[part], source[part] = self.wants[part], "want"
                continue
            predicted = self._demos[part].choose(features(part, drums, self.roles))
            if predicted is not None:
                chose[part], source[part] = predicted, "model"
        return chose, source

    def _demonstrate(
        self, bar: int, drums: Sequence[GridHit], plays: set[str], ended: set[str]
    ) -> None:
        """The complete bar before `bar`, with the drums `drums` that the loops in
        `plays` follow: an example for each loop that wanted a variation all through
        that bar (from its bar line to this one; a `want` that ended by itself at
        this bar line, `ended`, still counts), then retrain its model."""
        for part in PARTS:
            want = self._bar_wants[part] if self._bar_wants else "auto"
            changed = want != self.wants[part] and part not in ended
            if part not in plays or want == "auto" or changed:
                continue
            self._add_example(part, tuple(features(part, drums, self.roles)), want, bar - 1)

    def _add_example(self, part: str, values: tuple[float, ...], want: str, bar: int) -> None:
        """Add the example of the drums of `bar` mapped to `want`, then retrain."""
        demos = self._demos[part]
        demos.add(Example(part, values, want, bar))
        if self._bar_log is not None:
            self._bar_log.example(bar, part, want)
        if demos.train():
            self._log(f"ensemble: trained {part} tree, {len(demos.examples)} examples")

    def _pad_want(self, part: str, grid: GridHit | None) -> None:
        """Pad 16 (bass) or 15 (melody) with `learn demo` (#215): in `auto`, keep
        the variation playing (in the first beat, the bar before's) and add the
        example of the drums it answers; else the part's next variation, from the
        next bar line. Either way the `want` lasts to the end of the phrase
        (`WANT_MIN_BARS`)."""
        if grid is None or grid.bar < 0:
            self._log(
                f"ensemble: pad {self.layer_pad if part == 'bass' else self.melody_pad}{IGNORED}"
            )
            return
        end = (grid.bar // PHRASE + 1) * PHRASE
        if end - grid.bar - 1 < WANT_MIN_BARS:
            end += PHRASE
        self._want_ends[part] = end
        if self.wants[part] == "auto":
            bar = liked_bar(grid.bar, grid.step)
            values, variation, played = self._answers.get(bar, {}).get(part, ((), "", False))
            self.wants[part] = variation or WANTS[part][1]
            if played:
                self._add_example(part, values, variation, bar - 1)
            how = "kept" if played else "kept, rules"
        else:
            arms = WANTS[part][1:]
            self.wants[part] = arms[(arms.index(self.wants[part]) + 1) % len(arms)]
            how = "next"
        self._log(f"ensemble: want {part} {self.wants[part]} ({how}) to bar {end}")

    def _end_wants(self, bar: int) -> set[str]:
        """At the bar line `bar`: the parts whose pad `want` ends here go back to
        `auto` (#215)."""
        ended = set()
        for part in PARTS:
            end = self._want_ends[part]
            if end is None or bar < end:
                continue
            self._want_ends[part] = None
            if self.wants[part] != "auto":
                self.wants[part] = "auto"
                ended.add(part)
                self._log(f"ensemble: want {part} auto (phrase end), plays {self._plays(part)}")
        return ended

    def _plays(self, part: str) -> str:
        """What `auto` plays for `part` with `learn demo`, for the log (#215):
        `model (tree)`, `model (marked contexts, 1 label)` or `rules`."""
        demos = self._demos[part]
        if demos.plays == "rules":
            return "rules"
        if demos.plays == "tree":
            return "model (tree)"
        labels = len({e.label for e in demos.examples})
        return f"model (marked contexts, {labels} label{'s' if labels > 1 else ''})"

    def _log_learned(self) -> None:
        """Log each context whose top arm changed since the last log."""
        for part, learner in self._learners.items():
            for context, top in self._tops[part].items():
                now = learner.top(context)
                if now != top:
                    rule = rule_choice(part, context)
                    self._log(f"ensemble: learned {part} {context}>{now} (rule {rule})")
                    self._tops[part][context] = now

    def _learned(self) -> list[str]:
        """The reply `learned`: up to `LEARNED_REPLY` contexts that differ from the
        rules, bass first."""
        if self.learn == "nod":
            nodded = [f"bass:groove {g}>{n.variation}" for g, n in self._nods.bound_grooves()]
            return nodded[:LEARNED_REPLY]
        learned = [c for p in PARTS for c in self._learners[p].learned()]
        return learned[:LEARNED_REPLY]

    def _like(self, at: tuple[int, int] | None) -> None:
        """A like at (bar, step) of the clock (`None`: not running): credit each
        loop's choice in the bar it refers to (`learn.liked_bar`)."""
        if at is None:
            self._log(f"ensemble: pad {self.layer_pad}{IGNORED}")
            return
        bar = liked_bar(*at)
        if self._bar_log is not None:
            self._bar_log.like(bar)
        heard = self._heard.get(bar)
        if not heard:
            self._log(f"ensemble: like bar {bar}, no learned choice to credit")
            return
        for part, (context, arm, loop) in heard.items():
            self._learners[part].like(context, arm)
            if loop:
                self._loop_learners[part].like(context, loop)
        self.likes += 1
        credited = " ".join(
            f"{part} {context}>{arm}{f' ({loop})' if loop else ''}"
            for part, (context, arm, loop) in heard.items()
        )
        self._log(f"ensemble: like bar {bar} {credited}")

    @staticmethod
    def _transform_of(plan: BarPlan | None) -> str:
        """The reply `transform` of a loop's plan: `-` when it does not play."""
        return "-" if plan is None or plan.variation is None else plan.transform

    def _surprise(self, bar: int, bass: BarPlan, melody: BarPlan) -> str | None:
        """The surprise of `bar`, among those that can sound in it (#158): with
        `surprise 1` only the bass fill, with `surprise 2` also the melody's (#178)."""
        if not self.surprise or self._access is None or self._access.scheduler is None:
            return None
        candidates = []
        if bass.surprise and self._bass_active == "loop":
            candidates.append("fill")
        if self.surprise == 2 and melody.surprise and self.melody:
            candidates += ["octave", "passing"]
        chosen = surprise(self._random, bar, candidates)
        if chosen is not None:
            self._log(f"ensemble: surprise {chosen} in bar {bar}")
        return chosen

    def _plan_melody(
        self, start: BarStart, plan: BarPlan, heard: Motif, extra: str | None, caught: bool
    ) -> str:
        """Schedule the melody's notes of the bar that starts now, reshaped by the
        last bar's snares and hats `heard` with `rhythm 2` (#189) and with the
        surprise `extra` if it is the melody's, or the catch when `caught` (#290);
        the variation it plays (`-`: none)."""
        self._caught = None
        scheduler = self._access.scheduler if self._access else None
        if scheduler is None or not self.melody:
            self._plans["melody"] = None
            self._melody_memory.reset()
            return "-"
        last_bar = start.state.tick - start.state.beats_per_bar * TICKS_PER_BEAT
        self._melody_notes = [h for h in self._melody_notes if h.tick >= last_bar]
        channel = self.melody_channel
        if plan.cc is not None and self.filter_cc:
            cc = bytes([0xB0 | (channel - 1), self.filter_cc, plan.cc])
            self._melody_notes.append(scheduler.at(start.bar, 0, [cc]))
        chords = self._chords(start.bar)
        steps = start.state.beats_per_bar * STEPS_PER_BEAT
        notes = tuple(
            n for n in plan.notes(self._playing_loop("melody"), start.bar) if n.step < steps
        )
        if caught:
            notes = self._catch(start, plan, notes, steps)
        else:
            plan, notes = self._transform_melody(start.bar, plan, heard, notes, steps)
        self._plans["melody"] = plan
        if extra == "octave":
            notes = octave_up(notes)
        elif extra == "passing":
            notes = passing(notes)
        for note in notes:
            pitch = loop_pitch(note, *chords, self.melody_octave)
            velocity = min(max(round(plan.velocity * note.velocity), 1), 127)
            tick = _tick(note)
            self._melody_notes.append(
                scheduler.note(
                    start.bar, tick, pitch, velocity, note.length * SIXTEENTHS, channel, 1
                )
            )
        return plan.variation or "-"

    def _catch(
        self, start: BarStart, plan: BarPlan, planned: tuple[LoopNote, ...], steps: int
    ) -> tuple[LoopNote, ...]:
        """The catch's notes in the bar that starts now (#290): the rhythm of the last
        bar's hits (`catch 1`) or of the next variation (`catch 2`), the pitches of
        `planned`; logged once."""
        loop = self._playing_loop("melody")
        if self.catch == 1:
            rhythm = drummed(start.hits, steps)
        else:
            rhythm = written(loop, plan.variation, start.bar, steps)
        notes = catch_notes(rhythm, planned, start.bar % loop.bars, steps)
        played = [n.step for n in notes]
        self._caught = {"bar": start.bar - 1, "steps": played}
        self._log(
            f"ensemble: catch bar {start.bar} answers bar {start.bar - 1}, "
            f"steps {' '.join(map(str, played))}"
        )
        return notes

    def _transform_melody(
        self,
        bar: int,
        plan: BarPlan,
        heard: Motif,
        notes: tuple[LoopNote, ...],
        steps: int,
    ) -> tuple[BarPlan, tuple[LoopNote, ...]]:
        """The melody's rhythm transformation in `bar` with `rhythm 2` (#189): as
        `_transform_bass`, `rhythm.backbeat` towards the snares and hats in the
        phrase bars where the bass moves."""
        if self.rhythm < 2 or not self._melody_follows() or plan.skeleton or plan.variation is None:
            self._melody_memory.reset()
            return plan, notes
        if heard.snares or heard.hats:
            taken = self._melody_memory.take(heard)
        else:
            remembered = self._melody_memory.motif
            taken = remembered if self.no_drums == "hold" else Motif()
        snares, hats = taken.snares, taken.hats
        if bar % PHRASE == 0 and len(snares) + len(hats) >= MIN_HITS:
            self._log(
                "ensemble: rhythm motif "
                f"snare {' '.join(str(o.step) for o in snares)} "
                f"hat {' '.join(str(o.step) for o in hats)}".rstrip()
            )
        if bass_stage(bar) == "plain":
            return plan, notes
        shaped = backbeat(notes, fixed_steps(self._playing_loop("melody"), bar), snares, hats)
        if shaped.transform == "plain":
            return plan, notes
        source = tuple(sorted({o.step for o in (*snares, *hats)}))
        moved = Taken("snare hat", source, shaped.moves)
        played = tuple(n for n in shaped.notes if n.step < steps)
        return replace(plan, transform=shaped.transform, taken=moved), played

    def _chords(self, bar: int) -> tuple[tuple[int, str], tuple[int, str]]:
        """The (pitch class, quality) of the chords of `bar` and of the next bar."""
        progression = self.progression
        now, following = progression.chord(bar), progression.chord(bar + 1)
        return (
            (progression.tonic + now.root, now.quality),
            (progression.tonic + following.root, following.quality),
        )

    def _plan_bass(
        self,
        start: BarStart,
        plan: BarPlan,
        kicks: Sequence[GridHit],
        heard: Motif,
        fill: bool,
    ) -> str:
        """Schedule the bass loop's notes of the bar that starts now, reshaped by the
        last bar's kicks `heard` (#189) and with the surprise `fill`; the variation it
        plays (`-`: none)."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is None or self._bass_active != "loop":
            self._plans["bass"] = None
            self._memory.reset()
            return "-"
        last_bar = start.state.tick - start.state.beats_per_bar * TICKS_PER_BEAT
        self._bass_notes = [h for h in self._bass_notes if h.tick >= last_bar]
        bar = start.bar
        chords = self._chords(bar)
        steps_hit = [h.step for h in kicks]
        # Without kicks the notes keep the last bar's velocity; thin keeps #148's rule.
        accented = self.follow and (bool(kicks) or self.no_drums == "thin")
        accents = steps_hit if accented else None
        steps = start.state.beats_per_bar * STEPS_PER_BEAT
        loop = self._playing_loop("bass")
        notes = tuple(n for n in plan.notes(loop, bar) if n.step < steps)
        plan, notes = self._transform_bass(bar, plan, heard, notes, steps)
        self._plans["bass"] = plan
        if fill:
            notes = bass_fill(notes, bar % loop.bars, steps)
        starts = [_tick(n) for n in notes]
        for note, tick in zip(notes, starts, strict=True):
            pitch = loop_pitch(note, *chords, self.octave)
            velocity = bass_note_velocity(note, plan.velocity, accents)
            # Monophonic: a note ends by the next one's start (offsets) and the bar's end.
            end = min([s for s in starts if s > tick] + [steps * SIXTEENTHS])
            ticks = max(min(tick + note.length * SIXTEENTHS, end) - tick, 1)
            self._bass_notes.append(
                scheduler.note(bar, tick, pitch, velocity, ticks, self.channel, 1)
            )
        return plan.variation or "-"

    def _transform_bass(
        self,
        bar: int,
        plan: BarPlan,
        heard: Motif,
        notes: tuple[LoopNote, ...],
        steps: int,
    ) -> tuple[BarPlan, tuple[LoopNote, ...]]:
        """The bass's rhythm transformation in `bar` (#189): the plan with its
        `transform` and `taken`, and the notes it plays. Off with `rhythm 0`, in bars
        that do not follow the drums and in `thin`'s skeleton; a bar without kicks
        answers the remembered motif with `no-drums hold`, else plays the line."""
        if not self.rhythm or not self.follow or plan.skeleton or plan.variation is None:
            self._memory.reset()
            return plan, notes
        if heard.kicks:
            kicks = self._memory.take(heard).kicks
        else:
            kicks = self._memory.motif.kicks if self.no_drums == "hold" else ()
        steps_heard = tuple(o.step for o in kicks)
        if bar % PHRASE == 0 and len(kicks) >= MIN_HITS:
            self._log(f"ensemble: rhythm motif kick {' '.join(map(str, steps_heard))}")
        stage = bass_stage(bar)
        fixed = fixed_steps(self._playing_loop("bass"), bar)
        if stage == "lock":
            shaped = lock(notes, fixed, kicks)
        elif stage == "answer":
            shaped = answer(notes, fixed, kicks)
        else:
            shaped = Shaped(notes, "plain")
        if shaped.transform == "plain":
            return plan, notes
        taken = Taken("kick", steps_heard, shaped.moves)
        played = tuple(n for n in shaped.notes if n.step < steps)
        return replace(plan, transform=shaped.transform, taken=taken), played

    def _set_bass(self, mode: str) -> None:
        """Ask for a bass mode: it starts at the next bar line, or at once while the
        clock is not running."""
        self.bass = mode
        if not self._running():
            self._apply_bass()

    def _running(self) -> bool:
        """Whether the clock runs, so mode changes wait for the next bar line."""
        return self._access is not None and self._access.state().status == "running"

    def _melody_mode(self) -> str:
        """The melody mode asked for: `follow`, `fixed`, `off` or `still`."""
        if not self.melody:
            return "off"
        if not self.follow:
            return "fixed"
        return "still" if self.still else "follow"

    def _still(self) -> bool:
        """Whether the melody plays still while the bass follows (#233)."""
        return self.melody and self.follow and self.still

    def _melody_follows(self) -> bool:
        """Whether the melody loop follows the drums (`follow`, not `still`)."""
        return self.follow and not self.still

    def _sync_melody(self) -> None:
        """A melody change plays at once while the clock is not running."""
        if not self._running():
            self._melody_playing = self._melody_mode()

    def _apply_bass(self) -> None:
        """Switch to the asked bass mode, ending what the old one plays."""
        if self.bass == self._bass_active:
            return
        self._stop_bass_loop()
        self._drop_echoes()
        self._end()
        self._bass_active = self.bass

    def _stop_bass_loop(self) -> None:
        """Drop the pending bass loop notes and end the sounding one."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for handle in self._bass_notes:
                scheduler.cancel(handle)
        self._bass_notes = []

    def _cycle_melody(self) -> None:
        """follow -> fixed -> off -> follow, from the next bar line."""
        if self.melody and self.follow:
            self.follow = False
        elif self.melody:
            self.melody = False
        else:
            self.melody = self.follow = True
        self.still = False
        self._sync_melody()
        self._log(f"ensemble: melody {self._melody_mode()}")

    def _stop_melody(self) -> None:
        """Drop the pending melody notes and end the sounding ones."""
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for handle in self._melody_notes:
                scheduler.cancel(handle)
        self._melody_notes = []

    def _ticks(self, bar: int, step: int) -> int:
        return (bar * self._steps_per_bar() + step) * SIXTEENTHS

    def _steps_per_bar(self) -> int:
        assert self._access is not None
        return self._access.state().beats_per_bar * STEPS_PER_BEAT

    def _echo(self, bar: int, step: int, velocity: int) -> None:
        """Schedule last bar's kick in `bar`, ending the previous echo there."""
        scheduler = self._access.scheduler if self._access else None
        assert scheduler is not None
        tick = self._ticks(bar, step)
        note = self.progression.root_note(bar, self.octave)
        for echo in self._echoes:
            if echo.tick < tick < echo.off_tick:
                scheduler.cancel(echo.off)
                echo.off = scheduler.at(bar, step, [self._message(0x80, echo.note, 0)])
                echo.off_tick = tick
        on = scheduler.at(bar, step, [self._message(0x90, note, velocity)])
        off = scheduler.at(bar, step + self.length, [self._message(0x80, note, 0)])
        self._echoes.append(_Echo(tick, note, tick + self.length * SIXTEENTHS, on, off))

    def _play(self, bar: int, step: int | None, velocity: int) -> None:
        """Sound an immediate note now; `step` is `None` without a running clock."""
        assert self._access is not None
        scheduler = self._access.scheduler
        now = self._access.state().tick
        self._echoes = [e for e in self._echoes if e.off_tick > now]
        if step is not None and scheduler is not None:
            slot = self._ticks(bar, step)
            near = [e for e in self._echoes if abs(e.tick - slot) <= SIXTEENTHS]
            if any(e.tick <= now for e in near):
                return
            for echo in near:
                scheduler.cancel(echo.on)
                scheduler.cancel(echo.off)
                self._echoes.remove(echo)
        self._end()
        note = self.progression.root_note(bar, self.octave)
        self._off = self._message(0x80, note, 0)
        self._access.send_now([self._message(0x90, note, velocity)])
        if step is not None and scheduler is not None:
            self._off_handle = scheduler.at(bar, step + self.length, [self._off])
        else:
            holder: list[_Timer] = []
            timer = self._timer(NOTE_SECONDS, lambda: self._timed_off(holder[0]))
            holder.append(timer)
            self._off_handle = timer
            timer.start()

    def _timed_off(self, timer: _Timer) -> None:
        with self._lock:
            if self._off_handle is timer:
                self._end()

    def _end(self) -> None:
        """End the sounding immediate note, if any (the line stays monophonic)."""
        handle, off = self._off_handle, self._off
        self._off_handle = self._off = None
        if handle is None or off is None or self._access is None:
            return
        if isinstance(handle, Scheduled):
            if self._access.scheduler is not None:
                self._access.scheduler.cancel(handle)
        else:
            handle.cancel()
            self._access.send_now([off])

    def _message(self, status: int, note: int, velocity: int) -> bytes:
        return bytes([status | (self.channel - 1), note, velocity])

    def _cycle(self) -> None:
        """Bass loop -> rule -> off -> loop."""
        mode = BASS_MODES[(BASS_MODES.index(self.bass) + 1) % len(BASS_MODES)]
        self._set_bass(mode)
        self._log(f"ensemble: bass {mode}")

    def _set_bar(self, on: bool) -> None:
        if not on:
            self._drop_echoes()
        self.bar = on

    def _drop_echoes(self) -> None:
        scheduler = self._access.scheduler if self._access else None
        if scheduler is not None:
            for echo in self._echoes:
                scheduler.cancel(echo.on)
                scheduler.cancel(echo.off)
        self._echoes = []

    def controls(self) -> dict[str, ControlHandler]:
        """The preset controls (`/mpciml/preset/ensemble/<name>`)."""
        return {
            "bass": self._set_bass_control,
            "bass-loop": self._set_bass_loop,
            "bass-loop-step": lambda a: self._step("bass", a),
            "loop-step": lambda a: self._step("melody", a),
            "reload-loops": self._reload_loops,
            "immediate": lambda a: self._set(lambda: setattr(self, "immediate", _flag(a))),
            "bar": lambda a: self._set(lambda: self._set_bar(_flag(a))),
            "progression": self._set_progression,
            "progression-step": self._step_progression,
            "octave": lambda a: self._set(lambda: setattr(self, "octave", _whole(a, 0, 3))),
            "length": lambda a: self._set(lambda: setattr(self, "length", _whole(a, 1, 16))),
            "channel": self._set_channel,
            "role": self._set_role,
            "layer-pad": lambda a: self._set(
                lambda: setattr(self, "layer_pad", _whole(a, 0, PADS))
            ),
            "melody": self._set_melody,
            "loop": self._set_loop,
            "follow": self._set_follow,
            "melody-mode": self._set_melody_mode,
            "melody-octave": lambda a: self._set(
                lambda: setattr(self, "melody_octave", _whole(a, 2, 6))
            ),
            "melody-channel": self._set_melody_channel,
            "filter-cc": lambda a: self._set(lambda: setattr(self, "filter_cc", _whole(a, 0, 127))),
            "melody-pad": lambda a: self._set(
                lambda: setattr(self, "melody_pad", _whole(a, 0, PADS))
            ),
            "learn-cc": self._learn_cc,
            "no-drums": self._set_no_drums,
            "fade-bars": lambda a: self._set(lambda: setattr(self, "fade_bars", _whole(a, 0, 32))),
            "surprise": lambda a: self._set(lambda: setattr(self, "surprise", _whole(a, 0, 2))),
            "rhythm": lambda a: self._set(lambda: setattr(self, "rhythm", _whole(a, 0, 2))),
            "learn": self._set_learn,
            "like": self._like_control,
            "want": self._want_control,
            "save-profile": lambda a: self._profile_control(a, self._save_profile),
            "load-profile": lambda a: self._profile_control(a, self._load_profile),
            "reset-learning": self._reset_learning,
            "learn-loops": lambda a: self._set(lambda: setattr(self, "learn_loops", _flag(a))),
            "learn-log": self._set_learn_log,
            "mode-pads": lambda a: self._set(lambda: setattr(self, "mode_pads", _flag(a))),
            "status": lambda a: self._set(lambda: setattr(self, "status", _flag(a))),
            "follow-by": self._set_follow_by,
            "nod": self._nod_control,
            "learn-group": lambda a: self._set(lambda: setattr(self, "learn_group", _flag(a))),
            "new-groove": self._set_new_groove,
            "answer-after": lambda a: self._set(
                lambda: setattr(self, "answer_after", _whole(a, *ANSWER_AFTER))
            ),
            "catch": lambda a: self._set(lambda: setattr(self, "catch", _whole(a, 0, 2))),
        }

    def _set_learn_log(self, args: Sequence[float | int | str]) -> None:
        """`learn-log 0|1`: open a new per-bar log in the data folder, or close it."""
        on = _flag(args)
        with self._lock:
            if not on:
                self._close_log()
                return
            if self._bar_log is not None:
                return
            if self._data is None or self._profile is None:
                raise ValueError("no data folder: ensemble is not loaded by the engine")
            settings = {
                "learn": self.learn,
                "learn-loops": str(int(self.learn_loops)),
                "bass": self.bass,
                "melody-mode": self._melody_mode(),
                "bass-loop": self.bass_loop.name,
                "loop": self.loop.name,
                "progression": self.progression.name,
                "no-drums": self.no_drums,
                "fade-bars": str(self.fade_bars),
                "surprise": str(self.surprise),
                "rhythm": str(self.rhythm),
                "follow-by": self.follow_by,
                "learn-group": str(int(self.learn_group)),
                "new-groove": self.new_groove,
                "answer-after": str(self.answer_after),
                "catch": str(self.catch),
            }
            profile = PROFILE.as_posix() if self._profile.exists() else None
            path = log_path(self._data)
            try:
                self._bar_log = BarLog(path, settings, self._seed, profile)
            except OSError as error:
                raise ValueError(f"cannot write the learn log {path}: {error}") from error
            self._log(f"ensemble: learn log {path}")

    def _close_log(self) -> None:
        """Write what the per-bar log still holds and close it (`learn-log 0`)."""
        if self._bar_log is None:
            return
        log, self._bar_log = self._bar_log, None
        try:
            log.close()
        except OSError as error:
            self._log(f"ensemble: cannot finish the learn log {log.path}: {error}")
            return
        if log.written:
            self._log(f"ensemble: closed the learn log {log.path}")
        else:
            self._log(f"ensemble: closed the learn log {log.path} with no bar: no file")

    def _profile_control(self, args: Sequence[float | int | str], act: Callable[[], None]) -> None:
        """`save-profile` and `load-profile`: no arguments, with a data folder."""
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            if self._profile is None:
                raise ValueError("no data folder: ensemble is not loaded by the engine")
            act()
        self._report()

    def _save_profile(self) -> None:
        """Write the profile (`learn_profile`); `ValueError` when it cannot be."""
        assert self._profile is not None
        settings = {
            "progression": self.progression.name,
            "bass-loop": self.bass_loop.name,
            "loop": self.loop.name,
            "learn-loops": str(int(self.learn_loops)),
            "follow-by": self.follow_by,
        }
        try:
            write_profile(
                self._profile,
                self._learners,
                self._demos,
                settings,
                self._loop_learners,
                self._nods,
            )
        except OSError as error:
            raise ValueError(f"cannot write the profile {self._profile}: {error}") from error
        self._autosave = True
        self._log(f"ensemble: saved the profile {self._profile}")

    def _autosave_profile(self) -> None:
        """At a phrase start while learning: save, unless the profile was bad."""
        if self._profile is None or not self._autosave:
            return
        try:
            self._save_profile()
        except ValueError as error:
            self._log(f"ensemble: {error}")

    def _load_profile(self) -> None:
        """Read the profile and learn it; a bad one is kept from autosave, logged,
        counted in `profile-errors` and raises `ValueError`, the learning unchanged. A
        version 1 profile is renamed to `OLD_PROFILE` and learning starts empty (#250)."""
        assert self._profile is not None
        try:
            profile = read_profile(self._profile)
        except OldProfile:
            self._keep_old_profile()
            return
        except ValueError as error:
            self.profile_errors, self._autosave = 1, False
            self._log(f"ensemble: skipped the profile: {error}")
            raise
        apply_profile(profile, self._learners, self._demos, self._loop_learners, self._nods)
        self._invites.clear()
        self._sections.clear()
        self._tops = {p: {c: self._learners[p].top(c) for c in CONTEXTS[p]} for p in PARTS}
        self.profile_errors, self._autosave = 0, True
        examples = sum(len(d.examples) for d in self._demos.values())
        learned = len(self._learned())
        self._log(
            f"ensemble: loaded the profile {self._profile}: {learned} learned, "
            f"{examples} examples, {len(profile.nods)} nods"
        )

    def _keep_old_profile(self) -> None:
        """Rename a version 1 profile to `OLD_PROFILE` once and start with no nods;
        when that file exists already, the profile is skipped as a bad one (nothing
        learned is overwritten). `ValueError` when it cannot be renamed."""
        assert self._profile is not None and self._data is not None
        old = self._data / OLD_PROFILE
        try:
            if old.exists():
                raise OSError(f"{OLD_PROFILE.as_posix()} exists")
            self._profile.rename(old)
        except OSError as error:
            self.profile_errors, self._autosave = 1, False
            self._log(
                f"ensemble: skipped the profile: version 1 (likes/demo), not renamed: {error}"
            )
            raise ValueError(f"cannot keep the version 1 profile: {error}") from error
        empty = Profile({p: {} for p in PARTS}, (), {})
        apply_profile(empty, self._learners, self._demos, self._loop_learners, self._nods)
        self._tops = {p: {c: self._learners[p].top(c) for c in CONTEXTS[p]} for p in PARTS}
        self.profile_errors, self._autosave = 0, True
        self._log(f"ensemble: profile version 1 (likes/demo) kept as {OLD_PROFILE.as_posix()}")

    def _reset_learning(self, args: Sequence[float | int | str]) -> None:
        """`reset-learning`: back to the rules in memory; the file changes on a save."""
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            for part in PARTS:
                self._learners[part].reset()
                self._demos[part].reset()
                self._loop_learners[part].reset()
            self._chosen = {p: None for p in PARTS}
            self._tops = {p: {c: self._learners[p].top(c) for c in CONTEXTS[p]} for p in PARTS}
            self._heard = {}
            self._nods.reset()
            self._invites.clear()
            self._sections.clear()
            self._nodded.clear()
            self.likes = 0
            self._log("ensemble: reset learning to the rules")
        self._report()

    def _set_learn(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in LEARN_MODES:
            raise ValueError(f"expected one of {', '.join(LEARN_MODES)}, got {list(args)}")
        with self._lock:
            self.learn = str(args[0])

    def _like_control(self, args: Sequence[float | int | str]) -> None:
        """The control `like`: as pad 16 with `learn likes`, at the clock's position."""
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            if self.learn != "likes":
                raise ValueError("learn is not likes; send learn likes first")
            if not self._running():
                raise ValueError("the clock is not running")
            assert self._access is not None
            clock = self._access.state()
            self._like((clock.bar, clock.step))

    def _want_control(self, args: Sequence[float | int | str]) -> None:
        """The control `want bass|melody <want>`: as pads 16 and 15 with `learn demo`."""
        if len(args) != 2 or args[0] not in WANTS or args[1] not in WANTS[str(args[0])]:
            raise ValueError(f"expected bass|melody and auto or a variation, got {list(args)}")
        with self._lock:
            if self.learn != "demo":
                raise ValueError("learn is not demo; send learn demo first")
            if args[0] == "melody" and self._still():
                raise ValueError("the melody is still; a melody want does nothing")
            self.wants[str(args[0])] = str(args[1])
            self._want_ends[str(args[0])] = None
        self._report()

    def _nod_control(self, args: Sequence[float | int | str]) -> None:
        """The control `nod`: as pad 16 with `learn nod`, at the clock's position."""
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            if self.learn != "nod":
                raise ValueError("learn is not nod; send learn nod first")
            if not self._running():
                raise ValueError("the clock is not running")
            assert self._access is not None
            clock = self._access.state()
            self._nod((clock.bar, clock.step))
        self._report()

    def _set_new_groove(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in NEW_GROOVE:
            raise ValueError(f"expected one of {', '.join(NEW_GROOVE)}, got {list(args)}")
        with self._lock:
            self.new_groove = str(args[0])

    def _set_follow_by(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in FOLLOW_BY:
            raise ValueError(f"expected one of {', '.join(FOLLOW_BY)}, got {list(args)}")
        with self._lock:
            self.follow_by = str(args[0])

    def _set_no_drums(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in NO_DRUMS:
            raise ValueError(f"expected one of {', '.join(NO_DRUMS)}, got {list(args)}")
        with self._lock:
            self.no_drums = str(args[0])

    def _learn_cc(self, args: Sequence[float | int | str]) -> None:
        """Send only the brightness CC, as a sweep, so a DAW can map it (#159)."""
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            if self._access is None:
                raise ValueError("ensemble is not attached to the engine")
            if self._running():
                raise ValueError("the clock is running; stop the clock in the DAW first")
            if not self.filter_cc:
                raise ValueError("filter-cc is 0 (off)")
            status = 0xB0 | (self.melody_channel - 1)
            values = reversed(LEARN_CC_SWEEP) if self._learn_down else LEARN_CC_SWEEP
            self._learn_down = not self._learn_down
            messages = [bytes([status, self.filter_cc, value]) for value in values]
            self._access.send_now(messages)

    def _set(self, change: Callable[[], None]) -> None:
        with self._lock:
            change()

    def _set_progression(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in self.progressions:
            raise ValueError(f"expected one of {', '.join(self.progressions)}, got {list(args)}")
        with self._lock:
            self.progression = self.progressions[str(args[0])]

    def _step_progression(self, args: Sequence[float | int | str]) -> None:
        """Choose the next (1) or previous (-1) progression, wrapping around (#236)."""
        if len(args) != 1 or args[0] not in (1, -1):
            raise ValueError(f"expected 1 or -1, got {list(args)}")
        with self._lock:
            names = list(self.progressions)
            if self.progression.name in names:
                name = names[(names.index(self.progression.name) + int(args[0])) % len(names)]
            else:
                name = names[0 if args[0] == 1 else -1]
            self.progression = self.progressions[name]

    def _set_bass_control(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in BASS_MODES:
            raise ValueError(f"expected one of {', '.join(BASS_MODES)}, got {list(args)}")
        with self._lock:
            self._set_bass(str(args[0]))

    def _set_bass_loop(self, args: Sequence[float | int | str]) -> None:
        loop = self._pick(self.bass_loops, args)
        with self._lock:
            self.bass_loop = loop
            self._chosen["bass"] = None

    def _set_melody(self, args: Sequence[float | int | str]) -> None:
        """`melody 0|1|still`: `still` turns the melody on in `melody-mode still`."""
        if list(args) == ["still"]:
            self._melody_to(True, True, True)
        else:
            self._melody_to(_flag(args), None)

    def _set_follow(self, args: Sequence[float | int | str]) -> None:
        self._melody_to(None, _flag(args), False)

    def _set_melody_mode(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 1 or args[0] not in MELODY_SETTINGS:
            raise ValueError(f"expected one of {', '.join(MELODY_SETTINGS)}, got {list(args)}")
        if args[0] == "off":
            self._melody_to(False, None)
        else:
            self._melody_to(True, args[0] != "fixed", args[0] == "still")

    def _melody_to(self, on: bool | None, follow: bool | None, still: bool | None = None) -> None:
        """Set `melody`, `follow` and `still` (`None` keeps one); off drops the pending
        notes, so the melody stops at once."""
        with self._lock:
            if still is not None:
                self.still = still
            if follow is not None:
                self.follow = follow
            if on is not None:
                if not on:
                    self._stop_melody()
                    self._melody_playing = "off"
                self.melody = on
            self._sync_melody()

    def state(self) -> list[tuple[str, list[int | float | str]]]:
        """The `Preset.state` hook: the replies of ADR 0009, in its order. The melody's
        playing mode is `off` without `--clock` (it never plays)."""
        with self._lock:
            scheduler = self._access.scheduler if self._access else None
            melody = self._melody_playing if scheduler is not None else "off"
            return [
                ("bass", [self.bass, self._bass_active]),
                ("melody-mode", [self._melody_mode(), melody]),
                ("bass-loop", [self.bass_loop.name]),
                ("loop", [self.loop.name]),
                ("progression", [self.progression.name]),
                ("bass-loops", list(self.bass_loops)),
                ("loops", list(self.loops)),
                ("progressions", list(self.progressions)),
                ("octave", [self.octave]),
                ("melody-octave", [self.melody_octave]),
                ("channel", [self.channel]),
                ("melody-channel", [self.melody_channel]),
                ("length", [self.length]),
                ("filter-cc", [self.filter_cc]),
                ("layer-pad", [self.layer_pad]),
                ("melody-pad", [self.melody_pad]),
                ("immediate", [int(self.immediate)]),
                ("bar", [int(self.bar)]),
                ("roles", list(self.roles)),
                ("no-drums", [self.no_drums]),
                ("fade-bars", [self.fade_bars]),
                ("surprise", [self.surprise]),
                ("variation", list(self._variations if scheduler is not None else ("-", "-"))),
                ("loop-errors", [self.loop_errors]),
                ("rhythm", [self.rhythm]),
                ("transform", list(self._transforms if scheduler is not None else ("-", "-"))),
                ("learn", [self.learn]),
                ("likes", [self.likes]),
                ("chose", list(self._chose if scheduler is not None else ("-", "-"))),
                ("learned", list(self._learned() or ["-"])),
                ("want", list(self.wants.values())),
                ("examples", [len(d.examples) for d in self._demos.values()]),
                ("profile-errors", [self.profile_errors]),
                ("learn-loops", [int(self.learn_loops)]),
                ("playing-loops", list(self._loop_names if scheduler is not None else ("-", "-"))),
                ("learn-log", [int(self._bar_log is not None)]),
                ("mode-pads", [int(self.mode_pads)]),
                ("status", [int(self.status)]),
                ("progression-errors", [self.progression_errors]),
                ("follow-by", [self.follow_by]),
                ("learn-group", [int(self.learn_group)]),
                ("new-groove", [self.new_groove]),
                ("answer-after", [self.answer_after]),
                ("catch", [self.catch]),
            ]

    def data_folder(self, folder: Path) -> None:
        """The `Preset.data_folder` hook: read the user loops in `<folder>/loops/`, the
        user progressions in `<folder>/progressions/` (#236) and the profile
        `<folder>/learn/ensemble.json` when there is one (#196)."""
        with self._lock:
            self._folder = folder / USER_FOLDER
            self._read_user_loops()
            self._read_user_progressions(folder / PROGRESSION_FOLDER)
            self._data = folder
            self._profile = folder / PROFILE
            if self._profile.exists():
                with contextlib.suppress(ValueError):
                    self._load_profile()

    def _reload_loops(self, args: Sequence[float | int | str]) -> None:
        if args:
            raise ValueError(f"expected no arguments, got {list(args)}")
        with self._lock:
            if self._folder is None:
                raise ValueError("no data folder: ensemble is not loaded by the engine")
            self._read_user_loops()
            self._read_user_progressions(self._folder.parent / PROGRESSION_FOLDER)

    def _read_user_loops(self) -> None:
        """Read the user folder again. A changed loop plays from the next bar line; a
        playing loop whose file is gone keeps playing until another one is chosen."""
        assert self._folder is not None
        library, errors = load_user_loops(self._folder, self._library)
        for error in errors:
            self._log(f"ensemble: skipped a loop file: {error}")
        self.loop_errors = len(errors)
        self.bass_loops = library.played("bass")
        self.loops = library.played("melody")
        self.bass_loop = self.bass_loops.get(self.bass_loop.name, self.bass_loop)
        self.loop = self.loops.get(self.loop.name, self.loop)
        for part, chosen in self._chosen.items():
            if chosen is not None:
                loops = self.bass_loops if part == "bass" else self.loops
                self._chosen[part] = loops.get(chosen.name, chosen)
        users = len(library.loops) - len(self._library.loops)
        if users or errors:
            self._log(f"ensemble: {users} user loops from {self._folder}, {len(errors)} skipped")

    def _read_user_progressions(self, folder: Path) -> None:
        """Read the user progressions again (#236). A changed progression plays from
        the next bar; one whose file is gone keeps playing until another is chosen."""
        progressions, errors = load_user_progressions(folder, self._progressions)
        for error in errors:
            self._log(f"ensemble: skipped a progression file: {error}")
        self.progression_errors = len(errors)
        self.progressions = progressions
        self.progression = progressions.get(self.progression.name, self.progression)
        users = len(progressions) - len(self._progressions)
        if users or errors:
            self._log(f"ensemble: {users} user progressions from {folder}, {len(errors)} skipped")

    def _step(self, part: str, args: Sequence[float | int | str]) -> None:
        """Choose the next (1) or previous (-1) loop of `part`, wrapping around; from
        a loop no longer listed, the first or the last."""
        if len(args) != 1 or args[0] not in (1, -1):
            raise ValueError(f"expected 1 or -1, got {list(args)}")
        step = int(args[0])
        with self._lock:
            loops = self.bass_loops if part == "bass" else self.loops
            names = list(loops)
            current = self.bass_loop if part == "bass" else self.loop
            if current.name in names:
                name = names[(names.index(current.name) + step) % len(names)]
            else:
                name = names[0 if step == 1 else -1]
            if part == "bass":
                self.bass_loop = loops[name]
            else:
                self.loop = loops[name]
            self._chosen[part] = None

    def _set_loop(self, args: Sequence[float | int | str]) -> None:
        loop = self._pick(self.loops, args)
        with self._lock:
            self.loop = loop
            self._chosen["melody"] = None

    def _pick(self, loops: dict[str, Loop], args: Sequence[float | int | str]) -> Loop:
        if len(args) != 1 or args[0] not in loops:
            raise ValueError(f"expected one of {', '.join(loops)}, got {list(args)}")
        return loops[str(args[0])]

    def _set_melody_channel(self, args: Sequence[float | int | str]) -> None:
        channel = _whole(args, 1, 16)
        with self._lock:
            self._stop_melody()
            self.melody_channel = channel

    def _set_channel(self, args: Sequence[float | int | str]) -> None:
        channel = _whole(args, 1, 16)
        with self._lock:
            self._end()
            self._stop_bass_loop()
            self.channel = channel

    def _set_role(self, args: Sequence[float | int | str]) -> None:
        if len(args) != 2 or args[1] not in ROLES:
            raise ValueError(f"expected a pad 1-16 and one of {', '.join(ROLES)}")
        pad = _whole(args[:1], 1, PADS)
        with self._lock:
            self.roles[pad - 1] = str(args[1])


def _whole(args: Sequence[float | int | str], low: int, high: int) -> int:
    if len(args) != 1:
        raise ValueError(f"expected one value, got {len(args)}")
    (value,) = args
    if isinstance(value, bool) or not isinstance(value, int | float) or value != int(value):
        raise ValueError(f"expected a whole number, got {value!r}")
    if not low <= value <= high:
        raise ValueError(f"must be {low}-{high}, got {value}")
    return int(value)


def _flag(args: Sequence[float | int | str]) -> bool:
    return bool(_whole(args, 0, 1))


def _tick(note: LoopNote) -> int:
    """The clock tick of `note` in its bar: its step moved by its `offset`, rounded to
    a tick, never before the bar line."""
    return max(note.step * SIXTEENTHS + round(note.offset * SIXTEENTHS), 0)


def make_preset(log: Callable[[str], None] | None = None) -> Preset:
    """The built-in preset `ensemble`, with fresh settings and bass state (and a fresh
    random seed for the surprises)."""
    ensemble = Ensemble(log) if log is not None else Ensemble()
    return Preset(
        name="ensemble",
        version=__version__,
        description=(
            "A bass loop that follows the kick (or a rule-based bass) and a melody loop"
            " that follows the drums (MIDI notes, channels 2 and 3)"
        ),
        outputs=(),
        controls=ensemble.controls(),
        patch="mpc_iml:patches/mpc-iml.pd",
        clock=ensemble.attach,
        state=ensemble.state,
        data_folder=ensemble.data_folder,
    )
