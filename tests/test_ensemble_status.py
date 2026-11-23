"""The status line and the ignored presses of `ensemble` (#230): `status 0|1` logs, at
each bar line while the clock runs, the variations, their sources and what pads 16
and 15 do now; a press that does nothing because the clock is not running is logged
with either setting.

On the simulated DAW clock of `test_ensemble.py` (`Rig`, whose status line is off
unless asked). The golden sessions of `test_ensemble_learn.py` play with `status 1`,
so the golden files of `learn off` and `learn likes` check that the line changes
nothing that plays.
"""

import pytest
from test_ensemble import LAYER, START, Rig
from test_ensemble_demo import PUSHED
from test_ensemble_learn import MELODY, bar_of, reply

from mpc_iml.clock import PadHit
from mpc_iml.ensemble import Ensemble, for_musician


def status(rig: Rig) -> list[str]:
    return [line for line in rig.log if line.startswith("ensemble: bar ")]


def running(learn: str, mode_pads: int = 1, status: int = 1) -> Rig:
    rig = Rig(melody=True, bass="loop", status=status)
    controls = rig.ensemble.controls()
    controls["learn"]([learn])
    controls["mode-pads"]([mode_pads])
    rig.send(START)
    return rig


def test_status_defaults_to_1_and_has_a_reply() -> None:
    ensemble = Ensemble(lambda line: None)
    assert ensemble.status and dict(ensemble.state())["status"] == [1]
    ensemble.controls()["status"]([0])
    assert dict(ensemble.state())["status"] == [0]
    with pytest.raises(ValueError):
        ensemble.controls()["status"]([2])


def test_learn_demo_shows_the_variations_and_what_pad_16_does_before_and_after_presses() -> None:
    rig = running("demo")
    bar_of(rig, 0, hits=PUSHED)
    bar_of(rig, 1, press=8)
    bar_of(rig, 2, press=8)
    bar_of(rig, 3)
    assert status(rig) == [
        "ensemble: bar 0  Am7  bass -  melody -  16: keep home  15: keep open",
        "ensemble: bar 1  Am7  bass push (rule)  melody open (rule)  16: keep push  15: keep open",
        "ensemble: bar 1  Am7  bass push (rule)  melody open (rule)  16: next drive  15: keep open",
        "ensemble: bar 2  Fmaj7  bass push (want)  melody home (rule)  16: next drive"
        "  15: keep home",
        "ensemble: bar 2  Fmaj7  bass push (want)  melody home (rule)  16: next home"
        "  15: keep home",
        "ensemble: bar 3  Fmaj7  bass drive (want)  melody home (rule)  16: next home"
        "  15: keep home",
    ]
    assert all(for_musician(line) for line in status(rig))


@pytest.mark.parametrize(
    ("progression", "chords"),
    [
        ("minor-two", ["Am7", "Am7", "Fmaj7", "Fmaj7", "Am7"]),
        ("minor-turn", ["Bm7b5", "E7", "Am7", "Am7", "Bm7b5"]),
    ],
)
def test_the_status_line_names_the_chord_of_its_bar(progression: str, chords: list[str]) -> None:
    rig = running("off")
    rig.ensemble.controls()["progression"]([progression])
    for bar in range(5):
        bar_of(rig, bar)
    shown = {int(line.split()[2]): line.split()[3] for line in status(rig)}
    assert [shown[bar] for bar in range(5)] == chords


@pytest.mark.parametrize(
    ("learn", "mode_pads", "pads"),
    [
        ("off", 0, "16: -  15: -"),
        ("off", 1, "16: bass rule  15: melody fixed"),
        ("likes", 0, "16: like  15: -"),
        ("likes", 1, "16: like  15: melody fixed"),
        ("demo", 0, "16: keep home  15: keep home"),
    ],
)
def test_the_pad_text_of_each_learn_mode(learn: str, mode_pads: int, pads: str) -> None:
    rig = running(learn, mode_pads)
    bar_of(rig, 0)
    bar_of(rig, 1)
    (line,) = [line for line in status(rig) if line.startswith("ensemble: bar 1 ")]
    assert line.endswith(f"(rule)  {pads}") or line.endswith(f"(bandit)  {pads}"), line


def test_status_0_logs_no_status_line() -> None:
    rig = running("demo", status=0)
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    assert status(rig) == []
    assert "ensemble: want bass home (kept) to bar 4" in rig.log


@pytest.mark.parametrize("status_on", [0, 1])
@pytest.mark.parametrize(("learn", "mode_pads"), [("off", 0), ("likes", 1), ("demo", 1)])
def test_a_press_while_the_clock_is_stopped_is_shown_with_either_setting(
    learn: str, mode_pads: int, status_on: int
) -> None:
    rig = Rig(melody=True, bass="loop", status=status_on)
    controls = rig.ensemble.controls()
    controls["learn"]([learn])
    controls["mode-pads"]([mode_pads])
    rig.hit(LAYER)
    assert rig.log == ["ensemble: pad 16 ignored, the clock is not running"]
    assert for_musician(rig.log[0])
    assert reply(rig, "want") == ["auto", "auto"] and reply(rig, "likes") == [0]
    assert reply(rig, "bass") == ["loop", "loop"]


def test_a_mode_switch_while_the_clock_is_stopped_is_not_ignored() -> None:
    rig = Rig(melody=True, bass="loop", status=1)
    rig.ensemble.controls()["learn"](["likes"])
    rig.hit(MELODY)
    assert rig.log == ["ensemble: melody fixed"]
    rig.ensemble.on_pad(PadHit(0.0, LAYER - 36, 0, 100, None))
    assert rig.log[-1] == "ensemble: pad 16 ignored, the clock is not running"


def test_other_lines_are_not_for_the_musician() -> None:
    assert not for_musician("ensemble: want bass push (kept) to bar 4")
    assert not for_musician("ensemble: surprise fill in bar 3")
    assert not for_musician("engine: pad 16 ignored, the clock is not running")
