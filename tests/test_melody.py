"""The melody layer of `ensemble` and its rules in `mpc_iml.melody` (#144).

The layer runs on the simulated DAW clock of `test_ensemble.py` (`Rig`), which
calls `ClockAccess.bar_line` before `Scheduler.update`, as the engine does.
"""

from typing import Any

import pytest
from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, STOP, Rig

from mpc_iml.ensemble import NO_CLOCK, Ensemble
from mpc_iml.loops import load_loops
from mpc_iml.melody import (
    BRIGHTNESS_STEP,
    FADE,
    MELODY_VARIATIONS,
    ORNAMENTS,
    BarPlan,
    Follower,
    Loop,
    brightness,
    brightness_step,
    chord_note,
    melody_ornaments,
    melody_variation,
    melody_velocity,
)

LOOPS = load_loops().played("melody")

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


def test_velocity_and_brightness() -> None:
    assert (melody_velocity(1), melody_velocity(127), melody_velocity(200)) == (50, 120, 120)
    assert (brightness(0), brightness(8), brightness(16), brightness(40)) == (48, 79, 110, 110)


def test_brightness_moves_at_most_one_step_per_bar() -> None:
    assert BRIGHTNESS_STEP == 24
    assert (brightness_step(None, 110), brightness_step(48, 110), brightness_step(100, 48)) == (
        110,
        72,
        76,
    )
    follower = Follower(("open", ORNAMENTS))
    hats = [0] * 3 + [16] * 5 + [0] * 5 + [3, 16, 1, 12, 0, 9, 40, 0]
    sent = []
    for count in hats:
        plan = follower.plan_bar([100], ("home", 1), brightness(count), True, True)
        assert plan.cc is not None
        sent.append(plan.cc)
    assert sent[:13] == [48, 48, 48, 72, 96, 110, 110, 110, 86, 62, 48, 48, 48]
    assert all(isinstance(v, int) and 0 <= v <= 127 for v in sent)
    assert all(abs(b - a) <= BRIGHTNESS_STEP for a, b in zip(sent, sent[1:], strict=False))


def test_bars_without_drums_keep_the_brightness_for_the_next_step() -> None:
    follower = Follower(("open", ORNAMENTS))
    assert follower.plan_bar([100], ("home", 1), brightness(16), True, True).cc == 110
    assert follower.plan_bar([], ("home", 1), brightness(0), True, True).cc is None
    assert follower.plan_bar([100], ("home", 1), brightness(0), True, True).cc == 86


def test_loops_have_levels_and_lengths() -> None:
    keys, pluck = LOOPS["keys"], LOOPS["pluck"]
    assert (keys.bars, pluck.bars) == (2, 1)
    assert [n.step for n in keys.bar_notes(0, 1)] == [0, 10]
    assert [n.step for n in keys.bar_notes(3, 1)] == [0]
    assert [n.step for n in pluck.bar_notes(5, 1)] == [0, 4, 8, 12]
    assert len(pluck.variation("home").bar_notes(0, ORNAMENTS)) == 8
    assert all(n.level == 1 and 0 <= n.tone <= 3 for n in keys.notes + pluck.notes)


def sounding(loop: Loop, level: int) -> set[tuple[int, ...]]:
    """Every note of `loop` up to `level`, without its level."""
    return {
        (n.bar, n.step, n.tone, n.length, n.octave, n.chord, n.semitones, round(100 * n.velocity))
        for n in loop.notes
        if n.level <= level
    }


@pytest.mark.parametrize("name", list(LOOPS))
def test_the_skeleton_is_part_of_home(name: str) -> None:
    loop = LOOPS[name]
    assert sounding(loop, 1) <= sounding(loop.variation("home"), 1)


@pytest.mark.parametrize("name", list(LOOPS))
def test_every_melody_variation_is_a_full_line(name: str) -> None:
    loop = LOOPS[name]
    assert tuple(v.name for v in loop.variations) == MELODY_VARIATIONS
    for variation in loop.variations:
        assert variation.bars == loop.bars
        assert {n.level for n in variation.notes} == {1, ORNAMENTS}
        assert all(0 <= n.tone <= 3 and n.chord == n.semitones == 0 for n in variation.notes)
        for bar in range(loop.bars):
            line = variation.bar_notes(bar, 1)
            assert len(line) >= 2 and sum(n.length for n in line) >= 6
            assert all(n.step + n.length <= 16 for n in variation.bar_notes(bar, ORNAMENTS))


def test_variations_differ_and_unknown_names_fail() -> None:
    for loop in LOOPS.values():
        lines = [sounding(v, ORNAMENTS) for v in loop.variations]
        assert len({frozenset(line) for line in lines}) == len(lines)
    with pytest.raises(KeyError):
        LOOPS["keys"].variation("drive")


@pytest.mark.parametrize(
    ("hits", "hat_steps", "variation"),
    [
        (0, [], "open"),
        (5, [0, 4], "open"),
        (4, [3], "busy"),
        (6, [], "home"),
        (12, [0, 2, 4, 6, 8, 10], "home"),
        (13, [14], "home"),
        (14, [], "busy"),
        (9, [0, 7], "busy"),
    ],
)
def test_the_drums_choose_the_melody_variation(
    hits: int, hat_steps: list[int], variation: str
) -> None:
    assert melody_variation(hits, hat_steps) == variation


def test_melody_ornaments_join_with_eight_hits() -> None:
    assert [melody_ornaments(n) for n in (0, 1, 7, 8, 30)] == [1, 1, 1, 2, 2]


def test_follower_plays_the_chosen_variation() -> None:
    follower = Follower(("open", ORNAMENTS))
    assert follower.plan_bar([], ("busy", 2), 90, True, True) == BarPlan(None, 0, 100, None)
    assert follower.plan_bar([127] * 6, ("home", 1), 60, True, True) == BarPlan(
        "home", 1, 120, 60, surprise=True
    )
    assert follower.plan_bar([1], ("busy", 2), 40, True, True) == BarPlan(
        "busy", 2, 50, 40, surprise=True
    )
    assert follower.plan_bar([], ("home", 1), 40, True, False) == BarPlan(
        "home", ORNAMENTS, 100, None
    )


def empty_bars(follower: Follower, bars: int, no_drums: str, fade: int) -> list[BarPlan]:
    """The plans of `bars` bars without drums after one bar of `busy` at 120."""
    follower.plan_bar([127] * 9, ("busy", 2), 80, True, True)
    return [follower.plan_bar([], ("home", 1), 40, True, True, no_drums, fade) for _ in range(bars)]


def test_no_drums_lead_plays_the_lead_variation_then_fades_and_stops() -> None:
    plans = empty_bars(Follower(("open", ORNAMENTS)), 10, "lead", 8)
    assert {(p.variation, p.level, p.cc) for p in plans[:8]} == {("open", ORNAMENTS, None)}
    assert [p.velocity for p in plans[:8]] == [120] * 6 + [round(120 * FADE[1]), 48]
    assert [p.variation for p in plans[8:]] == [None, None]
    assert [p.surprise for p in plans] == [True] * 6 + [False] * 4


def test_no_drums_hold_keeps_the_last_choice_and_fade_bars_zero_never_stops() -> None:
    plans = empty_bars(Follower(("open", ORNAMENTS)), 40, "hold", 0)
    assert {(p.variation, p.level, p.velocity, p.surprise) for p in plans} == {
        ("busy", 2, 120, True)
    }
    assert empty_bars(Follower(("open", ORNAMENTS)), 2, "hold", 1)[0].velocity == 48


def test_no_drums_thin_is_the_skeleton_then_silence() -> None:
    plans = empty_bars(Follower(("open", ORNAMENTS)), 3, "thin", 8)
    assert plans[0] == BarPlan("home", 1, 120, None, skeleton=True)
    assert [p.variation for p in plans[1:]] == [None, None]
    keys = LOOPS["keys"]
    assert plans[0].notes(keys, 0) == keys.bar_notes(0, 1)
    assert len(plans[0].notes(keys, 0)) == 2


def test_an_incomplete_empty_bar_is_a_new_start() -> None:
    follower = Follower(("open", ORNAMENTS))
    follower.plan_bar([100], ("home", 1), 40, True, True)
    assert follower.plan_bar([], ("home", 1), 40, False, True).variation is None
    assert follower.plan_bar([], ("home", 1), 40, True, True).variation is None


def test_silent_until_the_first_hit_then_a_sparse_bar_plays_the_open_line() -> None:
    rig = started()
    play_bar(rig, 0, [])
    play_bar(rig, 1, [(0, KICK), (8, SNARE)])
    assert melody_on(rig) == []
    rig.until(3 * BAR)
    assert melody_on(rig) == [
        (2 * BAR, 69, 120),
        (2 * BAR + 4 * STEP, 72, 108),
        (2 * BAR + 8 * STEP, 76, 120),
    ]
    assert melody_off(rig) == [
        (2 * BAR + 3 * STEP, 69),
        (2 * BAR + 7 * STEP, 72),
        (2 * BAR + 14 * STEP, 76),
    ]
    assert ccs(rig) == [(2 * BAR, 74, 48)]
    assert rig.sent[[m for _, m in rig.sent].index(bytes([0xB2, 74, 48])) + 1][1][0] == 0x92


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


def test_empty_bars_lead_with_the_open_line() -> None:
    rig = started(loop=["pluck"])
    play_bar(rig, 0, [(s, HAT) for s in range(0, 16, 2)])
    play_bar(rig, 1, [])
    play_bar(rig, 2, [])
    rig.until(4 * BAR)
    bars = [t // BAR for t, _, _ in melody_on(rig)]
    assert bars == [1] * 6 + [2] * 5 + [3] * 5
    assert len(ccs(rig)) == 1


def test_thin_keeps_the_skeleton_one_empty_bar_two_stop_it() -> None:
    rig = started(loop=["pluck"], no_drums=["thin"])
    play_bar(rig, 0, [(s, HAT) for s in range(0, 16, 2)])
    play_bar(rig, 1, [])
    play_bar(rig, 2, [])
    rig.until(4 * BAR)
    bars = [t // BAR for t, _, _ in melody_on(rig)]
    assert bars == [1] * 6 + [2] * 4


def test_sixteenth_hats_choose_busy() -> None:
    rig = started(loop=["pluck"])
    play_bar(rig, 0, [(0, KICK), (3, HAT), (8, SNARE)])
    rig.until(2 * BAR)
    assert [(t - BAR) // STEP for t, _, _ in melody_on(rig)] == list(range(0, 16, 2))


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
    assert [m[1] for _, m in rig.sent if m[0] == 0x94] == [53, 60, 65, 64]
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
