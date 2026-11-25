"""The web demo follows the groove and plays the nods (#250, PR 6): `Settings.nods`
on a grid, and pad 16 of a replayed recording with `learn nod`."""

import pytest
from test_webdemo_replay import BAR, take

from mpc_iml.clock import SIXTEENTHS, TICKS_PER_BEAT
from mpc_iml.events import Event, MidiEvent
from mpc_iml.frames import bank_pad_to_note
from mpc_iml.measures import replay_settings
from mpc_iml.webdemo.app import parse_nods
from mpc_iml.webdemo.sim import Settings, Song, replay, simulate

STEADY = {"kick": [100, 0, 0, 0] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70, 0] * 8}
BUSY = {"kick": [100, 0, 0, 100] * 4, "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2, "hat": [70] * 16}
GRID = [STEADY] * 8 + [BUSY] * 8 + [STEADY] * 6
"""A groove, a second one, and the first one back."""
NOD = Settings(learn="nod", follow_by="groove", nods=(7,))
"""A nod on the last bar of the first groove's phrase (grid bar 8)."""


def sources(song: Song) -> list[str]:
    return [row.chose[0] for row in song.rows]


def test_the_defaults_follow_each_bar_as_before() -> None:
    assert Settings().follow_by == "bar" and Settings().nods == ()
    plain = simulate(GRID)
    assert simulate(GRID, Settings(follow_by="bar", learn="off")) == plain
    assert "fill" not in sources(plain)


def test_follow_by_groove_answers_the_fills_on_a_grid() -> None:
    song = simulate(GRID, Settings(follow_by="groove"))
    assert sources(song)[8] == "fill" and sources(song)[16] == "fill"
    assert "nod" not in sources(song) and song.learning == ()


def test_a_nod_on_a_grid_plays_its_variation_when_the_groove_comes_back() -> None:
    song = simulate(GRID, NOD)
    assert song.learning == (
        "ensemble: nod bar 7 -> groove 1 (bar 8), bass home",
        "ensemble: groove 1 back, bass home (nod)",
    )
    assert song.learned == ("bass:groove 1>home",)
    assert sources(song)[:17] == sources(simulate(GRID, Settings(follow_by="groove")))[:17]
    assert sources(song)[17:] == ["nod"] * 5


def test_pad_16_of_a_recording_is_the_nod() -> None:
    """The nod a grid sends with `nod` is pad 16 in the first beat of the bar after."""
    events: list[Event] = take(GRID)
    tick = 8 * BAR + SIXTEENTHS
    at = 0.1 + tick * 60.0 / 100.0 / TICKS_PER_BEAT + 0.001
    pad16 = MidiEvent(at, "note_on", 1, 100, bank_pad_to_note(0, 15))
    events = sorted([*events, pad16], key=lambda e: e.t)
    song = replay(events, Settings(learn="nod", follow_by="groove"))
    assert song.learning == simulate(GRID, NOD).learning
    assert sources(song) == sources(simulate(GRID, NOD))
    without = replay(events, Settings(follow_by="groove", mode_pads=0))
    assert "nod" not in sources(without) and without.learning == ()


def test_the_groove_settings_reach_the_band() -> None:
    song = simulate(GRID, Settings(follow_by="groove", answer_after=1))
    assert "fill" not in sources(song)
    invite = simulate(GRID, Settings(learn="nod", follow_by="groove", new_groove="invite"))
    assert "invite" in sources(invite)
    assert any(line.endswith("(invite)") for line in invite.learning)


def test_nods_are_checked() -> None:
    with pytest.raises(ValueError, match="nods need learn nod"):
        simulate(GRID, Settings(nods=(1,)))
    with pytest.raises(ValueError, match="a nod must be in bars 1-22, got bar 23"):
        simulate(GRID, Settings(learn="nod", nods=(22,)))
    with pytest.raises(ValueError, match="expected one of bar, groove"):
        simulate(GRID, Settings(follow_by="phrase"))


def test_parse_nods() -> None:
    assert parse_nods("16, 8 8") == (7, 15)
    assert parse_nods("") == ()
    with pytest.raises(ValueError, match="nods: '0' is not a bar number from 1"):
        parse_nods("0")


def test_replay_settings_take_the_groove_controls() -> None:
    controls = [
        ("follow-by", ["groove"]),
        ("answer-after", [1]),
        ("learn-group", [1]),
        ("new-groove", ["invite"]),
        ("learn", ["nod"]),
    ]
    assert replay_settings(controls) == Settings(
        follow_by="groove", answer_after=1, learn_group=1, new_groove="invite", learn="nod"
    )
