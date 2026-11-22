"""The rhythm transformation in `ensemble`'s bass (#189, RFC 0005 step 6), on the
simulated DAW clock of `test_ensemble.py` (`Rig`).

`boom`'s `push` line with ornaments plays steps 0, 3, 7, 10, 12 and 14 (0 and 8 are
its skeleton, 14 the approach into the next chord). After kicks on 0, 5 and 10,
`lock` moves 3 to 5 and `answer` plays it on 6; 7 has no free kick near.
"""

import json
from pathlib import Path
from typing import Any

from test_bass_loop import bass_off, bass_on
from test_ensemble import BAR, KICK, SNARE, START, STEP, Rig
from test_melody import HAT, play_bar

DATA = Path(__file__).parent / "data" / "ensemble-rhythm-0.json"
"""What `main` played before #189 for `PATTERN` (bass and melody Note Ons)."""

PATTERN = [
    [(0, KICK, 0.0), (4, SNARE, 0.0), (8, KICK, 0.0), (12, SNARE, 0.0)],
    [(0, KICK, 0.0), (4, SNARE, 1.0), (6, KICK, -1.0), (10, KICK, 2.0), (12, SNARE, 0.0)],
    [(0, KICK, 0.0), (2, HAT, 0.0), (6, KICK, 0.0), (10, KICK, 0.0), (12, SNARE, 0.0)],
    [(s, KICK, 0.0) for s in (0, 3, 6, 8, 11, 14)],
    [(4, SNARE, 0.0), (12, SNARE, 0.0)],
    [(0, KICK, 0.0)],
    [(0, KICK, 0.0), (7, KICK, 0.0), (9, KICK, 0.0), (4, SNARE, 0.0), (5, HAT, 0.0)],
    [(0, KICK, 0.0), (5, KICK, 0.0), (10, KICK, 0.0), (12, SNARE, 0.0)],
]
"""Eight bars, twice: steady, pushed with offsets, busy, no kicks, one kick."""

KICKS = [(0, KICK), (5, KICK), (10, KICK)]


def played(bass_loop: str, rhythm: int) -> list[list[int]]:
    """(tick, note, velocity) of every Note On for `PATTERN`, with the surprises on."""
    rig = Rig(melody=True, bass="loop", surprise=2, seed=5, rhythm=rhythm)
    rig.ensemble.controls()["bass-loop"]([bass_loop])
    rig.send(START)
    for repeat in range(2):
        for i, hits in enumerate(PATTERN):
            bar = repeat * len(PATTERN) + i
            for step, note, ticks in sorted(hits):
                rig.until(bar * BAR + step * STEP)
                rig.hit(note, 100, ticks)
            rig.until((bar + 1) * BAR)
    rig.until((2 * len(PATTERN) + 1) * BAR)
    return [list(on) for on in rig.on()]


def test_rhythm_0_plays_exactly_what_main_played() -> None:
    before = json.loads(DATA.read_text())
    for name in ("boom", "walk"):
        assert played(name, 0) == before[name]
        assert played(name, 1) != before[name]


def started(**controls: list[Any]) -> Rig:
    rig = Rig(bass="loop", rhythm=1)
    for name, args in controls.items():
        rig.ensemble.controls()[name.replace("_", "-")](args)
    rig.send(START)
    return rig


def steps_of(rig: Rig, bar: int) -> list[int]:
    return [s % 16 for s, _, _ in bass_on(rig) if s // 16 == bar]


def test_the_phrase_starts_plain_then_locks_then_answers() -> None:
    rig = started()
    for bar in range(3, 8):
        play_bar(rig, bar, KICKS)
    rig.until(9 * BAR)
    plain = [0, 3, 7, 10, 12, 14]
    assert [steps_of(rig, bar) for bar in (4, 5, 6, 7, 8)] == [
        plain,
        [0, 5, 7, 10, 12, 14],
        [0, 5, 7, 10, 12, 14],
        [0, 6, 7, 10, 12, 14],
        plain,
    ]
    assert [r["transform"] for r in rig.reports][1:] == [
        ["plain", "-"],
        ["lock", "-"],
        ["answer", "-"],
        ["plain", "-"],
    ]
    assert rig.log.count("ensemble: rhythm motif kick 0 5 10") == 2


def test_the_plan_shows_what_was_taken() -> None:
    rig = started()
    play_bar(rig, 4, KICKS)
    rig.until(5 * BAR + 1)
    plan = rig.ensemble.plans["bass"]
    assert plan is not None and plan.transform == "lock" and plan.taken is not None
    assert (plan.taken.role, plan.taken.steps) == ("kick", (0, 5, 10))
    assert [(m.start, m.step, m.source) for m in plan.taken.moves] == [(3, 5, 5)]


def test_moved_notes_keep_their_pitch_and_the_line_stays_monophonic() -> None:
    plain, moved = started(rhythm=[0]), started()
    for rig in (plain, moved):
        play_bar(rig, 4, KICKS)
        rig.until(6 * BAR)
    assert [n for _, n, _ in bass_on(plain)] == [n for _, n, _ in bass_on(moved)]
    ons = [s for s, _, _ in bass_on(moved)]
    offs = [s for s, _ in bass_off(moved)]
    assert all(off <= on for off, on in zip(offs, ons[1:], strict=False))


def test_one_kick_and_not_following_play_the_line_as_written() -> None:
    one, fixed = started(), started(follow=[0])
    play_bar(one, 4, [(0, KICK), (4, SNARE)])
    play_bar(fixed, 4, KICKS)
    for rig in (one, fixed):
        rig.until(6 * BAR + 1)
        plan = rig.ensemble.plans["bass"]
        assert plan is not None and (plan.transform, plan.taken) == ("plain", None)


def test_without_kicks_hold_answers_the_motif_and_lead_plays_the_line() -> None:
    lead, hold = started(), started(no_drums=["hold"])
    for rig in (lead, hold):
        play_bar(rig, 4, KICKS)
        play_bar(rig, 5, [(4, SNARE)])
        rig.until(6 * BAR + 1)
    lead_plan, hold_plan = lead.ensemble.plans["bass"], hold.ensemble.plans["bass"]
    assert lead_plan is not None and lead_plan.transform == "plain"
    assert hold_plan is not None and hold_plan.transform == "lock"
    hold.until(7 * BAR)
    assert steps_of(hold, 6)[:2] == [0, 5]


def test_the_fill_still_takes_the_last_beat_of_an_answer_bar() -> None:
    rig = Rig(bass="loop", rhythm=1, surprise=1, seed=1)
    rig.send(START)
    for bar in range(3, 7):
        play_bar(rig, bar, KICKS)
    rig.until(8 * BAR)
    fill = "ensemble: surprise fill in bar 7"
    assert fill in rig.log
    assert steps_of(rig, 7) == [0, 6, 7, 10, 12, 13, 14, 15]


def test_rhythm_0_and_bass_rule_report_plain_or_nothing() -> None:
    rig = started(rhythm=[0])
    play_bar(rig, 4, KICKS)
    rig.until(5 * BAR + 1)
    assert rig.reports[-1]["transform"] == ["plain", "-"]
    rig.ensemble.controls()["bass"](["rule"])
    play_bar(rig, 5, KICKS)
    rig.until(6 * BAR + 1)
    assert rig.reports[-1]["transform"] == ["-", "-"]
    assert rig.reports[-1]["rhythm"] == [0]
