"""The catch in `ensemble` (#290): when the melody plays it, what it plays, what
it leaves alone (surprises, the bass's fill answer, `rhythm 2`) and how it is
reported.

On the simulated DAW clock of `test_ensemble.py` (`Rig`). `catch 0` (the default)
runs none of it: the golden files of the other tests do not change. The pure
functions are tested in `test_catch.py`.
"""

from pathlib import Path
from typing import Any

import pytest
from test_ensemble import BAR, KICK, SNARE, START, STEP, Rig
from test_ensemble_grooves import FILL, ROLL, SILENT, A, play
from test_melody import HAT

from mpc_iml.learn_log import read_log

MELODY_ON, BASS_ON = 0x92, 0x91

FILL_STEPS = list(range(0, 16, 2))
"""The steps of `FILL` (snares on every 8th, a kick on 0)."""


def rig(catch: int = 1, seed: int = 1, melody: bool = True, **controls: Any) -> Rig:
    played = Rig(melody=melody, bass="loop", status=1, seed=seed)
    played.ensemble.controls()["catch"]([catch])
    for name, value in controls.items():
        played.ensemble.controls()[name.replace("_", "-")]([value])
    played.send(START)
    return played


def caught(played: Rig) -> list[int]:
    """The bars where a catch played, from its log line."""
    return [int(line.split()[3]) for line in played.log if line.startswith("ensemble: catch bar")]


def fields(played: Rig, index: int) -> dict[int, str]:
    """Bar -> a field of its status line (3: bass, 4: melody)."""
    shown = {}
    for line in played.log:
        if line.startswith("ensemble: bar "):
            parts = line.split("  ")
            shown[int(parts[0].split()[2])] = parts[index]
    return shown


def notes(played: Rig, status: int, bar: int) -> list[tuple[int, int, int]]:
    """(tick in the bar, note, velocity) of each Note On of `status` in `bar`."""
    return [
        (t - bar * BAR, m[1], m[2])
        for t, m in played.sent
        if m[0] == status and m[2] > 0 and bar * BAR <= t < (bar + 1) * BAR
    ]


@pytest.mark.parametrize(
    ("bars", "expected"),
    [
        ([A, A, A, FILL, A, A], [4]),
        ([A, A, FILL, A, A], []),
        ([A, A, A, FILL, ROLL, A, A], [4]),
        ([A, A, A, FILL, A, A, FILL, A], [4, 7]),
    ],
    ids=["G G F", "G F", "G G F F", "G G F G G F"],
)
def test_a_catch_answers_a_bar_that_leaves_a_held_groove(
    bars: list[list[tuple[int, int]]], expected: list[int]
) -> None:
    played = rig()
    play(played, bars)
    assert caught(played) == expected
    for bar in expected:
        assert fields(played, 2)[bar] == "fill"


@pytest.mark.parametrize("follow_by", ["bar", "groove"])
def test_the_catch_plays_the_drummers_rhythm_with_chose_catch(follow_by: str) -> None:
    played = rig(follow_by=follow_by)
    play(played, [A, A, A, FILL, A])
    assert [t // STEP for t, _, _ in notes(played, MELODY_ON, 4)] == FILL_STEPS
    assert fields(played, 4)[4].endswith("(catch)")
    assert not fields(played, 4)[5].endswith("(catch)")
    assert "ensemble: catch bar 4 answers bar 3, steps 0 2 4 6 8 10 12 14" in played.log
    chose = [r["chose"][1] for r in played.reports]
    assert "catch" in chose


def pitches(played: Rig, bar: int) -> list[tuple[int, int]]:
    """(tick in the bar, note) of the melody's Note Ons in `bar`."""
    return [(t, n) for t, n, _ in notes(played, MELODY_ON, bar)]


def test_catch_2_keeps_the_bars_pitches_and_accent_but_not_the_drums() -> None:
    # With `follow-by groove` the melody's variation comes from the groove, so the
    # two fills leave the planned variation alone and only the drums differ.
    drums, written, other = (rig(c, follow_by="groove") for c in (1, 2, 2))
    for played in (drums, written):
        play(played, [A, A, A, FILL, A])
    play(other, [A, A, A, ROLL, A])
    assert caught(drums) == caught(written) == caught(other) == [4]
    steps = [t // STEP for t, _ in pitches(written, 4)]
    assert steps != FILL_STEPS and steps[0] == 0
    assert pitches(written, 4) == pitches(other, 4)
    assert pitches(drums, 4)[0] == pitches(written, 4)[0]
    assert [n for _, n in pitches(drums, 4)][:3] == [n for _, n in pitches(written, 4)][:3]


@pytest.mark.parametrize(
    ("bars", "settings", "expected"),
    [
        ([A, A, A, FILL, A], {"catch": 0}, []),
        ([A, A, A, FILL, A], {"melody": False}, []),
        ([A, A, A, FILL, A], {"follow": 0}, []),
        ([A, A, A, FILL, A], {"melody_mode": "still"}, []),
        ([A, A, A, SILENT, A], {}, []),
        ([A, A, A, [(0, KICK)], A], {}, []),
        ([A, A, A, [(0, KICK), (0, 50), (4, 51)], A], {}, []),
        ([FILL, ROLL, FILL, ROLL, FILL, ROLL, A], {}, []),
        ([A, A, A, FILL, ROLL, FILL, ROLL, FILL, ROLL, A], {}, [4]),
    ],
    ids=[
        "catch 0",
        "melody off",
        "fixed",
        "still",
        "no drums",
        "one hit",
        "pads 15 and 16",
        "no groove",
        "free bars",
    ],
)
def test_no_catch(
    bars: list[list[tuple[int, int]]], settings: dict[str, Any], expected: list[int]
) -> None:
    settings = dict(settings)
    played = rig(settings.pop("catch", 1), melody=settings.pop("melody", True), **settings)
    play(played, bars)
    assert caught(played) == expected
    shown = fields(played, 4)
    assert [b for b, v in shown.items() if v.endswith("(catch)")] == expected


def test_no_catch_without_the_clock() -> None:
    played = Rig(clock=False, melody=True, bass="loop")
    played.ensemble.controls()["catch"]([1])
    for _ in range(4):
        played.hit(KICK, 100)
    assert caught(played) == []


class Always:
    """A random source that always draws a surprise, the first candidate."""

    def random(self) -> float:
        return 0.0

    def choice(self, items: list[str]) -> str:
        return items[0]


@pytest.mark.parametrize("catch", [0, 1])
def test_a_catch_bar_draws_no_surprise(catch: int) -> None:
    played = rig(catch, surprise=2)
    played.ensemble._random = Always()  # type: ignore[assignment]
    play(played, [A, A, A, A, A, A, FILL, A, A, A, A, A])
    surprises = [line for line in played.log if line.startswith("ensemble: surprise")]
    if catch:
        assert surprises == [
            "ensemble: surprise fill in bar 3",
            "ensemble: surprise fill in bar 11",
        ]
    else:
        assert "ensemble: surprise fill in bar 7" in surprises


def test_the_bass_of_a_catch_bar_is_the_bar_without_fill_or_surprise() -> None:
    bars = [A, A, A, A, A, A, FILL, A, A]
    with_catch, plain = rig(1, surprise=1), rig(0, surprise=0)
    with_catch.ensemble._random = Always()  # type: ignore[assignment]
    for played in (with_catch, plain):
        play(played, bars)
    assert caught(with_catch) == [7]
    assert notes(with_catch, BASS_ON, 7) == notes(plain, BASS_ON, 7)


def test_with_follow_by_groove_the_catch_bar_has_no_bass_fill() -> None:
    with_catch, without = rig(1, follow_by="groove"), rig(0, follow_by="groove")
    for played in (with_catch, without):
        play(played, [A, A, A, FILL, A, A])
    assert fields(without, 3)[4] == "bass home (fill)"
    assert fields(with_catch, 3)[4] == "bass home (rule)"
    steps = [t // STEP for t, _, _ in notes(with_catch, BASS_ON, 4)]
    assert steps[-4:] != [12, 13, 14, 15]
    assert steps == [t // STEP for t, _, _ in notes(with_catch, BASS_ON, 5)]


def test_rhythm_2_does_not_move_the_catch() -> None:
    plain, moved = rig(1), rig(1, rhythm=2)
    for played in (plain, moved):
        play(played, [A, A, A, FILL, A])
    assert notes(plain, MELODY_ON, 4) == notes(moved, MELODY_ON, 4)


def test_the_same_seed_and_input_play_the_same_notes() -> None:
    runs = [rig(1, seed=5, surprise=2, rhythm=2) for _ in range(2)]
    hats = [(s, HAT) for s in range(1, 16, 2)] + [(4, SNARE)]
    for played in runs:
        play(played, [A, A, A, FILL, A, A, hats, A, A, A, A, FILL, A])
    assert runs[0].sent == runs[1].sent
    assert caught(runs[0]) == caught(runs[1]) != []


def test_the_state_reply_and_bad_values() -> None:
    played = Rig()
    assert played.ensemble.state()[-1] == ("catch", [0])
    played.ensemble.controls()["catch"]([2])
    assert played.ensemble.state()[-1] == ("catch", [2])
    for bad in (3, -1, "on", 1.5):
        with pytest.raises(ValueError):
            played.ensemble.controls()["catch"]([bad])


def test_the_learn_log_has_the_setting_and_the_catch(tmp_path: Path) -> None:
    played = Rig(melody=True, bass="loop", seed=1)
    controls = played.ensemble.controls()
    controls["catch"]([1])
    played.ensemble.data_folder(tmp_path)
    controls["learn-log"]([1])
    played.send(START)
    play(played, [A, A, A, FILL, A])
    controls["learn-log"]([0])
    (path,) = (tmp_path / "learn").glob("log-*.jsonl")
    header, bars = read_log(path)
    assert header["settings"]["catch"] == "1"
    by_bar = {b["bar"]: b for b in bars}
    assert by_bar[4]["catch"] == {"bar": 3, "steps": FILL_STEPS}
    assert by_bar[4]["source"]["melody"] == "catch"
    assert by_bar[3]["catch"] is None and by_bar[5]["catch"] is None


def test_a_learn_log_without_catch_still_reads(tmp_path: Path) -> None:
    path = tmp_path / "old.jsonl"
    path.write_text(
        '{"format":"mpc-iml-ensemble-log","format_version":1,"toolkit":"0.1.0",'
        '"settings":{"learn":"off"},"seed":null,"profile":null}\n'
        '{"bar":1,"learn":"off","source":{"bass":"rule","melody":"rule"}}\n'
    )
    header, bars = read_log(path)
    assert "catch" not in header["settings"] and "catch" not in bars[0]
