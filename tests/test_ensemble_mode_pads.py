"""`mode-pads 0|1` in `ensemble` (#216): with 0, pads 15 and 16 keep the melody and
bass modes, and pad 16 still nods (`learn nod`, #250).

On the simulated DAW clock of `test_ensemble.py` (`Rig`). With the default 1 the
golden tests (`test_ensemble_learn.py`) check that nothing changed.
"""

import pytest
from test_ensemble import LAYER, START, STEP, Rig
from test_ensemble_learn import MELODY, bar_of, reply


def running(learn: str, mode_pads: int) -> Rig:
    rig = Rig(melody=True, bass="loop", surprise=0)
    controls = rig.ensemble.controls()
    controls["learn"]([learn])
    controls["mode-pads"]([mode_pads])
    rig.send(START)
    rig.until(4 * STEP)
    return rig


def test_mode_pads_defaults_to_1_and_has_a_reply() -> None:
    rig = Rig(melody=True, bass="loop")
    assert rig.ensemble.mode_pads and reply(rig, "mode-pads") == [1]
    rig.ensemble.controls()["mode-pads"]([0])
    assert reply(rig, "mode-pads") == [0]
    with pytest.raises(ValueError):
        rig.ensemble.controls()["mode-pads"]([2])


def test_with_1_pads_15_and_16_still_switch_the_modes() -> None:
    rig = running("off", 1)
    rig.hit(LAYER)
    rig.hit(MELODY)
    assert reply(rig, "bass")[0] != "loop"
    assert reply(rig, "melody-mode")[0] != "follow"
    assert len(rig.reports) == 2


@pytest.mark.parametrize("learn", ["off", "nod"])
def test_with_0_pads_15_and_16_switch_no_mode_and_send_no_reply(learn: str) -> None:
    rig = running(learn, 0)
    before = len(rig.reports)
    rig.hit(MELODY)
    if learn == "off":
        rig.hit(LAYER)
    assert reply(rig, "bass") == ["loop", "loop"]
    assert reply(rig, "melody-mode")[0] == "follow"
    assert len(rig.reports) == before
    assert not [line for line in rig.log if line.startswith(("ensemble: bass", "ensemble: melody"))]


def test_with_0_pad_16_is_still_a_nod_in_learn_nod() -> None:
    rig = running("nod", 0)
    bar_of(rig, 0)
    bar_of(rig, 1, press=8)
    bar_of(rig, 2)
    assert any(line.startswith("ensemble: nod bar 1") for line in rig.log)
    assert reply(rig, "bass") == ["loop", "loop"]
