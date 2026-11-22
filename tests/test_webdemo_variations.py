"""The web demo's `variations` tab (#221 PR 3): candidates next to their source,
blind mode and reveal, without Gradio."""

from pathlib import Path

import pytest
from test_vargen import TINY, write_loop

from mpc_iml.clock import SIXTEENTHS
from mpc_iml.loops import STEPS, load_loops
from mpc_iml.webdemo.app import play_variations
from mpc_iml.webdemo.sim import DRUMS, Settings
from mpc_iml.webdemo.synth import RATE
from mpc_iml.webdemo.variations import (
    DRUM_PATTERN,
    MAX_COUNT,
    PROVENANCE_HEADERS,
    clip_song,
    listen,
    table,
)


def test_the_source_comes_first_then_the_candidates(tmp_path: Path) -> None:
    listing = listen("boom", tmp_path, count=3)
    assert [c.label for c in listing.clips] == ["source", "1", "2", "3"]
    assert listing.clips[0].candidate is None and not listing.yours
    assert all(c.candidate is not None for c in listing.clips[1:])
    rows = table(listing)
    assert all(len(r) == len(PROVENANCE_HEADERS) for r in rows)
    assert rows[0][1] == "source: built-in boom/home" and rows[0][3] == "0"
    first = listing.clips[1].candidate
    assert first is not None
    assert rows[1][1] == "from built-in boom/home, novelty 0.2, corpus own"
    assert rows[1][2] == first.seed and rows[1][3].startswith(f"{first.distance[0]} (")


def test_the_same_settings_give_the_same_clips(tmp_path: Path) -> None:
    one = listen("walk", tmp_path, seed=5, novelty=0.5)
    two = listen("walk", tmp_path, seed=5, novelty=0.5)
    assert [c.song for c in one.clips] == [c.song for c in two.clips]


def test_each_clip_plays_its_notes_over_the_drums(tmp_path: Path) -> None:
    listing = listen("keys", tmp_path, count=2, tempo=100, progression="minor-four")
    for clip in listing.clips:
        song = clip.song
        assert song.bars == 4 and song.settings.tempo == 100
        keys = [n for n in song.notes if n.part == "keys"]
        drums = [n for n in song.notes if n.part in DRUMS]
        assert keys and len(drums) == 4 * sum(len(h) for h in DRUM_PATTERN.values())
        assert all(n.tick < song.ticks for n in song.notes)
    silent = listen("keys", tmp_path, count=1, drums=False)
    assert all(n.part == "keys" for c in silent.clips for n in c.song.notes)


def test_a_clip_repeats_the_line_on_the_progression() -> None:
    loop = load_loops().loops["boom"]
    song = clip_song(loop, "home", Settings(), drums=False, bars=8)
    per_pass = len(loop.variations["home"])
    assert song.bars == 8 and len(song.notes) == per_pass * 8 // loop.bars
    first = sorted(n.tick for n in song.notes)[:per_pass]
    later = sorted(n.tick for n in song.notes)[per_pass : 2 * per_pass]
    assert [t + loop.bars * STEPS * SIXTEENTHS for t in first] == later


def test_blind_mode_hides_the_source_until_reveal(tmp_path: Path) -> None:
    listing = listen("boom", tmp_path, blind=True, seed=3)
    assert [c.label for c in listing.clips] == ["A", "B", "C", "D", "E"]
    assert all(set(r[1:]) == {"?"} for r in table(listing))
    revealed = table(listing, reveal=True)
    sources = [r[0] for r in revealed if str(r[1]).startswith("source")]
    source = [c.label for c in listing.clips if c.candidate is None]
    assert sources == source and len(source) == 1
    again = listen("boom", tmp_path, blind=True, seed=3)
    assert [c.candidate for c in again.clips] == [c.candidate for c in listing.clips]


def test_your_loop_from_the_data_folder_or_a_file(tmp_path: Path) -> None:
    path = write_loop(tmp_path, "tiny", "bass", TINY)
    by_name = listen("tiny", tmp_path, count=1, novelty=0.5)
    assert by_name.yours and table(by_name)[0][1] == "source: your tiny/home"
    by_file = listen(str(path), tmp_path / "empty", count=1, novelty=0.5)
    assert by_file.yours and by_file.loop.name == "tiny"
    assert len(listen("tiny", tmp_path, novelty=0).clips) == 2


def test_the_clips_sound_and_draw(tmp_path: Path) -> None:
    clips = play_variations(listen("pluck", tmp_path, count=1))
    assert [label for label, _, _ in clips] == ["source", "1"]
    for _, (rate, samples), picture in clips:
        assert rate == RATE and samples.any() and picture.ndim == 3


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"count": MAX_COUNT + 1}, "count"),
        ({"progression": "nope"}, "progression"),
        ({"tempo": 10.0}, "tempo"),
        ({"variation": "push"}, "push"),
        ({"novelty": 2.0}, "novelty"),
        ({"setting": "every"}, "corpus"),
    ],
)
def test_bad_settings_are_errors(tmp_path: Path, changes: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        listen("keys", tmp_path, **changes)  # type: ignore[arg-type]


def test_an_unknown_loop_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown loop"):
        listen("nope", tmp_path)
