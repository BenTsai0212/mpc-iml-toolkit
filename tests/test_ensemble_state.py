"""`ensemble`'s state replies and the control `melody-mode` (ADR 0009, #153).

The preset runs on the simulated DAW clock of `test_ensemble.py`; its `Rig` records
the state each time the preset calls `ClockAccess.report()`.
"""

from typing import Any

import pytest
import test_engine
from test_engine_preset_state import installed
from test_ensemble import BAR, LAYER, START, STEP, STOP, Rig

from mpc_iml.ensemble import DEFAULT_ROLES, Ensemble, make_preset

receivers = test_engine.receivers
start = test_engine.start
"""The engine fixtures of `test_engine.py`."""

MELODY = 50
"""Note of pad 15 (the melody pad), bank A."""

NAMES = [
    "bass",
    "melody-mode",
    "bass-loop",
    "loop",
    "progression",
    "bass-loops",
    "loops",
    "progressions",
    "octave",
    "melody-octave",
    "channel",
    "melody-channel",
    "length",
    "filter-cc",
    "layer-pad",
    "melody-pad",
    "immediate",
    "bar",
    "roles",
]
"""The replies, in the order of ADR 0009."""


def state(ensemble: Ensemble) -> dict[str, list[Any]]:
    return {name: list(args) for name, args in ensemble.state()}


def modes(snapshot: dict[str, list[Any]]) -> tuple[list[Any], list[Any]]:
    return snapshot["bass"], snapshot["melody-mode"]


def running(bass: str = "loop") -> Rig:
    rig = Rig(melody=True, bass=bass)
    rig.send(START)
    rig.until(STEP)
    return rig


def test_the_state_after_build() -> None:
    ensemble = Ensemble()
    assert [name for name, _ in ensemble.state()] == NAMES
    assert state(ensemble) == {
        "bass": ["loop", "loop"],
        "melody-mode": ["follow", "off"],
        "bass-loop": ["boom"],
        "loop": ["keys"],
        "progression": ["minor-two"],
        "bass-loops": ["boom", "walk"],
        "loops": ["keys", "pluck"],
        "progressions": ["minor-two", "minor-four"],
        "octave": [1],
        "melody-octave": [4],
        "channel": [2],
        "melody-channel": [3],
        "length": [2],
        "filter-cc": [74],
        "layer-pad": [16],
        "melody-pad": [15],
        "immediate": [1],
        "bar": [1],
        "roles": list(DEFAULT_ROLES),
    }


def test_the_preset_has_the_state_hook() -> None:
    preset = make_preset(lambda line: None)
    assert preset.state is not None
    assert [name for name, _ in preset.state()] == NAMES


@pytest.mark.parametrize(
    ("control", "args", "name", "value"),
    [
        ("bass-loop", ["walk"], "bass-loop", ["walk"]),
        ("loop", ["pluck"], "loop", ["pluck"]),
        ("progression", ["minor-four"], "progression", ["minor-four"]),
        ("octave", [2], "octave", [2]),
        ("melody-octave", [5], "melody-octave", [5]),
        ("channel", [4], "channel", [4]),
        ("melody-channel", [6], "melody-channel", [6]),
        ("length", [8], "length", [8]),
        ("filter-cc", [0], "filter-cc", [0]),
        ("layer-pad", [0], "layer-pad", [0]),
        ("melody-pad", [9], "melody-pad", [9]),
        ("immediate", [0], "immediate", [0]),
        ("bar", [0], "bar", [0]),
    ],
)
def test_each_control_shows_in_the_state(
    control: str, args: list[Any], name: str, value: list[Any]
) -> None:
    ensemble = Ensemble()
    ensemble.controls()[control](args)
    assert state(ensemble)[name] == value


def test_role_shows_in_the_roles() -> None:
    ensemble = Ensemble()
    ensemble.controls()["role"]([16, "kick"])
    assert state(ensemble)["roles"] == [*DEFAULT_ROLES[:15], "kick"]


@pytest.mark.parametrize(
    ("mode", "melody", "follow"),
    [("fixed", True, False), ("off", False, False), ("follow", True, True)],
)
def test_melody_mode_sets_melody_and_follow(mode: str, melody: bool, follow: bool) -> None:
    rig = Rig(melody=True)
    rig.ensemble.controls()["follow"]([0])
    rig.ensemble.controls()["melody-mode"]([mode])
    assert (rig.ensemble.melody, rig.ensemble.follow) == (melody, mode != "fixed" and follow)
    assert state(rig.ensemble)["melody-mode"] == [mode, mode]
    assert rig.reports == []


@pytest.mark.parametrize("args", [["loud"], [], ["off", "on"], [1]])
def test_bad_melody_mode_is_rejected(args: list[Any]) -> None:
    with pytest.raises(ValueError):
        Ensemble().controls()["melody-mode"](args)


def test_melody_and_follow_still_set_the_mode() -> None:
    rig = Rig(melody=True)
    controls = rig.ensemble.controls()
    controls["follow"]([0])
    assert state(rig.ensemble)["melody-mode"] == ["fixed", "fixed"]
    controls["melody"]([0])
    assert state(rig.ensemble)["melody-mode"] == ["off", "off"]


def test_without_clock_the_melody_plays_off_and_the_bass_loop_falls_back() -> None:
    rig = Rig(clock=False, melody=True, bass="loop")
    assert modes(state(rig.ensemble)) == (["loop", "loop"], ["follow", "off"])
    rig.hit(MELODY)
    rig.hit(LAYER)
    assert [modes(r) for r in rig.reports] == [
        (["loop", "loop"], ["fixed", "off"]),
        (["rule", "rule"], ["fixed", "off"]),
    ]


def test_stopped_clock_pads_change_next_and_playing_at_once() -> None:
    rig = Rig(melody=True, bass="loop")
    rig.hit(LAYER)
    rig.hit(MELODY)
    assert [modes(r) for r in rig.reports] == [
        (["rule", "rule"], ["follow", "follow"]),
        (["rule", "rule"], ["fixed", "fixed"]),
    ]


def test_running_clock_pads_change_next_then_the_bar_line_playing() -> None:
    rig = running()
    rig.hit(LAYER)
    rig.hit(MELODY)
    assert [modes(r) for r in rig.reports] == [
        (["rule", "loop"], ["follow", "follow"]),
        (["rule", "loop"], ["fixed", "follow"]),
    ]
    rig.until(BAR + 1)
    assert modes(rig.reports[-1]) == (["rule", "rule"], ["fixed", "fixed"])
    assert len(rig.reports) == 3


def test_the_bar_line_reports_only_when_a_playing_mode_changes() -> None:
    rig = running()
    rig.until(3 * BAR + 1)
    assert rig.reports == []
    rig.ensemble.controls()["bass"](["off"])
    assert rig.reports == []
    rig.until(4 * BAR + 1)
    assert [modes(r) for r in rig.reports] == [(["off", "off"], ["follow", "follow"])]


def test_melody_mode_off_stops_at_once_on_a_running_clock() -> None:
    rig = running()
    controls = rig.ensemble.controls()
    controls["melody-mode"](["fixed"])
    assert state(rig.ensemble)["melody-mode"] == ["fixed", "follow"]
    controls["melody-mode"](["off"])
    assert state(rig.ensemble)["melody-mode"] == ["off", "off"]
    controls["melody-mode"](["follow"])
    assert state(rig.ensemble)["melody-mode"] == ["follow", "off"]
    rig.until(BAR + 1)
    assert state(rig.ensemble)["melody-mode"] == ["follow", "follow"]
    assert len(rig.reports) == 1


def test_a_change_while_stopped_after_running_plays_at_once() -> None:
    rig = running()
    rig.send(STOP)
    rig.hit(MELODY)
    assert modes(rig.reports[-1]) == (["loop", "loop"], ["fixed", "fixed"])


def test_the_engine_sends_ensemble_state_after_load_and_a_control(start: Any) -> None:
    found = installed(make_preset(lambda line: None))
    front = start(presets=found)
    prefix = "/mpciml/preset/ensemble/"
    replies = front.ask("/mpciml/preset/load", "ensemble")
    ensemble = [m for m in replies if m[0].startswith(prefix)]
    assert [m[0] for m in ensemble] == [prefix + name for name in NAMES]
    assert ensemble[1] == (prefix + "melody-mode", ["follow", "off"])
    replies = front.ask(prefix + "melody-mode", "fixed")
    assert (prefix + "melody-mode", ["fixed", "off"]) in replies
