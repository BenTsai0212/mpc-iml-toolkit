"""`learn likes` must not change while #215 changes `learn demo` (RFC 0005 step 8).

`tests/data/ensemble-learn-likes.json` was written from `main` before #215's changes
(`write_golden`). It holds the scripted sessions of `test_ensemble_learn.py` in
`learn likes` (in `pads`, pad 16 likes the bar playing and pad 15 cycles the melody
mode), and two sessions of `STEADY` bars in which pad 16 likes every bar whose bass
plays a variation other than `home` from bar 4: `steady` (`learn-loops 0`) learns
variations, and `steady-loops` (`learn-loops 1`) also changes the loops. Every Note On
and CC is compared, with the learning replies of every `report()` and, in the steady
sessions, at the end. The status line is on (#230), so the file also checks that it
changes nothing that plays. The steady sessions run on the four loops installed when
the file was written (`FIRST`): with `learn-loops 1` every installed loop is a choice,
so the hip-hop loops (#232) would change what `steady-loops` draws.
"""

import json
from pathlib import Path
from typing import Any

from test_ensemble import BAR, LAYER, START, STEP, Rig
from test_ensemble_learn import PRESSES, SEEDS, SESSIONS, STEADY, reply
from test_ensemble_rhythm import PATTERN

from mpc_iml.loops import LoopLibrary, load_loops

DATA = Path(__file__).parent / "data" / "ensemble-learn-likes.json"
"""What `main` played in `learn likes` before #215 for `SESSIONS` and `STEADY_LOOPS`."""

STEADY_LOOPS = {"steady": 0, "steady-loops": 1}
"""Steady session -> `learn-loops`."""

STEADY_SEED = 3
STEADY_BARS = 32
FIRST_LIKE = 4
"""The steady sessions like from this bar."""

FIRST = ("boom", "walk", "keys", "pluck")
"""The loops installed when the file was written, before #232."""

REPLIES = ("variation", "transform", "learn", "likes", "chose", "learned", "playing-loops")
"""Replies kept from every `report()`."""


def played(rig: Rig) -> dict[str, Any]:
    sent = [[t, *m] for t, m in rig.sent if m[0] & 0xF0 in (0x90, 0xB0)]
    reports = [{name: r[name] for name in REPLIES} for r in rig.reports]
    return {"sent": sent, "reports": reports}


def scripted(name: str) -> dict[str, Any]:
    """The session `name` of `SESSIONS`, as in `test_ensemble_learn.session`, in
    `learn likes`."""
    settings = SESSIONS[name]
    rig = Rig(melody=True, bass="loop", surprise=settings["surprise"], seed=SEEDS[name], status=1)
    controls = rig.ensemble.controls()
    for control, value in settings.items():
        if control != "surprise":
            controls[control]([value])
    controls["learn"](["likes"])
    rig.send(START)
    for repeat in range(2):
        for i, hits in enumerate(PATTERN):
            bar = repeat * len(PATTERN) + i
            pressed = [(2, PRESSES[bar], 0.0)] if name == "pads" and bar in PRESSES else []
            for step, note, ticks in sorted(hits + pressed):
                rig.until(bar * BAR + step * STEP)
                rig.hit(note, 100, ticks)
            rig.until((bar + 1) * BAR)
    rig.until((2 * len(PATTERN) + 1) * BAR)
    return played(rig)


def steady(name: str) -> dict[str, Any]:
    """The steady session `name`: pad 16 at steps 9 and 10 of every bar from
    `FIRST_LIKE` whose bass plays a variation other than `home` at step 8."""
    installed = load_loops().loops
    first = LoopLibrary({name: installed[name] for name in FIRST})
    rig = Rig(melody=True, bass="loop", seed=STEADY_SEED, status=1, library=first)
    controls = rig.ensemble.controls()
    controls["learn"](["likes"])
    controls["learn-loops"]([STEADY_LOOPS[name]])
    rig.send(START)
    for bar in range(STEADY_BARS):
        for step, note in sorted(STEADY):
            rig.until(bar * BAR + step * STEP)
            rig.hit(note, 100)
        if bar >= FIRST_LIKE and reply(rig, "variation")[0] not in ("home", "-"):
            for step in (9, 10):
                rig.until(bar * BAR + step * STEP)
                rig.hit(LAYER, 100)
        rig.until((bar + 1) * BAR)
    return {**played(rig), "end": {name: reply(rig, name) for name in REPLIES}}


def session(name: str) -> dict[str, Any]:
    return steady(name) if name in STEADY_LOOPS else scripted(name)


NAMES = [*SESSIONS, *STEADY_LOOPS]


def test_learn_likes_plays_exactly_what_main_played() -> None:
    before = json.loads(DATA.read_text())
    assert sorted(before) == sorted(NAMES)
    for name in NAMES:
        assert session(name) == before[name], name


def test_the_steady_sessions_learn_variations_and_loops() -> None:
    """The golden file covers learned choices and loops, not only the rules."""
    before = json.loads(DATA.read_text())
    for name in STEADY_LOOPS:
        assert before[name]["end"]["learned"] != ["-"], name
    loops = [{tuple(r["playing-loops"]) for r in before[n]["reports"]} for n in STEADY_LOOPS]
    assert loops[0] == {("boom", "keys")}
    assert len(loops[1]) > 1


def write_golden() -> None:
    """Write `DATA` (run once from `main`, before #215's changes)."""
    DATA.write_text(json.dumps({n: session(n) for n in NAMES}, indent=None) + "\n")
