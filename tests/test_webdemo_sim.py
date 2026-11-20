"""The web demo's offline run of `ensemble` on a step grid (#166)."""

import pytest

from mpc_iml.clock import TICKS_PER_BEAT
from mpc_iml.melody import FIXED_VELOCITY, ORNAMENTS
from mpc_iml.webdemo.sim import MAX_BARS, STEPS, Settings, Song, chord_name, simulate

BAR = 4 * TICKS_PER_BEAT
SPARSE = {"kick": [100, 0, 0, 0] * 4}
"""Four on-beat kicks: 4 hits, no hats."""
BUSY = {
    "kick": [100, 0, 0, 100] * 4,
    "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2,
    "hat": [70] * STEPS,
}
"""Off-beat kicks and 16th hats: 26 hits."""


def band(song: Song, bar: int) -> list[str]:
    return [n.part for n in song.notes if n.part in ("bass", "keys") and n.tick // BAR == bar]


def test_sparse_and_busy_bars_choose_different_variations() -> None:
    song = simulate([SPARSE, BUSY])
    sparse, busy = song.rows
    assert sparse.bass is not None and sparse.melody is not None
    assert busy.bass is not None and busy.melody is not None
    assert (sparse.bass.variation, sparse.melody.variation) == ("home", "open")
    assert (busy.bass.variation, busy.melody.variation) == ("drive", "busy")
    assert (sparse.melody.level, busy.melody.level) == (1, ORNAMENTS)
    assert (sparse.kicks, sparse.hats, sparse.hits) == ((0, 4, 8, 12), (), 4)
    assert (busy.hits, len(busy.hats), busy.velocity) == (26, 16, pytest.approx(2100 / 26))
    assert (sparse.melody.cc, busy.melody.cc) == (40, 127)
    assert [v for _, v in song.brightness] == [40, 127]
    assert (sparse.bass_rule, sparse.chord, busy.chord) == ("drums", "Am7", "Fmaj7")


def test_the_band_answers_each_bar_in_the_bar_after_it() -> None:
    song = simulate([{}, SPARSE, {}])
    assert song.bars == 4 and song.ticks == 4 * BAR
    assert band(song, 0) == band(song, 1) == []
    assert "bass" in band(song, 2) and "keys" in band(song, 2)
    assert song.rows[0].bass is not None and song.rows[0].bass.variation is None
    drums = [n for n in song.notes if n.part == "kick"]
    assert [n.tick for n in drums] == [BAR + s * 6 for s in (0, 4, 8, 12)]
    assert all(n.tick + n.ticks <= song.ticks for n in song.notes)


def test_bars_without_drums_follow_no_drums_and_fade() -> None:
    song = simulate([SPARSE, {}, {}, {}], Settings(fade_bars=2))
    plans = [r.melody for r in song.rows]
    assert all(p is not None for p in plans)
    velocities = [p.velocity for p in plans if p is not None]
    assert velocities[1:3] == [round(velocities[0] * 0.7), round(velocities[0] * 0.4)]
    assert [p.variation for p in plans if p is not None] == ["open", "open", "open", None]
    assert [r.melody_rule for r in song.rows] == ["drums", "lead", "lead", "lead"]
    assert band(song, 4) == []


def test_fixed_plays_home_at_the_fixed_velocity() -> None:
    song = simulate([BUSY], Settings(melody_mode="fixed"))
    (row,) = song.rows
    assert row.melody is not None and row.bass is not None
    assert (row.melody.variation, row.melody.velocity) == ("home", FIXED_VELOCITY)
    assert (row.bass.variation, row.melody_rule) == ("home", "fixed")


def test_melody_off_and_settings_reach_the_preset() -> None:
    song = simulate([SPARSE], Settings(melody_mode="off", progression="minor-four", tempo=120))
    assert song.rows[0].melody is None and band(song, 1).count("keys") == 0
    assert song.rows[0].chord == chord_name("minor-four", 1) == "Gm7"
    assert song.seconds == pytest.approx(4.0)


def test_the_same_grid_gives_the_same_song() -> None:
    grid = [SPARSE, BUSY, {}]
    assert simulate(grid) == simulate(grid)


@pytest.mark.parametrize(
    ("grid", "settings"),
    [
        ([], Settings()),
        ([{}] * (MAX_BARS + 1), Settings()),
        ([{"clap": [0] * STEPS}], Settings()),
        ([{"kick": [0] * 15}], Settings()),
        ([{"kick": [128] + [0] * 15}], Settings()),
        ([{}], Settings(tempo=200)),
        ([{}], Settings(bass_loop="none")),
        ([{}], Settings(no_drums="loud")),
    ],
)
def test_bad_input_is_refused(grid: list[dict[str, list[int]]], settings: Settings) -> None:
    with pytest.raises(ValueError):
        simulate(grid, settings)
