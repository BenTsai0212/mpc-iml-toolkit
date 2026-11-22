"""`ensemble`'s state replies and the control `melody-mode` (ADR 0009, #153), with
`no-drums`, `fade-bars` and `variation` (#158).

The preset runs on the simulated DAW clock of `test_ensemble.py`; its `Rig` records
the state each time the preset calls `ClockAccess.report()`.
"""

from typing import Any

import pytest
import test_engine
from test_engine_preset_state import installed
from test_ensemble import BAR, KICK, LAYER, START, STEP, STOP, Rig
from test_melody import play_bar

from mpc_iml.ensemble import DEFAULT_ROLES, LEARN_CC_SWEEP, Ensemble, make_preset

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
    "no-drums",
    "fade-bars",
    "surprise",
    "variation",
    "loop-errors",
    "rhythm",
    "transform",
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
        "no-drums": ["lead"],
        "fade-bars": [8],
        "surprise": [1],
        "variation": ["-", "-"],
        "loop-errors": [0],
        "rhythm": [1],
        "transform": ["-", "-"],
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
        ("no-drums", ["thin"], "no-drums", ["thin"]),
        ("fade-bars", [0], "fade-bars", [0]),
        ("fade-bars", [32], "fade-bars", [32]),
        ("rhythm", [0], "rhythm", [0]),
    ],
)
def test_each_control_shows_in_the_state(
    control: str, args: list[Any], name: str, value: list[Any]
) -> None:
    ensemble = Ensemble()
    ensemble.controls()[control](args)
    assert state(ensemble)[name] == value


@pytest.mark.parametrize(
    ("control", "args"),
    [
        ("no-drums", ["stop"]),
        ("no-drums", []),
        ("fade-bars", [33]),
        ("fade-bars", [-1]),
        ("rhythm", [3]),
        ("rhythm", [-1]),
        ("rhythm", ["lock"]),
    ],
)
def test_bad_no_drums_and_fade_bars_are_rejected(control: str, args: list[Any]) -> None:
    ensemble = Ensemble()
    with pytest.raises(ValueError):
        ensemble.controls()[control](args)
    assert state(ensemble)["no-drums"] == ["lead"] and state(ensemble)["fade-bars"] == [8]


def test_the_bar_line_reports_when_a_playing_variation_changes() -> None:
    rig = running()
    play_bar(rig, 1, [(0, KICK), (8, KICK)])
    rig.until(2 * BAR + 1)
    assert [r["variation"] for r in rig.reports] == [["home", "open"]]
    play_bar(rig, 2, [(0, KICK), (8, KICK)])
    rig.until(3 * BAR + 1)
    assert len(rig.reports) == 1
    play_bar(rig, 3, [(0, KICK), (10, KICK)])
    rig.until(4 * BAR + 1)
    assert [r["variation"] for r in rig.reports][1:] == [["push", "open"]]
    rig.ensemble.controls()["bass"](["off"])
    rig.ensemble.controls()["melody-mode"](["fixed"])
    rig.until(5 * BAR + 1)
    assert rig.reports[-1]["variation"] == ["-", "home"]


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


# learn-cc (#159): the brightness CC alone, so a DAW maps it and not a melody note.


def ccs(rig: Rig) -> list[tuple[int, int, int]]:
    """(status, controller, value) of every message sent."""
    return [(m[0], m[1], m[2]) for _, m in rig.sent]


def test_learn_cc_sweeps_only_the_cc_up_then_down_without_clock() -> None:
    rig = Rig(clock=False, melody=True)
    learn = rig.ensemble.controls()["learn-cc"]
    learn([])
    assert ccs(rig) == [(0xB2, 74, v) for v in LEARN_CC_SWEEP]
    learn([])
    assert ccs(rig)[5:] == [(0xB2, 74, v) for v in reversed(LEARN_CC_SWEEP)]
    learn([])
    assert ccs(rig)[10:] == [(0xB2, 74, v) for v in LEARN_CC_SWEEP]
    assert LEARN_CC_SWEEP == (0, 32, 64, 96, 127)


def test_learn_cc_follows_filter_cc_and_melody_channel() -> None:
    rig = Rig(clock=False, melody=True)
    controls = rig.ensemble.controls()
    controls["filter-cc"]([71])
    controls["melody-channel"]([5])
    controls["learn-cc"]([])
    assert ccs(rig) == [(0xB4, 71, v) for v in LEARN_CC_SWEEP]


def test_learn_cc_only_while_the_clock_is_not_running() -> None:
    rig = Rig(melody=True)
    learn = rig.ensemble.controls()["learn-cc"]
    learn([])
    assert len(rig.sent) == 5, "waiting: accepted"
    rig.send(START)
    with pytest.raises(ValueError, match="clock is running"):
        learn([])
    rig.until(BAR + STEP)
    rig.send(STOP)
    stopped = len(rig.sent)
    learn([])
    assert ccs(rig)[stopped:] == [(0xB2, 74, v) for v in reversed(LEARN_CC_SWEEP)]


@pytest.mark.parametrize("args", [[1], ["x"]])
def test_learn_cc_takes_no_arguments(args: list[Any]) -> None:
    rig = Rig(clock=False)
    with pytest.raises(ValueError, match="no arguments"):
        rig.ensemble.controls()["learn-cc"](args)
    assert rig.sent == []


def test_learn_cc_is_refused_when_filter_cc_is_off() -> None:
    rig = Rig(clock=False)
    controls = rig.ensemble.controls()
    controls["filter-cc"]([0])
    with pytest.raises(ValueError, match="filter-cc is 0"):
        controls["learn-cc"]([])
    assert rig.sent == []


def test_the_engine_accepts_learn_cc_and_sends_the_state(start: Any) -> None:
    found = installed(make_preset(lambda line: None))
    front = start(presets=found)
    prefix = "/mpciml/preset/ensemble/"
    front.ask("/mpciml/preset/load", "ensemble")
    replies = front.ask(prefix + "learn-cc")
    assert not [m for m in replies if m[0] == "/mpciml/error"]
    assert [m[0] for m in replies if m[0].startswith(prefix)] == [prefix + n for n in NAMES]
    replies = front.ask(prefix + "learn-cc", 1)
    assert [m[0] for m in replies] == ["/mpciml/error"]
    assert replies[0][1][0] == "bad_arguments"
