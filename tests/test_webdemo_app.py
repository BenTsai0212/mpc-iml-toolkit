"""The web demo's page (#166): its functions without a browser, and the page built."""

import os

import pytest

from mpc_iml.webdemo import __main__ as webdemo_main
from mpc_iml.webdemo.app import (
    ANALYTICS_ENV,
    BARS,
    EXAMPLES,
    HEADERS,
    TABLE_HEADERS,
    analytics_default_off,
    play,
    resize,
    to_table,
)
from mpc_iml.webdemo.sim import STEPS, Settings
from mpc_iml.webdemo.synth import RATE


def column(table: list[list[str | int]], name: str) -> list[str | int]:
    i = TABLE_HEADERS.index(name)
    return [row[i] for row in table]


def test_the_grid_has_a_row_per_bar_and_drum() -> None:
    table = to_table(EXAMPLES["sparse"])
    assert len(table) == 24 and all(len(r) == len(HEADERS) == STEPS + 1 for r in table)
    assert [r[0] for r in table[:4]] == ["bar 1 kick", "bar 1 snare", "bar 1 hat", "bar 2 kick"]
    assert table[0][1:] == [100, 0, 0, 0] * 4 and table[1][1:] == [0] * STEPS


def test_resize_keeps_the_bars_it_can_and_adds_empty_ones() -> None:
    table = to_table(EXAMPLES["busy"])
    assert resize(table, BARS[0]) == table[:12]
    grown = resize(to_table(EXAMPLES["busy"][:4]), 6)
    assert grown[:12] == table[:12] and [r[0] for r in grown[12:]][::3] == [
        "bar 5 kick",
        "bar 6 kick",
    ]
    assert all(r[1:] == [0] * STEPS for r in grown[12:])


def test_sparse_and_busy_examples_sound_and_read_different() -> None:
    (rate, sparse_audio), sparse, *_ = play(to_table(EXAMPLES["sparse"]), Settings())
    (_, busy_audio), busy, *_ = play(to_table(EXAMPLES["busy"]), Settings())
    assert rate == RATE and sparse_audio.any() and busy_audio.any()
    assert len(sparse) == len(busy) == 8 and all(len(r) == len(TABLE_HEADERS) for r in sparse)
    assert sparse[0][:1] + sparse[0][3:8] == ["1 → 2", "1 5 9 13", "-", 4, "100", "Am7"]
    assert set(column(sparse, "bass")) == {"home + ornaments"}
    assert set(column(busy, "bass")) == {"drive + ornaments"}
    assert set(column(sparse, "melody")) == {"open"}
    assert set(column(busy, "melody")) == {"busy + ornaments"}
    assert (column(sparse, "brightness")[0], column(busy, "brightness")[0]) == (48, 110)


def test_the_table_names_the_no_drums_rule_when_the_drums_stop() -> None:
    _, table, *_ = play(to_table(EXAMPLES["drums stop"]), Settings(fade_bars=2, surprise=0))
    melody = column(table, "melody")
    assert melody[:4] == ["busy + ornaments"] * 4
    assert melody[4:6] == ["open + ornaments (lead)"] * 2
    assert melody[6:] == ["silent (lead)"] * 2
    assert column(table, "melody vel")[4:6] == [66, 38]
    assert column(table, "kicks")[4:] == ["-"] * 4
    assert column(table, "melody vel")[6:] == ["-", "-"]


def test_fixed_and_off_are_shown() -> None:
    table = to_table(EXAMPLES["sparse"][:4])
    _, fixed, *_ = play(table, Settings(melody_mode="fixed"))
    _, off, *_ = play(table, Settings(melody_mode="off"))
    assert set(column(fixed, "melody")) == {"home + ornaments (fixed)"}
    assert set(column(off, "melody")) == {"off"} and set(column(off, "brightness")) == {"-"}


def test_empty_cells_are_no_hits_and_bad_cells_are_refused() -> None:
    table = to_table(EXAMPLES["sparse"][:4])
    blank = [[r[0], *["" if c == 0 else c for c in r[1:]]] for r in table]
    assert play(blank, Settings())[1] == play(table, Settings())[1]
    floats = [[r[0], *[float(c) for c in r[1:]]] for r in table]
    assert play(floats, Settings())[1] == play(table, Settings())[1]
    for cell, message in [("x", "not a number"), (128, "0-127"), (1.5, "0-127")]:
        bad = [list(r) for r in table]
        bad[0][3] = cell
        with pytest.raises(ValueError, match=message):
            play(bad, Settings())
    with pytest.raises(ValueError, match="3 rows per bar"):
        play(table[:-1], Settings())
    with pytest.raises(ValueError, match="tempo"):
        play(table, Settings(tempo=200))


def test_without_the_extra_it_prints_the_install_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(webdemo_main, "gradio_installed", lambda: False)
    assert webdemo_main.main([]) == 2
    assert "uv sync --extra demo" in capsys.readouterr().err


def test_the_page_builds() -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    import gradio as gr

    from mpc_iml.webdemo.app import build

    page = build()
    assert isinstance(page, gr.Blocks)
    assert {type(b).__name__ for b in page.blocks.values()} >= {
        "Dataframe",
        "Audio",
        "Button",
        "Slider",
        "Dropdown",
        "Radio",
        "Checkbox",
        "Number",
        "File",
        "Image",
        "Tab",
    }
    tabs = {getattr(b, "label", None) for b in page.blocks.values() if type(b).__name__ == "Tab"}
    assert tabs == {"step grid", "recording", "variations", "grooves"}
    rhythm = [b for b in page.blocks.values() if getattr(b, "label", None) == "rhythm"]
    assert len(rhythm) == 1 and getattr(rhythm[0], "value", None) == 0


def test_analytics_are_off_unless_the_environment_sets_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ANALYTICS_ENV, raising=False)
    assert analytics_default_off() is False
    assert os.environ[ANALYTICS_ENV] == "False"
    monkeypatch.setenv(ANALYTICS_ENV, "True")
    assert analytics_default_off() is True
    assert os.environ[ANALYTICS_ENV] == "True"


def test_the_built_page_leaves_analytics_off(monkeypatch: pytest.MonkeyPatch) -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from gradio import analytics

    from mpc_iml.webdemo.app import build

    monkeypatch.delenv(ANALYTICS_ENV, raising=False)
    page = build()
    assert page.analytics_enabled is False and analytics.analytics_enabled() is False
