"""The web demo's learning settings (#196, #250): `learn off` plays as before, the
table shows the contexts and `chose`, and the learning settings it cannot play are
refused. The nods are in `test_webdemo_nod.py`."""

import pytest

from mpc_iml.webdemo.app import TABLE_HEADERS, play, to_table
from mpc_iml.webdemo.sim import Settings, simulate

SPARSE = {"kick": [100, 0, 0, 0] * 4}
"""Four on-beat kicks: the rules choose `home` for the bass."""
BUSY = {
    "kick": [100, 0, 0, 100] * 4,
    "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2,
    "hat": [70] * 16,
}
"""Dense kicks with a backbeat: the rules choose `drive` for the bass."""


def test_learn_off_plays_as_before() -> None:
    grid = [SPARSE, BUSY, {}, SPARSE]
    before, off = simulate(grid), simulate(grid, Settings(learn="off"))
    assert before == off and off.learning == () and off.learned == ()
    assert {r.chose for r in off.rows} == {("rule", "rule")}
    contexts = [r.context for r in off.rows]
    assert contexts[:3] == [
        ("grid/-", "sparse/none"),
        ("dense/beat", "dense/16ths"),
        ("none/-", "sparse/none"),
    ]


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (Settings(learn="maybe"), "learn must be one of off, nod"),
        (Settings(learn="likes"), "learn must be one of off, nod"),
        (Settings(learn="demo"), "learn must be one of off, nod"),
        (Settings(nods=(1,)), "nods need learn nod"),
    ],
)
def test_bad_learning_settings_are_refused(settings: Settings, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simulate([SPARSE] * 4, settings)


def test_the_page_shows_the_columns() -> None:
    shown = play(to_table([SPARSE, BUSY]), Settings())
    context, chose = TABLE_HEADERS.index("context"), TABLE_HEADERS.index("chose")
    assert shown.table[0][context] == "grid/- / sparse/none"
    assert [row[chose] for row in shown.table] == ["rule / rule", "rule / rule"]
    assert shown.learning == ""
