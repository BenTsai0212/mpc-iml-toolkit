"""The "Make sounds" part of the band tab (#288): the tests run `fake_generator.py`
(#284) and synthetic tones, never a real model, and need no browser."""

import hashlib
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from test_sounds_audition import a_set
from test_sounds_generate import calls, generator, generator_file, prompts
from test_webdemo_tabs import Page

from mpc_iml.bands import load_bands
from mpc_iml.sounds import soundset
from mpc_iml.sounds.audition import audition, play, report
from mpc_iml.sounds.generate import Generator, run_take
from mpc_iml.webdemo import __main__ as webdemo_main
from mpc_iml.webdemo.bandtab import MAKE, list_sets, pick_set
from mpc_iml.webdemo.makesounds import (
    HOW_TO_START,
    bands_in,
    chosen_at_start,
    document,
    make,
    plan_line,
    rows,
    set_name,
    start_seed,
    words_of,
)

LOFI = load_bands()["lofi"]
TRAP = load_bands()["trap"]
NAMES = ["bass", "keys", "vibes", "pad", "kick", "snare", "hat"]
TRAP_NAMES = ["808", "keys", "bell", "pad", "kick", "snare", "clap", "hat", "openhat"]


def defaults() -> dict[str, str]:
    found = {p.name: p.sound.words for p in LOFI.players}
    found.update({name: hit.words for name, hit in LOFI.hits.items()})
    return found


def run_all(chunks: Iterator[list[str]]) -> list[list[str]]:
    return list(chunks)


def origins(folder: Path, name: str) -> list[dict[str, Any]]:
    data = soundset.read_document(folder)
    if name in data["hits"]:
        return [data["hits"][name]["origin"]]
    return [f["origin"] for f in data["instruments"][name]["files"]]


def files_of(folder: Path, skip: str) -> dict[str, str]:
    """A digest of each file of the set but `sound-set.json` and those of `skip`."""
    found = {}
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder).as_posix()
        if path.is_file() and path.name != soundset.FILE and skip not in path.name:
            found[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return found


# Rows, chosen names and the line before making


def test_the_rows_of_lofi_without_a_set_are_the_band_defaults() -> None:
    found = rows(LOFI, None)
    assert [row[0] for row in found] == NAMES
    assert [row[1] for row in found] == ["bass", "melody", "melody", "melody"] + ["hit"] * 3
    assert words_of(found) == defaults()
    assert chosen_at_start(LOFI, None) == NAMES


def test_a_set_built_from_recordings_shows_the_defaults(tmp_path: Path) -> None:
    out = a_set(tmp_path, LOFI)
    data = document(out.parent, out.name)
    assert data is not None
    assert words_of(rows(LOFI, data)) == defaults()
    assert chosen_at_start(LOFI, data) == []
    assert start_seed(LOFI, data, "bass") == 1
    assert bands_in(data) == []
    assert set_name(LOFI, out.name, data) == out.name
    assert set_name(TRAP, out.name, data) == "trap-set"


def test_the_line_before_making(tmp_path: Path) -> None:
    words = defaults()
    line = plan_line(LOFI, None, "lofi-set", NAMES, words)
    assert "25 take(s)" in line and "replaces nothing" in line
    out = a_set(tmp_path, LOFI)
    data = document(out.parent, out.name)
    line = plan_line(LOFI, data, "set", ["vibes"], words)
    assert "3 take(s)" in line and "replaces vibes in the set" in line


@pytest.mark.parametrize(
    ("name", "chosen", "words", "says"),
    [
        ("Lofi Set", ["vibes"], {}, "is not a name"),
        ("lofi-set", ["vibes"], {"vibes": "  "}, "words for 'vibes' are empty"),
        ("lofi-set", [], {}, "Choose at least one"),
    ],
)
def test_what_cannot_be_made_is_said_and_runs_nothing(
    tmp_path: Path, name: str, chosen: list[str], words: dict[str, str], says: str
) -> None:
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    given = defaults() | words
    assert says in plan_line(LOFI, None, name, chosen, given)
    sounds = tmp_path / "sounds"
    chunks = run_all(make(LOFI, gen, sounds, name, chosen, given))
    assert len(chunks) == 1 and says in chunks[0][0]
    assert calls(log) == []
    assert not sounds.exists()


def test_without_a_generator_make_says_how_to_start(tmp_path: Path) -> None:
    assert run_all(make(LOFI, None, tmp_path, "lofi-set", NAMES, defaults())) == [[HOW_TO_START]]
    assert "--generator" in HOW_TO_START and "--sounds" in HOW_TO_START


def test_a_refused_sound_set_is_said(tmp_path: Path) -> None:
    gen = generator(tmp_path)
    sounds = tmp_path / "sounds"
    (sounds / "bad").mkdir(parents=True)
    (sounds / "bad" / soundset.FILE).write_text('{"format": "x"}', encoding="utf-8")
    chunks = run_all(make(LOFI, gen, sounds, "bad", ["kick"], defaults()))
    assert chunks[0][0].endswith("nothing more is made")


def test_a_folder_that_cannot_be_written_is_said(tmp_path: Path) -> None:
    gen = generator(tmp_path)
    sounds = tmp_path / "sounds"
    sounds.write_text("a file, not a folder", encoding="utf-8")
    chunks = run_all(make(LOFI, gen, sounds, "lofi-set", ["kick"], defaults()))
    assert any("kick: not made: " in line for chunk in chunks for line in chunk)


# Making with the test generator


def test_every_failed_take_of_one_player_does_not_stop_the_others(tmp_path: Path) -> None:
    gen = generator(tmp_path, "--fail", "C5,F5,A5")
    sounds = tmp_path / "sounds"
    chunks = run_all(make(LOFI, gen, sounds, "lofi-set", ["vibes", "kick"], defaults()))
    last = chunks[-1]
    assert last[0] == "1 of 2 made in `lofi-set`:"
    assert last[1] == "vibes: not made: no take can be used"
    assert last[2].startswith("kick: made, hits/kick.wav")
    assert set(soundset.load(sounds / "lofi-set").hits) == {"kick"}


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, list[int], int]:
    """A whole `lofi` set made through `make`, with the number of takes run before each
    yield."""
    tmp_path = tmp_path_factory.mktemp("made")
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    sounds = tmp_path / "sounds"
    count = [0]

    def counted(g: Generator, prompt: str, seed: int, seconds: float, out: Path) -> None:
        count[0] += 1
        run_take(g, prompt, seed, seconds, out)

    before = []
    for _ in make(LOFI, gen, sounds, "lofi-set", NAMES, defaults(), run=counted):
        before.append(count[0])
    return sounds, log, before, count[0]


def test_a_whole_set_is_made_and_each_arrives_as_it_finishes(
    made: tuple[Path, Path, list[int], int],
) -> None:
    sounds, _, before, total = made
    assert total == 25
    assert len(before) == len(NAMES) + 1
    assert before[:7] == [8, 15, 18, 22, 23, 24, 25]
    assert before == sorted(before)
    out = sounds / "lofi-set"
    assert soundset.problems(out) == []
    assert list_sets(sounds).choices() == ["lofi-set"]
    assert pick_set(LOFI, sounds, ["lofi-set"], None) == "lofi-set"
    loaded = soundset.load(out)
    assert report(LOFI, loaded, audition(play(LOFI), loaded)) == [
        "bass: 0 note(s) no instrument played",
        "melody: 0 note(s) no instrument played",
    ]
    data = document(sounds, "lofi-set")
    assert words_of(rows(LOFI, data)) == defaults()
    assert chosen_at_start(LOFI, data) == []
    for name, words in defaults().items():
        assert {o["settings"]["words"] for o in origins(out, name)} == {words}


def trap_defaults() -> dict[str, str]:
    found = {p.name: p.sound.words for p in TRAP.players}
    found.update({name: hit.words for name, hit in TRAP.hits.items()})
    return found


def test_a_set_made_for_lofi_is_not_offered_for_trap(
    made: tuple[Path, Path, list[int], int], tmp_path: Path
) -> None:
    sounds = tmp_path / "sounds"
    shutil.copytree(made[0], sounds)
    lofi = document(sounds, "lofi-set")
    assert bands_in(lofi) == ["lofi"]
    picked = pick_set(TRAP, sounds, ["lofi-set"], None)
    assert picked == "lofi-set"
    named = set_name(TRAP, picked, lofi)
    assert named == "trap-set"
    data = document(sounds, named)
    assert data is None
    found = rows(TRAP, data)
    assert [row[0] for row in found] == TRAP_NAMES
    assert chosen_at_start(TRAP, data) == TRAP_NAMES
    line = plan_line(TRAP, data, named, TRAP_NAMES, words_of(found))
    assert "replaces nothing in the set `trap-set`" in line and "lofi" not in line
    assert set_name(LOFI, "lofi-set", lofi) == "lofi-set"

    run_all(make(TRAP, generator(tmp_path), sounds, named, TRAP_NAMES, trap_defaults()))
    names = list_sets(sounds).choices()
    assert names == ["lofi-set", "trap-set"]
    assert pick_set(TRAP, sounds, names, None) == "trap-set"
    assert pick_set(TRAP, sounds, names, "lofi-set") == "trap-set"
    assert pick_set(LOFI, sounds, names, None) == "lofi-set"
    assert pick_set(LOFI, sounds, names, "trap-set") == "lofi-set"
    trap = document(sounds, "trap-set")
    assert bands_in(trap) == ["trap"]
    assert set_name(TRAP, "trap-set", trap) == "trap-set"
    assert set_name(LOFI, "trap-set", trap) == "lofi-set"


def test_typing_the_lofi_set_for_trap_names_lofi(made: tuple[Path, Path, list[int], int]) -> None:
    lofi = document(made[0], "lofi-set")
    line = plan_line(TRAP, lofi, "lofi-set", ["808"], trap_defaults())
    assert "holds sounds made for the band `lofi`, not `trap`" in line
    assert "holds sounds" not in plan_line(LOFI, lofi, "lofi-set", ["bass"], defaults())


def test_trying_vibes_again_uses_new_seeds_and_keeps_the_rest(
    made: tuple[Path, Path, list[int], int], tmp_path: Path
) -> None:
    sounds = tmp_path / "sounds"
    shutil.copytree(made[0], sounds)
    out = sounds / "lofi-set"
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    seeds = [o["seed"] for o in origins(out, "vibes")]
    kept = files_of(out, "vibes")
    data = document(sounds, "lofi-set")
    assert start_seed(LOFI, data, "vibes") == max(seeds) + 1
    run_all(make(LOFI, gen, sounds, "lofi-set", ["vibes"], defaults()))
    asked = [int(c[c.index("--seed") + 1]) for c in calls(log)]
    assert len(asked) == 3 and min(asked) > max(seeds)
    assert files_of(out, "vibes") == kept
    assert soundset.problems(out) == []
    assert all(o["seed"] > max(seeds) for o in origins(out, "vibes"))

    words = defaults() | {"vibes": "Glass marimba, bright"}
    run_all(make(LOFI, gen, sounds, "lofi-set", ["vibes"], words))
    assert prompts(log)[-1].startswith("Glass marimba, bright | note ")
    assert {o["settings"]["words"] for o in origins(out, "vibes")} == {"Glass marimba, bright"}
    found = words_of(rows(LOFI, document(sounds, "lofi-set")))
    assert found == words
    assert files_of(out, "vibes") == kept


def test_other_words_for_the_bass_show_in_its_row(tmp_path: Path) -> None:
    gen = generator(tmp_path)
    sounds = tmp_path / "sounds"
    words = defaults() | {"bass": "Deep synth bass, round"}
    run_all(make(LOFI, gen, sounds, "lofi-set", ["bass", "kick"], words))
    assert words_of(rows(LOFI, document(sounds, "lofi-set"))) == words


# The page


def make_page(tmp_path: Path, with_generator: bool) -> Page:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo.app import build

    sounds = tmp_path / "sounds"
    sounds.mkdir(exist_ok=True)
    gen = generator(tmp_path) if with_generator else None
    return Page(build(sounds=sounds, generator=gen))


def buttons(page: Page) -> list[str]:
    return [getattr(b, "value", "") for b in page.blocks.values() if type(b).__name__ == "Button"]


def test_without_a_generator_the_part_says_how_and_has_no_make_button(tmp_path: Path) -> None:
    page = make_page(tmp_path, False)
    assert MAKE not in buttons(page)
    texts = [getattr(b, "value", "") for b in page.blocks.values()]
    assert HOW_TO_START in texts


def test_with_a_generator_make_runs_one_at_a_time(tmp_path: Path) -> None:
    page = make_page(tmp_path, True)
    assert buttons(page).count(MAKE) == 1
    _, fn = page.handler(MAKE)
    event = next(f for f in page.page.fns.values() if f.fn is fn)
    assert event.concurrency_limit == 1
    assert page.one("CheckboxGroup", "which to make") >= 0
    assert page.one("Dataframe", "players and hits") >= 0


def test_the_page_makes_a_set_and_chooses_it(tmp_path: Path) -> None:
    page = make_page(tmp_path, True)
    _, on_make = page.handler(MAKE)
    sent = list(on_make("lofi", "lofi-set", rows(LOFI, None), ["kick"]))
    assert sent[0][1]["interactive"] is False
    last = sent[-1]
    assert "kick: made, hits/kick.wav" in last[0]
    assert last[1]["interactive"] is True and last[1]["value"] == MAKE
    assert last[2]["value"] == "lofi-set" and last[2]["choices"] == ["lofi-set"]
    assert "drum hits: kick" in last[4]


def loader(page: Page) -> tuple[list[int], Any]:
    """The outputs and the handler of the band tab's load event (the one that sets the
    sound set)."""
    chosen = page.one("Dropdown", "sound set")
    for index, dependency in enumerate(page.config["dependencies"]):
        loads = any(event == "load" for _, event in dependency["targets"])
        if loads and chosen in dependency["outputs"]:
            return dependency["outputs"], page.page.fns[index].fn
    raise AssertionError("no load handler")


def test_opening_the_page_again_reads_the_folder(tmp_path: Path) -> None:
    page = make_page(tmp_path, True)
    outputs, on_open = loader(page)
    assert outputs[0] == page.one("Dropdown", "sound set")
    assert outputs[3] == page.one("Textbox", "set name")
    assert outputs[5] == page.one("CheckboxGroup", "which to make")
    _, on_make = page.handler(MAKE)
    list(on_make("lofi", "lofi-set", rows(LOFI, None), NAMES))
    opened = on_open("lofi", None)
    assert opened[0]["value"] == "lofi-set" and opened[0]["choices"] == ["lofi-set"]
    assert "bass: instrument bass" in opened[2]
    assert opened[3] == "lofi-set"
    assert opened[5]["value"] == []
    assert opened[6].startswith("Choose at least one")
    trap = on_open("trap", None)
    assert trap[3] == "trap-set" and trap[5]["value"] == TRAP_NAMES


def test_without_a_generator_the_page_load_fills_part_2(tmp_path: Path) -> None:
    page = make_page(tmp_path, False)
    outputs, on_open = loader(page)
    assert len(outputs) == 3
    assert on_open("lofi", None)[0]["choices"] == []


def test_the_demo_starts_with_and_without_a_generator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    if not webdemo_main.gradio_installed():
        pytest.skip("needs the demo extra")
    from mpc_iml.webdemo import app

    started: list[tuple[Any, ...]] = []

    class Launched:
        def launch(self, **options: Any) -> None:
            started.append(tuple(options.items()))

    built: list[tuple[Any, ...]] = []

    def fake_build(*args: Any) -> Launched:
        built.append(args)
        return Launched()

    monkeypatch.setattr(app, "build", fake_build)
    sounds = tmp_path / "sounds"
    assert webdemo_main.main(["--sounds", str(sounds)]) == 0
    assert built[-1][3] is None
    path = generator_file(tmp_path)
    assert webdemo_main.main(["--sounds", str(sounds), "--generator", str(path)]) == 0
    assert isinstance(built[-1][3], Generator)
    refused = tmp_path / "other.json"
    shutil.copy(path, refused)
    assert webdemo_main.main(["--sounds", str(sounds), "--generator", str(refused)]) == 2
    assert "the file name must equal the name" in capsys.readouterr().err
    assert len(started) == 2
