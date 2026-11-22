"""The web demo shows the rhythm transformation (#189, PR 4)."""

import numpy as np
import pytest
from test_webdemo_replay import take

from mpc_iml.clock import SIXTEENTHS, TICKS_PER_BEAT
from mpc_iml.webdemo import roll
from mpc_iml.webdemo.app import TABLE_HEADERS, play, to_table
from mpc_iml.webdemo.sim import STEPS, Settings, Song, replay, simulate

BAR = 4 * TICKS_PER_BEAT
KICKS = [100 if s in (0, 6, 10) else 0 for s in range(STEPS)]
GROOVE = {"kick": KICKS, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70, 0] * 8}
"""Kicks on steps 0, 6 and 10, the backbeat and 8th hats."""


def onsets(song: Song, part: str, bar: int) -> list[int]:
    """The steps of `part`'s notes starting in song `bar` (rounded to a step)."""
    return [
        round((n.tick - bar * BAR) / SIXTEENTHS)
        for n in song.notes
        if n.part == part and n.tick // BAR == bar
    ]


def column(table: list[list[str | int]], name: str) -> list[str | int]:
    i = TABLE_HEADERS.index(name)
    return [row[i] for row in table]


def test_the_bass_moves_to_the_kicks_in_phrase_bars_1_to_3() -> None:
    song = simulate([GROOVE] * 8)
    plain = simulate([GROOVE] * 8, Settings(rhythm=0))
    assert Settings().rhythm == 1
    assert [r.bass.transform for r in song.rows if r.bass is not None] == [
        "lock",
        "lock",
        "answer",
        "plain",
    ] * 2
    for bar in (1, 2, 5, 6):
        assert 6 in onsets(song, "bass", bar) and 6 not in onsets(plain, "bass", bar)
        assert {0, 10} <= set(onsets(song, "bass", bar))
    for bar in (3, 4, 7):
        assert onsets(song, "bass", bar) == onsets(plain, "bass", bar)
    assert onsets(song, "keys", 1) == onsets(plain, "keys", 1)


def test_rhythm_0_plays_the_lines_as_written() -> None:
    song = simulate([GROOVE] * 4, Settings(rhythm=0))
    assert {r.bass.transform for r in song.rows if r.bass is not None} == {"plain"}
    assert not any(n.moved for n in song.notes)


def test_moved_notes_are_marked_and_drawn_lighter() -> None:
    song = simulate([GROOVE] * 4)
    moved = [n for n in song.notes if n.moved]
    assert moved and {n.part for n in moved} == {"bass"}
    assert {(n.tick // BAR, round(n.tick % BAR / SIXTEENTHS)) for n in moved} == {(1, 6), (2, 6)}
    light = roll.colour("bass", moved=True)
    assert light != roll.COLOURS["bass"]
    assert all(
        c <= light[i] <= b
        for i, (c, b) in enumerate(zip(roll.COLOURS["bass"], roll.BACKGROUND, strict=True))
    )
    colours = {tuple(c) for c in roll.draw(song).reshape(-1, 3)}
    assert {light, roll.COLOURS["bass"]} <= colours


def test_rhythm_2_moves_the_melody_too() -> None:
    song = simulate([GROOVE] * 4, Settings(rhythm=2))
    assert [r.melody.transform for r in song.rows if r.melody is not None] == [
        "backbeat",
        "backbeat",
        "backbeat",
        "plain",
    ]
    assert any(n.moved and n.part == "keys" for n in song.notes)


def test_the_table_shows_the_transformation_and_what_it_took() -> None:
    _, table, *_ = play(to_table([GROOVE] * 4), Settings())
    assert len(table[0]) == len(TABLE_HEADERS)
    assert TABLE_HEADERS[:4] == ["bar", "transform", "took", "kicks"]
    assert table[0][:3] == ["1 → 2", "lock / plain", "kick 1 7 11 → bass 7"]
    assert column(table, "transform") == [
        "lock / plain",
        "lock / plain",
        "answer / plain",
        "plain / plain",
    ]
    assert column(table, "took")[:2] == ["kick 1 7 11 → bass 7"] * 2
    assert column(table, "took")[3] == "-"
    _, both, *_ = play(to_table([GROOVE] * 4), Settings(rhythm=2))
    assert str(column(both, "took")[1]).startswith("kick 1 7 11 → bass 7; snare hat ")
    _, off, *_ = play(to_table([GROOVE] * 2), Settings(melody_mode="off", rhythm=0))
    assert column(off, "transform") == ["plain / -"] * 2


def test_a_recording_replays_with_rhythm_on() -> None:
    events = take([GROOVE] * 4)
    song = replay(events)
    assert song.settings.rhythm == 1 and song.bars == 5
    assert [r.bass.transform for r in song.rows if r.bass is not None][:3] == [
        "lock",
        "lock",
        "answer",
    ]
    assert 6 in onsets(song, "bass", 1)
    assert onsets(replay(events, Settings(rhythm=0)), "bass", 1) != onsets(song, "bass", 1)


@pytest.mark.parametrize("value", [-1, 3])
def test_a_bad_rhythm_is_refused(value: int) -> None:
    with pytest.raises(ValueError):
        simulate([GROOVE], Settings(rhythm=value))


def test_the_same_grid_with_rhythm_gives_the_same_audio() -> None:
    first = play(to_table([GROOVE] * 2), Settings())
    second = play(to_table([GROOVE] * 2), Settings())
    assert np.array_equal(first.audio[1], second.audio[1])
