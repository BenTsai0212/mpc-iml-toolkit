"""The rhythm transformation in `ensemble`'s melody (#189, `rhythm 2`), on the
simulated DAW clock of `test_ensemble.py` (`Rig`).

After snares on 4 and 12 and 8th hats on 2, 6, 10 and 14, `keys`'s `home` line in its
second bar (0, 6, 8 and 12; 0 is the skeleton) moves 8 to the hat on 10, and in its
first bar (0, 3, 6, 10; 0 and 10 are the skeleton) 3 to the hat on 2.
"""

from typing import Any

from test_ensemble import BAR, KICK, SNARE, START, STEP, Rig
from test_melody import HAT, melody_on, play_bar

BACKBEAT = [(0, KICK), (8, KICK), (4, SNARE), (12, SNARE)] + [(s, HAT) for s in (2, 6, 10, 14)]


def started(rhythm: int = 2, **controls: list[Any]) -> Rig:
    rig = Rig(melody=True, bass="loop", rhythm=rhythm)
    for name, args in controls.items():
        rig.ensemble.controls()[name.replace("_", "-")](args)
    rig.send(START)
    return rig


def steps_of(rig: Rig, bar: int) -> list[int]:
    return [t // STEP % 16 for t, _, _ in melody_on(rig) if t // BAR == bar]


def notes_of(rig: Rig, bar: int) -> list[int]:
    return [n for t, n, _ in melody_on(rig) if t // BAR == bar]


def test_rhythm_2_moves_the_melody_to_the_backbeat_after_the_phrase_start() -> None:
    plain, moved = started(rhythm=1), started()
    for rig in (plain, moved):
        for bar in range(3, 8):
            play_bar(rig, bar, BACKBEAT)
        rig.until(9 * BAR)
    assert [steps_of(plain, bar) for bar in range(4, 9)] == [
        [0, 3, 6, 10],
        [0, 6, 8, 12],
        [0, 3, 6, 10],
        [0, 6, 8, 12],
        [0, 3, 6, 10],
    ]
    assert [steps_of(moved, bar) for bar in range(4, 9)] == [
        [0, 3, 6, 10],
        [0, 6, 10, 12],
        [0, 2, 6, 10],
        [0, 6, 10, 12],
        [0, 3, 6, 10],
    ]
    for bar in range(4, 9):
        assert notes_of(plain, bar) == notes_of(moved, bar)
    assert [r["transform"] for r in moved.reports][-3:] == [
        ["lock", "backbeat"],
        ["answer", "backbeat"],
        ["plain", "plain"],
    ]
    assert all(r["transform"][1] in ("-", "plain") for r in plain.reports)
    assert moved.log.count("ensemble: rhythm motif snare 4 12 hat 2 6 10 14") == 2


def test_the_melody_plan_shows_what_was_taken() -> None:
    rig = started()
    play_bar(rig, 4, BACKBEAT)
    rig.until(5 * BAR + 1)
    plan = rig.ensemble.plans["melody"]
    assert plan is not None and plan.transform == "backbeat" and plan.taken is not None
    assert (plan.taken.role, plan.taken.steps) == ("snare hat", (2, 4, 6, 10, 12, 14))
    assert [(m.start, m.step, m.source) for m in plan.taken.moves] == [(8, 10, 10)]


def test_without_snares_or_hats_hold_answers_the_motif_and_lead_plays_the_line() -> None:
    lead, hold = started(), started(no_drums=["hold"])
    for rig in (lead, hold):
        play_bar(rig, 4, BACKBEAT)
        play_bar(rig, 5, [(0, KICK), (8, KICK)])
        rig.until(6 * BAR + 1)
    lead_plan, hold_plan = lead.ensemble.plans["melody"], hold.ensemble.plans["melody"]
    assert lead_plan is not None and lead_plan.transform == "plain"
    assert hold_plan is not None and hold_plan.transform == "backbeat"


def test_one_hit_and_fixed_play_the_melody_as_written() -> None:
    one, fixed = started(), started(follow=[0])
    play_bar(one, 4, [(0, KICK), (8, KICK), (4, SNARE)])
    play_bar(fixed, 4, BACKBEAT)
    for rig in (one, fixed):
        rig.until(5 * BAR + 1)
        plan = rig.ensemble.plans["melody"]
        assert plan is not None and (plan.transform, plan.taken) == ("plain", None)


def test_melody_off_reports_nothing_for_the_melody() -> None:
    rig = started(melody=[0])
    play_bar(rig, 4, BACKBEAT)
    rig.until(5 * BAR + 1)
    assert rig.reports[-1]["transform"][1] == "-"
    assert rig.reports[-1]["rhythm"] == [2]
