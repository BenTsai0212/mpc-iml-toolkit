"""The melody layer of `ensemble` and its rules in `mpc_iml.melody` (#144).

The layer runs on the simulated DAW clock of `test_ensemble.py` (`Rig`), which
calls `ClockAccess.bar_line` before `Scheduler.update`, as the engine does.
"""

from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, STOP, Rig

from mpc_iml.ensemble import NO_CLOCK, Ensemble
from mpc_iml.melody import (
    LOOPS,
    BarPlan,
    Follower,
    brightness,
    chord_note,
    density,
    melody_velocity,
)

HAT, MELODY = 38, 50
"""Notes of pad 3 (hat) and pad 15 (the melody pad), bank A."""


def started(**controls: list[Any]) -> Rig:
    rig = Rig(melody=True)
    for name, args in controls.items():
        rig.ensemble.controls()[name.replace("_", "-")](args)
    rig.send(START)
    return rig


def melody_on(rig: Rig) -> list[tuple[int, int, int]]:
    """(tick, note, velocity) of every Note On on channel 3."""
    return [(t, m[1], m[2]) for t, m in rig.sent if m[0] == 0x92]


def melody_off(rig: Rig) -> list[tuple[int, int]]:
    return [(t, m[1]) for t, m in rig.sent if m[0] == 0x82]


def ccs(rig: Rig) -> list[tuple[int, int, int]]:
    return [(t, m[1], m[2]) for t, m in rig.sent if m[0] & 0xF0 == 0xB0]


def play_bar(rig: Rig, bar: int, hits: list[tuple[int, int]], velocity: int = 127) -> None:
    """Hit (step, note) pairs in `bar`, then run the clock to the end of the bar."""
    for step, note in sorted(hits):
        rig.until(bar * BAR + step * STEP)
        rig.hit(note, velocity)
    rig.until((bar + 1) * BAR)


def test_chord_tones_follow_the_quality() -> None:
    assert [chord_note(9, "m7", t, 4) for t in range(4)] == [69, 72, 76, 79]
    assert [chord_note(5, "maj7", t, 4) for t in range(4)] == [65, 69, 72, 76]
    assert [chord_note(2 + 7, "7", t, 3) for t in range(4)] == [57, 61, 64, 67]


def test_density_velocity_and_brightness() -> None:
    assert [density(n) for n in (1, 4, 5, 10, 11, 30)] == [1, 1, 2, 2, 3, 3]
    assert (melody_velocity(1), melody_velocity(127), melody_velocity(200)) == (50, 120, 120)
    assert (brightness(0), brightness(8), brightness(16), brightness(40)) == (40, 84, 127, 127)


def test_loops_have_levels_and_lengths() -> None:
    keys, pluck = LOOPS["keys"], LOOPS["pluck"]
    assert (keys.bars, pluck.bars) == (2, 1)
    assert [n.step for n in keys.bar_notes(0, 1)] == [0, 10]
    assert [n.step for n in keys.bar_notes(3, 1)] == [0]
    assert [n.step for n in pluck.bar_notes(5, 1)] == [0, 4, 8, 12]
    assert len(pluck.bar_notes(0, 3)) == 8
    assert all(n.level in (1, 2, 3) and 0 <= n.tone <= 3 for n in keys.notes + pluck.notes)


def test_follower_no_drums() -> None:
    follower = Follower()
    assert follower.plan_bar([], 0, True, True) == BarPlan(0, 100, None)
    assert follower.plan_bar([127] * 6, 4, True, True) == BarPlan(2, 120, brightness(4))
    assert follower.plan_bar([], 0, True, True) == BarPlan(1, 120, None)
    assert follower.plan_bar([], 0, True, True).level == 0
    assert follower.plan_bar([], 0, True, True).level == 0
    assert follower.plan_bar([1], 0, True, True) == BarPlan(1, 50, 40)
    assert follower.plan_bar([], 0, False, True).level == 0
    assert follower.plan_bar([], 0, True, True).level == 0
    assert follower.plan_bar([], 0, True, False) == BarPlan(3, 100, None)


def test_silent_until_the_first_hit_then_a_sparse_bar_plays_the_skeleton() -> None:
    rig = started()
    play_bar(rig, 0, [])
    play_bar(rig, 1, [(0, KICK), (8, SNARE)])
    assert melody_on(rig) == []
    rig.until(3 * BAR)
    assert melody_on(rig) == [(2 * BAR, 65, 120), (2 * BAR + 10 * STEP, 76, 120)]
    assert melody_off(rig) == [(2 * BAR + 4 * STEP, 65)]
    assert ccs(rig) == [(2 * BAR, 74, 40)]
    assert rig.sent[[m for _, m in rig.sent].index(bytes([0xB2, 74, 40])) + 1][1][0] == 0x92


def test_a_busy_bar_plays_every_level_louder_softer_and_brighter() -> None:
    rig = started()
    hits = [(s, KICK if s % 8 == 0 else HAT) for s in range(0, 16, 2)]
    play_bar(rig, 0, [])
    play_bar(rig, 1, hits + [(4, SNARE), (12, SNARE), (6, SNARE)], velocity=64)
    rig.until(3 * BAR)
    velocity = melody_velocity(64)
    assert [n for _, n, _ in melody_on(rig)] == [65, 69, 72, 76]
    assert {v for _, _, v in melody_on(rig)} == {
        velocity,
        round(velocity * 0.9),
        round(velocity * 0.8),
    }
    assert ccs(rig) == [(2 * BAR, 74, brightness(6))]


def test_one_empty_bar_keeps_the_skeleton_two_stop_it() -> None:
    rig = started(loop=["pluck"])
    play_bar(rig, 0, [(s, HAT) for s in range(0, 16, 2)])
    play_bar(rig, 1, [])
    play_bar(rig, 2, [])
    rig.until(4 * BAR)
    bars = [t // BAR for t, _, _ in melody_on(rig)]
    assert bars == [1] * 6 + [2] * 4
    assert len(ccs(rig)) == 1


def test_follow_off_plays_everything_from_velocity_100_without_cc() -> None:
    rig = started(follow=[0], filter_cc=[74])
    rig.until(2 * BAR)
    assert len(melody_on(rig)) == 8 and {v for _, _, v in melody_on(rig)} == {100, 90, 80}
    assert ccs(rig) == []


def test_controls_octave_channel_and_filter_cc() -> None:
    rig = started(melody_octave=[3], melody_channel=[5], filter_cc=[0], loop=["pluck"])
    play_bar(rig, 0, [])
    play_bar(rig, 1, [(0, KICK)])
    rig.until(3 * BAR)
    assert [m[1] for _, m in rig.sent if m[0] == 0x94] == [53, 60, 60, 60]
    assert melody_on(rig) == ccs(rig) == []


def test_melody_pad_cycles_follow_fixed_off_and_is_not_a_drum() -> None:
    rig = started()
    rig.until(BAR + STEP)
    for _ in range(4):
        rig.hit(MELODY)
    assert rig.log == [
        "ensemble: melody fixed",
        "ensemble: melody off",
        "ensemble: melody follow",
        "ensemble: melody fixed",
    ]
    rig.hit(MELODY)
    rig.hit(MELODY)
    rig.hit(LAYER)
    rig.until(3 * BAR)
    assert rig.sent == []


def test_melody_off_drops_pending_and_ends_sounding_notes() -> None:
    rig = started(follow=[0])
    rig.until(2 * STEP)
    rig.ensemble.controls()["melody"]([0])
    rig.until(3 * BAR)
    assert melody_on(rig) == [(0, 69, 100)]
    assert melody_off(rig) == [(2 * STEP - 1, 69)]


def test_stop_ends_every_melody_note() -> None:
    rig = started(follow=[0])
    rig.until(BAR + 13 * STEP)
    rig.send(STOP)
    rig.until(3 * BAR)
    assert len(melody_on(rig)) == len(melody_off(rig)) > 0


def test_the_bass_is_the_same_with_the_melody_on() -> None:
    def bass(melody: bool) -> list[tuple[int, bytes]]:
        rig = Rig(melody=melody)
        rig.send(START)
        play_bar(rig, 0, [(0, KICK), (6, KICK), (8, SNARE)])
        rig.until(3 * BAR)
        return [(t, m) for t, m in rig.sent if m[0] & 0x0F == 1]

    assert bass(True) == bass(False) != []


def test_without_clock_no_melody() -> None:
    rig = Rig(clock=False, melody=True)
    rig.hit()
    assert rig.log[0] == NO_CLOCK
    assert all(m[0] & 0x0F == 1 for _, m in rig.sent)


@pytest.mark.parametrize(
    ("control", "args"),
    [
        ("melody", [2]),
        ("loop", ["bossa"]),
        ("follow", ["yes"]),
        ("melody-octave", [1]),
        ("melody-channel", [0]),
        ("filter-cc", [128]),
        ("melody-pad", [17]),
    ],
)
def test_bad_melody_control_arguments_are_rejected(control: str, args: list[Any]) -> None:
    with pytest.raises(ValueError):
        Ensemble().controls()[control](args)
