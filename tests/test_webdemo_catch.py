"""The web demo plays the catch (#290, PR 2): `Settings.catch` on a grid and a
replayed recording, the catch steps in the rows and the table, and the trial file's
settings in the replay of `measures`."""

from pathlib import Path

import pytest
from test_webdemo_nod import GRID
from test_webdemo_replay import take

from mpc_iml.measures import replay_settings
from mpc_iml.recording import Header, write_recording
from mpc_iml.trial.spec import load_trial
from mpc_iml.webdemo.app import TABLE_HEADERS, show, upload
from mpc_iml.webdemo.sim import Settings, Song, replay, simulate

CATCH_TRIAL = Path(__file__).parent.parent / "examples" / "trial" / "catch.json"
DEPARTURES = [8, 16]
"""The grid bars (from 0) after which the keys catch in `GRID`: the first bar of the
second groove (a bar that leaves the first one) and the first bar back."""


def caught(song: Song) -> dict[int, tuple[int, ...]]:
    return {row.bar: row.catch for row in song.rows if row.catch is not None}


def melody_notes(song: Song, bar: int) -> list[tuple[int, int, int]]:
    """(tick, pitch, velocity) of the keys' notes in song bar `bar`."""
    ticks = song.ticks // song.bars
    return [
        (n.tick, n.pitch, n.velocity)
        for n in song.notes
        if n.part == "keys" and bar * ticks <= n.tick < (bar + 1) * ticks
    ]


def test_catch_0_is_the_default_and_plays_as_before() -> None:
    assert Settings().catch == 0
    plain = simulate(GRID)
    assert simulate(GRID, Settings(catch=0)) == plain
    assert caught(plain) == {} and all(row.chose[1] != "catch" for row in plain.rows)


@pytest.mark.parametrize("catch", [1, 2])
def test_the_rows_show_the_catch_and_chose_catch(catch: int) -> None:
    song = simulate(GRID, Settings(catch=catch))
    assert list(caught(song)) == DEPARTURES
    for row in song.rows:
        assert (row.chose[1] == "catch") == (row.bar in DEPARTURES)
        if row.catch is not None:
            assert row.catch[0] == 0 and len(row.catch) <= 8
    plain = simulate(GRID)
    for bar in range(len(GRID) + 1):
        same = melody_notes(song, bar) == melody_notes(plain, bar)
        assert same == (bar - 1 not in DEPARTURES), bar


def test_catch_1_takes_the_bar_it_answers_and_catch_2_an_earlier_bar() -> None:
    """`GRID` bar 8 is the busy groove (a kick on every 4th step and the 3rd after
    it, hats on each step), bar 16 the steady one (hats on the 8ths)."""
    busy, steady = (0, 3, 4, 7, 8, 11, 12, 15), (0, 2, 4, 6, 8, 10, 12, 14)
    assert caught(simulate(GRID, Settings(catch=1))) == {8: busy, 16: steady}
    assert caught(simulate(GRID, Settings(catch=2))) == {8: steady, 16: busy}


@pytest.mark.parametrize("catch", [0, 1, 2])
def test_a_recording_plays_the_catch_as_the_same_grid(catch: int, tmp_path: Path) -> None:
    song = replay(take(GRID), Settings(catch=catch))
    expected = simulate(GRID, Settings(tempo=100.0, catch=catch))
    assert song.rows == expected.rows and song.notes == expected.notes
    path = tmp_path / "take.jsonl"
    write_recording(path, Header(), take(GRID))
    shown, _ = upload(path, Settings(catch=catch))
    melody = [row[TABLE_HEADERS.index("melody")] for row in shown.table]
    chose = [row[TABLE_HEADERS.index("chose")] for row in shown.table]
    marked = [i for i, cell in enumerate(melody) if ", catch " in str(cell)]
    assert marked == ([] if catch == 0 else DEPARTURES)
    assert [i for i, cell in enumerate(chose) if str(cell).endswith("/ catch")] == marked


def test_the_table_counts_the_catch_steps_from_1() -> None:
    table = show(simulate(GRID, Settings(catch=1))).table
    cell = str(table[8][TABLE_HEADERS.index("melody")])
    assert cell.endswith(", catch 1 4 5 8 9 12 13 16")


def test_a_bad_catch_is_refused() -> None:
    with pytest.raises(ValueError):
        simulate(GRID, Settings(catch=3))


def test_the_catch_trial_replays_each_condition() -> None:
    """`measures --trial` replays a recording with the condition's `catch`."""
    trial, _ = load_trial(CATCH_TRIAL)
    for condition in trial.conditions:
        settings = replay_settings(trial.messages(condition))
        assert settings.catch == int(condition.name.removeprefix("catch-"))
        assert settings.melody_mode == "follow" and settings.follow_by == "bar"


def test_the_page_has_the_catch_choice() -> None:
    from mpc_iml.webdemo import __main__ as webdemo_main

    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo.app import build

    page = build()
    radios = [b for b in page.blocks.values() if getattr(b, "label", None) == "catch"]
    assert len(radios) == 1 and getattr(radios[0], "value", None) == 0
