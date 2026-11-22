"""The web demo's learning path (#196): likes, wants and pad presses (#215) over a
scripted session."""

import pytest

from mpc_iml.webdemo.app import (
    TABLE_HEADERS,
    learning,
    parse_likes,
    parse_presses,
    parse_wants,
    play,
    to_table,
)
from mpc_iml.webdemo.sim import Settings, simulate

SPARSE = {"kick": [100, 0, 0, 0] * 4}
"""Four on-beat kicks: the rules choose `home` for the bass."""
BUSY = {
    "kick": [100, 0, 0, 100] * 4,
    "snare": [0, 0, 0, 0, 90, 0, 0, 0] * 2,
    "hat": [70] * 16,
}
"""Dense kicks with a backbeat: the rules choose `drive` for the bass."""
DEMO = [SPARSE] * 5 + [BUSY] * 5 + [SPARSE, BUSY] * 2
WANTS = ((0, "bass", "push"), (4, "bass", "home"), (9, "bass", "auto"))
"""Push over the sparse bars, home over the busy ones, then the model plays."""
PRESSED = [SPARSE] * 4 + [BUSY] * 4 + [SPARSE, BUSY] * 2
PRESSES = ((0, "bass"), (0, "bass"), (4, "bass"))
"""Pad 16 twice in the answer to bar 1 (keep `home`, next `push`), then once in the
answer to bar 5 (keep the rules' `drive` on the busy drums)."""


def variations(song_rows: object) -> list[str | None]:
    return [r.bass.variation if r.bass else None for r in song_rows]  # type: ignore[attr-defined]


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


def test_likes_credit_the_answer_to_each_listed_bar() -> None:
    song = simulate([SPARSE] * 8, Settings(learn="likes", likes=(0, 2, 5), seed=3))
    assert [r.liked for r in song.rows] == [b in (0, 2, 5) for b in range(8)]
    assert {r.chose for r in song.rows} == {("bandit", "bandit")}
    likes = [line for line in song.learning if line.startswith("ensemble: like bar")]
    assert [line.split()[3] for line in likes] == ["1", "3", "6"]
    assert simulate([SPARSE] * 8, Settings(learn="likes", likes=(0, 2, 5), seed=3)) == song


def test_liking_a_choice_the_rules_did_not_make_teaches_it() -> None:
    grid = [SPARSE] * 32
    first = simulate(grid, Settings(learn="likes", seed=3))
    liked = tuple(b for b, r in enumerate(first.rows) if r.bass and r.bass.variation == "push")
    assert liked, "the softmax explores push at least once in 32 bars"
    song = simulate(grid, Settings(learn="likes", likes=liked[:8], seed=3))
    assert variations(song.rows).count("push") > variations(first.rows).count("push")


def test_wants_play_and_train_the_tree() -> None:
    song = simulate(DEMO, Settings(learn="demo", wants=WANTS))
    assert [r.chose[0] for r in song.rows] == ["want"] * 9 + ["model"] * 5
    assert variations(song.rows) == ["push"] * 4 + ["home"] * 6 + ["push", "home"] * 2
    assert "ensemble: trained bass tree, 7 examples" in song.learning
    rules = simulate(DEMO)
    assert variations(rules.rows)[10:] == ["home", "drive"] * 2


def test_pad_presses_keep_then_next_and_go_back_to_auto_at_the_phrase_end() -> None:
    song = simulate(PRESSED, Settings(learn="demo", presses=PRESSES))
    assert [r.pressed for r in song.rows][:5] == [("bass", "bass"), (), (), (), ("bass",)]
    assert [r.chose[0] for r in song.rows] == (["rule"] + ["want"] * 2 + ["model"]) * 2 + [
        "model"
    ] * 4
    assert song.learning[:3] == (
        "ensemble: want bass home (kept) to bar 4",
        "ensemble: want bass push (next) to bar 4",
        "ensemble: want bass auto (phrase end), plays model (marked contexts, 2 labels)",
    )
    assert "ensemble: want bass drive (kept) to bar 8" in song.learning
    assert "ensemble: want bass auto (phrase end), plays model (tree)" in song.learning
    assert variations(song.rows)[8:] == ["push", "drive"] * 2
    assert variations(simulate(PRESSED).rows)[8:] == ["home", "drive"] * 2
    assert simulate(PRESSED, Settings(learn="demo", presses=PRESSES)) == song


def test_pad_15_presses_choose_the_melody() -> None:
    song = simulate([SPARSE] * 4, Settings(learn="demo", presses=((0, "melody"),)))
    assert song.rows[0].pressed == ("melody",)
    assert song.learning[0].startswith("ensemble: want melody ")
    assert song.learning[0].endswith(" to bar 4")
    assert [r.chose[1] for r in song.rows][1:3] == ["want", "want"]


@pytest.mark.parametrize(
    ("settings", "message"),
    [
        (Settings(learn="maybe"), "learn must be one of"),
        (Settings(likes=(1,)), "likes need learn likes"),
        (Settings(learn="demo", wants=((0, "bass", "drive"),), likes=(1,)), "likes need"),
        (Settings(wants=((0, "bass", "push"),)), "wants need learn demo"),
        (Settings(learn="likes", likes=(4,)), "a like must be in bars 1-4"),
        (Settings(learn="demo", wants=((0, "bass", "open"),)), "a want is bass"),
        (Settings(learn="demo", wants=((9, "melody", "open"),)), "a want must be in bars"),
        (Settings(learn="likes", presses=((0, "bass"),)), "presses need learn demo"),
        (Settings(learn="demo", presses=((4, "bass"),)), "a press must be in bars 1-4"),
        (Settings(learn="demo", presses=((0, "keys"),)), "a press is bass or melody"),
    ],
)
def test_bad_learning_settings_are_refused(settings: Settings, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        simulate([SPARSE] * 4, settings)


def test_the_page_parses_likes_and_wants_and_shows_the_columns() -> None:
    assert parse_likes("3, 1 3") == (0, 2) and parse_likes("") == ()
    assert parse_wants("1 bass push, 5 bass home; 10 bass auto") == WANTS
    for bad in ("0", "x"):
        with pytest.raises(ValueError, match="likes"):
            parse_likes(bad)
    with pytest.raises(ValueError, match="wants"):
        parse_wants("1 bass")
    assert parse_presses("1 bass, 1 bass; 5 bass") == PRESSES and parse_presses("") == ()
    for bad in ("1", "0 bass", "x bass", "1 bass push"):
        with pytest.raises(ValueError, match="presses"):
            parse_presses(bad)
    shown = play(to_table(DEMO), Settings(learn="demo", wants=WANTS))
    context, chose = TABLE_HEADERS.index("context"), TABLE_HEADERS.index("chose")
    assert shown.table[0][context] == "grid/- / sparse/none"
    assert [row[chose] for row in shown.table][8:10] == ["want / rule", "model / rule"]
    assert shown.learning.splitlines()[-1] == "learned: -"
    liked = play(to_table([SPARSE] * 4), Settings(learn="likes", likes=(1,)))
    assert liked.table[1][chose] == "bandit / bandit, liked"
    pressed = play(to_table(PRESSED), Settings(learn="demo", presses=PRESSES))
    assert pressed.table[0][chose] == "rule / rule, pressed bass, pressed bass"
    assert pressed.learning.splitlines()[0] == "ensemble: want bass home (kept) to bar 4"
    assert play(to_table([SPARSE] * 4), Settings()).learning == ""


def test_the_learning_text_lists_what_was_learned() -> None:
    song = simulate([SPARSE] * 4, Settings(learn="likes", likes=(0, 1, 2), seed=3))
    text = learning(song)
    assert text.splitlines()[:3] == list(song.learning)[:3]
    assert text.endswith("learned: " + (" ".join(song.learned) or "-"))
