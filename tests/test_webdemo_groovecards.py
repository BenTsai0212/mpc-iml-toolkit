"""The grooves tab's cards, audio and export, without Gradio (#249, PR 2)."""

import json
import os
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from test_grooves import FILL, A, B, C
from test_grooves_offline import recording

from mpc_iml.events import Event, MidiEvent
from mpc_iml.frames import bank_pad_to_note
from mpc_iml.grooves import STEPS
from mpc_iml.grooves.groups import Group
from mpc_iml.grooves.offline import track_many
from mpc_iml.recording import Header, write_recording
from mpc_iml.webdemo.groovecards import (
    CLIP_BARS,
    DEFAULT_BPM,
    LEAD,
    Found,
    audio,
    cards,
    choose_sections,
    export_text,
    find_recordings,
    letter,
    load,
    played,
    prototype_loop,
    shuffle,
    summary,
)
from mpc_iml.webdemo.synth import RATE, TAIL, Hit, render_hits

TEMPO = 100.0
BAR_SECONDS = 4 * 60.0 / TEMPO
STEP_SECONDS = BAR_SECONDS / STEPS
KICK = bank_pad_to_note(0, 0)


def save(path: Path, events: list[Event], mtime: float) -> Path:
    write_recording(path, Header(), events)
    os.utime(path, (mtime, mtime))
    return path


def onset(samples: np.ndarray) -> int:
    return int(np.flatnonzero(samples)[0])


def nudge(events: list[Event], kick: int, early: float, velocity: int) -> list[Event]:
    """`events` with the `kick`-th kick (from 0, the extra first note excluded)
    played `early` seconds early at `velocity`."""
    kicks = [i for i, e in enumerate(events) if isinstance(e, MidiEvent) and e.note == KICK][1:]
    i = kicks[kick]
    old = events[i]
    assert isinstance(old, MidiEvent)
    new = MidiEvent(old.t - early, "note_on", 1, velocity, KICK)
    rest = events[:i] + events[i + 1 :]
    at = next(j for j, e in enumerate(rest) if e.t > new.t)
    return [*rest[:at], new, *rest[at:]]


def test_render_hits_places_each_hit_at_its_time_and_velocity() -> None:
    out = render_hits([Hit(0.5, "kick", 127)], 1.0)
    assert out.dtype == np.int16 and len(out) == round((1.0 + TAIL) * RATE)
    assert onset(out) == round(0.5 * RATE)
    soft = render_hits([Hit(0.5, "kick", 40)], 1.0)
    ratio = np.abs(soft).max() / np.abs(out).max()
    assert ratio == pytest.approx(40 / 127, abs=0.01)
    assert render_hits([Hit(-0.01, "hat", 100)], 1.0)[0] != 0
    with pytest.raises(ValueError, match="bass"):
        render_hits([Hit(0.0, "bass", 100)], 1.0)


def test_the_audio_uses_the_recorded_timing_and_velocity(tmp_path: Path) -> None:
    # A's kick is on steps 0, 8 and 10: the 4th kick is step 0 of bar 2.
    events = nudge(recording([A] * 5, tempo=TEMPO), 3, 0.020, 40)
    many = track_many([save(tmp_path / "a.jsonl", events, 1_000)])
    source = many.sources[0]
    [(_, section)] = choose_sections(many, 1)
    clip = played(source, section, "x")
    assert clip.seconds == pytest.approx(LEAD + 4 * BAR_SECONDS, abs=1e-6)
    kicks = sorted(h.t for h in clip.hits if h.part == "kick")
    on_grid = [LEAD + bar * BAR_SECONDS + s * STEP_SECONDS for bar in range(4) for s in (0, 8, 10)]
    assert kicks == pytest.approx(sorted(t - 0.020 * (i == 3) for i, t in enumerate(on_grid)))
    early = next(h for h in clip.hits if h.part == "kick" and h.velocity == 40)
    assert early.t == pytest.approx(LEAD + BAR_SECONDS - 0.020)
    # In the samples: the early, soft kick starts 20 ms early and is softer.
    alone = render_hits([early], clip.seconds)
    grid = render_hits([Hit(LEAD + BAR_SECONDS, "kick", 90)], clip.seconds)
    assert onset(grid) - onset(alone) == round(0.020 * RATE)
    assert np.abs(alone).max() < np.abs(grid).max() * 0.5
    rate, samples = audio(clip)
    assert rate == RATE and len(samples) == round((clip.seconds + TAIL) * RATE)


def test_the_prototype_loop_is_on_the_grid() -> None:
    clip = prototype_loop(A, 120.0)
    step = 60.0 / 120.0 / 4
    assert clip.seconds == pytest.approx(LEAD + 2 * STEPS * step)
    kicks = sorted(h.t for h in clip.hits if h.part == "kick")
    assert kicks == pytest.approx(
        [LEAD + (b * STEPS + s) * step for b in (0, 1) for s in (0, 8, 10)]
    )
    assert {h.velocity for h in clip.hits} == {100}


def test_sections_prefer_another_recording_then_the_second_longest(tmp_path: Path) -> None:
    one = save(tmp_path / "a.jsonl", recording([A] * 6 + [B] * 4 + [A] * 4, tempo=TEMPO), 1_000)
    many = track_many([one])
    chosen = choose_sections(many, 1)
    assert [s.length for _, s in chosen] == [6, 3]
    two = save(tmp_path / "b.jsonl", recording([A] * 3, tempo=TEMPO), 2_000)
    many = track_many([one, two])
    chosen = choose_sections(many, 1)
    assert [(Path(src.path).name, s.length) for src, s in chosen] == [
        ("a.jsonl", 6),
        ("b.jsonl", 2),
    ]
    long = save(tmp_path / "c.jsonl", recording([C] * (CLIP_BARS + 4), tempo=TEMPO), 3_000)
    many = track_many([long])
    [(source, section)] = choose_sections(many, 1)
    clip = played(source, section, "x")
    assert clip.seconds == pytest.approx(LEAD + CLIP_BARS * BAR_SECONDS, abs=1e-6)


def folder(tmp_path: Path) -> Path:
    session = tmp_path / "trials" / "s1"
    session.mkdir(parents=True)
    save(session / "a.jsonl", recording([A] * 5, [FILL, B, B, B], tempo=TEMPO), 1_000)
    save(session / "b.jsonl", recording([A] * 4, [C] * 4, tempo=TEMPO), 2_000)
    (session / "session.jsonl").write_text(json.dumps({"type": "header", "format": "x"}) + "\n")
    (session / "engine.log").write_text("engine started\n")
    return session


def test_a_folder_gives_its_recordings_and_skips_other_files(tmp_path: Path) -> None:
    folder(tmp_path)
    found = find_recordings("\n  trials/s1  \n", tmp_path)
    assert [g for g, _ in found.paths] == ["trials/s1/a.jsonl", "trials/s1/b.jsonl"]
    assert found.skipped == (
        "trials/s1/engine.log: not a .jsonl file",
        "trials/s1/session.jsonl: not a recording",
    )
    loaded = load(found, "2026-11-24T15:00:00+00:00")
    assert [s.path for s in loaded.groups.sources] == ["trials/s1/a.jsonl", "trials/s1/b.jsonl"]
    assert [e.id for e in loaded.groups.grooves] == [1, 2, 3]
    assert summary(loaded.groups) == (
        "3 grooves (12 bars), 0 fill bars, 0 free bars, 1 bar with no groove yet, "
        "0 bars with no drums, in 2 recordings"
    )
    # A one-line path is used as given, absolute without a data folder.
    absolute = find_recordings(str(tmp_path / "trials/s1/a.jsonl"), None)
    assert absolute.paths == (
        (str(tmp_path / "trials/s1/a.jsonl"), tmp_path / "trials/s1/a.jsonl"),
    )


@pytest.mark.parametrize(
    ("text", "data", "message"),
    [
        ("  \n", True, "enter a folder"),
        ("trials/s1", False, "absolute path"),
        ("nowhere.jsonl", True, "nowhere.jsonl: no such file"),
        ("empty", True, "empty: no mpc-iml-recording"),
    ],
)
def test_bad_input_gives_clear_errors(tmp_path: Path, text: str, data: bool, message: str) -> None:
    (tmp_path / "empty").mkdir()
    (tmp_path / "empty" / "notes.txt").write_text("x")
    with pytest.raises(ValueError, match=message):
        find_recordings(text, tmp_path if data else None)


def test_a_recording_without_clock_is_named_as_given(tmp_path: Path) -> None:
    save(tmp_path / "noclock.jsonl", [MidiEvent(0.0, "note_on", 1, 90, KICK)], 1_000)
    with pytest.raises(ValueError, match=r"^noclock\.jsonl: .*--clock"):
        load(find_recordings("noclock.jsonl", tmp_path), "now")


def test_cards_show_the_grid_counts_words_and_audio(tmp_path: Path) -> None:
    folder(tmp_path)
    loaded = load(find_recordings("trials/s1", tmp_path), "now")
    first = cards(loaded.groups, loaded.many)[0]
    assert first.title == "groove 1"
    assert first.grid.splitlines()[0] == "kick  x... .... x.x. ...."
    assert first.counts.endswith("in 2 sections, in 2 recordings")
    assert first.words.startswith("about 3 kicks a bar")
    assert [c.label for c in first.played] == [
        "a.jsonl, take 1, from bar 1",
        "b.jsonl, take 1, from bar 1",
    ]
    assert first.loop.label == "prototype" and first.loop.hits
    # Without the recordings, the card has the prototype loop only.
    bare = cards(loaded.groups, None)[0]
    assert bare.played == () and bare.counts.startswith(f"{first.counts.split(',')[0]}")
    step = 60.0 / DEFAULT_BPM / 4
    assert bare.loop.seconds == pytest.approx(LEAD + 2 * STEPS * step)


def test_blind_cards_hide_ids_and_counts_and_the_seed_fixes_the_order(tmp_path: Path) -> None:
    folder(tmp_path)
    found = find_recordings("trials/s1", tmp_path)
    blind = load(found, "now", blind=True, seed=5).groups
    assert blind.blind and blind.seed == 5
    assert load(found, "now", blind=True, seed=5).groups == blind
    shown = cards(blind, load(found, "now").many)
    assert [c.title for c in shown] == ["card A", "card B", "card C"]
    assert all(c.counts == "" for c in shown)
    assert all(c.label.startswith("played ") for card in shown for c in card.played)
    assert summary(blind) == "3 cards"
    orders = {tuple(e.id for e in shuffle(blind, seed).grooves) for seed in range(20)}
    assert len(orders) > 1
    assert [letter(i) for i in (0, 25, 26, 27, 701, 702)] == ["A", "Z", "AA", "AB", "ZZ", "AAA"]


def test_the_export_lists_groups_cards_and_notes(tmp_path: Path) -> None:
    folder(tmp_path)
    groups = load(find_recordings("trials/s1", tmp_path), "now").groups
    one, two, three = groups.grooves
    groups = replace(
        groups,
        groups=(Group(1, "the steady basic", "verses"), Group(2, "", "")),
        grooves=(replace(one, group=1, note="my usual"), two, replace(three, group=1)),
    )
    assert export_text(groups) == (
        "Groove groups (with groove ids)\n"
        "\n"
        "the steady basic\n"
        "  for: verses\n"
        "  - groove 1: my usual\n"
        "  - groove 3\n"
        "\n"
        "(no name)\n"
        "  (none)\n"
        "\n"
        "not sure\n"
        "  - groove 2\n"
    )
    blind = shuffle(groups, 1)
    text = export_text(blind)
    assert text.startswith("Groove groups (blind)\n") and "groove" not in text.split("\n", 1)[1]
    assert f"  - card {next(e.card for e in blind.grooves if e.id == 1)}: my usual\n" in text


def test_found_paths_keep_the_order_given(tmp_path: Path) -> None:
    folder(tmp_path)
    found = find_recordings("trials/s1/b.jsonl\ntrials/s1/a.jsonl", tmp_path)
    assert isinstance(found, Found) and [g for g, _ in found.paths][0] == "trials/s1/b.jsonl"
    # Tracking still goes by file date: a.jsonl first.
    assert [s.path for s in load(found, "now").groups.sources][0] == "trials/s1/a.jsonl"
