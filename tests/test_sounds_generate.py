"""Generating the notes of an instrument and a drum hit with a model the musician
installed (#284): the tests run `fake_generator.py`, never a real model."""

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from tones import RATE, tone, write

from mpc_iml.sounds import soundset
from mpc_iml.sounds.generate import (
    Generator,
    GeneratorError,
    fill,
    generate_hit,
    generate_notes,
    load_generator,
    main,
    next_note,
    parse_generator,
    problems,
    take_file,
)
from mpc_iml.sounds.hits import make_hit
from mpc_iml.sounds.instrument import build
from mpc_iml.sounds.soundset import Origin

SCRIPT = Path(__file__).parent / "fake_generator.py"
NOTE_PROMPT = "{words} | note {note}"
HIT_PROMPT = "{words} | hit"


def generator_data(*flags: str, log: Path | None = None, timeout: float = 60) -> dict[str, Any]:
    command = [sys.executable, str(SCRIPT), "--prompt", "{prompt}", "--seed", "{seed}"]
    command += ["--seconds", "{seconds}", "--out", "{out}", *flags]
    if log is not None:
        command += ["--log", str(log)]
    return {
        "format": "mpc-iml-generator",
        "format_version": 1,
        "name": "fake",
        "title": "Fake model",
        "model": "fake-model-small",
        "command": command,
        "note_prompt": NOTE_PROMPT,
        "hit_prompt": HIT_PROMPT,
        "timeout": timeout,
    }


def generator_file(folder: Path, *flags: str, **options: Any) -> Path:
    path = folder / "fake.json"
    path.write_text(json.dumps(generator_data(*flags, **options)), encoding="utf-8")
    return path


def generator(folder: Path, *flags: str, **options: Any) -> Generator:
    return load_generator(generator_file(folder, *flags, **options))


def calls(log: Path) -> list[list[str]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines()]


def prompts(log: Path) -> list[str]:
    return [args[args.index("--prompt") + 1] for args in calls(log)]


def read_set(folder: Path) -> dict[str, Any]:
    data = json.loads((folder / "sound-set.json").read_text())
    assert isinstance(data, dict)
    return data


# The generator file


def test_a_good_generator_file_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = generator_file(tmp_path)
    assert main(["check", str(path)]) == 0
    assert "ok, generator 'fake' for model 'fake-model-small'" in capsys.readouterr().out
    loaded = load_generator(path)
    assert loaded.timeout == 60
    assert loaded.folder is None
    data = generator_data()
    del data["timeout"], data["title"]
    assert parse_generator(data).timeout == 120


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"colour": "red"}, "colour: unknown field"),
        ({"command": ["gen", "-o", "{out}"]}, "command: has no {prompt}"),
        ({"command": ["gen", "-p", "{prompt}"]}, "command: has no {out}"),
        (
            {"command": ["gen", "-p", "{prompt}", "-o", "{out}", "--steps", "{steps}"]},
            "command[6]: unknown placeholder {steps}",
        ),
        ({"note_prompt": "{words}, one note"}, "note_prompt: has no {note}"),
        ({"hit_prompt": "a one-shot"}, "hit_prompt: has no {words}"),
        ({"timeout": 0}, "timeout: must be a number of seconds above 0, not 0"),
        ({"command": "gen {prompt} {out}"}, "command: must be a list"),
        ({"name": "Fake Model"}, "name: 'Fake Model' is not a name"),
        ({"format_version": 2}, "format_version: must be 1"),
    ],
)
def test_a_refused_generator_file_names_the_problem(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: dict[str, Any], problem: str
) -> None:
    data = {**generator_data(), **change}
    assert any(problem in found for found in problems(data))
    path = tmp_path / "fake.json"
    path.write_text(json.dumps(data))
    assert main(["check", str(path)]) == 1
    assert problem in capsys.readouterr().err


def test_the_file_name_must_equal_the_name(tmp_path: Path) -> None:
    path = tmp_path / "other.json"
    path.write_text(json.dumps(generator_data()))
    with pytest.raises(GeneratorError, match="file name must equal the name 'fake'"):
        load_generator(path)


def test_placeholders_are_filled_in_one_pass() -> None:
    assert fill("{words} | note {note}", {"words": "{note}", "note": "E2"}) == "{note} | note E2"
    loaded = parse_generator(generator_data())
    assert loaded.note("warm bass", 40) == "warm bass | note E2"
    assert loaded.note("x", 42) == "x | note F#2"
    assert loaded.hit("dusty kick") == "dusty kick | hit"
    assert take_file("bass", 3, 42) == "bass-Fs2-s3.wav"
    assert take_file("kick", 1) == "kick-s1.wav"


# Notes


def test_notes_as_asked_give_an_instrument(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    out = tmp_path / "set"
    result = generate_notes("bass", gen, "warm bass", [40, 45, 50], out, seconds=2)

    assert result.instrument is not None
    assert [r.centre for r in result.instrument.regions] == [40, 45, 50]
    assert sorted(p.name for p in (out / "takes").iterdir()) == [
        "bass-A2-s1.wav",
        "bass-D3-s1.wav",
        "bass-E2-s1.wav",
    ]
    assert result.unanswered == ()
    assert [r.source for r in result.instrument.regions] == [
        out / "takes" / "bass-E2-s1.wav",
        out / "takes" / "bass-A2-s1.wav",
        out / "takes" / "bass-D3-s1.wav",
    ]
    assert prompts(log) == [
        "warm bass | note E2",
        "warm bass | note A2",
        "warm bass | note D3",
    ]
    files = read_set(out)["instruments"]["bass"]["files"]
    assert [f["file"] for f in files] == ["bass-E2-s1.wav", "bass-A2-s1.wav", "bass-D3-s1.wav"]
    assert files[0]["origin"] == {
        "kind": "generated",
        "model": "fake-model-small",
        "prompt": "warm bass | note E2",
        "seed": 1,
        "settings": {
            "generator": "fake",
            "words": "warm bass",
            "asked": "E2",
            "seconds": 2,
            "round": 1,
        },
    }
    assert not [p for p in out.iterdir() if p.name.startswith(".takes-")]
    assert soundset.problems(out) == []


def test_a_note_an_octave_away_is_asked_the_other_way(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, "--high", "A2,A1", log=log)
    out = tmp_path / "set"
    result = generate_notes("bass", gen, "warm bass", [40, 45, 50], out, seconds=2)

    asked = [
        (t.round, t.asked, t.seed, t.measured.note if t.measured else None) for t in result.takes
    ]
    assert asked == [(1, 40, 1, 40), (1, 45, 1, 57), (1, 50, 1, 50), (2, 33, 2, 45)]
    assert prompts(log)[-1] == "warm bass | note A1"
    assert result.unanswered == ()
    assert result.instrument is not None
    centres = [r.centre for r in result.instrument.regions]
    assert {40, 45, 50} <= set(centres)
    files = {f["file"]: f for f in read_set(out)["instruments"]["bass"]["files"]}
    assert files["bass-A1-s2.wav"]["origin"]["settings"] == {
        "generator": "fake",
        "words": "warm bass",
        "asked": "A1",
        "seconds": 2,
        "round": 2,
    }
    assert ("region" in files["bass-A2-s1.wav"]) == (57 in centres)
    assert ("left_out" in files["bass-A2-s1.wav"]) == (57 not in centres)


def test_one_round_asks_nothing_again(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, "--high", "A2", log=log)
    out = tmp_path / "set"
    argv = ["notes", "bass", "--generator", str(path), "--words", "warm bass"]
    argv += ["--notes", "40", "45", "50", "--out", str(out), "--duration", "2", "--rounds", "1"]
    assert main(argv) == 0
    assert len(calls(log)) == 3
    printed = capsys.readouterr().out
    assert "A2 (45) was not answered by a clean take" in printed
    assert "round 1 asked A2   seed 1  measured A3" in printed
    assert "bass: samples/bass-E2.wav" in printed


def test_next_note_goes_the_other_way_only_by_whole_octaves(tmp_path: Path) -> None:
    gen = generator(tmp_path, "--high", "A2")
    result = generate_notes("x", gen, "w", [45], tmp_path / "set", seconds=2, rounds=1)
    assert next_note(45, result.takes) == 33
    assert next_note(45, []) == 45


def test_failed_takes_are_reported_and_the_others_build(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = generator_file(
        tmp_path, "--fail", "E2", "--silent", "A2", "--sleep", "D3", "--nothing", "G3", timeout=1
    )
    out = tmp_path / "set"
    argv = ["notes", "keys", "--generator", str(path), "--words", "soft keys", "--out", str(out)]
    argv += ["--notes", "E2", "A2", "D3", "G3", "C4", "--duration", "2", "--rounds", "1"]
    assert main(argv) == 0
    printed = capsys.readouterr().out
    assert "asked E2   seed 1  failed: the command ended with status 3" in printed
    assert "    | error: out of memory" in printed
    assert "asked A2   seed 1  failed: the file cannot be used: the recording is silent" in printed
    assert "asked D3   seed 1  failed: ran past the timeout of 1 s" in printed
    assert "asked G3   seed 1  failed: the command wrote no file" in printed
    assert "keys: samples/keys-C4.wav" in printed
    assert [f["file"] for f in read_set(out)["instruments"]["keys"]["files"]] == ["keys-C4-s1.wav"]


def test_when_every_take_fails_the_set_is_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "set"
    make_hit("kick", write(tmp_path / "k.wav", tone(36.0, seconds=0.5)), out)
    before = (out / "sound-set.json").read_text()
    path = generator_file(tmp_path, "--fail", "E2,E1")
    argv = ["notes", "bass", "--generator", str(path), "--words", "w", "--out", str(out)]
    assert main([*argv, "--notes", "E2", "--duration", "2"]) == 1
    assert "no take can be used; the sound set is unchanged" in capsys.readouterr().out
    assert (out / "sound-set.json").read_text() == before
    assert not (out / "takes").exists()
    assert sorted(p.name for p in out.iterdir()) == ["hits", "sound-set.json"]


def test_words_reach_the_command_as_one_argument(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    gen = generator(tmp_path, log=log)
    words = 'it\'s "dusty"; $(rm -rf ~) `x` & ok\nsecond line'
    generate_notes("keys", gen, words, [60], tmp_path / "set", seconds=2)
    generate_hit("kick", gen, words, tmp_path / "set", duration=0.5)
    assert prompts(log) == [f"{words} | note C4", f"{words} | hit"]


def test_generating_again_replaces_only_its_own_takes(tmp_path: Path) -> None:
    gen = generator(tmp_path)
    out = tmp_path / "set"
    generate_notes("bass", gen, "warm", [40, 45], out, seconds=2)
    generate_notes("keys", gen, "soft", [60], out, seconds=2)
    generate_hit("kick", gen, "dusty kick", out, duration=0.5)
    before = sorted(p.name for p in (out / "takes").iterdir())
    assert before == ["bass-A2-s1.wav", "bass-E2-s1.wav", "keys-C4-s1.wav", "kick-s1.wav"]

    result = generate_notes("bass", gen, "dark", [50], out, seconds=2, seed=7)
    assert result.instrument is not None
    assert sorted(p.name for p in (out / "takes").iterdir()) == [
        "bass-D3-s7.wav",
        "keys-C4-s1.wav",
        "kick-s1.wav",
    ]
    assert sorted(p.name for p in (out / "samples").iterdir()) == ["bass-D3.wav", "keys-C4.wav"]
    data = read_set(out)
    assert data["instruments"]["bass"]["files"][0]["origin"]["prompt"] == "dark | note D3"
    assert set(data["instruments"]) == {"bass", "keys"}
    assert set(data["hits"]) == {"kick"}
    assert soundset.problems(out) == []


# Hits


def test_a_generated_hit(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    argv = ["hit", "kick", "--generator", str(path), "--words", "dusty kick", "--out", str(out)]
    assert main([*argv, "--seed", "4", "--seconds", "0.3"]) == 0
    assert "kick: hits/kick.wav  0.30 s" in capsys.readouterr().out
    assert (out / "takes" / "kick-s4.wav").is_file()
    assert (out / "hits" / "kick.wav").is_file()
    assert calls(log)[0][calls(log)[0].index("--seconds") + 1] == "1"
    hit = read_set(out)["hits"]["kick"]
    assert hit["file"] == "kick-s4.wav"
    assert hit["origin"] == {
        "kind": "generated",
        "model": "fake-model-small",
        "prompt": "dusty kick | hit",
        "seed": 4,
        "settings": {"generator": "fake", "words": "dusty kick", "seconds": 1.0},
    }


# Checked before the model is run


@pytest.mark.parametrize(
    "problem",
    ["generator", "option", "sound-set"],
)
def test_problems_stop_both_commands_before_the_generator_runs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], problem: str
) -> None:
    log = tmp_path / "log.jsonl"
    path = generator_file(tmp_path, log=log)
    out = tmp_path / "set"
    out.mkdir()
    notes = ["notes", "bass", "--notes", "E2", "--duration", "2"]
    hit = ["hit", "kick"]
    extra_notes: list[str] = []
    extra_hit: list[str] = []
    if problem == "generator":
        data = generator_data(log=log)
        data["command"] = ["gen", "{prompt}"]
        path.write_text(json.dumps(data))
    elif problem == "option":
        extra_notes = ["--octave", "9"]
        extra_hit = ["--seconds", "0"]
    else:
        (out / "sound-set.json").write_text('{"format": "something else"}')
    common = ["--generator", str(path), "--words", "w", "--out", str(out)]
    assert main([*notes, *common, *extra_notes]) == 1
    assert main([*hit, *common, *extra_hit]) == 1
    assert capsys.readouterr().out.count("error:") == 2
    assert not log.exists()
    assert not (out / "takes").exists()


# Origins and sound sets


@pytest.mark.parametrize(
    "origin",
    [
        Origin("generated", None, "p", 1),
        Origin("generated", "m", "p", "1"),  # type: ignore[arg-type]
        Origin("generated", "m", "p", 1, settings=["x"]),  # type: ignore[arg-type]
        Origin("generated", "m", "p", 1, settings={"x": float("nan")}),
    ],
)
def test_build_and_make_hit_refuse_an_origin_before_writing(tmp_path: Path, origin: Origin) -> None:
    note = write(tmp_path / "c4.wav", tone(60.0))
    out = tmp_path / "set"
    with pytest.raises(soundset.SoundSetError, match="origin"):
        build("keys", [note], out, origins={note: origin})
    with pytest.raises(soundset.SoundSetError, match="origin"):
        make_hit("kick", note, out, origin=origin)
    assert not out.exists()


def test_check_passes_when_takes_were_deleted(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gen = generator(tmp_path)
    out = tmp_path / "set"
    generate_notes("bass", gen, "warm", [40, 45], out, seconds=2)
    generate_hit("kick", gen, "dusty", out, duration=0.5)
    (out / "takes" / "bass-E2-s1.wav").unlink()
    (out / "takes" / "kick-s1.wav").unlink()
    assert soundset.main(["check", str(out)]) == 0
    assert "3 generated take(s), 2 missing from takes/" in capsys.readouterr().out


def test_generate_is_not_imported_by_the_core() -> None:
    import subprocess

    code = (
        "import sys, mpc_iml, mpc_iml.engine, mpc_iml.ensemble, mpc_iml.bands;"
        "print('mpc_iml.sounds.generate' in sys.modules)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert done.stdout.strip() == "False"


def test_a_silent_hit_take_is_refused(tmp_path: Path) -> None:
    def silent(gen: Generator, prompt: str, seed: int, seconds: float, out: Path) -> None:
        from mpc_iml.sounds import wav

        wav.write(out, np.zeros((RATE, 2), dtype=np.float32), RATE)

    result = generate_hit("kick", generator(tmp_path), "w", tmp_path / "set", run=silent)
    assert result.hit is None
    assert result.error == "the file cannot be used: the recording is silent"
    assert not (tmp_path / "set" / "sound-set.json").exists()
