"""The bass loop layer of `ensemble` (#148): bass mode `loop`, on the simulated DAW
clock of `test_ensemble.py` (`Rig`). Over `minor-two` in octave 1, Am7 is A1 (33)
and Fmaj7 is F1 (29); the approach into Fmaj7 is E1 (28)."""

from typing import Any

from test_ensemble import BAR, KICK, LAYER, SNARE, START, STEP, STOP, Rig
from test_melody import HAT, melody_on, play_bar

from mpc_iml.ensemble import NO_CLOCK


def started(melody: bool = False, **controls: list[Any]) -> Rig:
    rig = Rig(melody=melody, bass="loop")
    for name, args in controls.items():
        rig.ensemble.controls()[name.replace("_", "-")](args)
    rig.send(START)
    return rig


def bass_on(rig: Rig) -> list[tuple[int, int, int]]:
    """(step from song start, note, velocity) of every Note On on channel 2."""
    return [(t // STEP, m[1], m[2]) for t, m in rig.sent if m[0] == 0x91]


def bass_off(rig: Rig) -> list[tuple[int, int]]:
    return [(t // STEP, m[1]) for t, m in rig.sent if m[0] == 0x81]


def test_silent_until_a_kick_then_a_sparse_bar_plays_the_skeleton_with_accents() -> None:
    rig = started()
    play_bar(rig, 0, [(4, SNARE)])
    play_bar(rig, 1, [(0, KICK), (10, KICK)])
    rig.until(3 * BAR)
    assert bass_on(rig) == [(32, 29, 120), (40, 36, 96)]
    assert bass_off(rig) == [(35, 29), (42, 36)]


def test_a_busy_bar_plays_every_level_with_accents_on_the_kicks() -> None:
    rig = started()
    play_bar(rig, 1, [(s, KICK) for s in (0, 3, 6, 8, 14)], velocity=1)
    rig.until(3 * BAR)
    assert bass_on(rig) == [
        (32, 29, 50),
        (35, 29, 35),
        (38, 41, 50),
        (40, 36, 50),
        (43, 36, 30),
        (46, 28, 50),
    ]


def test_kick_count_sets_the_density_and_other_pads_do_not_count() -> None:
    rig = started()
    hits = [(0, KICK), (4, SNARE), (6, KICK), (8, HAT), (10, KICK), (12, HAT), (14, SNARE)]
    play_bar(rig, 1, hits)
    rig.until(3 * BAR)
    assert [s % 16 for s, _, _ in bass_on(rig)] == [0, 6, 8, 14]


def test_no_kicks_one_bar_skeleton_two_bars_silence_back_after_a_kick() -> None:
    rig = started()
    play_bar(rig, 1, [(0, KICK), (6, KICK), (10, KICK)])
    play_bar(rig, 2, [(4, SNARE), (8, HAT)])
    play_bar(rig, 3, [(4, SNARE), (12, SNARE)])
    play_bar(rig, 4, [(8, KICK)])
    rig.until(6 * BAR)
    bars = [(s // 16, s % 16) for s, _, _ in bass_on(rig)]
    assert bars == [(2, 0), (2, 6), (2, 8), (2, 14), (3, 0), (3, 8), (5, 0), (5, 8)]


def test_follow_off_plays_every_level_at_100_without_accents() -> None:
    rig = started(follow=[0])
    rig.until(BAR)
    assert bass_on(rig) == [
        (0, 33, 100),
        (3, 33, 70),
        (6, 45, 100),
        (8, 40, 100),
        (11, 40, 75),
        (14, 32, 100),
    ]


def test_walk_has_a_passing_note_and_approaches_into_the_next_chord() -> None:
    rig = started(follow=[0], bass_loop=["walk"], progression=["minor-four"])
    rig.until(2 * BAR)
    notes = {s: n for s, n, _ in bass_on(rig)}
    assert (notes[14], notes[16 + 12], notes[16 + 14]) == (30, 32, 33)


def test_layer_pad_switches_the_mode_at_the_next_bar_line() -> None:
    rig = started(follow=[0])
    rig.until(2 * STEP)
    rig.hit(LAYER)
    rig.until(BAR + 4 * STEP + 1)
    rig.hit()
    rig.until(2 * BAR)
    assert rig.log == ["ensemble: bass rule"]
    assert [s for s, _, _ in bass_on(rig)] == [0, 3, 6, 8, 11, 14, 20]
    rig.until(2 * BAR + 1)
    rig.hit(LAYER)
    rig.until(2 * BAR + 4 * STEP + 1)
    rig.hit()
    play_bar(rig, 3, [(2, KICK), (8, KICK)])
    assert len(bass_on(rig)) == 8 and rig.log[-1] == "ensemble: bass off"


def test_bass_off_and_switching_while_stopped_apply_at_once() -> None:
    rig = Rig(bass="rule")
    rig.ensemble.controls()["bass"](["off"])
    rig.send(START)
    play_bar(rig, 0, [(0, KICK), (8, KICK)])
    rig.until(2 * BAR)
    assert bass_on(rig) == []


def test_stop_ends_every_bass_note() -> None:
    rig = started(follow=[0])
    rig.until(BAR + 7 * STEP)
    rig.send(STOP)
    rig.until(3 * BAR)
    assert len(bass_on(rig)) == len(bass_off(rig)) > 0


def test_the_melody_is_the_same_with_the_bass_loop_on() -> None:
    def melody(bass: str) -> list[tuple[int, int, int]]:
        rig = Rig(melody=True, bass=bass)
        rig.send(START)
        for bar in range(3):
            play_bar(rig, bar, [(0, KICK), (4, SNARE), (6, KICK), (8, HAT)])
        return melody_on(rig)

    assert melody("loop") == melody("off") != []


def test_without_clock_the_loop_plays_a_note_on_each_kick() -> None:
    rig = Rig(clock=False, bass="loop")
    rig.ensemble.controls()["immediate"]([0])
    rig.hit()
    assert rig.log == [NO_CLOCK]
    assert [m for _, m in rig.sent] == [bytes([0x91, 33, 120])]
