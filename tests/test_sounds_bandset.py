"""A whole sound set for a band from a model the musician installed (#286): the tests
run `fake_generator.py` (#284) and synthetic tones, never a real model."""

import json
from pathlib import Path
from typing import Any

import pytest
from test_sounds_generate import calls, generator, generator_file, prompts

from mpc_iml.bands import load_bands
from mpc_iml.sounds import soundset
from mpc_iml.sounds.audition import audition, play, report
from mpc_iml.sounds.bandset import Made, ask_notes, generate_band, plan
from mpc_iml.sounds.generate import main
from mpc_iml.sounds.notes import note_name, note_number

NOTES = {
    "lofi": {
        "bass": "C2 F2 A2 D3",
        "keys": "E3 A3 D4 G4 C5 F5 A5",
        "vibes": "C5 F5 A5",
        "pad": "E3 A3 D4 G4",
    },
    "trap": {
        "808": "D1 G1 C2 F2 A2",
        "keys": "G3 C4 F4 A4",
        "bell": "D5 G5 C6",
        "pad": "G3 C4 F4 A4",
    },
}
"""The notes asked for in round 1, as written in #286."""
TAKES = {"lofi": 25, "trap": 26}


def read_set(folder: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((folder / "sound-set.json").read_text())
    return data


def test_ask_notes_follows_the_rule() -> None:
    assert [note_name(n) for n in ask_notes(note_number("C#2"), note_number("E3"))] == [
        "C2",
        "F2",
        "A2",
        "D3",
    ]
    assert ask_notes(60, 60) == [60]
    assert ask_notes(60, 62) == [60]
    assert ask_notes(60, 63) == [60, 65]
    assert ask_notes(64, 70) == [64, 69]


@pytest.mark.parametrize("name", ["lofi", "trap"])
def test_the_notes_asked_for_the_built_in_bands(name: str) -> None:
    planned = plan(load_bands()[name])
    found = {p.player.name: " ".join(note_name(n) for n in p.notes) for p in planned.players}
    assert found == NOTES[name]
    assert not any("#" in note_name(n) for p in planned.players for n in p.notes)
    assert planned.takes == TAKES[name]


@pytest.mark.parametrize("name", ["lofi", "trap"])
def test_plan_prints_and_runs_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str
) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    assert main(["band", name, "--generator", str(path), "--out", str(out), "--plan"]) == 0
    printed = capsys.readouterr().out
    band = load_bands()[name]
    for player in band.players:
        line = next(x for x in printed.splitlines() if x.startswith(f"{player.name}: "))
        assert repr(player.sound.words) in line
        assert f"notes {NOTES[name][player.name]};" in line
    for hit in band.hits.values():
        assert f"{hit.name}: {hit.words!r}" in printed
    assert f"{name}: {TAKES[name]} take(s) in round 1" in printed
    assert not log.exists()
    assert not out.exists()


@pytest.mark.parametrize(("name", "hits"), [("lofi", 3), ("trap", 5)])
def test_a_band_gives_a_whole_set(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], name: str, hits: int
) -> None:
    path = generator_file(tmp_path)
    out = tmp_path / "set"
    argv = ["band", name, "--generator", str(path), "--out", str(out), "--rounds", "1"]
    assert main(argv) == 0
    printed = capsys.readouterr().out.splitlines()
    band = load_bands()[name]
    assert soundset.problems(out) == []
    loaded = soundset.load(out)
    assert list(loaded.instruments) == [p.name for p in band.players]
    assert len(loaded.hits) == hits and set(loaded.hits) == set(band.hits)
    for player in band.players:
        instrument = loaded.instruments[player.name]
        assert instrument.plays == player.plays
        assert instrument.settings["prefer"] == player.prefer
        assert instrument.settings["release"] == player.release
        assert f"{player.name}: made, " in "\n".join(printed)
        assert {r.origin.settings["words"] for r in instrument.regions if r.origin} == {
            player.sound.words
        }
        assert {r.origin.settings["band"] for r in instrument.regions if r.origin} == {name}
    for hit in band.hits.values():
        assert any(line.startswith(f"{hit.name}: made, hits/{hit.name}.wav") for line in printed)
        origin = loaded.hits[hit.name].origin
        assert origin is not None and origin.settings == {
            "generator": "fake",
            "words": hit.words,
            "band": name,
            "seconds": 1.0,
        }
    assert printed[-2] == f"  uv run python -m mpc_iml.sounds.soundset check {out}"
    assert printed[-1].startswith(f"  uv run python -m mpc_iml.sounds.audition {name} {out} --out ")
    result = audition(play(band), loaded)
    assert report(band, loaded, result) == [
        "bass: 0 note(s) no instrument played",
        "melody: 0 note(s) no instrument played",
    ]


def test_words_replace_one_player(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    out = tmp_path / "set"
    band = load_bands()["lofi"]
    results = generate_band(
        band, gen, out, words={"bass": "fretless bass"}, only=["bass", "keys", "kick"], rounds=1
    )
    assert all(r.made for r in results)
    sent = prompts(log)
    assert [p for p in sent if p.startswith("fretless bass")] == [
        f"fretless bass | note {n}" for n in "C2 C2 F2 F2 A2 A2 D3 D3".split()
    ]
    keys = band.players[1].sound.words
    assert [p for p in sent if p.startswith(keys)] == [
        f"{keys} | note {n}" for n in NOTES["lofi"]["keys"].split()
    ]
    assert f"{band.hits['kick'].words} | hit" in sent
    assert len(sent) == 8 + 7 + 1
    files = read_set(out)["instruments"]["bass"]["files"]
    assert {f["origin"]["prompt"].split(" | ")[0] for f in files} == {"fretless bass"}


def test_only_asks_for_those_and_leaves_the_others(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    common = ["band", "lofi", "--generator", str(path), "--out", str(out), "--rounds", "1"]
    assert main([*common, "--only", "bass", "vibes", "kick", "snare"]) == 0
    files = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    before = read_set(out)
    log.unlink()

    assert main([*common, "--only", "vibes", "kick", "--seed", "5"]) == 0
    vibes = load_bands()["lofi"].players[2].sound.words
    assert sorted(prompts(log)) == sorted(
        [f"{vibes} | note {n}" for n in NOTES["lofi"]["vibes"].split()]
        + [f"{load_bands()['lofi'].hits['kick'].words} | hit"]
    )
    after = read_set(out)
    assert after["instruments"]["bass"] == before["instruments"]["bass"]
    assert after["hits"]["snare"] == before["hits"]["snare"]
    for p, data in files.items():
        if p.name.startswith(("bass", "snare")):
            assert p.read_bytes() == data, p
    assert after["hits"]["kick"]["origin"]["seed"] == 5


@pytest.mark.parametrize(
    ("extra", "said"),
    [
        (["--words", "drums=loud"], "--words: 'drums' is neither a player nor a hit"),
        (["--words", "bass"], "--words 'bass': write it as <name>=<words>"),
        (["--only", "bass", "cowbell"], "--only: 'cowbell' is neither a player nor a hit"),
        (["--words", "bass= "], "--words: the words for 'bass' are empty"),
    ],
)
def test_wrong_names_stop_before_the_generator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str], said: str
) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    assert main(["band", "lofi", "--generator", str(path), "--out", str(out), *extra]) == 1
    assert said in capsys.readouterr().out
    assert not log.exists()
    assert not out.exists()


def test_an_unknown_band_stops_before_the_generator(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    assert main(["band", "boombap", "--generator", str(path), "--out", str(out)]) == 1
    assert "no built-in band 'boombap'; bands: lofi, trap" in capsys.readouterr().out
    assert not log.exists()
    assert not out.exists()


def test_a_player_that_fails_does_not_stop_the_others(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fail = ",".join(f"{n}{o}" for n in "CDEFGAB" for o in (5, 6))
    path = generator_file(tmp_path, "--fail", fail)
    out = tmp_path / "set"
    argv = ["band", "trap", "--generator", str(path), "--out", str(out), "--rounds", "1"]
    assert main(argv) == 1
    printed = capsys.readouterr().out.splitlines()
    assert "bell: not made: no take can be used" in printed
    assert printed[-3] == "next: listen before keeping the set:"
    finals = printed[-12:-3]
    assert [line.split(":")[0] for line in finals] == [
        "808",
        "keys",
        "bell",
        "pad",
        "kick",
        "snare",
        "clap",
        "hat",
        "openhat",
    ]
    data = read_set(out)
    assert set(data["instruments"]) == {"808", "keys", "pad"}
    assert len(data["hits"]) == 5


def test_done_is_called_for_each_in_order(tmp_path: Path) -> None:
    gen = generator(tmp_path)
    finished: list[Made] = []
    results = generate_band(
        load_bands()["trap"],
        gen,
        tmp_path / "set",
        only=["openhat", "bell", "kick"],
        rounds=1,
        done=finished.append,
    )
    assert [m.name for m in finished] == ["bell", "kick", "openhat"]
    assert finished == results
    assert [m.kind for m in finished] == ["player", "hit", "hit"]


def test_the_take_runner_can_be_replaced(tmp_path: Path) -> None:
    asked: list[str] = []

    def nothing(gen: Any, prompt: str, seed: int, seconds: float, out: Path) -> None:
        asked.append(prompt)

    results = generate_band(
        load_bands()["lofi"], generator(tmp_path), tmp_path / "set", only=["hat"], run=nothing
    )
    assert asked == [f"{load_bands()['lofi'].hits['hat'].words} | hit"]
    assert results[0].error == "the command wrote no file"
    assert calls(tmp_path / "log.jsonl") == []
